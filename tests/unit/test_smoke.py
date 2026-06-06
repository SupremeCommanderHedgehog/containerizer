"""Smoke test: package imports and CLI exposes a version."""

from click.testing import CliRunner

from containerizer import __version__
from containerizer.cli import main


def test_package_has_version() -> None:
    assert __version__ == "0.0.0"


def test_cli_version_flag() -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["--version"])
    assert result.exit_code == 0
    assert "containerizer, version 0.0.0" in result.output
