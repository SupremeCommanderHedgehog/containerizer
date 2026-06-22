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
    # Issue #105: --start-cmd companion. Only meaningful when start_cmd is set;
    # CLI validates that combination.
    start_ready_seconds: int = 60
    keep_intermediates: bool = False
    # Issue #105: sentinel-None default so the CLI can distinguish "user
    # explicitly set 30" from "user didn't set anything" and the auto-scale
    # in effective_verify_soak_seconds can fire only in the latter case.
    verify_soak_seconds: int | None = None
    skip_verify: bool = False
    debug: bool = False

    # Issue #102.
    extra_installers: tuple[Path, ...] = ()
    apt_sources: tuple[str, ...] = ()
    apt_keys: tuple[Path, ...] = ()

    @property
    def effective_verify_soak_seconds(self) -> int:
        """Resolved soak value. Explicit --verify-soak-seconds always wins.
        Otherwise: 30 by default, max(60, start_ready_seconds) when
        --start-cmd is set."""
        if self.verify_soak_seconds is not None:
            return self.verify_soak_seconds
        if self.start_cmd is not None:
            return max(60, self.start_ready_seconds)
        return 30


class BuildResult(BaseModel):
    """Structured result of a successful `run_pipeline` invocation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    final_dir: Path
    intermediates_dir: Path | None
    verify: VerifyReport | None = None
    skip_reason: Literal["sentinel", "flag"] | None = None
    warnings: list[str] = []
