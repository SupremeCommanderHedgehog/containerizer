"""Typed JSON models for probe outputs."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class InstallerKind(StrEnum):
    elf = "elf"
    deb = "deb"
    rpm = "rpm"
    appimage = "appimage"
    shell = "shell"
    tarball = "tarball"
    unknown = "unknown"


class ElfProbe(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = 1
    arch: str
    bit: Literal[32, 64]
    endianness: Literal["little", "big"]
    interpreter: str | None
    is_static: bool
    needed_libs: list[str] = Field(default_factory=list)
    glibc_min: str | None


class BaseImageSuggestion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    image: str
    reasons: list[str]


class DebProbe(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = 1
    package: str
    version: str
    arch: str
    depends: list[str] = Field(default_factory=list)
    pre_depends: list[str] = Field(default_factory=list)
    recommends: list[str] = Field(default_factory=list)
    maintainer: str | None = None
    description: str | None = None
    systemd_units: list[str] = Field(default_factory=list)


class ProbeResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = 1
    kind: InstallerKind
    arch: str | None = None
    elf: ElfProbe | None = None
    deb: DebProbe | None = None
    base_image: BaseImageSuggestion
