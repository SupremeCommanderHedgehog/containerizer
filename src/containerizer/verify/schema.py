"""Pydantic models for the verifier's verify.json output.

This module is the contract every other verify/ module depends on.
Reuses TracePath / TracePort from analyze.schema; no new path/port shape.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from containerizer.analyze.schema import TracePath, TracePort


class VerifyDiff(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    new_paths: list[TracePath]
    new_ports: list[TracePort]
    new_caps: list[str]
    new_syscalls: list[int]
    new_execs: list[str]


class VerifyReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    original_marker: Literal["COMPLETE", "PARTIAL"]
    observed_marker: Literal["COMPLETE", "PARTIAL"]
    diff: VerifyDiff
    warnings: list[str] = []
