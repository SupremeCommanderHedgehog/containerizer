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
