"""Serialize VerifyReport to disk with deterministic formatting."""

from __future__ import annotations

import json
from pathlib import Path

from containerizer.verify.schema import VerifyReport


def write_verify_json(report: VerifyReport, path: Path) -> None:
    """Pretty-print the report with Pydantic field order; trailing newline."""
    obj: dict[str, object] = report.model_dump(by_alias=True, mode="json")
    text = json.dumps(obj, indent=2, sort_keys=False)
    path.write_text(text + "\n", encoding="utf-8")
