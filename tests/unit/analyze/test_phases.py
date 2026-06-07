"""Tests for analyze.phases."""

from __future__ import annotations

import json
from pathlib import Path

from containerizer.analyze.phases import split_phases

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "trace" / "phase-split"


def _load(name: str) -> list[dict[str, object]]:
    return [json.loads(line) for line in (FIXTURES / name).read_text().splitlines() if line]


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
