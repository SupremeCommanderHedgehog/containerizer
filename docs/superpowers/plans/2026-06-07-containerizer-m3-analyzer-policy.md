# M3 Analyzer + Policy Derivation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the M3 milestone of the containerizer per [`docs/superpowers/specs/2026-06-07-containerizer-m3-analyzer-policy.md`](../specs/2026-06-07-containerizer-m3-analyzer-policy.md): a `containerizer analyze <trace-dir> -o <out-dir>` subcommand that consumes the six per-collector JSONL streams + `FALLBACKS.json` + `PHASE_MARKER` + `COMPLETE`/`PARTIAL` marker produced by M2, and writes a normalized `trace.json` plus a derived `policy.json` to `<out-dir>`.

**Architecture:** A new `src/containerizer/analyze/` package with one module per responsibility (`schema`, `reader`, `phases`, `paths`, `ports`, `caps`, `syscalls`, `execs`, `derive`, `writer`, `cli`). `schema.py` defines all Pydantic v2 models; every other module imports from it and nothing imports back. The CLI subcommand is one step from the user's POV; internally it's a two-phase pipeline (event-normalize → policy-derive). Tests are fixture-driven: hand-crafted JSONL snippets under `tests/fixtures/trace/paths-rules/` and `tests/fixtures/trace/phase-split/` for unit tests, plus a single hand-crafted `synthetic-recorded/` directory + golden `trace.json` / `policy.json` for the end-to-end smoke test.

**Tech Stack:** Python 3.11+ + Click + Pydantic v2 (already in `pyproject.toml`), pytest with the `integration` marker (already registered in M2). No new third-party dependencies.

---

## Conventions used throughout

- **Working directory:** all commands assume `C:\Users\yizshachuck\source\containerizer\` is the cwd. Use absolute paths in tools (Read/Edit/Write); use relative paths in shell commands.
- **Each task starts on its own feature branch off the latest `main`** (e.g., `feat/m3-task-N-<slug>`). PR per task, signed-commit-per-task, squash-merge through protected `main`. Mirrors the M2 pattern.
- **Commit signing.** Every commit MUST be signed per the user's global `CLAUDE.md`:
  ```
  git -c user.email="github.v5f9w@bitbucket.onl" \
      -c user.signingkey=BE707B220C995478 \
      commit -S -m "<message>"
  ```
  Never pass `--no-gpg-sign`. Never amend a published commit.
- **Conventional commit subject** per task. `feat(analyze):` for new analyze modules; `test(analyze):` for fixtures and tests; `docs:` for the spec/plan/MANUAL updates; `ci:` if the workflow needs touching (it does not for M3).
- **Close the matching issue.** This plan covers issues #38 (analyzer) and #39 (policy derivation). Final task references both with `Closes #38, #39`.
- **Coverage gate.** `pyproject.toml` enforces `--cov-fail-under=90`. New code in `src/containerizer/analyze/` must keep total coverage ≥ 90%. The integration test (Task 13) does not contribute to coverage.
- **Lint + type gate.** `ruff check . && ruff format --check . && mypy src tests && pytest` must pass before pushing every task.
- **Pydantic style.** v2, `BaseModel` subclasses, `Literal` for closed enums, `Field(alias="...", serialization_alias="...")` for the `class` reserved word. Match the precedent in `src/containerizer/probe/schema.py`.
- **JSON output style.** Pretty-printed (`indent=2`), keys sorted, deterministic so golden-file diffs are stable. `schema_version` is the first key at each top level.
- **No magic numbers.** Constants live at module top (`SYS_EXECVE_X86_64 = 59`, `AF_INET = 2`, etc.) with a one-line comment if non-obvious.
- **Line endings.** Repo is set up for LF; Windows working copies see CRLF warnings on `.bt` files. Benign.

---

## File map

Files created or modified by this plan:

| Path | Purpose | Task |
|---|---|---|
| `src/containerizer/analyze/__init__.py` | Package marker | 2 |
| `src/containerizer/analyze/schema.py` | Pydantic models (TraceJson, PolicyJson, sub-models) | 2 |
| `src/containerizer/analyze/reader.py` | Parse `<trace-dir>` into typed in-memory events | 3 |
| `src/containerizer/analyze/phases.py` | Split events by `PHASE_MARKER` | 4 |
| `src/containerizer/analyze/paths.py` | Path classifier (7 rules) + aggregation | 5 |
| `src/containerizer/analyze/ports.py` | bind.jsonl → TracePort list | 6 |
| `src/containerizer/analyze/caps.py` | capable.jsonl → dedup + superset filter | 7 |
| `src/containerizer/analyze/syscalls.py` | syscalls.jsonl → sorted unique syscall_ids | 8 |
| `src/containerizer/analyze/execs.py` | execve filter → unique comm list | 8 |
| `src/containerizer/analyze/derive.py` | TraceJson → PolicyJson | 9 |
| `src/containerizer/analyze/writer.py` | Serialize TraceJson / PolicyJson | 10 |
| `src/containerizer/analyze/cli.py` | `containerizer analyze` Click subcommand | 11 |
| `src/containerizer/cli.py` | Register `analyze_cmd` on the main group | 11 |
| `tests/unit/analyze/__init__.py` | Test package marker | 2 |
| `tests/unit/analyze/test_schema.py` | Schema round-trip + alias tests | 2 |
| `tests/unit/analyze/test_reader.py` | Reader: missing files, empty files, fallbacks, malformed | 3 |
| `tests/unit/analyze/test_phases.py` | Phase-split: COMPLETE+marker, PARTIAL, boundary | 4 |
| `tests/unit/analyze/test_paths.py` | Parametrized over `tests/fixtures/trace/paths-rules/` | 5 |
| `tests/unit/analyze/test_ports.py` | Port dedup, tcp/udp/unix/? handling | 6 |
| `tests/unit/analyze/test_caps.py` | Capability dedup + superset filter | 7 |
| `tests/unit/analyze/test_syscalls.py` | Phase-filter, sort, dedup | 8 |
| `tests/unit/analyze/test_execs.py` | execve filter, sort, dedup | 8 |
| `tests/unit/analyze/test_derive.py` | systemd heuristic, conservative defaults, sentinel | 9 |
| `tests/unit/analyze/test_writer.py` | schema_version, sort, alias serialization | 10 |
| `tests/unit/analyze/test_cli.py` | CLI surface + error paths | 11 |
| `tests/fixtures/trace/paths-rules/*.jsonl` | One fixture per path-class rule + collision | 5 |
| `tests/fixtures/trace/phase-split/*.jsonl` | COMPLETE-with-marker, PARTIAL-no-marker fixtures | 4 |
| `tests/fixtures/trace/synthetic-recorded/` | Hand-crafted recorded trace dir for smoke test | 12 |
| `tests/fixtures/analyze/expected/synthetic-trace.json` | Golden trace.json | 12 |
| `tests/fixtures/analyze/expected/synthetic-policy.json` | Golden policy.json | 12 |
| `tests/integration/analyze/__init__.py` | Test package marker | 13 |
| `tests/integration/analyze/test_analyze_smoke.py` | End-to-end CLI vs golden files | 13 |
| `sandbox/record-fixture.sh` | Helper to regenerate `synthetic-recorded/` from real trace | 12 |
| `MANUAL.md` | Add scenario 7 (running analyze) | 14 |

---

## Task 1: New `analyze/` package + empty test directory

**Issue:** prep (no individual issue).

**Files:**
- Create: `src/containerizer/analyze/__init__.py`
- Create: `tests/unit/analyze/__init__.py`

This task lands first to give every later task a stable target package. Just two empty files; the rest of the plan modifies them.

- [ ] **Step 1: Create the package marker**

Write `src/containerizer/analyze/__init__.py`:

```python
"""Containerizer trace analyzer + policy derivation (M3)."""
```

- [ ] **Step 2: Create the unit-test package marker**

Write `tests/unit/analyze/__init__.py`:

```python
```

(empty file — pytest auto-discovers, but the `__init__.py` keeps `mypy --strict` from complaining about an implicit namespace package).

- [ ] **Step 3: Run the gate**

```
ruff check . && ruff format --check . && mypy src tests && pytest
```

Expected: PASS. No tests yet, but the new package doesn't break anything.

- [ ] **Step 4: Commit**

```
git -c user.email="github.v5f9w@bitbucket.onl" \
    -c user.signingkey=BE707B220C995478 \
    commit -S -m "feat(analyze): bootstrap analyze package + test directory"
```

---

## Task 2: `schema.py` — Pydantic models

**Issue:** #38 (groundwork).

**Files:**
- Create: `src/containerizer/analyze/schema.py`
- Create: `tests/unit/analyze/test_schema.py`

The contract every other module depends on. Tests must pin the JSON shape and the `class` alias behavior so later tasks (and M4) can't accidentally break it.

- [ ] **Step 1: Write the failing tests**

Write `tests/unit/analyze/test_schema.py`:

```python
"""Tests for analyze schema models."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from containerizer.analyze.schema import (
    PolicyImage,
    PolicyJson,
    PolicyPort,
    PolicyRuntime,
    PolicyVolume,
    TraceJson,
    TraceOutbound,
    TracePath,
    TracePhase,
    TracePort,
)


def _empty_phase() -> TracePhase:
    return TracePhase(
        duration_s=0.0,
        paths=[],
        ports=[],
        outbound=[],
        caps=[],
        syscalls=[],
        execs=[],
    )


def test_tracepath_serializes_class_alias() -> None:
    p = TracePath(path="/var/lib/x", ops=["write"], class_="persistent_rw", by=["app"])
    dumped = json.loads(p.model_dump_json(by_alias=True))
    assert dumped["class"] == "persistent_rw"
    assert "class_" not in dumped


def test_tracepath_class_invalid_rejected() -> None:
    with pytest.raises(ValidationError):
        TracePath(path="/x", ops=["read"], class_="nonsense", by=[])  # type: ignore[arg-type]


def test_tracejson_round_trip() -> None:
    tj = TraceJson(
        phase_marker_ns=12345,
        marker="COMPLETE",
        install=_empty_phase(),
        runtime=_empty_phase(),
        warnings=["x"],
    )
    s = tj.model_dump_json(by_alias=True)
    tj2 = TraceJson.model_validate_json(s)
    assert tj2 == tj
    assert tj2.schema_version == 1


def test_tracejson_partial_marker_allows_none_phase_marker() -> None:
    tj = TraceJson(
        phase_marker_ns=None,
        marker="PARTIAL",
        install=_empty_phase(),
        runtime=_empty_phase(),
        warnings=[],
    )
    assert tj.phase_marker_ns is None


def test_policyjson_defaults_and_round_trip() -> None:
    pj = PolicyJson(
        image=PolicyImage(
            base="ubuntu:24.04",
            apt_packages=[],
            post_install_cleanup=["/installer"],
            systemd_required=False,
            entrypoint=["__UNSET__"],
        ),
        runtime=PolicyRuntime(
            volumes=[],
            tmpfs=[],
            binds_ro=[],
            publish_ports=[],
            caps_add=[],
            seccomp_syscalls=[],
            read_only_rootfs=False,
        ),
    )
    s = pj.model_dump_json(by_alias=True)
    pj2 = PolicyJson.model_validate_json(s)
    assert pj2 == pj
    assert pj2.schema_version == 1
    assert pj2.image.installer_path == "/installer"
    assert pj2.runtime.caps_drop == ["ALL"]
    assert pj2.runtime.no_new_privileges is True


def test_policyport_proto_restricted() -> None:
    PolicyPort(host=8443, container=8443, proto="tcp")
    PolicyPort(host=53, container=53, proto="udp")
    with pytest.raises(ValidationError):
        PolicyPort(host=1, container=1, proto="unix")  # type: ignore[arg-type]


def test_policyvolume_basic() -> None:
    v = PolicyVolume(name="unifi-data", mount="/var/lib/unifi")
    assert v.name == "unifi-data"
    assert v.mount == "/var/lib/unifi"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/analyze/test_schema.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'containerizer.analyze.schema'`.

