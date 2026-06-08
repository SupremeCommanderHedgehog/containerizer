"""End-to-end smoke tests for `containerizer verify`."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest
from click.testing import CliRunner

from containerizer.verify.cli import verify_cmd

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "verify"
EXPECTED = FIXTURES / "expected"


def _load_json(path: Path) -> dict[str, object]:
    return cast(dict[str, object], json.loads(path.read_text(encoding="utf-8")))


@pytest.fixture
def golden_with_new() -> dict[str, object]:
    return _load_json(EXPECTED / "verify-with-new.json")


def test_clean_observed_exits_zero_with_empty_diff(tmp_path: Path) -> None:
    out = tmp_path / "out"
    result = CliRunner().invoke(
        verify_cmd,
        [
            "--original",
            str(FIXTURES / "original.json"),
            "--observed",
            str(FIXTURES / "observed-clean.json"),
            "-o",
            str(out),
        ],
    )
    assert result.exit_code == 0, result.output
    report = _load_json(out / "verify.json")
    diff = cast(dict[str, object], report["diff"])
    assert diff["new_paths"] == []
    assert diff["new_ports"] == []
    assert diff["new_caps"] == []
    assert diff["new_syscalls"] == []
    assert diff["new_execs"] == []


def test_observed_with_new_matches_golden(
    tmp_path: Path,
    golden_with_new: dict[str, object],
) -> None:
    out = tmp_path / "out"
    result = CliRunner().invoke(
        verify_cmd,
        [
            "--original",
            str(FIXTURES / "original.json"),
            "--observed",
            str(FIXTURES / "observed-with-new.json"),
            "-o",
            str(out),
        ],
    )
    assert result.exit_code == 1, result.output
    actual = _load_json(out / "verify.json")
    assert actual == golden_with_new
