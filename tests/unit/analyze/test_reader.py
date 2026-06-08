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