- [ ] **Step 3: Implement `schema.py`**

Write `src/containerizer/analyze/schema.py`:

```python
"""Pydantic models for the analyzer's trace.json and policy.json outputs.

This module is the contract every other analyze/ module depends on.
Nothing in analyze/ should import from outside this file's siblings;
everything imports from here.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class TracePath(BaseModel):
    """One aggregated path entry in trace.json.

    The aggregator collapses many per-file events into one entry keyed
    on the mount-relevant root (see spec §5.3).
    """

    model_config = ConfigDict(populate_by_name=True)

    path: str
    ops: list[Literal["read", "write", "mkdir", "stat", "exec"]]
    class_: Literal[
        "image_static",
        "persistent_rw",
        "ephemeral_rw",
        "host_config_ro",
        "device",
        "unknown_rw",
        "unknown_ro",
    ] = Field(alias="class", serialization_alias="class")
    by: list[str]


class TracePort(BaseModel):
    port: int
    proto: Literal["tcp", "udp", "unix", "?"]
    by: str
    ipv4: bool
    ipv6: bool


class TraceOutbound(BaseModel):
    daddr: str
    dport: int
    comm: str


class TracePhase(BaseModel):
    duration_s: float
    exit: int | None = None
    paths: list[TracePath]
    ports: list[TracePort]
    outbound: list[TraceOutbound]
    caps: list[str]
    syscalls: list[int]
    execs: list[str]


class TraceJson(BaseModel):
    schema_version: Literal[1] = 1
    phase_marker_ns: int | None
    marker: Literal["COMPLETE", "PARTIAL"]
    install: TracePhase
    runtime: TracePhase
    warnings: list[str]


class PolicyImage(BaseModel):
    base: str
    apt_packages: list[str]
    installer_path: str = "/installer"
    post_install_cleanup: list[str]
    systemd_required: bool
    entrypoint: list[str]


class PolicyVolume(BaseModel):
    name: str
    mount: str


class PolicyPort(BaseModel):
    host: int
    container: int
    proto: Literal["tcp", "udp"]


class PolicyRuntime(BaseModel):
    volumes: list[PolicyVolume]
    tmpfs: list[str]
    binds_ro: list[str]
    publish_ports: list[PolicyPort]
    caps_add: list[str]
    caps_drop: list[str] = ["ALL"]
    seccomp_syscalls: list[int]
    read_only_rootfs: bool
    no_new_privileges: bool = True


class PolicyJson(BaseModel):
    schema_version: Literal[1] = 1
    image: PolicyImage
    runtime: PolicyRuntime
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/analyze/test_schema.py -v`
Expected: all 7 tests PASS.

- [ ] **Step 5: Run the gate**

```
ruff check . && ruff format --check . && mypy src tests && pytest
```

Expected: PASS, coverage still ≥ 90%.

- [ ] **Step 6: Commit**

```
git -c user.email="github.v5f9w@bitbucket.onl" \
    -c user.signingkey=BE707B220C995478 \
    commit -S -m "feat(analyze): schema.py — TraceJson + PolicyJson Pydantic models"
```

---

## Task 3: `reader.py` — parse the trace directory into typed events

**Issue:** #38.

**Files:**
- Create: `src/containerizer/analyze/reader.py`
- Create: `tests/unit/analyze/test_reader.py`

Reads `<trace-dir>` and returns a typed bundle: per-collector event lists + FALLBACKS map + phase_marker_ns + marker. Skips non-JSON lines (bpftrace map-dump residue from script exit). Hard-errors on missing-not-fallback collectors; warns on present-but-empty.

- [ ] **Step 1: Write the failing tests**

Write `tests/unit/analyze/test_reader.py`:

```python
"""Tests for analyze.reader."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from containerizer.analyze.reader import (
    MissingMarker,
    MissingRequiredCollector,
    TraceBundle,
    read_trace_dir,
)

COLLECTORS = ("open", "bind", "syscalls", "connect", "accept", "capable")


def _make_complete_trace(tmp_path: Path) -> Path:
    d = tmp_path / "t"
    d.mkdir()
    for name in COLLECTORS:
        (d / f"{name}.jsonl").write_text("", encoding="utf-8")
    (d / "FALLBACKS.json").write_text("{}", encoding="utf-8")
    (d / "PHASE_MARKER").write_text("monotonic_ns: 12345\n", encoding="utf-8")
    (d / "COMPLETE").write_text("", encoding="utf-8")
    return d


def test_read_complete_empty_trace(tmp_path: Path) -> None:
    d = _make_complete_trace(tmp_path)
    bundle = read_trace_dir(d)
    assert isinstance(bundle, TraceBundle)
    assert bundle.marker == "COMPLETE"
    assert bundle.phase_marker_ns == 12345
    assert bundle.fallbacks == {}
    assert bundle.events == {name: [] for name in COLLECTORS}
    assert bundle.warnings == []


def test_read_partial_no_phase_marker(tmp_path: Path) -> None:
    d = tmp_path / "t"
    d.mkdir()
    for name in COLLECTORS:
        (d / f"{name}.jsonl").write_text("", encoding="utf-8")
    (d / "FALLBACKS.json").write_text("{}", encoding="utf-8")
    (d / "PARTIAL").write_text("", encoding="utf-8")
    bundle = read_trace_dir(d)
    assert bundle.marker == "PARTIAL"
    assert bundle.phase_marker_ns is None


def test_no_marker_is_hard_error(tmp_path: Path) -> None:
    d = tmp_path / "t"
    d.mkdir()
    for name in COLLECTORS:
        (d / f"{name}.jsonl").write_text("", encoding="utf-8")
    (d / "FALLBACKS.json").write_text("{}", encoding="utf-8")
    with pytest.raises(MissingMarker):
        read_trace_dir(d)


def test_missing_non_fallback_collector_errors(tmp_path: Path) -> None:
    d = _make_complete_trace(tmp_path)
    (d / "connect.jsonl").unlink()
    with pytest.raises(MissingRequiredCollector):
        read_trace_dir(d)


def test_missing_fallback_collector_is_warning(tmp_path: Path) -> None:
    d = _make_complete_trace(tmp_path)
    (d / "connect.jsonl").unlink()
    (d / "FALLBACKS.json").write_text(
        json.dumps({"connect": {"reason": "x", "fallback": "strace -e trace=network"}}),
        encoding="utf-8",
    )
    bundle = read_trace_dir(d)
    assert any("connect" in w for w in bundle.warnings)
    assert "connect" in bundle.events  # key present even with no data
    assert bundle.events["connect"] == []


def test_present_empty_non_fallback_collector_is_warning(tmp_path: Path) -> None:
    d = _make_complete_trace(tmp_path)
    # connect.jsonl is empty + not in FALLBACKS -> warning only
    bundle = read_trace_dir(d)
    assert any("connect" in w for w in bundle.warnings)


def test_jsonl_with_non_json_lines_are_skipped(tmp_path: Path) -> None:
    d = _make_complete_trace(tmp_path)
    (d / "open.jsonl").write_text(
        "Attaching 2 probes...\n"
        '{"ts_ns":1,"pid":2,"comm":"x","path":"/a","flags":0,"mode":0,"ret":0}\n'
        "@args[123]: 456\n",
        encoding="utf-8",
    )
    bundle = read_trace_dir(d)
    assert len(bundle.events["open"]) == 1
    assert bundle.events["open"][0]["path"] == "/a"


def test_malformed_json_inside_brace_line_is_hard_error(tmp_path: Path) -> None:
    d = _make_complete_trace(tmp_path)
    (d / "open.jsonl").write_text("{not really json\n", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        read_trace_dir(d)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/analyze/test_reader.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `reader.py`**

Write `src/containerizer/analyze/reader.py`:

```python
"""Read a trace directory produced by `containerizer trace` into typed events."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

COLLECTORS: tuple[str, ...] = (
    "open",
    "bind",
    "syscalls",
    "connect",
    "accept",
    "capable",
)


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


def read_trace_dir(trace_dir: Path) -> TraceBundle:
    """Parse a trace directory. See spec §5.1 (reader.py) for behavior."""
    if (trace_dir / "COMPLETE").exists():
        marker: Literal["COMPLETE", "PARTIAL"] = "COMPLETE"
    elif (trace_dir / "PARTIAL").exists():
        marker = "PARTIAL"
    else:
        raise MissingMarker(
            f"no COMPLETE or PARTIAL marker in {trace_dir}; "
            "trace is corrupt or in-flight"
        )

    phase_marker_ns = _read_phase_marker(trace_dir / "PHASE_MARKER")
    fallbacks = _read_fallbacks(trace_dir / "FALLBACKS.json")

    warnings: list[str] = []
    events: dict[str, list[dict[str, object]]] = {}
    for name in COLLECTORS:
        jsonl_path = trace_dir / f"{name}.jsonl"
        if not jsonl_path.exists():
            if name in fallbacks:
                warnings.append(
                    f"collector {name}: missing .jsonl; fallback recorded "
                    f"({fallbacks[name].get('reason', 'unknown')})"
                )
                events[name] = []
                continue
            raise MissingRequiredCollector(
                f"{jsonl_path} missing and {name} is not in FALLBACKS.json"
            )

        parsed = _parse_jsonl(jsonl_path)
        events[name] = parsed
        if not parsed and name not in fallbacks:
            warnings.append(f"collector {name}: .jsonl present but empty")

    return TraceBundle(
        marker=marker,
        phase_marker_ns=phase_marker_ns,
        fallbacks=fallbacks,
        events=events,
        warnings=warnings,
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
        return int(text[len(prefix):].strip())
    except ValueError:
        return None


def _read_fallbacks(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _parse_jsonl(path: Path) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        # bpftrace dumps non-cleared map contents at script exit
        # (e.g., "@args[3429]: 140732759619824"); skip anything that
        # doesn't look like a JSON object.
        if not line.startswith("{"):
            continue
        out.append(json.loads(line))
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/analyze/test_reader.py -v`
Expected: all 8 tests PASS.

- [ ] **Step 5: Run the full gate and commit**

```
ruff check . && ruff format --check . && mypy src tests && pytest
git -c user.email="github.v5f9w@bitbucket.onl" \
    -c user.signingkey=BE707B220C995478 \
    commit -S -m "feat(analyze): reader.py — parse trace dir into typed events"
```

---

## Task 4: `phases.py` + phase-split fixtures

**Issue:** #38.

**Files:**
- Create: `src/containerizer/analyze/phases.py`
- Create: `tests/unit/analyze/test_phases.py`
- Create: `tests/fixtures/trace/phase-split/complete-with-marker.jsonl`
- Create: `tests/fixtures/trace/phase-split/partial-no-marker.jsonl`

Split a list of timestamped events into (install_events, runtime_events). For COMPLETE-with-marker: events with `ts_ns < phase_marker_ns` → install. For PARTIAL: every event → install, runtime is empty.

- [ ] **Step 1: Create the fixtures**

Write `tests/fixtures/trace/phase-split/complete-with-marker.jsonl`:

```
{"ts_ns":100,"pid":1,"comm":"x"}
{"ts_ns":200,"pid":1,"comm":"x"}
{"ts_ns":1000,"pid":1,"comm":"x"}
{"ts_ns":1500,"pid":1,"comm":"x"}
```

(phase_marker_ns = 1000 — events at 100, 200 → install; events at 1000, 1500 → runtime. Boundary is `>=`.)

Write `tests/fixtures/trace/phase-split/partial-no-marker.jsonl`:

```
{"ts_ns":100,"pid":1,"comm":"x"}
{"ts_ns":200,"pid":1,"comm":"x"}
{"ts_ns":300,"pid":1,"comm":"x"}
```

- [ ] **Step 2: Write the failing tests**

Write `tests/unit/analyze/test_phases.py`:

```python
"""Tests for analyze.phases."""

from __future__ import annotations

import json
from pathlib import Path

from containerizer.analyze.phases import split_phases

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "trace" / "phase-split"


def _load(name: str) -> list[dict[str, object]]:
    return [json.loads(l) for l in (FIXTURES / name).read_text().splitlines() if l]


def test_complete_split_at_marker() -> None:
    events = _load("complete-with-marker.jsonl")
    install, runtime = split_phases(events, phase_marker_ns=1000, marker="COMPLETE")
    assert [e["ts_ns"] for e in install] == [100, 200]
    assert [e["ts_ns"] for e in runtime] == [1000, 1500]


def test_partial_puts_everything_in_install() -> None:
    events = _load("partial-no-marker.jsonl")
    install, runtime = split_phases(events, phase_marker_ns=None, marker="PARTIAL")
    assert [e["ts_ns"] for e in install] == [100, 200, 300]
    assert runtime == []


def test_complete_without_marker_treats_all_as_install() -> None:
    # Should not happen in practice (reader.py guarantees marker presence),
    # but the function is defensive.
    install, runtime = split_phases([{"ts_ns": 1}], phase_marker_ns=None, marker="COMPLETE")
    assert install == [{"ts_ns": 1}]
    assert runtime == []


def test_event_without_ts_ns_goes_to_install() -> None:
    # Defensive: capable.jsonl records don't have ts_ns
    install, runtime = split_phases(
        [{"pid": 1, "cap": "CAP_NET_BIND_SERVICE"}],
        phase_marker_ns=1000,
        marker="COMPLETE",
    )
    assert len(install) == 1
    assert runtime == []
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/unit/analyze/test_phases.py -v`
Expected: FAIL.

- [ ] **Step 4: Implement `phases.py`**

Write `src/containerizer/analyze/phases.py`:

```python
"""Split collector events into install and runtime by PHASE_MARKER.

