"""End-to-end smoke test for `containerizer analyze` against committed fixture."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest
from click.testing import CliRunner

from containerizer.analyze.cli import analyze_cmd

REPO_ROOT = Path(__file__).resolve().parents[3]
RECORDED = REPO_ROOT / "tests" / "fixtures" / "trace" / "synthetic-recorded"
EXPECTED = REPO_ROOT / "tests" / "fixtures" / "analyze" / "expected"


def _load_json(path: Path) -> dict[str, object]:
    return cast(dict[str, object], json.loads(path.read_text(encoding="utf-8")))


@pytest.fixture
def golden_trace() -> dict[str, object]:
    return _load_json(EXPECTED / "synthetic-trace.json")


@pytest.fixture
def golden_policy() -> dict[str, object]:
    return _load_json(EXPECTED / "synthetic-policy.json")


def test_analyze_matches_golden(
    tmp_path: Path,
    golden_trace: dict[str, object],
    golden_policy: dict[str, object],
) -> None:
    out = tmp_path / "out"
    runner = CliRunner()
    result = runner.invoke(analyze_cmd, [str(RECORDED), "-o", str(out)])
    assert result.exit_code == 0, result.output

    actual_trace = _load_json(out / "trace.json")
    actual_policy = _load_json(out / "policy.json")

    assert actual_trace == golden_trace
    assert actual_policy == golden_policy
