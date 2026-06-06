"""Tests for base-image suggestion."""

import pytest

from containerizer.probe.base_image import suggest_base_image
from containerizer.probe.schema import ElfProbe


def _elf(glibc: str | None) -> ElfProbe:
    return ElfProbe(
        arch="x86_64",
        bit=64,
        endianness="little",
        interpreter="/lib64/ld-linux-x86-64.so.2",
        is_static=False,
        needed_libs=["libc.so.6"],
        glibc_min=glibc,
    )


@pytest.mark.parametrize(
    ("glibc", "expected_image"),
    [
        ("2.35", "ubuntu:24.04"),
        ("2.36", "ubuntu:24.04"),
        ("2.31", "ubuntu:22.04"),
        ("2.34", "ubuntu:22.04"),
        ("2.30", "ubuntu:20.04"),
        (None, "ubuntu:24.04"),
    ],
)
def test_suggest_base_image_for_glibc(glibc: str | None, expected_image: str) -> None:
    elf = _elf(glibc)
    result = suggest_base_image(elf)
    assert result.image == expected_image
    assert any("glibc" in r or "default" in r for r in result.reasons)


def test_suggest_base_image_includes_arch_reason() -> None:
    elf = _elf("2.35")
    result = suggest_base_image(elf)
    assert any("x86_64" in r for r in result.reasons)
