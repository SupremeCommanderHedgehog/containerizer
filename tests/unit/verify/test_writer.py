"""Tests for containerizer.verify.writer."""

from __future__ import annotations

import json
from pathlib import Path

from containerizer.verify.schema import VerifyDiff, VerifyReport
from containerizer.verify.writer import write_verify_json


def _report() -> VerifyReport:
    return VerifyReport(
        original_marker="COMPLETE",
        observed_marker="COMPLETE",
        diff=VerifyDiff(new_paths=[], new_ports=[], new_caps=[], new_syscalls=[], new_execs=[]),
    )


def test_writer_emits_schema_version_first(tmp_path: Path) -> None:
    out = tmp_path / "verify.json"
    write_verify_json(_report(), out)
    text = out.read_text(encoding="utf-8")
    obj = json.loads(text)
    # Pydantic field order preserved; schema_version is first
    keys = list(obj.keys())
    assert keys[0] == "schema_version"
    assert obj["schema_version"] == 1


def test_writer_pretty_printed_with_trailing_newline(tmp_path: Path) -> None:
    out = tmp_path / "verify.json"
    write_verify_json(_report(), out)
    text = out.read_text(encoding="utf-8")
    assert text.endswith("\n")
    assert "  " in text  # indented JSON


def test_writer_round_trip(tmp_path: Path) -> None:
    out = tmp_path / "verify.json"
    write_verify_json(_report(), out)
    obj = json.loads(out.read_text(encoding="utf-8"))
    r2 = VerifyReport.model_validate(obj)
    assert r2 == _report()
