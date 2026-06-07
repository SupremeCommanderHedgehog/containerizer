"""Tests for the TraceRunner class."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from containerizer.trace.runner import OutputDirNotEmpty, TraceRunner


def test_argv_is_the_podman_run_command(tmp_path: Path) -> None:
    installer = tmp_path / "install.sh"
    installer.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    output = tmp_path / "trace"
    output.mkdir()

    runner = TraceRunner(
        image_tag="localhost/containerizer-runner:sha-abc12345",
        installer=installer,
        output_dir=output,
    )

    argv = runner.argv()
    assert argv[:2] == ["podman", "run"]
    assert "--rm" in argv
    assert "-i" in argv
    assert "-t" not in argv
    assert "--privileged" in argv
    assert "--pid=host" in argv
    assert "-v" in argv
    assert "/sys/kernel/debug:/sys/kernel/debug" in argv
    assert "/sys/kernel/tracing:/sys/kernel/tracing" in argv
    assert "/sys/kernel/btf:/sys/kernel/btf" in argv
    assert "/lib/modules:/lib/modules:ro" in argv
    assert "/usr/src:/usr/src:ro" in argv
    assert f"{installer.resolve()}:/installer:ro" in argv
    assert f"{output.resolve()}:/work/trace" in argv
    assert argv[-2] == "localhost/containerizer-runner:sha-abc12345"
    assert argv[-1] == "/installer"


def test_output_dir_with_complete_marker_is_rejected_without_force(tmp_path: Path) -> None:
    installer = tmp_path / "install.sh"
    installer.write_text("", encoding="utf-8")
    output = tmp_path / "trace"
    output.mkdir()
    (output / "COMPLETE").write_text("", encoding="utf-8")

    with pytest.raises(OutputDirNotEmpty):
        TraceRunner(
            image_tag="localhost/containerizer-runner:sha-abc12345",
            installer=installer,
            output_dir=output,
        ).validate_output_dir(force=False)


def test_output_dir_with_complete_marker_is_accepted_with_force(tmp_path: Path) -> None:
    installer = tmp_path / "install.sh"
    installer.write_text("", encoding="utf-8")
    output = tmp_path / "trace"
    output.mkdir()
    (output / "COMPLETE").write_text("", encoding="utf-8")

    TraceRunner(
        image_tag="localhost/containerizer-runner:sha-abc12345",
        installer=installer,
        output_dir=output,
    ).validate_output_dir(force=True)


def test_output_dir_with_partial_marker_is_also_blocked(tmp_path: Path) -> None:
    installer = tmp_path / "install.sh"
    installer.write_text("", encoding="utf-8")
    output = tmp_path / "trace"
    output.mkdir()
    (output / "PARTIAL").write_text("", encoding="utf-8")

    with pytest.raises(OutputDirNotEmpty):
        TraceRunner(
            image_tag="localhost/containerizer-runner:sha-abc12345",
            installer=installer,
            output_dir=output,
        ).validate_output_dir(force=False)


@patch("containerizer.trace.runner.subprocess.run")
def test_run_calls_subprocess_with_argv(mock_run: MagicMock, tmp_path: Path) -> None:
    mock_run.return_value.returncode = 0
    installer = tmp_path / "install.sh"
    installer.write_text("", encoding="utf-8")
    output = tmp_path / "trace"
    output.mkdir()

    runner = TraceRunner(
        image_tag="localhost/containerizer-runner:sha-abc12345",
        installer=installer,
        output_dir=output,
    )
    assert runner.run() == 0
    mock_run.assert_called_once_with(runner.argv(), check=False)
