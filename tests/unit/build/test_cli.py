"""CliRunner tests for `containerizer build` with the pipeline faked at module level."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from containerizer.build import cli as build_cli_module
from containerizer.build.cli import build_cmd
from containerizer.build.config import BuildResult
from containerizer.verify.schema import VerifyDiff, VerifyReport


def _ok_result(final_dir: Path) -> BuildResult:
    return BuildResult(
        final_dir=final_dir,
        intermediates_dir=None,
        verify=VerifyReport(
            original_marker="COMPLETE",
            observed_marker="COMPLETE",
            diff=VerifyDiff(
                new_paths=[],
                new_ports=[],
                new_caps=[],
                new_syscalls=[],
                new_execs=[],
            ),
        ),
    )


def test_missing_installer_exits_2(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        build_cmd,
        [
            str(tmp_path / "nope.bin"),
            "--name",
            "demo",
            "-o",
            str(tmp_path / "out"),
        ],
    )
    assert result.exit_code == 2


def test_preflight_failure_exits_2(tmp_path: Path) -> None:
    installer = tmp_path / "i.bin"
    installer.write_text("x", encoding="utf-8")
    runner = CliRunner()
    with patch.object(
        build_cli_module,
        "preflight_podman",
        side_effect=build_cli_module.PreflightError("no podman"),
    ):
        result = runner.invoke(
            build_cmd,
            [
                str(installer),
                "--name",
                "demo",
                "-o",
                str(tmp_path / "out"),
            ],
        )
    assert result.exit_code == 2
    assert "no podman" in result.stderr


def test_happy_path_exits_0_and_calls_pipeline(tmp_path: Path) -> None:
    installer = tmp_path / "i.bin"
    installer.write_text("x", encoding="utf-8")
    out = tmp_path / "out"

    captured: dict[str, object] = {}

    def fake_run_pipeline(config: object, **kwargs: object) -> BuildResult:
        captured["config"] = config
        captured["kwargs"] = kwargs
        return _ok_result(out / "demo")

    runner = CliRunner()
    with (
        patch.object(build_cli_module, "preflight_podman", return_value=None),
        patch.object(build_cli_module, "run_pipeline", side_effect=fake_run_pipeline),
    ):
        result = runner.invoke(
            build_cmd,
            [
                str(installer),
                "--name",
                "demo",
                "-o",
                str(out),
                "--verify-soak-seconds",
                "45",
                "--keep-intermediates",
            ],
        )

    assert result.exit_code == 0, result.output
    cfg = captured["config"]
    assert cfg.name == "demo"  # type: ignore[attr-defined]
    assert cfg.verify_soak_seconds == 45  # type: ignore[attr-defined]
    assert cfg.keep_intermediates is True  # type: ignore[attr-defined]


def test_non_empty_diff_warns_but_exits_0(tmp_path: Path) -> None:
    installer = tmp_path / "i.bin"
    installer.write_text("x", encoding="utf-8")
    out = tmp_path / "out"

    diff_result = BuildResult(
        final_dir=out / "demo",
        intermediates_dir=None,
        verify=VerifyReport(
            original_marker="COMPLETE",
            observed_marker="COMPLETE",
            diff=VerifyDiff(
                new_paths=[],
                new_ports=[],
                new_caps=["CAP_SYS_CHROOT"],
                new_syscalls=[],
                new_execs=[],
            ),
        ),
    )

    def fake_run_pipeline(config: object, **kwargs: object) -> BuildResult:
        return diff_result

    runner = CliRunner()
    with (
        patch.object(build_cli_module, "preflight_podman", return_value=None),
        patch.object(build_cli_module, "run_pipeline", side_effect=fake_run_pipeline),
    ):
        result = runner.invoke(
            build_cmd,
            [
                str(installer),
                "--name",
                "demo",
                "-o",
                str(out),
            ],
        )
    assert result.exit_code == 0
    assert "1 new caps" in result.stderr or "new caps" in result.stderr


def test_sentinel_skip_exits_0(tmp_path: Path) -> None:
    installer = tmp_path / "i.bin"
    installer.write_text("x", encoding="utf-8")
    out = tmp_path / "out"

    sentinel_result = BuildResult(
        final_dir=out / "demo",
        intermediates_dir=None,
        verify=None,
        skip_reason="sentinel",
    )

    runner = CliRunner()
    with (
        patch.object(build_cli_module, "preflight_podman", return_value=None),
        patch.object(build_cli_module, "run_pipeline", return_value=sentinel_result),
    ):
        result = runner.invoke(
            build_cmd,
            [
                str(installer),
                "--name",
                "demo",
                "-o",
                str(out),
            ],
        )
    assert result.exit_code == 0
    assert "skipped" in result.stderr.lower()


def test_install_trace_fn_passes_tty_from_stdin_isatty(tmp_path: Path) -> None:
    """`_default_install_trace_fn` must propagate sys.stdin.isatty() into the
    TraceRunner so interactive installers (UniFi etc.) get a TTY when the
    user is at a terminal, but stay non-TTY in CI/piped contexts."""
    installer = tmp_path / "i.bin"
    installer.write_text("x", encoding="utf-8")
    output = tmp_path / "trace"
    output.mkdir()

    captured: dict[str, object] = {}

    class FakeRunner:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

        def run(self) -> int:
            return 0

    class FakeImage:
        tag = "runner:fake"

        def __init__(self, *, sandbox_dir: Path) -> None:
            pass

        def exists(self) -> bool:
            return True

    with (
        patch.object(build_cli_module, "TraceRunner", FakeRunner),
        patch.object(build_cli_module, "RunnerImage", FakeImage),
        patch.object(build_cli_module.sys.stdin, "isatty", return_value=True),
    ):
        rc = build_cli_module._default_install_trace_fn(installer, None, output)
    assert rc == 0
    assert captured["tty"] is True

    captured.clear()
    with (
        patch.object(build_cli_module, "TraceRunner", FakeRunner),
        patch.object(build_cli_module, "RunnerImage", FakeImage),
        patch.object(build_cli_module.sys.stdin, "isatty", return_value=False),
    ):
        rc = build_cli_module._default_install_trace_fn(installer, None, output)
    assert rc == 0
    assert captured["tty"] is False


def test_pipeline_error_exits_1(tmp_path: Path) -> None:
    installer = tmp_path / "i.bin"
    installer.write_text("x", encoding="utf-8")
    out = tmp_path / "out"

    from containerizer.build.pipeline import PipelineError

    runner = CliRunner()
    with (
        patch.object(build_cli_module, "preflight_podman", return_value=None),
        patch.object(
            build_cli_module,
            "run_pipeline",
            side_effect=PipelineError("install trace did not finalise"),
        ),
    ):
        result = runner.invoke(
            build_cmd,
            [
                str(installer),
                "--name",
                "demo",
                "-o",
                str(out),
            ],
        )
    assert result.exit_code == 1
    assert "did not finalise" in result.stderr


def test_build_cli_plumbs_multi_deb_flags(tmp_path: Path, monkeypatch) -> None:
    """Issue #102: --installer / --apt-source / --apt-key reach BuildConfig."""
    from click.testing import CliRunner

    from containerizer.build import cli as build_cli
    from containerizer.build.config import BuildResult

    primary = tmp_path / "primary.deb"
    primary.write_bytes(b"!<arch>\n")
    extra = tmp_path / "extra.deb"
    extra.write_bytes(b"!<arch>\n")
    key = tmp_path / "mongo.gpg"
    key.write_bytes(b"\x00")
    out = tmp_path / "out"

    captured: dict[str, object] = {}

    def fake_run_pipeline(config, **kw):
        captured["config"] = config
        return BuildResult(final_dir=out / "x", intermediates_dir=None)

    monkeypatch.setattr(build_cli, "preflight_podman", lambda: None)
    monkeypatch.setattr(build_cli, "run_pipeline", fake_run_pipeline)
    monkeypatch.setattr(build_cli, "_print_summary", lambda r: None)

    result = CliRunner().invoke(
        build_cli.build_cmd,
        [
            str(primary),
            "--name",
            "x",
            "-o",
            str(out),
            "--installer",
            str(extra),
            "--apt-source",
            "deb http://y noble main",
            "--apt-key",
            str(key),
        ],
    )
    assert result.exit_code == 0, result.output
    cfg = captured["config"]
    assert cfg.extra_installers == (extra.resolve(),)
    assert cfg.apt_sources == ("deb http://y noble main",)
    assert cfg.apt_keys == (key.resolve(),)


