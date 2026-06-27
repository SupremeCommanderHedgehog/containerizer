"""CLI tests for `containerizer trace`."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from containerizer.trace import cli as trace_cli_module
from containerizer.trace.cli import trace_cmd


def test_empty_start_cmd_normalized_to_none(tmp_path: Path) -> None:
    """`--start-cmd ''` is treated as if --start-cmd wasn't passed at all."""
    installer = tmp_path / "i.bin"
    installer.write_text("x", encoding="utf-8")
    out_dir = tmp_path / "out"

    with patch.object(
        trace_cli_module, "_podman_machine_is_running", return_value=True
    ), patch.object(
        trace_cli_module, "RunnerImage"
    ) as mock_image, patch.object(
        trace_cli_module, "TraceRunner"
    ) as mock_runner_cls, patch.object(
        trace_cli_module, "_print_summary"
    ):
        mock_image.return_value.exists.return_value = True
        mock_image.return_value.tag = "test:latest"
        mock_runner_cls.return_value.run.return_value = 0

        runner = CliRunner()
        result = runner.invoke(
            trace_cmd,
            [str(installer), "-o", str(out_dir), "--start-cmd", ""],
        )

    assert result.exit_code == 0, result.output
    kwargs = mock_runner_cls.call_args.kwargs
    assert kwargs.get("start_cmd") is None
