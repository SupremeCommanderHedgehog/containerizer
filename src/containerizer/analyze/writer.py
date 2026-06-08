"""Serialize TraceJson and PolicyJson to disk with deterministic formatting."""

from __future__ import annotations

import json
from pathlib import Path

from containerizer.analyze.schema import PolicyJson, TraceJson


def write_trace_json(trace: TraceJson, path: Path) -> None:
    _write(trace.model_dump(by_alias=True, mode="json"), path)


def write_policy_json(policy: PolicyJson, path: Path) -> None:
    _write(policy.model_dump(by_alias=True, mode="json"), path)


def _write(obj: dict[str, object], path: Path) -> None:
    # We deliberately do NOT sort top-level keys because the Pydantic
    # field order encodes the spec's chosen presentation order
    # (schema_version first, etc.). Nested lists are produced in the
    # same order they came out of the aggregators (already sorted).
    text = json.dumps(obj, indent=2, sort_keys=False)
    path.write_text(text + "\n", encoding="utf-8")
