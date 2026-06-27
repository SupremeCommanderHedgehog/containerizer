"""Public-API tests for the assemble_trace_json helper promoted from analyze/cli.py."""

from __future__ import annotations

from pathlib import Path

from containerizer.analyze.assemble import assemble_trace_json
from containerizer.analyze.reader import TraceBundle, read_trace_dir
from containerizer.analyze.schema import TraceJson


def test_assemble_trace_json_from_synthetic_fixture() -> None:
    fixture = Path("tests/fixtures/trace/synthetic-recorded")
    bundle = read_trace_dir(fixture)

    result = assemble_trace_json(bundle)

    assert isinstance(result, TraceJson)
    assert result.marker in ("COMPLETE", "PARTIAL")
    assert result.runtime is not None
    assert result.install is not None


def test_assemble_propagates_start_cmd_from_bundle() -> None:
    bundle = TraceBundle(
        marker="COMPLETE",
        phase_marker_ns=100,
        fallbacks={},
        events={name: [] for name in ("open", "bind", "syscalls", "connect", "accept", "capable")},
        warnings=[],
        start_cmd="/etc/init.d/mongod start",
    )
    trace = assemble_trace_json(bundle)
    assert trace.start_cmd == "/etc/init.d/mongod start"