PHASE_MARKER carries a `monotonic_ns:` line written by the orchestrator
right after the installer exits. bpftrace's `nsecs` and `/proc/uptime`
are both CLOCK_MONOTONIC, so direct comparison with event ts_ns is
apples-to-apples. If a future collector switches clock sources, this
will silently misclassify — keep the comment.
"""

from __future__ import annotations

from typing import Literal


def split_phases(
    events: list[dict[str, object]],
    *,
    phase_marker_ns: int | None,
    marker: Literal["COMPLETE", "PARTIAL"],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """Return (install_events, runtime_events).

    Behavior:
      - PARTIAL marker: every event -> install; runtime is empty.
      - COMPLETE + phase_marker_ns: events with ts_ns < phase_marker_ns -> install;
        events with ts_ns >= phase_marker_ns -> runtime.
      - COMPLETE without phase_marker_ns: treat all as install (defensive).
      - An event without a ts_ns field is sent to install.
    """
    if marker == "PARTIAL" or phase_marker_ns is None:
        return list(events), []

    install: list[dict[str, object]] = []
    runtime: list[dict[str, object]] = []
    for e in events:
        ts = e.get("ts_ns")
        if not isinstance(ts, int):
            install.append(e)
            continue
        if ts < phase_marker_ns:
            install.append(e)
        else:
            runtime.append(e)
    return install, runtime
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/unit/analyze/test_phases.py -v`
Expected: all 4 tests PASS.

- [ ] **Step 6: Gate + commit**

```
ruff check . && ruff format --check . && mypy src tests && pytest
git -c user.email="github.v5f9w@bitbucket.onl" \
    -c user.signingkey=BE707B220C995478 \
    commit -S -m "feat(analyze): phases.py — split events by PHASE_MARKER"
```

---

## Task 5: `paths.py` — path classifier (7 rules) + aggregation

**Issue:** #38.

**Files:**
- Create: `src/containerizer/analyze/paths.py`
- Create: `tests/unit/analyze/test_paths.py`
- Create: `tests/fixtures/trace/paths-rules/rule1-image-static.jsonl`
- Create: `tests/fixtures/trace/paths-rules/rule2-persistent-rw.jsonl`
- Create: `tests/fixtures/trace/paths-rules/rule3-ephemeral-rw.jsonl`
- Create: `tests/fixtures/trace/paths-rules/rule4-host-config.jsonl`
- Create: `tests/fixtures/trace/paths-rules/rule5-device.jsonl`
- Create: `tests/fixtures/trace/paths-rules/rule6-proc-sys-filtered.jsonl`
- Create: `tests/fixtures/trace/paths-rules/rule7a-unknown-rw.jsonl`
- Create: `tests/fixtures/trace/paths-rules/rule7b-unknown-ro.jsonl`
- Create: `tests/fixtures/trace/paths-rules/collision-mixed-class.jsonl`

The single most rule-heavy module. Lock the seven-rule order from spec §5.2 in a module-level table. The aggregator collapses many file events into one entry per mount-relevant root (spec §5.3).

The fixture format: each `.jsonl` file is a runtime-phase event stream (one JSON object per line, exactly the shape of `open.jsonl` records) PLUS a leading line starting with `# expected:` that is itself a JSON object representing the expected classified output (a list of TracePath dicts). The test parser splits on the `# expected:` prefix.

- [ ] **Step 1: Create the rule-1 fixture (image_static)**

Write `tests/fixtures/trace/paths-rules/rule1-image-static.jsonl`:

```
# expected: [{"path":"/opt/unifi","ops":["read","stat"],"class":"image_static","by":["unifi"]}]
{"ts_ns":1,"pid":1,"comm":"unifi","path":"/opt/unifi/lib/server.jar","flags":0,"mode":0,"ret":3}
{"ts_ns":2,"pid":1,"comm":"unifi","path":"/opt/unifi/config/system.properties","flags":0,"mode":0,"ret":4}
```

(`flags=0` and `ret>=0` is a `read`; `stat` is harder to represent in open.jsonl since open implies the file was opened, but in our schema we map openat with flags & O_PATH==0 + ret>=0 → "read", which is good enough for the fixture; the analyzer just needs to detect the class and stable ops set. Adjust the expected `ops` to whatever the classifier actually produces.)

> **Note for implementer:** the exact ops set produced by the classifier depends on how it interprets `open.jsonl` records. Decide once during Step 3 implementation and pin it consistently across all fixtures. If you settle on "every successful open is a `read`", then `ops` is always `["read"]` for rule 1; update all fixture expecteds accordingly. The contract the test enforces is that the classifier produces the SAME ops shape for the same input.

- [ ] **Step 2: Create the remaining rule fixtures**

Write the seven other fixtures, one per rule, following the same `# expected:` header pattern:

`rule2-persistent-rw.jsonl`:
```
# expected: [{"path":"/var/lib/unifi","ops":["read","write"],"class":"persistent_rw","by":["mongod"]}]
{"ts_ns":1,"pid":1,"comm":"mongod","path":"/var/lib/unifi/db/wt.db","flags":2,"mode":420,"ret":3}
{"ts_ns":2,"pid":1,"comm":"mongod","path":"/var/lib/unifi/db/journal","flags":1,"mode":420,"ret":4}
```
(`flags=2` is `O_RDWR` → "write"; `flags=1` is `O_WRONLY` → "write".)

`rule3-ephemeral-rw.jsonl`:
```
# expected: [{"path":"/tmp","ops":["read","write"],"class":"ephemeral_rw","by":["app"]}]
{"ts_ns":1,"pid":1,"comm":"app","path":"/tmp/x","flags":1,"mode":420,"ret":3}
{"ts_ns":2,"pid":1,"comm":"app","path":"/tmp/sub/y","flags":1,"mode":420,"ret":4}
```

`rule4-host-config.jsonl`:
```
# expected: [{"path":"/etc/resolv.conf","ops":["read"],"class":"host_config_ro","by":["app"]}]
{"ts_ns":1,"pid":1,"comm":"app","path":"/etc/resolv.conf","flags":0,"mode":0,"ret":3}
```

`rule5-device.jsonl`:
```
# expected: [{"path":"/dev/nvidia0","ops":["read"],"class":"device","by":["app"]}]
{"ts_ns":1,"pid":1,"comm":"app","path":"/dev/nvidia0","flags":0,"mode":0,"ret":3}
```

`rule6-proc-sys-filtered.jsonl`:
```
# expected: []
{"ts_ns":1,"pid":1,"comm":"app","path":"/proc/self/status","flags":0,"mode":0,"ret":3}
{"ts_ns":2,"pid":1,"comm":"app","path":"/sys/kernel/btf/vmlinux","flags":0,"mode":0,"ret":4}
```

`rule7a-unknown-rw.jsonl`:
```
# expected: [{"path":"/srv/weird","ops":["read","write"],"class":"unknown_rw","by":["app"]}]
{"ts_ns":1,"pid":1,"comm":"app","path":"/srv/weird","flags":1,"mode":420,"ret":3}
```

`rule7b-unknown-ro.jsonl`:
```
# expected: [{"path":"/srv/weird-ro","ops":["read"],"class":"unknown_ro","by":["app"]}]
{"ts_ns":1,"pid":1,"comm":"app","path":"/srv/weird-ro","flags":0,"mode":0,"ret":3}
```

`collision-mixed-class.jsonl` (rule 1 read + rule 7a write under the same `/opt/x` root):
```
# expected: [{"path":"/opt/x","ops":["read","write"],"class":"unknown_rw","by":["app"]}]
{"ts_ns":1,"pid":1,"comm":"app","path":"/opt/x/data.bin","flags":0,"mode":0,"ret":3}
{"ts_ns":2,"pid":1,"comm":"app","path":"/opt/x/cache","flags":1,"mode":420,"ret":4}
```

- [ ] **Step 3: Write the failing test (parametrized over fixtures)**

Write `tests/unit/analyze/test_paths.py`:

```python
"""Tests for analyze.paths classifier + aggregation, parametrized over fixtures."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from containerizer.analyze.paths import classify_runtime

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "trace" / "paths-rules"


