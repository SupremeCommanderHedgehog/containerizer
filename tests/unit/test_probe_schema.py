"""Pydantic model contract for probe outputs."""

import json

import pytest
from pydantic import ValidationError

from containerizer.probe.schema import (
    BaseImageSuggestion,
    DebProbe,
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


def _probe_result() -> ProbeResult:
    return ProbeResult(
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


def test_probe_result_serialises_elf_kind() -> None:
    payload = json.loads(_probe_result().model_dump_json())
    assert payload["kind"] == "elf"
    assert payload["elf"]["glibc_min"] == "2.35"
    assert payload["base_image"]["image"] == "ubuntu:24.04"
    assert payload["schema_version"] == 1


def test_probe_result_is_frozen() -> None:
    result = _probe_result()
    with pytest.raises(ValidationError):
        result.arch = "aarch64"


def test_deb_probe_round_trips_through_json() -> None:
    probe = DebProbe(
        package="hello",
        version="2.10-3",
        arch="amd64",
        depends=["libc6 (>= 2.34)"],
        maintainer="Santiago Vila <sanvila@debian.org>",
        description="example package",
        systemd_units=["hello.service"],
    )
    blob = probe.model_dump_json()
    restored = DebProbe.model_validate_json(blob)
    assert restored == probe


def test_deb_probe_defaults_lists_to_empty() -> None:
    """Verify default_factory=list actually produces empty lists when
    Depends / Pre-Depends / Recommends / systemd_units are omitted."""
    probe = DebProbe(package="x", version="1", arch="amd64")
    assert probe.depends == []
    assert probe.pre_depends == []
    assert probe.recommends == []
    assert probe.systemd_units == []
    assert probe.maintainer is None
    assert probe.description is None


def test_deb_probe_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        DebProbe.model_validate(
            {
                "package": "x",
                "version": "1",
                "arch": "amd64",
                "extra_unwanted": True,
            }
        )
