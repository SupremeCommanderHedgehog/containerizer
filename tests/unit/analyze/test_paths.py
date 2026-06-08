"""Tests for analyze.paths classifier + aggregation, parametrized over fixtures."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from containerizer.analyze.paths import classify_runtime

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "trace" / "paths-rules"


def _load(path: Path) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    expected: list[dict[str, object]] = []
    events: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("# expected:"):
            expected = json.loads(line[len("# expected:") :].strip())
        elif line.startswith("{"):
            events.append(json.loads(line))
    return events, expected


@pytest.mark.parametrize("fixture", sorted(FIXTURES.glob("*.jsonl")), ids=lambda p: p.name)
def test_rule_classification(fixture: Path) -> None:
    events, expected = _load(fixture)
    aggregated = classify_runtime(events)
    # Compare as JSON to neutralize Pydantic field ordering vs dict ordering.
    actual = [json.loads(p.model_dump_json(by_alias=True)) for p in aggregated]
    # Sort both sides by path for deterministic compare.
    actual.sort(key=lambda x: str(x["path"]))
    expected.sort(key=lambda x: str(x["path"]))
    assert actual == expected