def _load(path: Path) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    expected: list[dict[str, object]] = []
    events: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("# expected:"):
            expected = json.loads(line[len("# expected:"):].strip())
        elif line.startswith("{"):
            events.append(json.loads(line))
    return events, expected


@pytest.mark.parametrize("fixture", sorted(FIXTURES.glob("*.jsonl")), ids=lambda p: p.name)
def test_rule_classification(fixture: Path) -> None:
    events, expected = _load(fixture)
    aggregated = classify_runtime(events)
    # Compare as JSON to neutralize Pydantic field ordering vs dict ordering.
    actual = [
        json.loads(p.model_dump_json(by_alias=True)) for p in aggregated
    ]
    # Sort both sides by path for deterministic compare.
    actual.sort(key=lambda x: x["path"])
    expected.sort(key=lambda x: x["path"])
    assert actual == expected
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `pytest tests/unit/analyze/test_paths.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 5: Implement `paths.py`**

Write `src/containerizer/analyze/paths.py`:

```python
"""Path classifier (7 rules, first match wins) + aggregation.

See spec §5.2 (rules table) and §5.3 (aggregation).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Iterable, Literal

from containerizer.analyze.schema import TracePath

# open(2) flag bits we care about.
O_WRONLY = 1
O_RDWR = 2
O_CREAT = 64

# Rule classes (literal type names match TracePath.class_).
Klass = Literal[
    "image_static",
    "persistent_rw",
    "ephemeral_rw",
    "host_config_ro",
    "device",
    "unknown_rw",
    "unknown_ro",
]

IMAGE_STATIC_PREFIXES = ("/opt/", "/usr/lib/", "/usr/share/")
PERSISTENT_ROOTS = ("/var/lib/", "/var/log/", "/var/spool/")
EPHEMERAL_ROOTS = ("/tmp/", "/run/", "/var/run/", "/var/tmp/", "/dev/shm/")
HOST_CONFIG_PATHS = frozenset({
    "/etc/resolv.conf",
    "/etc/hosts",
    "/etc/localtime",
    "/etc/timezone",
})
FILTERED_ROOTS = ("/proc/", "/sys/")


@dataclass
class _RawPathEvent:
    path: str
    op: Literal["read", "write", "mkdir", "stat", "exec"]
    comm: str


def classify_runtime(events: Iterable[dict[str, object]]) -> list[TracePath]:
    """Take a list of open.jsonl-shaped records (runtime phase only) and
    return aggregated TracePath entries (one per mount-relevant root)."""

    raw = [_to_raw(e) for e in events if isinstance(e.get("path"), str)]
    # Filter rule 6 first — /proc, /sys never reach aggregation.
    raw = [r for r in raw if not _is_filtered(r.path)]

    # Bucket by (class, aggregation_key)
    buckets: dict[tuple[Klass, str], tuple[set[str], set[str]]] = {}
    for r in raw:
        klass, agg_key = _classify_one(r)
        ops, comms = buckets.setdefault((klass, agg_key), (set(), set()))
        ops.add(r.op)
        comms.add(r.comm)

    # Detect collisions: same agg_key under different classes that include
    # both image_static (read-only) AND a write-emitting class. Promote
    # whole aggregate to unknown_rw.
    by_key: dict[str, list[Klass]] = {}
    for (klass, agg_key), _ in buckets.items():
        by_key.setdefault(agg_key, []).append(klass)

    collided: set[str] = set()
    for agg_key, classes in by_key.items():
        if "image_static" in classes and any(
            k.endswith("_rw") for k in classes if k != "image_static"
        ):
            collided.add(agg_key)

    out: list[TracePath] = []
    if collided:
        # Merge all entries under a collided key into one unknown_rw aggregate.
        merged: dict[str, tuple[set[str], set[str]]] = {}
        for (klass, agg_key), (ops, comms) in buckets.items():
            if agg_key in collided:
                m_ops, m_comms = merged.setdefault(agg_key, (set(), set()))
                m_ops.update(ops)
                m_comms.update(comms)
        for agg_key, (ops, comms) in merged.items():
            out.append(
                TracePath(
                    path=agg_key,
                    ops=sorted(ops),
                    class_="unknown_rw",
                    by=sorted(comms),
                )
            )
        # Then add non-collided entries.
        for (klass, agg_key), (ops, comms) in buckets.items():
            if agg_key in collided:
                continue
            out.append(
                TracePath(
                    path=agg_key,
                    ops=sorted(ops),
                    class_=klass,
                    by=sorted(comms),
                )
            )
    else:
        for (klass, agg_key), (ops, comms) in buckets.items():
            out.append(
                TracePath(
                    path=agg_key,
                    ops=sorted(ops),
                    class_=klass,
                    by=sorted(comms),
                )
            )
    out.sort(key=lambda p: p.path)
    return out


def _to_raw(e: dict[str, object]) -> _RawPathEvent:
    path = str(e.get("path", ""))
    flags = int(e.get("flags", 0) or 0)
    op: Literal["read", "write", "mkdir", "stat", "exec"]
    if flags & (O_WRONLY | O_RDWR):
        op = "write"
    else:
        op = "read"
    return _RawPathEvent(path=path, op=op, comm=str(e.get("comm", "?")))


def _is_filtered(path: str) -> bool:
    return any(path == r.rstrip("/") or path.startswith(r) for r in FILTERED_ROOTS)


def _classify_one(r: _RawPathEvent) -> tuple[Klass, str]:
    p = r.path
    # Rule 4 — exact match host config (before rule 1 since these live
    # under /etc but aren't covered by /etc/* in rule 1).
    if p in HOST_CONFIG_PATHS:
        return ("host_config_ro", p)
    # Rule 5 — /dev/<leaf>
    if p.startswith("/dev/"):
        return ("device", p)
    # Rule 1 — image_static (only if op is non-write)
    for prefix in IMAGE_STATIC_PREFIXES:
        if p.startswith(prefix):
            key = _first_component_under(p, prefix)
            if r.op == "write":
                return ("unknown_rw", key)
            return ("image_static", key)
    # Rule 2 — persistent_rw (only if write)
    for prefix in PERSISTENT_ROOTS:
        if p.startswith(prefix):
            key = _first_component_under(p, prefix)
            if r.op == "write":
                return ("persistent_rw", key)
            # read under persistent root with no writes anywhere — treat as
            # unknown_ro so the user notices. Rule says "AND write ∈ ops",
            # so a pure read here doesn't match rule 2.
            return ("unknown_ro", p)
    # Rule 3 — ephemeral_rw (only if write)
    for prefix in EPHEMERAL_ROOTS:
        if p.startswith(prefix):
            key = prefix.rstrip("/")
            if r.op == "write":
                return ("ephemeral_rw", key)
            return ("unknown_ro", p)
    # Rule 7 — fallthrough
    if r.op == "write":
        return ("unknown_rw", p)
    return ("unknown_ro", p)


def _first_component_under(p: str, prefix: str) -> str:
    """For p like '/opt/unifi/lib/x' and prefix '/opt/', return '/opt/unifi'."""
    rest = p[len(prefix):]
    first = rest.split("/", 1)[0]
    return prefix.rstrip("/") + "/" + first
```

- [ ] **Step 6: Run the tests, fix fixture expecteds as needed**

Run: `pytest tests/unit/analyze/test_paths.py -v`

Expected: 9 fixtures discovered (one per `.jsonl` file). At least the simple ones should pass. For each test that fails, decide whether the classifier needs adjusting OR the fixture's `# expected:` needs updating; the contract is "the classifier matches the spec's intent and the fixtures match the classifier's actual behavior".

- [ ] **Step 7: Iterate until green, then gate + commit**

```
ruff check . && ruff format --check . && mypy src tests && pytest
git -c user.email="github.v5f9w@bitbucket.onl" \
    -c user.signingkey=BE707B220C995478 \
    commit -S -m "feat(analyze): paths.py — 7-rule classifier + aggregation"
```

---

## Task 6: `ports.py` — bind.jsonl → TracePort list

**Issue:** #38.

**Files:**
- Create: `src/containerizer/analyze/ports.py`
- Create: `tests/unit/analyze/test_ports.py`

Dedup on `(port, proto, comm)`. Output one `TracePort` per unique tuple. `ipv4`/`ipv6` flags set from family.

- [ ] **Step 1: Write the failing tests**

Write `tests/unit/analyze/test_ports.py`:

```python
"""Tests for analyze.ports."""

from __future__ import annotations

from containerizer.analyze.ports import aggregate_ports


def test_dedup_per_port_proto_comm() -> None:
    events = [
        {"family": 2, "port": 8443, "proto": "tcp", "comm": "unifi"},
        {"family": 2, "port": 8443, "proto": "tcp", "comm": "unifi"},  # dup
        {"family": 10, "port": 8443, "proto": "tcp", "comm": "unifi"},  # v6 same comm
    ]
    aggregated = aggregate_ports(events)
    assert len(aggregated) == 1
    p = aggregated[0]
    assert p.port == 8443
    assert p.proto == "tcp"
    assert p.by == "unifi"
    assert p.ipv4 is True
    assert p.ipv6 is True


def test_distinct_comm_separate_entries() -> None:
    events = [
        {"family": 2, "port": 5432, "proto": "tcp", "comm": "postgres"},
        {"family": 2, "port": 5432, "proto": "tcp", "comm": "pgbouncer"},
    ]
    assert len(aggregate_ports(events)) == 2


def test_unix_and_unknown_proto_kept() -> None:
    events = [
        {"family": 1, "port": 0, "proto": "unix", "comm": "app"},
        {"family": 2, "port": 7777, "proto": "?", "comm": "app"},
    ]
    aggregated = aggregate_ports(events)
    protos = sorted(p.proto for p in aggregated)
    assert protos == ["?", "unix"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/analyze/test_ports.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `ports.py`**

Write `src/containerizer/analyze/ports.py`:

```python
"""bind.jsonl events -> TracePort list (one per (port, proto, comm))."""

from __future__ import annotations

from typing import Iterable

from containerizer.analyze.schema import TracePort

AF_INET = 2
AF_INET6 = 10


def aggregate_ports(events: Iterable[dict[str, object]]) -> list[TracePort]:
    """Dedup bind events on (port, proto, comm). ipv4/ipv6 OR across families."""
    buckets: dict[tuple[int, str, str], list[bool]] = {}
    for e in events:
        port = int(e.get("port", 0) or 0)
        proto = str(e.get("proto", "?"))
        comm = str(e.get("comm", "?"))
        family = int(e.get("family", 0) or 0)
        key = (port, proto, comm)
        v4_v6 = buckets.setdefault(key, [False, False])
        if family == AF_INET:
            v4_v6[0] = True
        elif family == AF_INET6:
            v4_v6[1] = True
    out: list[TracePort] = []
    for (port, proto, comm), (v4, v6) in buckets.items():
        if proto not in ("tcp", "udp", "unix", "?"):
            continue
        out.append(
            TracePort(
                port=port,
                proto=proto,  # type: ignore[arg-type]
                by=comm,
                ipv4=v4,
                ipv6=v6,
            )
        )
    out.sort(key=lambda p: (p.proto, p.port, p.by))
    return out
```

- [ ] **Step 4: Run tests + gate + commit**

```
pytest tests/unit/analyze/test_ports.py -v
ruff check . && ruff format --check . && mypy src tests && pytest
git -c user.email="github.v5f9w@bitbucket.onl" \
    -c user.signingkey=BE707B220C995478 \
    commit -S -m "feat(analyze): ports.py — bind.jsonl dedup"
```

---

## Task 7: `caps.py` — capability dedup + superset filter

**Issue:** #38.

**Files:**
- Create: `src/containerizer/analyze/caps.py`
- Create: `tests/unit/analyze/test_caps.py`

Dedup `capable.jsonl` capability names. Drop subset-of-superset entries (e.g., `CAP_DAC_READ_SEARCH` when `CAP_DAC_OVERRIDE` is present).

- [ ] **Step 1: Write the failing tests**

Write `tests/unit/analyze/test_caps.py`:

```python
"""Tests for analyze.caps."""

from __future__ import annotations

from containerizer.analyze.caps import aggregate_caps


def test_basic_dedup() -> None:
    events = [
        {"cap_name": "CAP_NET_BIND_SERVICE"},
        {"cap_name": "CAP_NET_BIND_SERVICE"},
        {"cap_name": "CAP_CHOWN"},
    ]
    assert aggregate_caps(events) == ["CAP_CHOWN", "CAP_NET_BIND_SERVICE"]


def test_dac_superset_filter() -> None:
    events = [
        {"cap_name": "CAP_DAC_OVERRIDE"},
        {"cap_name": "CAP_DAC_READ_SEARCH"},
    ]
    # CAP_DAC_OVERRIDE includes CAP_DAC_READ_SEARCH; latter dropped.
    assert aggregate_caps(events) == ["CAP_DAC_OVERRIDE"]


def test_kept_when_superset_absent() -> None:
    events = [{"cap_name": "CAP_DAC_READ_SEARCH"}]
    assert aggregate_caps(events) == ["CAP_DAC_READ_SEARCH"]


def test_alternative_field_name_capa() -> None:
    # Some bcc capable variants emit "cap" instead of "cap_name"; tolerate.
    events = [{"cap": "CAP_NET_RAW"}]
    assert aggregate_caps(events) == ["CAP_NET_RAW"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/analyze/test_caps.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `caps.py`**

Write `src/containerizer/analyze/caps.py`:

```python
"""capable.jsonl -> deduped + superset-filtered capability list."""

from __future__ import annotations

from typing import Iterable

# {superset_cap: {capabilities subsumed by it}}
SUPERSETS: dict[str, frozenset[str]] = {
    "CAP_DAC_OVERRIDE": frozenset({"CAP_DAC_READ_SEARCH"}),
    "CAP_SYS_ADMIN": frozenset({"CAP_BPF", "CAP_PERFMON"}),
    "CAP_NET_ADMIN": frozenset({"CAP_NET_RAW"}),
}


def aggregate_caps(events: Iterable[dict[str, object]]) -> list[str]:
    seen: set[str] = set()
    for e in events:
        name = e.get("cap_name") or e.get("cap")
        if isinstance(name, str):
            seen.add(name)
    # Drop subsumed caps when their superset is present.
    for superset, subsumed in SUPERSETS.items():
        if superset in seen:
            seen -= subsumed
    return sorted(seen)
```

- [ ] **Step 4: Run tests + gate + commit**

```
pytest tests/unit/analyze/test_caps.py -v
ruff check . && ruff format --check . && mypy src tests && pytest
git -c user.email="github.v5f9w@bitbucket.onl" \
    -c user.signingkey=BE707B220C995478 \
    commit -S -m "feat(analyze): caps.py — capability dedup + superset filter"
```

---

## Task 8: `syscalls.py` + `execs.py`

**Issue:** #38.

**Files:**
- Create: `src/containerizer/analyze/syscalls.py`
- Create: `src/containerizer/analyze/execs.py`
- Create: `tests/unit/analyze/test_syscalls.py`
- Create: `tests/unit/analyze/test_execs.py`

Both modules consume `syscalls.jsonl`. `syscalls.py` returns sorted unique `syscall_id` ints. `execs.py` filters to execve events and returns sorted unique comm strings.

- [ ] **Step 1: Write failing tests for syscalls.py**

Write `tests/unit/analyze/test_syscalls.py`:

```python
"""Tests for analyze.syscalls."""

from __future__ import annotations

from containerizer.analyze.syscalls import aggregate_syscalls


def test_sorted_unique() -> None:
    events = [
        {"syscall_id": 5, "pid": 1, "count": 10},
        {"syscall_id": 1, "pid": 1, "count": 3},
        {"syscall_id": 5, "pid": 2, "count": 1},
        {"syscall_id": 3, "pid": 1, "count": 2},
    ]
    assert aggregate_syscalls(events) == [1, 3, 5]


def test_empty() -> None:
    assert aggregate_syscalls([]) == []


def test_skips_missing_syscall_id() -> None:
    events = [{"pid": 1, "count": 1}, {"syscall_id": 42}]
    assert aggregate_syscalls(events) == [42]
```

- [ ] **Step 2: Write failing tests for execs.py**

Write `tests/unit/analyze/test_execs.py`:

```python
"""Tests for analyze.execs."""

from __future__ import annotations

from containerizer.analyze.execs import aggregate_execs

SYS_EXECVE = 59  # x86_64


def test_filters_to_execve_and_dedups() -> None:
    events = [
        {"syscall_id": SYS_EXECVE, "comm": "java"},
        {"syscall_id": SYS_EXECVE, "comm": "mongod"},
        {"syscall_id": SYS_EXECVE, "comm": "java"},
        {"syscall_id": 1, "comm": "irrelevant"},
    ]
    assert aggregate_execs(events) == ["java", "mongod"]


def test_empty() -> None:
    assert aggregate_execs([]) == []
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/unit/analyze/test_syscalls.py tests/unit/analyze/test_execs.py -v`
Expected: FAIL.

- [ ] **Step 4: Implement `syscalls.py`**

Write `src/containerizer/analyze/syscalls.py`:

```python
"""syscalls.jsonl -> sorted unique syscall_id ints (runtime phase events)."""

from __future__ import annotations

from typing import Iterable


def aggregate_syscalls(events: Iterable[dict[str, object]]) -> list[int]:
    seen: set[int] = set()
    for e in events:
        sid = e.get("syscall_id")
        if isinstance(sid, int):
            seen.add(sid)
    return sorted(seen)
```

- [ ] **Step 5: Implement `execs.py`**

Write `src/containerizer/analyze/execs.py`:

```python
"""SYS_execve filter over syscalls.jsonl -> sorted unique comm list."""

from __future__ import annotations

from typing import Iterable

# syscall numbers from the kernel; x86_64-only for M3.
SYS_EXECVE_X86_64 = 59


def aggregate_execs(events: Iterable[dict[str, object]]) -> list[str]:
    seen: set[str] = set()
    for e in events:
        if e.get("syscall_id") != SYS_EXECVE_X86_64:
            continue
        comm = e.get("comm")
        if isinstance(comm, str):
            seen.add(comm)
    return sorted(seen)
```

- [ ] **Step 6: Run tests + gate + commit**

```
pytest tests/unit/analyze/test_syscalls.py tests/unit/analyze/test_execs.py -v
ruff check . && ruff format --check . && mypy src tests && pytest
git -c user.email="github.v5f9w@bitbucket.onl" \
    -c user.signingkey=BE707B220C995478 \
    commit -S -m "feat(analyze): syscalls.py + execs.py — runtime-phase aggregators"
```

---

## Task 9: `derive.py` — TraceJson → PolicyJson

**Issue:** #39.

**Files:**
- Create: `src/containerizer/analyze/derive.py`
- Create: `tests/unit/analyze/test_derive.py`

The policy-decision module. Every default rule from spec §5.6 lives here.

- [ ] **Step 1: Write the failing tests**

Write `tests/unit/analyze/test_derive.py`:

```python
"""Tests for analyze.derive."""

from __future__ import annotations

from containerizer.analyze.derive import derive_policy
from containerizer.analyze.schema import (
    TraceJson,
    TraceOutbound,
    TracePath,
    TracePhase,
    TracePort,
)

EMPTY_PHASE = TracePhase(
    duration_s=0.0,
    paths=[],
    ports=[],
    outbound=[],
    caps=[],
    syscalls=[],
    execs=[],
)


def _make_trace(
    *,
    install: TracePhase = EMPTY_PHASE,
    runtime: TracePhase = EMPTY_PHASE,
    marker: str = "COMPLETE",
    warnings: list[str] | None = None,
) -> TraceJson:
    return TraceJson(
        phase_marker_ns=100 if marker == "COMPLETE" else None,
        marker=marker,  # type: ignore[arg-type]
        install=install,
        runtime=runtime,
        warnings=warnings or [],
    )


def test_systemd_heuristic_true_when_execs_include_systemd() -> None:
    runtime = TracePhase(
        duration_s=1.0, paths=[], ports=[], outbound=[],
        caps=[], syscalls=[], execs=["systemd", "java"],
    )
    policy = derive_policy(_make_trace(runtime=runtime))
    assert policy.image.systemd_required is True
    assert policy.image.entrypoint == ["/sbin/init"]


def test_systemd_heuristic_false_emits_sentinel_entrypoint() -> None:
    runtime = TracePhase(
        duration_s=1.0, paths=[], ports=[], outbound=[],
        caps=[], syscalls=[], execs=["java"],
    )
    policy = derive_policy(_make_trace(runtime=runtime))
    assert policy.image.systemd_required is False
    assert policy.image.entrypoint == ["__UNSET__"]


def test_conservative_defaults_in_minimal_trace() -> None:
    policy = derive_policy(_make_trace())
    assert policy.image.apt_packages == []
    assert policy.image.installer_path == "/installer"
    assert policy.image.post_install_cleanup == ["/var/cache/apt/archives/*", "/installer"]
    assert policy.runtime.read_only_rootfs is False
    assert policy.runtime.no_new_privileges is True
    assert policy.runtime.caps_drop == ["ALL"]


def test_volumes_from_persistent_rw_paths() -> None:
    runtime = TracePhase(
        duration_s=1.0,
        paths=[
            TracePath(path="/var/lib/unifi", ops=["read", "write"], class_="persistent_rw", by=["m"]),
            TracePath(path="/var/log/unifi", ops=["write"], class_="persistent_rw", by=["m"]),
        ],
        ports=[], outbound=[], caps=[], syscalls=[], execs=[],
    )
    policy = derive_policy(_make_trace(runtime=runtime))
    names = sorted(v.name for v in policy.runtime.volumes)
    mounts = sorted(v.mount for v in policy.runtime.volumes)
    assert mounts == ["/var/lib/unifi", "/var/log/unifi"]
    # Both leaf components are "unifi"; expect disambiguation.
    assert "unifi-data" in names
    assert any(n != "unifi-data" for n in names)


def test_tmpfs_from_ephemeral_rw_paths() -> None:
    runtime = TracePhase(
        duration_s=1.0,
        paths=[
            TracePath(path="/tmp", ops=["write"], class_="ephemeral_rw", by=["x"]),
            TracePath(path="/run", ops=["write"], class_="ephemeral_rw", by=["x"]),
        ],
        ports=[], outbound=[], caps=[], syscalls=[], execs=[],
    )
    policy = derive_policy(_make_trace(runtime=runtime))
    assert sorted(policy.runtime.tmpfs) == ["/run", "/tmp"]


def test_binds_ro_from_host_config_paths() -> None:
    runtime = TracePhase(
        duration_s=1.0,
        paths=[TracePath(path="/etc/resolv.conf", ops=["read"], class_="host_config_ro", by=["x"])],
        ports=[], outbound=[], caps=[], syscalls=[], execs=[],
    )
    policy = derive_policy(_make_trace(runtime=runtime))
    assert policy.runtime.binds_ro == ["/etc/resolv.conf"]


def test_publish_ports_filtered_to_tcp_udp() -> None:
    runtime = TracePhase(
        duration_s=1.0, paths=[],
        ports=[
            TracePort(port=8443, proto="tcp", by="x", ipv4=True, ipv6=False),
            TracePort(port=0, proto="unix", by="x", ipv4=True, ipv6=False),
            TracePort(port=53, proto="udp", by="x", ipv4=True, ipv6=False),
        ],
        outbound=[], caps=[], syscalls=[], execs=[],
    )
    policy = derive_policy(_make_trace(runtime=runtime))
    protos = sorted(p.proto for p in policy.runtime.publish_ports)
    assert protos == ["tcp", "udp"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/analyze/test_derive.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `derive.py`**

Write `src/containerizer/analyze/derive.py`:

```python
"""Derive PolicyJson from TraceJson. All policy decisions live here."""

from __future__ import annotations

from containerizer.analyze.schema import (
    PolicyImage,
    PolicyJson,
    PolicyPort,
    PolicyRuntime,
    PolicyVolume,
    TraceJson,
)

SENTINEL_ENTRYPOINT = "__UNSET__"
SYSTEMD_COMMS = frozenset({"systemd", "systemctl", "init", "systemd-tmpfiles"})


def derive_policy(trace: TraceJson, *, probe_base: str = "ubuntu:24.04") -> PolicyJson:
    """Turn a normalized TraceJson into a PolicyJson the M4 generator can consume."""
    runtime = trace.runtime

    # Volumes from persistent_rw paths. Disambiguate name collisions by
    # prepending the parent's leaf component.
    persistent = [p for p in runtime.paths if p.class_ == "persistent_rw"]
    volumes = _derive_volumes(persistent)

    tmpfs = sorted({p.path for p in runtime.paths if p.class_ == "ephemeral_rw"})
    binds_ro = sorted({p.path for p in runtime.paths if p.class_ == "host_config_ro"})

    publish_ports = [
        PolicyPort(host=p.port, container=p.port, proto=p.proto)  # type: ignore[arg-type]
        for p in runtime.ports
        if p.proto in ("tcp", "udp")
    ]

    systemd_required = _systemd_required(trace)
    entrypoint = ["/sbin/init"] if systemd_required else [SENTINEL_ENTRYPOINT]

    return PolicyJson(
        image=PolicyImage(
            base=probe_base,
            apt_packages=[],
            installer_path="/installer",
            post_install_cleanup=["/var/cache/apt/archives/*", "/installer"],
            systemd_required=systemd_required,
            entrypoint=entrypoint,
        ),
        runtime=PolicyRuntime(
            volumes=volumes,
            tmpfs=tmpfs,
            binds_ro=binds_ro,
            publish_ports=publish_ports,
            caps_add=runtime.caps,
            seccomp_syscalls=runtime.syscalls,
            read_only_rootfs=False,
        ),
    )


def _derive_volumes(persistent_paths: list) -> list[PolicyVolume]:
    """Name each volume <leaf>-data; disambiguate collisions with parent leaf."""
    by_name: dict[str, list[str]] = {}
    for p in persistent_paths:
        leaf = p.path.rsplit("/", 1)[-1]
        name = f"{leaf}-data"
        by_name.setdefault(name, []).append(p.path)

    out: list[PolicyVolume] = []
    for name, paths in by_name.items():
        if len(paths) == 1:
            out.append(PolicyVolume(name=name, mount=paths[0]))
            continue
        # Collision — disambiguate with parent leaf.
        for path in paths:
            parts = path.rstrip("/").split("/")
            parent_leaf = parts[-2] if len(parts) >= 2 else "root"
            leaf = parts[-1]
            uniq = f"{parent_leaf}-{leaf}-data"
            out.append(PolicyVolume(name=uniq, mount=path))
    out.sort(key=lambda v: v.mount)
    return out


def _systemd_required(trace: TraceJson) -> bool:
    runtime_execs = set(trace.runtime.execs)
    if runtime_execs & SYSTEMD_COMMS:
        return True
    # Or any persistent_rw write to /etc/systemd/system/ during install
    for p in trace.install.paths:
        if p.class_ == "persistent_rw" and p.path.startswith("/etc/systemd/system"):
            return True
    return False
```

- [ ] **Step 4: Run tests + gate + commit**

```
pytest tests/unit/analyze/test_derive.py -v
ruff check . && ruff format --check . && mypy src tests && pytest
git -c user.email="github.v5f9w@bitbucket.onl" \
    -c user.signingkey=BE707B220C995478 \
    commit -S -m "feat(analyze): derive.py — TraceJson -> PolicyJson"
```

---

## Task 10: `writer.py` — pretty-printed deterministic JSON

**Issue:** #38, #39.

**Files:**
- Create: `src/containerizer/analyze/writer.py`
- Create: `tests/unit/analyze/test_writer.py`

`indent=2`, keys sorted, `class` alias serialization. The contract for golden-file stability.

- [ ] **Step 1: Write the failing tests**

Write `tests/unit/analyze/test_writer.py`:

```python
"""Tests for analyze.writer."""

from __future__ import annotations

import json
from pathlib import Path

from containerizer.analyze.schema import (
    PolicyImage,
    PolicyJson,
    PolicyRuntime,
    TraceJson,
    TracePath,
    TracePhase,
)
from containerizer.analyze.writer import write_policy_json, write_trace_json

EMPTY_PHASE = TracePhase(
    duration_s=0.0, paths=[], ports=[], outbound=[],
    caps=[], syscalls=[], execs=[],
)


def _trace_with_path() -> TraceJson:
    return TraceJson(
        phase_marker_ns=12,
        marker="COMPLETE",
        install=EMPTY_PHASE,
        runtime=TracePhase(
            duration_s=1.0,
            paths=[TracePath(path="/x", ops=["read"], class_="image_static", by=["a"])],
            ports=[], outbound=[], caps=[], syscalls=[], execs=[],
        ),
        warnings=[],
    )


def _policy_minimal() -> PolicyJson:
    return PolicyJson(
        image=PolicyImage(
            base="ubuntu:24.04",
            apt_packages=[],
            post_install_cleanup=["/installer"],
            systemd_required=False,
            entrypoint=["__UNSET__"],
        ),
        runtime=PolicyRuntime(
            volumes=[], tmpfs=[], binds_ro=[], publish_ports=[],
            caps_add=[], seccomp_syscalls=[], read_only_rootfs=False,
        ),
    )


def test_trace_writer_pretty_with_class_alias(tmp_path: Path) -> None:
    out = tmp_path / "trace.json"
    write_trace_json(_trace_with_path(), out)
    text = out.read_text(encoding="utf-8")
    assert "  " in text  # pretty
    obj = json.loads(text)
    assert obj["schema_version"] == 1
    assert obj["runtime"]["paths"][0]["class"] == "image_static"
    assert "class_" not in obj["runtime"]["paths"][0]


def test_policy_writer_round_trip(tmp_path: Path) -> None:
    out = tmp_path / "policy.json"
    write_policy_json(_policy_minimal(), out)
    obj = json.loads(out.read_text())
    pj = PolicyJson.model_validate(obj)
    assert pj == _policy_minimal()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/analyze/test_writer.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `writer.py`**

Write `src/containerizer/analyze/writer.py`:

```python
"""Serialize TraceJson and PolicyJson to disk with deterministic formatting."""

from __future__ import annotations

import json
from pathlib import Path

from containerizer.analyze.schema import PolicyJson, TraceJson


def write_trace_json(trace: TraceJson, path: Path) -> None:
    _write(trace.model_dump(by_alias=True, mode="json"), path)


def write_policy_json(policy: PolicyJson, path: Path) -> None:
    _write(policy.model_dump(by_alias=True, mode="json"), path)


def _write(obj: dict, path: Path) -> None:
    text = json.dumps(obj, indent=2, sort_keys=False)
    # We deliberately do NOT sort top-level keys because the Pydantic
    # field order encodes the spec's chosen presentation order
    # (schema_version first, etc.). Nested lists are produced in the
    # same order they came out of the aggregators (already sorted).
    path.write_text(text + "\n", encoding="utf-8")
```

- [ ] **Step 4: Run tests + gate + commit**

```
pytest tests/unit/analyze/test_writer.py -v
ruff check . && ruff format --check . && mypy src tests && pytest
git -c user.email="github.v5f9w@bitbucket.onl" \
    -c user.signingkey=BE707B220C995478 \
    commit -S -m "feat(analyze): writer.py — deterministic trace.json/policy.json"
```

---

## Task 11: `cli.py` — analyze subcommand + wiring

**Issue:** #38, #39.

**Files:**
- Create: `src/containerizer/analyze/cli.py`
- Modify: `src/containerizer/cli.py`
- Create: `tests/unit/analyze/test_cli.py`

The pipeline glue: read → split phases → build per-phase aggregates → assemble TraceJson → derive PolicyJson → write both. Click subcommand with `<trace-dir>` argument and `-o/--output-dir` option.

- [ ] **Step 1: Write the failing test**

Write `tests/unit/analyze/test_cli.py`:

```python
"""Tests for the `containerizer analyze` Click subcommand."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from containerizer.analyze.cli import analyze_cmd

