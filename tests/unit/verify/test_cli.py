"""Tests for the `containerizer verify` Click subcommand."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

from click.testing import CliRunner

from containerizer.analyze.schema import (
    TraceJson,
    TracePath,
    TracePhase,
    TracePort,
)
from containerizer.verify.cli import verify_cmd


def _empty_phase() -> TracePhase:
    return TracePhase(
        duration_s=1.0,
        paths=[],
        ports=[],
        outbound=[],
        caps=[],
        syscalls=[],
        execs=[],
    )


def _write_trace(
    path: Path,
    *,
    runtime: TracePhase,
    marker: str = "COMPLETE",
) -> None:
    t = TraceJson(
        phase_marker_ns=1000,
        marker=marker,  # type: ignore[arg-type]
        install=_empty_phase(),
        runtime=runtime,
        warnings=[],
    )
    path.write_text(t.model_dump_json(indent=2) + "\n", encoding="utf-8")


def _load_json(path: Path) -> dict[str, object]:
    return cast(dict[str, object], json.loads(path.read_text(encoding="utf-8")))


def test_verify_identical_traces_exits_zero(tmp_path: Path) -> None:
    orig = tmp_path / "orig.json"
    obs = tmp_path / "obs.json"
    runtime = TracePhase(
        duration_s=1.0,
        paths=[],
        ports=[],
        outbound=[],
        caps=["CAP_FOO"],
        syscalls=[1],
        execs=["app"],
    )
    _write_trace(orig, runtime=runtime)
    _write_trace(obs, runtime=runtime)
    out = tmp_path / "out"

    result = CliRunner().invoke(
        verify_cmd, ["--original", str(orig), "--observed", str(obs), "-o", str(out)]
    )
    assert result.exit_code == 0, result.output
    assert (out / "verify.json").exists()
    report = _load_json(out / "verify.json")
    diff = cast(dict[str, object], report["diff"])
    assert diff["new_paths"] == []
    assert diff["new_caps"] == []


def test_verify_new_event_exits_one_with_summary(tmp_path: Path) -> None:
    orig = tmp_path / "orig.json"
    obs = tmp_path / "obs.json"
    _write_trace(
        orig,
        runtime=TracePhase(
            duration_s=1.0,
            paths=[],
            ports=[],
            outbound=[],
            caps=[],
            syscalls=[],
            execs=[],
        ),
    )
    _write_trace(
        obs,
        runtime=TracePhase(
            duration_s=1.0,
            paths=[
                TracePath(  # type: ignore[call-arg]
                    path="/new", ops=["read"], class_="persistent_rw", by=["a"]
                )
            ],
            ports=[TracePort(port=80, proto="tcp", by="a", ipv4=True, ipv6=False)],
            outbound=[],
            caps=["CAP_X"],
            syscalls=[99],
            execs=["new"],
        ),
    )
    out = tmp_path / "out"

    result = CliRunner().invoke(
        verify_cmd, ["--original", str(orig), "--observed", str(obs), "-o", str(out)]
    )
    assert result.exit_code == 1, result.output
    assert "1 new paths" in result.stderr
    assert "1 new ports" in result.stderr
    assert "1 new caps" in result.stderr
    assert "1 new syscalls" in result.stderr
    assert "1 new execs" in result.stderr

    report = _load_json(out / "verify.json")
    diff = cast(dict[str, object], report["diff"])
    assert len(cast(list[object], diff["new_paths"])) == 1


def test_verify_missing_input_errors(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        verify_cmd,
        [
            "--original",
            str(tmp_path / "nope.json"),
            "--observed",
            str(tmp_path / "also-nope.json"),
            "-o",
            str(tmp_path / "out"),
        ],
    )
    assert result.exit_code != 0
    assert result.exit_code != 1  # 2-or-other operational error, not "diff found"


def test_verify_partial_marker_warning_surfaces(tmp_path: Path) -> None:
    orig = tmp_path / "orig.json"
    obs = tmp_path / "obs.json"
    runtime = _empty_phase()
    _write_trace(orig, runtime=runtime, marker="PARTIAL")
    _write_trace(obs, runtime=runtime)
    out = tmp_path / "out"

    result = CliRunner().invoke(
        verify_cmd, ["--original", str(orig), "--observed", str(obs), "-o", str(out)]
    )
    assert result.exit_code == 0, result.output
    report = _load_json(out / "verify.json")
    warnings = cast(list[str], report["warnings"])
    assert any("PARTIAL" in w for w in warnings)


def test_main_cli_lists_verify() -> None:
    from containerizer.cli import main

    result = CliRunner().invoke(main, ["--help"])
    assert "verify" in result.output
