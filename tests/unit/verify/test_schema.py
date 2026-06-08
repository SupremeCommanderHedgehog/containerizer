"""Tests for containerizer.verify.schema."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from containerizer.analyze.schema import TracePath, TracePort
from containerizer.verify.schema import VerifyDiff, VerifyReport


def _empty_diff() -> VerifyDiff:
    return VerifyDiff(
        new_paths=[],
        new_ports=[],
        new_caps=[],
        new_syscalls=[],
        new_execs=[],
    )


def test_verify_report_round_trip_minimal() -> None:
    r = VerifyReport(
        original_marker="COMPLETE",
        observed_marker="COMPLETE",
        diff=_empty_diff(),
    )
    raw = r.model_dump_json()
    r2 = VerifyReport.model_validate_json(raw)
    assert r == r2
    assert r2.schema_version == 1
    assert r2.warnings == []


def test_verify_report_carries_warnings_and_partial_markers() -> None:
    r = VerifyReport(
        original_marker="PARTIAL",
        observed_marker="COMPLETE",
        diff=_empty_diff(),
        warnings=["original trace marker is PARTIAL; comparison may be incomplete"],
    )
    assert r.original_marker == "PARTIAL"
    assert r.warnings == ["original trace marker is PARTIAL; comparison may be incomplete"]


def test_verify_diff_carries_typed_paths_and_ports() -> None:
    diff = VerifyDiff(
        new_paths=[
            TracePath(  # type: ignore[call-arg]
                path="/var/lib/x", ops=["read"], class_="persistent_rw", by=["a"]
            )
        ],
        new_ports=[TracePort(port=80, proto="tcp", by="a", ipv4=True, ipv6=False)],
        new_caps=["CAP_NET_BIND_SERVICE"],
        new_syscalls=[59],
        new_execs=["app"],
    )
    assert diff.new_paths[0].path == "/var/lib/x"
    assert diff.new_ports[0].port == 80


def test_verify_report_frozen() -> None:
    r = VerifyReport(
        original_marker="COMPLETE",
        observed_marker="COMPLETE",
        diff=_empty_diff(),
    )
    with pytest.raises(ValidationError):
        r.warnings = ["x"]


def test_verify_report_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        VerifyReport.model_validate(
            {
                "schema_version": 1,
                "original_marker": "COMPLETE",
                "observed_marker": "COMPLETE",
                "diff": _empty_diff().model_dump(),
                "warnings": [],
                "unexpected": True,
            }
        )