COLLECTORS = ("open", "bind", "syscalls", "connect", "accept", "capable")


def _make_trace(tmp_path: Path) -> Path:
    d = tmp_path / "trace"
    d.mkdir()
    (d / "open.jsonl").write_text(
        '{"ts_ns":1,"pid":1,"comm":"app","path":"/var/lib/unifi/db","flags":1,"mode":420,"ret":3}\n',
        encoding="utf-8",
    )
    for name in ("bind", "syscalls", "connect", "accept", "capable"):
        (d / f"{name}.jsonl").write_text("", encoding="utf-8")
    (d / "FALLBACKS.json").write_text("{}", encoding="utf-8")
    (d / "PHASE_MARKER").write_text("monotonic_ns: 0\n", encoding="utf-8")
    (d / "COMPLETE").write_text("", encoding="utf-8")
    return d


def test_analyze_writes_both_files(tmp_path: Path) -> None:
    trace = _make_trace(tmp_path)
    out = tmp_path / "out"
    runner = CliRunner()
    result = runner.invoke(analyze_cmd, [str(trace), "-o", str(out)])
    assert result.exit_code == 0, result.output
    assert (out / "trace.json").exists()
    assert (out / "policy.json").exists()
    # Round-trip-validate as a smoke check.
    from containerizer.analyze.schema import PolicyJson, TraceJson
    TraceJson.model_validate_json((out / "trace.json").read_text())
    PolicyJson.model_validate_json((out / "policy.json").read_text())


