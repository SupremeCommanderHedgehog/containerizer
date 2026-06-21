"""Pydantic models for the build orchestrator's inputs and outputs."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from containerizer.verify.schema import VerifyReport


class BuildConfig(BaseModel):
    """User-facing configuration for one `containerizer build` invocation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    installer: Path
    name: str
    out_dir: Path
    base_image: str | None = None
    start_cmd: str | None = None
    keep_intermediates: bool = False
    verify_soak_seconds: int = 30
    skip_verify: bool = False
    debug: bool = False

    # Issue #102.
    extra_installers: tuple[Path, ...] = ()
    apt_sources: tuple[str, ...] = ()
    apt_keys: tuple[Path, ...] = ()


class BuildResult(BaseModel):
    """Structured result of a successful `run_pipeline` invocation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    final_dir: Path
    intermediates_dir: Path | None
    verify: VerifyReport | None = None
    skip_reason: Literal["sentinel", "flag"] | None = None
    warnings: list[str] = []
