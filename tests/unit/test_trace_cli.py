"""Tests for the `containerizer trace` Click subcommand."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from containerizer.cli import main
from containerizer.trace.cli import _podman_machine_is_running
from containerizer.trace.runner import OutputDirNotEmpty


def test_trace_help_lists_required_options() -> None:
    result = CliRunner().invoke(main, ["trace", "--help"])
    assert result.exit_code == 0
    assert "Statically analyse" not in result.output  # not the probe help
    assert "-o" in result.output or "--output-dir" in result.output
    assert "--force" in result.output


@patch("containerizer.trace.cli._podman_machine_is_running")
def test_trace_refuses_when_podman_machine_is_not_running(
    mock_machine: MagicMock, tmp_path: Path
) -> None:
    mock_machine.return_value = False
    installer = tmp_path / "fake-installer"
    installer.write_bytes(b"\x00")
    output = tmp_path / "out"

    result = CliRunner().invoke(main, ["trace", str(installer), "-o", str(output)])
    assert result.exit_code != 0
    assert "podman machine" in result.output.lower()
    assert "start" in result.output.lower()


@patch("containerizer.trace.cli.TraceRunner")
@patch("containerizer.trace.cli.RunnerImage")
@patch("containerizer.trace.cli._podman_machine_is_running")
def test_trace_builds_image_when_missing(
    mock_machine: MagicMock,
    mock_image_cls: MagicMock,
    mock_runner_cls: MagicMock,
    tmp_path: Path,
) -> None:
    mock_machine.return_value = True
    image = MagicMock()
    image.exists.return_value = False
    image.tag = "localhost/containerizer-runner:sha-abcdef12"
    mock_image_cls.return_value = image

    runner = MagicMock()
    runner.run.return_value = 0
    mock_runner_cls.return_value = runner

    installer = tmp_path / "fake-installer"
    installer.write_bytes(b"\x00")
    output = tmp_path / "out"
    output.mkdir()
    (output / "COMPLETE").write_text("", encoding="utf-8")  # written by orchestrator

    result = CliRunner().invoke(main, ["trace", str(installer), "-o", str(output)])
    assert result.exit_code == 0
    image.build.assert_called_once()


@patch("containerizer.trace.cli.TraceRunner")
@patch("containerizer.trace.cli.RunnerImage")
@patch("containerizer.trace.cli._podman_machine_is_running")
def test_trace_skips_build_when_image_exists(
    mock_machine: MagicMock,
    mock_image_cls: MagicMock,
    mock_runner_cls: MagicMock,
    tmp_path: Path,
) -> None:
    mock_machine.return_value = True
    image = MagicMock()
    image.exists.return_value = True
    image.tag = "localhost/containerizer-runner:sha-abcdef12"
    mock_image_cls.return_value = image

    runner = MagicMock()
    runner.run.return_value = 0
    mock_runner_cls.return_value = runner

    installer = tmp_path / "fake-installer"
    installer.write_bytes(b"\x00")
    output = tmp_path / "out"
    output.mkdir()
    (output / "COMPLETE").write_text("", encoding="utf-8")

    result = CliRunner().invoke(main, ["trace", str(installer), "-o", str(output)])
    assert result.exit_code == 0
    image.build.assert_not_called()


@patch("containerizer.trace.cli.TraceRunner")
@patch("containerizer.trace.cli.RunnerImage")
@patch("containerizer.trace.cli._podman_machine_is_running")
def test_trace_reports_partial_marker(
    mock_machine: MagicMock,
    mock_image_cls: MagicMock,
    mock_runner_cls: MagicMock,
    tmp_path: Path,
) -> None:
    mock_machine.return_value = True
    image = MagicMock()
    image.exists.return_value = True
    image.tag = "localhost/containerizer-runner:sha-abcdef12"
    mock_image_cls.return_value = image

    runner = MagicMock()
    runner.run.return_value = 0
    mock_runner_cls.return_value = runner

    installer = tmp_path / "fake-installer"
    installer.write_bytes(b"\x00")
    output = tmp_path / "out"
    output.mkdir()
    (output / "PARTIAL").write_text("", encoding="utf-8")

    result = CliRunner().invoke(main, ["trace", str(installer), "-o", str(output)])
    assert result.exit_code == 0
    assert "PARTIAL" in result.output


@patch("containerizer.trace.cli.TraceRunner")
@patch("containerizer.trace.cli.RunnerImage")
@patch("containerizer.trace.cli._podman_machine_is_running")
def test_trace_refuses_when_output_dir_already_has_marker(
    mock_machine: MagicMock,
    mock_image_cls: MagicMock,
    mock_runner_cls: MagicMock,
    tmp_path: Path,
) -> None:
    mock_machine.return_value = True
    image = MagicMock()
    image.exists.return_value = True
    image.tag = "localhost/containerizer-runner:sha-abcdef12"
    mock_image_cls.return_value = image

    runner = MagicMock()
    runner.validate_output_dir.side_effect = OutputDirNotEmpty("already has COMPLETE")
    mock_runner_cls.return_value = runner

    installer = tmp_path / "fake-installer"
    installer.write_bytes(b"\x00")
    output = tmp_path / "out"
    output.mkdir()

    result = CliRunner().invoke(main, ["trace", str(installer), "-o", str(output)])
    assert result.exit_code != 0
    assert "already has COMPLETE" in result.output
    runner.run.assert_not_called()


@patch("containerizer.trace.cli.TraceRunner")
@patch("containerizer.trace.cli.RunnerImage")
@patch("containerizer.trace.cli._podman_machine_is_running")
def test_trace_errors_when_no_marker_is_written(
    mock_machine: MagicMock,
    mock_image_cls: MagicMock,
    mock_runner_cls: MagicMock,
    tmp_path: Path,
) -> None:
    mock_machine.return_value = True
    image = MagicMock()
    image.exists.return_value = True
    image.tag = "localhost/containerizer-runner:sha-abcdef12"
    mock_image_cls.return_value = image

    runner = MagicMock()
    runner.run.return_value = 0
    mock_runner_cls.return_value = runner

    installer = tmp_path / "fake-installer"
    installer.write_bytes(b"\x00")
    output = tmp_path / "out"
    output.mkdir()  # no COMPLETE/PARTIAL written

    result = CliRunner().invoke(main, ["trace", str(installer), "-o", str(output)])
    assert result.exit_code != 0
    assert "did not finalise" in result.output


@patch("containerizer.trace.cli.TraceRunner")
@patch("containerizer.trace.cli.RunnerImage")
@patch("containerizer.trace.cli._podman_machine_is_running")
def test_trace_warns_on_fallbacks_and_propagates_nonzero_exit(
    mock_machine: MagicMock,
    mock_image_cls: MagicMock,
    mock_runner_cls: MagicMock,
    tmp_path: Path,
) -> None:
    mock_machine.return_value = True
    image = MagicMock()
    image.exists.return_value = True
    image.tag = "localhost/containerizer-runner:sha-abcdef12"
    mock_image_cls.return_value = image

    runner = MagicMock()
    runner.run.return_value = 7  # nonzero podman exit
    mock_runner_cls.return_value = runner

    installer = tmp_path / "fake-installer"
    installer.write_bytes(b"\x00")
    output = tmp_path / "out"
    output.mkdir()
    (output / "PARTIAL").write_text("", encoding="utf-8")
    (output / "FALLBACKS.json").write_text('{"open": "strace"}', encoding="utf-8")
    # also create a populated jsonl to exercise the count branch
    (output / "open.jsonl").write_text("{}\n{}\n", encoding="utf-8")

    result = CliRunner().invoke(main, ["trace", str(installer), "-o", str(output)])
    assert result.exit_code != 0
    assert "fell back to strace" in result.output
    assert "podman exited with code 7" in result.output


@patch("containerizer.trace.cli.subprocess.run")
@patch("containerizer.trace.cli.sys.platform", "win32")
def test_podman_machine_is_running_true_when_a_machine_reports_running(
    mock_run: MagicMock,
) -> None:
    mock_run.return_value = MagicMock(returncode=0, stdout='[{"Running": true}]')
    assert _podman_machine_is_running() is True


@patch("containerizer.trace.cli.subprocess.run")
@patch("containerizer.trace.cli.sys.platform", "win32")
def test_podman_machine_is_running_false_when_no_machine_is_running(
    mock_run: MagicMock,
) -> None:
    mock_run.return_value = MagicMock(returncode=0, stdout='[{"Running": false}]')
    assert _podman_machine_is_running() is False


@patch("containerizer.trace.cli.subprocess.run")
@patch("containerizer.trace.cli.sys.platform", "win32")
def test_podman_machine_is_running_false_when_podman_is_not_installed(
    mock_run: MagicMock,
) -> None:
    mock_run.side_effect = FileNotFoundError
    assert _podman_machine_is_running() is False


@patch("containerizer.trace.cli.subprocess.run")
@patch("containerizer.trace.cli.sys.platform", "win32")
def test_podman_machine_is_running_false_when_command_fails(
    mock_run: MagicMock,
) -> None:
    mock_run.return_value = MagicMock(returncode=1, stdout="")
    assert _podman_machine_is_running() is False


@patch("containerizer.trace.cli.subprocess.run")
@patch("containerizer.trace.cli.sys.platform", "win32")
def test_podman_machine_is_running_false_when_output_is_not_json(
    mock_run: MagicMock,
) -> None:
    mock_run.return_value = MagicMock(returncode=0, stdout="not-json")
    assert _podman_machine_is_running() is False


@patch("containerizer.trace.cli.subprocess.run")
@patch("containerizer.trace.cli.sys.platform", "linux")
def test_podman_machine_is_running_returns_true_on_linux_when_podman_present(
    mock_run: MagicMock,
) -> None:
    from containerizer.trace.cli import _podman_machine_is_running

    mock_run.return_value.returncode = 0
    assert _podman_machine_is_running() is True
    # Should call `podman --version`, not `podman machine ls`.
    args = mock_run.call_args.args[0]
    assert args == ["podman", "--version"]


@patch("containerizer.trace.cli.subprocess.run", side_effect=FileNotFoundError)
@patch("containerizer.trace.cli.sys.platform", "linux")
def test_podman_machine_is_running_returns_false_on_linux_when_podman_missing(
    mock_run: MagicMock,
) -> None:
    from containerizer.trace.cli import _podman_machine_is_running

    assert _podman_machine_is_running() is False