def test_missing_trace_dir_errors(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(analyze_cmd, [str(tmp_path / "nope"), "-o", str(tmp_path / "out")])
    assert result.exit_code != 0


def test_main_cli_lists_analyze() -> None:
    from containerizer.cli import main
    runner = CliRunner()
    result = runner.invoke(main, ["--help"])
    assert "analyze" in result.output
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/analyze/test_cli.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `cli.py`**

Write `src/containerizer/analyze/cli.py`:

```python
"""`containerizer analyze <trace-dir> -o <out-dir>` Click subcommand."""

from __future__ import annotations

from pathlib import Path

import click

from containerizer.analyze.caps import aggregate_caps
from containerizer.analyze.derive import derive_policy
from containerizer.analyze.execs import aggregate_execs
from containerizer.analyze.paths import classify_runtime
from containerizer.analyze.phases import split_phases
from containerizer.analyze.ports import aggregate_ports
from containerizer.analyze.reader import read_trace_dir
from containerizer.analyze.schema import (
    TraceJson,
    TracePhase,
)
from containerizer.analyze.syscalls import aggregate_syscalls
from containerizer.analyze.writer import write_policy_json, write_trace_json


@click.command("analyze")
@click.argument(
    "trace_dir",
    type=click.Path(exists=True, file_okay=False, dir_okay=True, readable=True, path_type=Path),
)
@click.option(
    "-o",
    "--output-dir",
    required=True,
    type=click.Path(path_type=Path),
    help="Directory the trace.json and policy.json are written to.",
)
def analyze_cmd(trace_dir: Path, output_dir: Path) -> None:
    """Analyze TRACE_DIR (produced by `containerizer trace`) and emit
    trace.json + policy.json."""
    output_dir.mkdir(parents=True, exist_ok=True)
    bundle = read_trace_dir(trace_dir)
    trace = _assemble_trace_json(bundle)
    policy = derive_policy(trace)
    write_trace_json(trace, output_dir / "trace.json")
    write_policy_json(policy, output_dir / "policy.json")
    click.echo(f"wrote {output_dir / 'trace.json'} and {output_dir / 'policy.json'}")


def _assemble_trace_json(bundle) -> TraceJson:
    open_install, open_runtime = split_phases(
        bundle.events["open"], phase_marker_ns=bundle.phase_marker_ns, marker=bundle.marker
    )
    bind_install, bind_runtime = split_phases(
        bundle.events["bind"], phase_marker_ns=bundle.phase_marker_ns, marker=bundle.marker
    )
    sys_install, sys_runtime = split_phases(
        bundle.events["syscalls"], phase_marker_ns=bundle.phase_marker_ns, marker=bundle.marker
    )
    connect_install, connect_runtime = split_phases(
        bundle.events["connect"], phase_marker_ns=bundle.phase_marker_ns, marker=bundle.marker
    )
    capable_install, capable_runtime = split_phases(
        bundle.events["capable"], phase_marker_ns=bundle.phase_marker_ns, marker=bundle.marker
    )

    warnings = list(bundle.warnings)
    # FALLBACKS reasons surface as warnings too.
    for collector, info in bundle.fallbacks.items():
        warnings.append(
            f"collector {collector}: fellback to {info.get('fallback', '?')} "
            f"(reason: {info.get('reason', '?')})"
        )

    install = TracePhase(
        duration_s=0.0,  # M3 doesn't compute durations; M5 will.
        paths=classify_runtime(open_install),  # use same classifier; install paths included
        ports=aggregate_ports(bind_install),
        outbound=[],  # outbound aggregation comes from connect runtime only in M3
        caps=aggregate_caps(capable_install),
        syscalls=aggregate_syscalls(sys_install),
        execs=aggregate_execs(sys_install),
    )
    runtime = TracePhase(
        duration_s=0.0,
        paths=classify_runtime(open_runtime),
        ports=aggregate_ports(bind_runtime),
        outbound=[],  # spec §2 defers connect_runtime outbound rollup to M5.
        caps=aggregate_caps(capable_runtime),
        syscalls=aggregate_syscalls(sys_runtime),
        execs=aggregate_execs(sys_runtime),
    )
    # Silence unused-var lint for the deferred-aggregation event lists.
    _ = (connect_runtime, capable_runtime)

    return TraceJson(
        phase_marker_ns=bundle.phase_marker_ns,
        marker=bundle.marker,
        install=install,
        runtime=runtime,
        warnings=warnings,
    )
```

- [ ] **Step 4: Wire the subcommand into the main CLI**

Edit `src/containerizer/cli.py`. Add the import and registration:

```python
# Near the other imports at the top:
from containerizer.analyze.cli import analyze_cmd

# Near the bottom, after `main.add_command(trace_cmd)`:
main.add_command(analyze_cmd)
```

- [ ] **Step 5: Run tests + gate + commit**

```
pytest tests/unit/analyze/test_cli.py -v
ruff check . && ruff format --check . && mypy src tests && pytest
git -c user.email="github.v5f9w@bitbucket.onl" \
    -c user.signingkey=BE707B220C995478 \
    commit -S -m "feat(analyze): cli.py — wire analyze subcommand into main group"
```

---

## Task 12: Hand-crafted `synthetic-recorded/` fixture + golden files + helper script

**Issue:** #38, #39.

**Files:**
- Create: `tests/fixtures/trace/synthetic-recorded/open.jsonl`
- Create: `tests/fixtures/trace/synthetic-recorded/bind.jsonl`
- Create: `tests/fixtures/trace/synthetic-recorded/syscalls.jsonl`
- Create: `tests/fixtures/trace/synthetic-recorded/connect.jsonl`
- Create: `tests/fixtures/trace/synthetic-recorded/accept.jsonl`
- Create: `tests/fixtures/trace/synthetic-recorded/capable.jsonl`
- Create: `tests/fixtures/trace/synthetic-recorded/FALLBACKS.json`
- Create: `tests/fixtures/trace/synthetic-recorded/PHASE_MARKER`
- Create: `tests/fixtures/trace/synthetic-recorded/COMPLETE`
- Create: `tests/fixtures/analyze/expected/synthetic-trace.json`
- Create: `tests/fixtures/analyze/expected/synthetic-policy.json`
- Create: `sandbox/record-fixture.sh`

Hand-craft a small but realistic recorded trace + the golden outputs the analyzer should produce from it. Spec §7.4 envisioned capturing this from a real synthetic run, but the implementer doesn't need Linux/podman here: hand-write the bytes so the smoke test is self-contained.

- [ ] **Step 1: Hand-craft `synthetic-recorded/` JSONL streams**

The recorded trace should exercise at least: a persistent_rw path (rule 2), a host_config_ro path (rule 4), and a tcp bind. ts_ns values are scrubbed to small monotonic integers starting at 0 so the fixture is bit-stable.

Write `tests/fixtures/trace/synthetic-recorded/open.jsonl`:

```
{"ts_ns":100,"pid":10,"comm":"setup","path":"/var/lib/app/init.db","flags":65,"mode":420,"ret":3}
{"ts_ns":200,"pid":10,"comm":"setup","path":"/etc/resolv.conf","flags":0,"mode":0,"ret":4}
{"ts_ns":2000,"pid":11,"comm":"app","path":"/var/lib/app/state.db","flags":2,"mode":420,"ret":5}
{"ts_ns":2100,"pid":11,"comm":"app","path":"/etc/resolv.conf","flags":0,"mode":0,"ret":6}
```

Write `tests/fixtures/trace/synthetic-recorded/bind.jsonl`:

```
{"ts_ns":2200,"pid":11,"comm":"app","family":2,"addr":"127.0.0.1","port":7777,"proto":"tcp"}
```

Write `tests/fixtures/trace/synthetic-recorded/syscalls.jsonl`:

```
{"pid":10,"comm":"setup","syscall_id":59,"count":1,"first_ts_ns":50}
{"pid":11,"comm":"app","syscall_id":59,"count":1,"first_ts_ns":1500}
{"pid":11,"comm":"app","syscall_id":1,"count":100,"first_ts_ns":1800}
```

Write empty `connect.jsonl` (no outbound in the recorded trace):

```
```

Write empty `accept.jsonl`:

```
```

Write `tests/fixtures/trace/synthetic-recorded/capable.jsonl`:

```
{"ts_ns":2300,"pid":11,"comm":"app","cap":"CAP_NET_BIND_SERVICE","cap_name":"CAP_NET_BIND_SERVICE"}
```

Write `tests/fixtures/trace/synthetic-recorded/FALLBACKS.json`:

```
{}
```

Write `tests/fixtures/trace/synthetic-recorded/PHASE_MARKER`:

```
monotonic_ns: 1000
```

Write `tests/fixtures/trace/synthetic-recorded/COMPLETE` (empty file).

- [ ] **Step 2: Generate the golden trace.json**

Run the analyzer against the fixture to produce the candidate output, then commit it as the golden:

```
.venv\Scripts\containerizer.exe analyze tests/fixtures/trace/synthetic-recorded -o tests/fixtures/analyze/expected
# Rename the two outputs to the golden names:
mv tests/fixtures/analyze/expected/trace.json tests/fixtures/analyze/expected/synthetic-trace.json
mv tests/fixtures/analyze/expected/policy.json tests/fixtures/analyze/expected/synthetic-policy.json
```

(On Linux/Mac use `containerizer analyze ...` directly. On Windows in PowerShell, use the venv path above.)

- [ ] **Step 3: Manually inspect the goldens**

Open `synthetic-trace.json` and `synthetic-policy.json`. Verify:

- `trace.json.runtime.paths` contains entries for `/var/lib/app` (`persistent_rw`) and `/etc/resolv.conf` (`host_config_ro`).
- `trace.json.runtime.ports` has the tcp:7777 bind.
- `policy.json.runtime.volumes` includes `app-data` mounted at `/var/lib/app`.
- `policy.json.runtime.binds_ro` includes `/etc/resolv.conf`.
- `policy.json.runtime.publish_ports` includes `{"host":7777, "container":7777, "proto":"tcp"}`.

If any field is wrong, fix the analyzer (not the goldens) by jumping back to the relevant task.

- [ ] **Step 4: Write the regenerate helper `sandbox/record-fixture.sh`**

Write `sandbox/record-fixture.sh`:

```bash
#!/usr/bin/env bash
# Regenerate tests/fixtures/trace/synthetic-recorded/ from a real
# `containerizer trace` run against the synthetic installer. Not
# wired into CI — run by hand whenever the collector schema changes
# enough that the committed fixture goes stale.
#
# Usage (Linux/podman host):
#   bash sandbox/record-fixture.sh
#
# After this finishes, also re-run:
#   containerizer analyze tests/fixtures/trace/synthetic-recorded \
#       -o tests/fixtures/analyze/expected
#   mv tests/fixtures/analyze/expected/trace.json tests/fixtures/analyze/expected/synthetic-trace.json
#   mv tests/fixtures/analyze/expected/policy.json tests/fixtures/analyze/expected/synthetic-policy.json
# to refresh the goldens, then commit both.

set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
TRACE_OUT=$(mktemp -d)
RECORDED="$ROOT/tests/fixtures/trace/synthetic-recorded"

containerizer trace "$ROOT/tests/fixtures/trace/synthetic-installer.sh" -o "$TRACE_OUT"

# Scrub ts_ns + phase_marker_ns to monotonic-relative starting at 0
# so the fixture is bit-stable across recordings.
python3 - "$TRACE_OUT" "$RECORDED" <<'PY'
import json
import sys
from pathlib import Path

src = Path(sys.argv[1])
dst = Path(sys.argv[2])
dst.mkdir(parents=True, exist_ok=True)

# Find baseline ts_ns
baseline = None
for p in sorted(src.glob("*.jsonl")):
    for line in p.read_text().splitlines():
        if line.startswith("{"):
            r = json.loads(line)
            if isinstance(r.get("ts_ns"), int):
                baseline = min(baseline, r["ts_ns"]) if baseline is not None else r["ts_ns"]

if baseline is None:
    baseline = 0

def rewrite(line):
    if not line.startswith("{"):
        return line
    r = json.loads(line)
    if isinstance(r.get("ts_ns"), int):
        r["ts_ns"] -= baseline
    if isinstance(r.get("first_ts_ns"), int):
        r["first_ts_ns"] -= baseline
    return json.dumps(r)

for p in sorted(src.iterdir()):
    if p.name in ("COMPLETE", "PARTIAL", "FALLBACKS.json"):
        (dst / p.name).write_bytes(p.read_bytes())
    elif p.name == "PHASE_MARKER":
        text = p.read_text().strip()
        if text.startswith("monotonic_ns:"):
            ns = int(text.split(":", 1)[1].strip())
            (dst / p.name).write_text(f"monotonic_ns: {ns - baseline}\n")
        else:
            (dst / p.name).write_bytes(p.read_bytes())
    elif p.suffix == ".jsonl":
        lines = [rewrite(line) for line in p.read_text().splitlines()]
        (dst / p.name).write_text("\n".join(lines) + ("\n" if lines else ""))
PY
echo "wrote $RECORDED"
rm -rf "$TRACE_OUT"
```

`chmod +x sandbox/record-fixture.sh`.

- [ ] **Step 5: Run the full gate**

```
ruff check . && ruff format --check . && mypy src tests && pytest
```

Expected: PASS. The goldens aren't consumed by any test yet (that's Task 13), so adding them shouldn't break anything.

