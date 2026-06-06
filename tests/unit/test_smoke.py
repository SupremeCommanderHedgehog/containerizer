"""Smoke test: package imports and CLI exposes a version."""

import re

from click.testing import CliRunner

from containerizer import __version__
from containerizer.cli import main

_SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:[-+].+)?$")


def test_package_has_version() -> None:
    assert _SEMVER.match(__version__), f"version {__version__!r} is not semver"


def test_cli_version_flag() -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["--version"])
    assert result.exit_code == 0
    assert result.output.startswith("containerizer, version ")
    assert __version__ in result.output
