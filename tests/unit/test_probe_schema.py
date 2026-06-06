"""Pydantic model contract for probe outputs."""

import json

import pytest
from pydantic import ValidationError

from containerizer.probe.schema import (
    BaseImageSuggestion,
    ElfProbe,
    InstallerKind,
    ProbeResult,
)


def test_elf_probe_minimum_required_fields() -> None:
    probe = ElfProbe(
        arch="x86_64",
        bit=64,
        endianness="little",
        interpreter="/lib64/ld-linux-x86-64.so.2",
        is_static=False,
        needed_libs=["libc.so.6"],
        glibc_min="2.35",
    )
    assert probe.schema_version == 1
    assert probe.arch == "x86_64"


def test_elf_probe_rejects_unknown_endianness() -> None:
    with pytest.raises(ValidationError):
        ElfProbe(
            arch="x86_64",
            bit=64,
            endianness="middle",  # type: ignore[arg-type]
            interpreter=None,
            is_static=True,
            needed_libs=[],
            glibc_min=None,
        )


def test_base_image_suggestion_round_trips_json() -> None:
    sug = BaseImageSuggestion(image="ubuntu:24.04", reasons=["glibc 2.35", "x86_64"])
    payload = sug.model_dump_json()
    assert BaseImageSuggestion.model_validate_json(payload) == sug


def test_probe_result_serialises_elf_kind() -> None:
    result = ProbeResult(
        kind=InstallerKind.elf,
        arch="x86_64",
        elf=ElfProbe(
            arch="x86_64",
            bit=64,
            endianness="little",
            interpreter="/lib64/ld-linux-x86-64.so.2",
            is_static=False,
            needed_libs=["libc.so.6"],
            glibc_min="2.35",
        ),
        base_image=BaseImageSuggestion(image="ubuntu:24.04", reasons=["glibc 2.35"]),
    )
    payload = json.loads(result.model_dump_json())
    assert payload["kind"] == "elf"
    assert payload["elf"]["glibc_min"] == "2.35"
    assert payload["base_image"]["image"] == "ubuntu:24.04"
    assert payload["schema_version"] == 1