- [ ] **Step 6: Commit**

```
git -c user.email="github.v5f9w@bitbucket.onl" \
    -c user.signingkey=BE707B220C995478 \
    commit -S -m "test(analyze): hand-crafted synthetic-recorded fixture + goldens"
```

---

## Task 13: Integration smoke test against `synthetic-recorded/`

**Issue:** #38, #39.

**Files:**
- Create: `tests/integration/analyze/__init__.py`
- Create: `tests/integration/analyze/test_analyze_smoke.py`

End-to-end test that invokes `containerizer analyze` against the committed fixture and diffs the produced trace.json + policy.json against the goldens.

Note: this test is *not* marked `@pytest.mark.integration` because it doesn't require podman or any external resource — it just runs the analyzer against committed bytes. The `integration/` directory placement is for organization (parallel to `integration/trace/`), not the marker.

- [ ] **Step 1: Create the package marker**

Write `tests/integration/analyze/__init__.py`:

```python
```

- [ ] **Step 2: Write the smoke test**

Write `tests/integration/analyze/test_analyze_smoke.py`:

```python
"""End-to-end smoke test for `containerizer analyze` against committed fixture."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from containerizer.analyze.cli import analyze_cmd

REPO_ROOT = Path(__file__).resolve().parents[3]
RECORDED = REPO_ROOT / "tests" / "fixtures" / "trace" / "synthetic-recorded"
EXPECTED = REPO_ROOT / "tests" / "fixtures" / "analyze" / "expected"


@pytest.fixture
def golden_trace() -> dict:
    return json.loads((EXPECTED / "synthetic-trace.json").read_text(encoding="utf-8"))


@pytest.fixture
def golden_policy() -> dict:
    return json.loads((EXPECTED / "synthetic-policy.json").read_text(encoding="utf-8"))


def test_analyze_matches_golden(
    tmp_path: Path,
    golden_trace: dict,
    golden_policy: dict,
) -> None:
    out = tmp_path / "out"
    runner = CliRunner()
    result = runner.invoke(analyze_cmd, [str(RECORDED), "-o", str(out)])
    assert result.exit_code == 0, result.output

    actual_trace = json.loads((out / "trace.json").read_text(encoding="utf-8"))
    actual_policy = json.loads((out / "policy.json").read_text(encoding="utf-8"))

    assert actual_trace == golden_trace
    assert actual_policy == golden_policy
```

