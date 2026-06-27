"""Tests for trace.runner sidecar-file materialization."""

from __future__ import annotations

from pathlib import Path

from containerizer.trace.runner import TraceRunner


def _install_runner(output_dir: Path, installer: Path, **overrides: object) -> TraceRunner:
    return TraceRunner(
        image_tag="dummy:latest",
        installer=installer,
        output_dir=output_dir,
        **overrides,  # type: ignore[arg-type]
    )


def test_runner_writes_start_cmd_file_when_set(tmp_path: Path) -> None:
    installer = tmp_path / "i.bin"
    installer.write_text("x", encoding="utf-8")
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    runner = _install_runner(
        output_dir, installer, start_cmd="/etc/init.d/unifi start"
    )

    runner._materialize_start_cmd_file()

    sidecar = output_dir / "START_CMD"
    assert sidecar.exists()
    assert sidecar.read_text(encoding="utf-8") == "/etc/init.d/unifi start"


def test_runner_omits_start_cmd_file_when_unset(tmp_path: Path) -> None:
    installer = tmp_path / "i.bin"
    installer.write_text("x", encoding="utf-8")
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    runner = _install_runner(output_dir, installer)  # start_cmd default = None

    runner._materialize_start_cmd_file()

    assert list(output_dir.iterdir()) == []