def test_build_cli_no_longer_warns_about_start_cmd(tmp_path: Path, monkeypatch) -> None:
    """Issue #105: the 'has no effect' warning must be gone."""
    from click.testing import CliRunner

    from containerizer.build.cli import build_cmd

    installer = tmp_path / "foo.deb"
    installer.write_bytes(b"!<arch>\nfake")

    monkeypatch.setattr("containerizer.build.cli.preflight_podman", lambda: None)

    def _boom(*a, **kw):
        raise SystemExit(0)

    monkeypatch.setattr("containerizer.build.cli.run_pipeline", _boom)

    runner = CliRunner()
    result = runner.invoke(
        build_cmd,
        [str(installer), "--name", "foo", "--start-cmd", "/etc/init.d/foo start"],
    )
    output = result.output or ""
    assert "has no effect" not in output


def test_build_cli_start_ready_seconds_without_start_cmd_errors(
    tmp_path: Path, monkeypatch
) -> None:
    from click.testing import CliRunner

    from containerizer.build.cli import build_cmd

    installer = tmp_path / "foo.deb"
    installer.write_bytes(b"!<arch>\nfake")
    monkeypatch.setattr("containerizer.build.cli.preflight_podman", lambda: None)

    runner = CliRunner()
    result = runner.invoke(
        build_cmd,
        [str(installer), "--name", "foo", "--start-ready-seconds", "90"],
    )
    assert result.exit_code != 0
    err = result.output or ""
    assert "--start-ready-seconds requires --start-cmd" in err


def test_build_cli_accepts_start_cmd_and_ready_seconds_together(
    tmp_path: Path, monkeypatch
) -> None:
    from click.testing import CliRunner

    from containerizer.build.cli import build_cmd

    installer = tmp_path / "foo.deb"
    installer.write_bytes(b"!<arch>\nfake")
    monkeypatch.setattr("containerizer.build.cli.preflight_podman", lambda: None)
    captured = {}

    def _capture(config, **kw):
        captured["config"] = config
        raise SystemExit(0)

    monkeypatch.setattr("containerizer.build.cli.run_pipeline", _capture)

    runner = CliRunner()
    result = runner.invoke(
        build_cmd,
        [
            str(installer),
            "--name",
            "foo",
            "--start-cmd",
            "/etc/init.d/foo start",
            "--start-ready-seconds",
            "90",
        ],
    )
    assert result.exit_code == 0, result.output
    cfg = captured["config"]
    assert cfg.start_cmd == "/etc/init.d/foo start"
    assert cfg.start_ready_seconds == 90
    assert cfg.verify_soak_seconds is None
    assert cfg.effective_verify_soak_seconds == 90
