"""Tests for the `containerizer analyze` Click subcommand."""

from __future__ import annotations

from pathlib import Path

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
