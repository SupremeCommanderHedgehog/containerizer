"""Tests for the `containerizer analyze` Click subcommand."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from containerizer.analyze.cli import SENTINEL_WARNING, _assemble_trace_json, analyze_cmd
from containerizer.analyze.reader import TraceBundle

COLLECTORS = ("open", "bind", "syscalls", "connect", "accept", "capable")


def _bundle(
    *,
    open_events: list[dict[str, object]] | None = None,
    sys_events: list[dict[str, object]] | None = None,
    phase_marker_ns: int = 1000,
) -> TraceBundle:
    """Build an in-memory TraceBundle for cli warning tests.

    Bypasses on-disk fixtures so each test asserts one warning behavior in
    isolation. All events flagged as runtime via ts_ns > phase_marker_ns.
    """
    empty: list[dict[str, object]] = []
    return TraceBundle(
        events={
            "open": open_events or empty,
            "bind": empty,
            "syscalls": sys_events or empty,
            "connect": empty,
            "accept": empty,
            "capable": empty,
        },
        phase_marker_ns=phase_marker_ns,
        marker="COMPLETE",
        warnings=[],
        fallbacks={},
    )


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


# --- spec §5.7 warning surface tests ---------------------------------------


def test_unknown_rw_emits_warning_per_aggregate() -> None:
    """Runtime path that falls through to unknown_rw must surface a warning."""
    bundle = _bundle(
        open_events=[
            # ts_ns > phase_marker_ns => runtime; flags=1 => write;
            # path not under any known prefix => rule 7 unknown_rw.
            {
                "ts_ns": 2000,
                "pid": 100,
                "comm": "app",
                "path": "/srv/mystery/data",
                "flags": 1,
                "mode": 420,
                "ret": 3,
            },
            # A second unknown_rw under a different path; one warning per aggregate.
            {
                "ts_ns": 2100,
                "pid": 100,
                "comm": "app",
                "path": "/srv/other/blob",
                "flags": 1,
                "mode": 420,
                "ret": 3,
            },
            # systemd exec so sentinel warning doesn't crowd the assertion.
            {
                "ts_ns": 2200,
                "pid": 1,
                "comm": "systemd",
                "path": "/sbin/init",
                "flags": 0,
                "mode": 0,
                "ret": 3,
            },
        ],
        sys_events=[
            {"syscall_id": 59, "comm": "systemd", "first_ts_ns": 2200, "pid": 1, "count": 1},
        ],
    )
    trace = _assemble_trace_json(bundle)
    rw_warnings = [w for w in trace.warnings if w.startswith("unknown_rw aggregate:")]
    assert len(rw_warnings) == 2
    assert "unknown_rw aggregate: /srv/mystery/data" in trace.warnings
    assert "unknown_rw aggregate: /srv/other/blob" in trace.warnings


def test_device_emits_warning_per_aggregate() -> None:
    """Runtime open on /dev/<x> must surface a per-aggregate device warning."""
    bundle = _bundle(
        open_events=[
            {
                "ts_ns": 2000,
                "pid": 100,
                "comm": "app",
                "path": "/dev/ttyUSB0",
                "flags": 2,
                "mode": 420,
                "ret": 3,
            },
            # systemd present to suppress the sentinel warning.
            {
                "ts_ns": 2100,
                "pid": 1,
                "comm": "systemd",
                "path": "/sbin/init",
                "flags": 0,
                "mode": 0,
                "ret": 3,
            },
        ],
        sys_events=[
            {"syscall_id": 59, "comm": "systemd", "first_ts_ns": 2100, "pid": 1, "count": 1},
        ],
    )
    trace = _assemble_trace_json(bundle)
    dev_warnings = [w for w in trace.warnings if w.startswith("device aggregate:")]
    assert dev_warnings == ["device aggregate: /dev/ttyUSB0"]


def test_sentinel_entrypoint_emits_warning() -> None:
    """When no recognizable daemon exec is seen, sentinel warning fires."""
    bundle = _bundle(
        open_events=[
            {
                "ts_ns": 2000,
                "pid": 100,
                "comm": "app",
                "path": "/var/lib/app/db",
                "flags": 1,
                "mode": 420,
                "ret": 3,
            },
        ],
        sys_events=[
            # execve of "app" only — no systemd / systemctl / init.
            {"syscall_id": 59, "comm": "app", "first_ts_ns": 2000, "pid": 100, "count": 1},
        ],
    )
    trace = _assemble_trace_json(bundle)
    assert SENTINEL_WARNING in trace.warnings
    # Spec-mandated exact text:
    assert SENTINEL_WARNING == "entrypoint is sentinel ['__UNSET__']; M4 must refuse this policy"


def test_systemd_required_suppresses_sentinel_warning() -> None:
    """When runtime execs include 'systemd', no sentinel warning is emitted."""
    bundle = _bundle(
        open_events=[
            {
                "ts_ns": 2000,
                "pid": 1,
                "comm": "systemd",
                "path": "/sbin/init",
                "flags": 0,
                "mode": 0,
                "ret": 3,
            },
        ],
        sys_events=[
            {"syscall_id": 59, "comm": "systemd", "first_ts_ns": 2000, "pid": 1, "count": 1},
        ],
    )
    trace = _assemble_trace_json(bundle)
    assert SENTINEL_WARNING not in trace.warnings
    assert not any(w.startswith("entrypoint is sentinel") for w in trace.warnings)