- [ ] **Step 3: Run the test**

Run: `pytest tests/integration/analyze/test_analyze_smoke.py -v`
Expected: PASS (Task 12 produced goldens that match what the analyzer now emits).

- [ ] **Step 4: Gate + commit**

```
ruff check . && ruff format --check . && mypy src tests && pytest
git -c user.email="github.v5f9w@bitbucket.onl" \
    -c user.signingkey=BE707B220C995478 \
    commit -S -m "test(analyze): integration smoke test against golden fixture"
```

---

## Task 14: MANUAL.md scenario + final PR landing

**Issue:** #38, #39.

**Files:**
- Modify: `MANUAL.md`

Document the new `analyze` subcommand for users. One scenario, ~10 lines.

- [ ] **Step 1: Read the current MANUAL.md to find the trace scenario format**

Read `MANUAL.md` and locate the M2 trace scenario (likely scenario 6). The M3 scenario mirrors its style.

- [ ] **Step 2: Add scenario 7 — analyze the trace**

After the trace scenario, append:

```markdown
## Scenario 7 — Analyze a captured trace

After `containerizer trace` produces a trace directory, run the analyzer to derive structured outputs:

```pwsh
PS> containerizer analyze .\unifi-trace\ -o .\unifi-analyze\
wrote unifi-analyze\trace.json and unifi-analyze\policy.json
```

`trace.json` is the normalized view of the raw collector streams (paths classified into image_static / persistent_rw / ephemeral_rw / host_config_ro / device / unknown_rw / unknown_ro, ports aggregated, capabilities deduped, syscalls listed). `policy.json` is the derived input to the M4 generator (volumes, tmpfs, binds_ro, publish_ports, caps_add, seccomp_syscalls, entrypoint). See `docs/superpowers/specs/2026-06-07-containerizer-m3-analyzer-policy.md` for the full schema.
```

- [ ] **Step 3: Gate + commit**

```
ruff check . && ruff format --check . && mypy src tests && pytest
git -c user.email="github.v5f9w@bitbucket.onl" \
    -c user.signingkey=BE707B220C995478 \
    commit -S -m "docs: MANUAL.md scenario 7 — containerizer analyze"
```

- [ ] **Step 4: Open the final PR**

```
gh pr create --title "feat(analyze): M3 analyzer + policy derivation" --body "$(cat <<'EOF'
## Summary

Closes #38, #39.

Implements the M3 milestone per `docs/superpowers/specs/2026-06-07-containerizer-m3-analyzer-policy.md`. New `src/containerizer/analyze/` package with one module per responsibility (schema, reader, phases, paths, ports, caps, syscalls, execs, derive, writer, cli). Single `containerizer analyze <trace-dir> -o <out-dir>` CLI subcommand writes `trace.json` (normalized) and `policy.json` (derived input for M4 generator).

Path classifier covers all 7 rules from spec §5.2 with aggregation per §5.3. Conservative defaults for `read_only_rootfs` (false), `apt_packages` ([]), and `entrypoint` (sentinel when no systemd detected) per spec §4.5–§4.6.

## Test plan

- [x] Unit tests for every module (parametrized over fixture jsonl files for the path classifier).
- [x] End-to-end smoke test (`tests/integration/analyze/test_analyze_smoke.py`) against the committed `synthetic-recorded/` fixture, gated by golden `trace.json` / `policy.json`.
- [x] Coverage stays ≥ 90%.
- [x] Lint + type gate green.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Wait for CI to go green on all branch-protection required checks, then squash-merge.

---

## Exit criteria

M3 is done when:

1. `containerizer analyze tests/fixtures/trace/synthetic-recorded -o <tmp>` produces a `trace.json` and `policy.json` matching the committed golden files (`tests/integration/analyze/test_analyze_smoke.py` passes).
2. All path-class rule fixtures classify per spec §5.2 and aggregate per spec §5.3 (`tests/unit/analyze/test_paths.py` is parametrized across 9 fixtures and all green).
3. PARTIAL trace handling produces a shaped-correctly `policy.json` with warnings populated (covered by `test_phases.py` and `test_derive.py`).
4. `PolicyJson.model_validate_json(<golden policy.json>)` and `TraceJson.model_validate_json(<golden trace.json>)` both succeed — i.e., the schemas accept their own output (verified by `test_writer.py`).
5. `pytest` (unit + integration, no `-m integration` exclusion) is green.

M3 is **not** required to:

- produce a useful policy for a real installer (M6 problem).
- detect a daemon entrypoint correctly (M5/M6 problem).
- flip `read_only_rootfs` on (M6).
- parse `apt_packages` out of `install.log` (M6).
- consume the strace fallback logs as events (#77 follow-up area; spec §4.3).
