"""Read a trace directory produced by `containerizer trace` into typed events."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from containerizer.analyze.strace_reader import parse_strace_network_log

COLLECTORS: tuple[str, ...] = (
    "open",
    "bind",
    "syscalls",
    "connect",
    "accept",
    "capable",
)

# Collectors whose strace fallback log we know how to parse. Other
# fallbacks (open, syscalls, capable use different strace domains and
# different output shapes) are left on disk and warned about, but the
# events themselves stay empty until those parsers exist.
_FALLBACK_PARSEABLE: frozenset[str] = frozenset({"bind", "connect", "accept"})


class MissingMarker(Exception):
    """Neither COMPLETE nor PARTIAL marker present — trace is corrupt or in-flight."""


class MissingRequiredCollector(Exception):
    """A collector file is missing AND not listed in FALLBACKS.json."""


@dataclass
class TraceBundle:
    marker: Literal["COMPLETE", "PARTIAL"]
    phase_marker_ns: int | None
    fallbacks: dict[str, dict[str, str]]
    # events[collector_name] = list of parsed JSON dicts (one per .jsonl line)
    events: dict[str, list[dict[str, object]]]
    warnings: list[str] = field(default_factory=list)
    start_cmd: str | None = None


def read_trace_dir(trace_dir: Path) -> TraceBundle:
    """Parse a trace directory. See spec §5.1 (reader.py) for behavior."""
    if (trace_dir / "COMPLETE").exists():
        marker: Literal["COMPLETE", "PARTIAL"] = "COMPLETE"
    elif (trace_dir / "PARTIAL").exists():
        marker = "PARTIAL"
    else:
        raise MissingMarker(
            f"no COMPLETE or PARTIAL marker in {trace_dir}; trace is corrupt or in-flight"
        )

    phase_marker_ns = _read_phase_marker(trace_dir / "PHASE_MARKER")
    fallbacks = _read_fallbacks(trace_dir / "FALLBACKS.json")

    warnings: list[str] = []
    events: dict[str, list[dict[str, object]]] = {}
    empty_present: list[str] = []
    for name in COLLECTORS:
        jsonl_path = trace_dir / f"{name}.jsonl"
        if not jsonl_path.exists():
            if name in fallbacks:
                recovered = _consume_fallback(trace_dir, name)
                if recovered:
                    warnings.append(
                        f"collector {name}: missing .jsonl; recovered "
                        f"{len(recovered)} events from {name}.fallback.log"
                    )
                else:
                    warnings.append(
                        f"collector {name}: missing .jsonl; fallback recorded "
                        f"({fallbacks[name].get('reason', 'unknown')})"
                    )
                events[name] = recovered
                continue
            raise MissingRequiredCollector(
                f"{jsonl_path} missing and {name} is not in FALLBACKS.json"
            )

        parsed = _parse_jsonl(jsonl_path)
        events[name] = parsed
        if not parsed and name not in fallbacks:
            empty_present.append(name)

    # Only warn about present-but-empty collectors when the trace recorded
    # *some* activity. An entirely empty trace is the "container did nothing
    # observable" case (e.g., a bare `true`) — legitimate, not noise-worthy.
    if any(events[name] for name in COLLECTORS):
        for name in empty_present:
            warnings.append(f"collector {name}: .jsonl present but empty")

    # START_CMD is optional: absent for traces taken without --start-cmd. Read
    # verbatim per spec §3.1; CLI normalization (Task 6) prevents empty strings.
    start_cmd_path = trace_dir / "START_CMD"
    start_cmd = start_cmd_path.read_text(encoding="utf-8") if start_cmd_path.exists() else None
    return TraceBundle(
        marker=marker,
        phase_marker_ns=phase_marker_ns,
        fallbacks=fallbacks,
        events=events,
        warnings=warnings,
        start_cmd=start_cmd,
    )


@dataclass(frozen=True)
class InstallInputs:
    """User-supplied install-time inputs surfaced from trace-dir marker files."""

    installers: tuple[str, ...] = ()
    apt_sources: tuple[str, ...] = ()
    apt_keys: tuple[str, ...] = ()


def read_install_inputs(trace_dir: Path) -> InstallInputs:
    """Read INSTALLERS / apt-sources.list / APT_KEYS marker files.

    All three files are optional; missing files yield empty tuples.
    Blank lines are skipped.
    """
    return InstallInputs(
        installers=_read_lines(trace_dir / "INSTALLERS"),
        apt_sources=_read_lines(trace_dir / "apt-sources.list"),
        apt_keys=_read_lines(trace_dir / "APT_KEYS"),
    )


def _read_lines(path: Path) -> tuple[str, ...]:
    if not path.exists():
        return ()
    return tuple(
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    )


def _read_phase_marker(path: Path) -> int | None:
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8").strip()
    # Orchestrator writes "monotonic_ns: <int>\n"
    prefix = "monotonic_ns:"
    if not text.startswith(prefix):
        return None
    try:
        return int(text[len(prefix) :].strip())
    except ValueError:
        return None


def _read_fallbacks(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return {}
    data: dict[str, dict[str, str]] = json.loads(path.read_text(encoding="utf-8"))
    return data


def _consume_fallback(trace_dir: Path, collector: str) -> list[dict[str, object]]:
    """Parse the strace fallback log for a network collector. Returns
    an empty list when the log is missing, the collector isn't one we
    know how to parse from strace, or strace produced no matching
    events."""
    if collector not in _FALLBACK_PARSEABLE:
        return []
    log_path = trace_dir / f"{collector}.fallback.log"
    if not log_path.exists():
        return []
    parsed = parse_strace_network_log(log_path)
    return list(parsed.get(collector, []))


def _parse_jsonl(path: Path) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    bad_lines = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        # bpftrace dumps non-cleared map contents at script exit
        # (e.g., "@args[3429]: 140732759619824"); skip anything that
        # doesn't look like a JSON object.
        if not line.startswith("{"):
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            # bpftrace occasionally emits stray escape sequences in
            # paths or comm fields (\x.., bare \ before non-escape
            # chars) when the kernel surfaces non-ASCII bytes. Skip
            # the line; the rest of the trace is still useful.
            bad_lines += 1
            continue
    if bad_lines:
        print(
            f"[analyze] _parse_jsonl({path.name}): skipped {bad_lines} "
            "malformed JSON line(s) (likely bpftrace stray escapes)",
            file=sys.stderr,
        )
    return out
