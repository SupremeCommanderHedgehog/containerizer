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
    # Give every collector except `connect` at least one event so the trace
    # is not the "container did nothing" case; connect.jsonl is empty +
    # not in FALLBACKS -> warning only.
    for name in COLLECTORS:
        if name == "connect":
            continue
        (d / f"{name}.jsonl").write_text(
            '{"ts_ns":1}\n',
            encoding="utf-8",
        )
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


def test_bind_fallback_log_is_parsed_into_events(tmp_path: Path) -> None:
    """When bind.jsonl is missing AND bind is in FALLBACKS.json AND
    bind.fallback.log exists, the strace log is parsed and bind events
    populate the bundle -- closes the silent data gap on BTF-less hosts."""
    d = _make_complete_trace(tmp_path)
    (d / "bind.jsonl").unlink()
    (d / "FALLBACKS.json").write_text(
        json.dumps({"bind": {"reason": "BTF missing", "fallback": "strace -e trace=network"}}),
        encoding="utf-8",
    )
    bind_sa = '{sa_family=AF_INET, sin_port=htons(8080), sin_addr=inet_addr("0.0.0.0")}'
    (d / "bind.fallback.log").write_text(
        "[pid 1] socket(AF_INET, SOCK_STREAM, IPPROTO_TCP) = 5\n"
        f"[pid 1] bind(5, {bind_sa}, 16) = 0\n",
        encoding="utf-8",
    )
    bundle = read_trace_dir(d)
    assert len(bundle.events["bind"]) == 1
    assert bundle.events["bind"][0]["port"] == 8080
    assert bundle.events["bind"][0]["proto"] == "tcp"
    # Warning should mention that we recovered events, not the generic
    # "fallback recorded" message reserved for the no-recovery case.
    assert any("recovered" in w and "bind" in w for w in bundle.warnings)


def test_connect_fallback_log_is_parsed(tmp_path: Path) -> None:
    d = _make_complete_trace(tmp_path)
    (d / "connect.jsonl").unlink()
    (d / "FALLBACKS.json").write_text(
        json.dumps({"connect": {"reason": "BTF missing", "fallback": "strace -e trace=network"}}),
        encoding="utf-8",
    )
    connect_sa = '{sa_family=AF_INET, sin_port=htons(443), sin_addr=inet_addr("1.2.3.4")}'
    (d / "connect.fallback.log").write_text(
        f"[pid 1] connect(6, {connect_sa}, 16) = 0\n",
        encoding="utf-8",
    )
    bundle = read_trace_dir(d)
    assert len(bundle.events["connect"]) == 1
    assert bundle.events["connect"][0]["daddr"] == "1.2.3.4"


def test_accept_fallback_log_is_parsed(tmp_path: Path) -> None:
    d = _make_complete_trace(tmp_path)
    (d / "accept.jsonl").unlink()
    (d / "FALLBACKS.json").write_text(
        json.dumps({"accept": {"reason": "BTF missing", "fallback": "strace -e trace=network"}}),
        encoding="utf-8",
    )
    accept_sa = '{sa_family=AF_INET, sin_port=htons(54321), sin_addr=inet_addr("10.0.0.1")}'
    (d / "accept.fallback.log").write_text(
        f"[pid 1] accept4(5, {accept_sa}, [16], SOCK_CLOEXEC) = 6\n",
        encoding="utf-8",
    )
    bundle = read_trace_dir(d)
    assert len(bundle.events["accept"]) == 1
    assert bundle.events["accept"][0]["raddr"] == "10.0.0.1"


def test_fallback_in_manifest_without_log_file_warns_only(tmp_path: Path) -> None:
    """FALLBACKS.json claims a fallback was launched but no .fallback.log
    exists on disk (orchestrator killed strace before it wrote anything,
    or the fd race lost). Keep the existing 'fallback recorded' warning;
    don't crash."""
    d = _make_complete_trace(tmp_path)
    (d / "bind.jsonl").unlink()
    (d / "FALLBACKS.json").write_text(
        json.dumps({"bind": {"reason": "BTF missing", "fallback": "strace -e trace=network"}}),
        encoding="utf-8",
    )
    bundle = read_trace_dir(d)
    assert bundle.events["bind"] == []
    assert any("fallback recorded" in w for w in bundle.warnings)


def test_unparseable_collector_fallback_log_is_ignored(tmp_path: Path) -> None:
    """open/syscalls/capable fallbacks use strace domains we don't parse yet.
    The fallback log is left on disk for forensic value; the bundle stays
    empty + warns (current behavior preserved)."""
    d = _make_complete_trace(tmp_path)
    (d / "open.jsonl").unlink()
    (d / "FALLBACKS.json").write_text(
        json.dumps({"open": {"reason": "kheaders mismatch", "fallback": "strace -e trace=file"}}),
        encoding="utf-8",
    )
    (d / "open.fallback.log").write_text("anything here\n", encoding="utf-8")
    bundle = read_trace_dir(d)
    assert bundle.events["open"] == []
    assert any("fallback recorded" in w and "open" in w for w in bundle.warnings)
