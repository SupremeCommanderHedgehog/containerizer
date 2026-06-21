"""Tests for base-image suggestion."""

import pytest

from containerizer.probe.base_image import suggest_base_image
from containerizer.probe.schema import DebProbe, ElfProbe


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
    ("glibc", "expected_image", "expected_reason_fragment"),
    [
        ("2.36", "ubuntu:24.04", "requires Ubuntu 24.04"),
        ("2.35", "ubuntu:22.04", "fits Ubuntu 22.04"),
        ("2.34", "ubuntu:22.04", "fits Ubuntu 22.04"),
        ("2.31", "ubuntu:22.04", "fits Ubuntu 22.04"),
        ("2.30", "ubuntu:20.04", "fits Ubuntu 20.04"),
        (None, "ubuntu:24.04", "no glibc requirement"),
    ],
)
def test_suggest_base_image_for_glibc(
    glibc: str | None, expected_image: str, expected_reason_fragment: str
) -> None:
    elf = _elf(glibc)
    result = suggest_base_image(elf)
    assert result.image == expected_image
    assert any(expected_reason_fragment in r for r in result.reasons), result.reasons


def test_suggest_base_image_for_unparseable_glibc() -> None:
    elf = _elf("not-a-version")
    result = suggest_base_image(elf)
    assert result.image == "ubuntu:24.04"
    assert any("could not parse" in r for r in result.reasons), result.reasons


def test_suggest_base_image_includes_arch_reason() -> None:
    elf = _elf("2.35")
    result = suggest_base_image(elf)
    assert any("x86_64" in r for r in result.reasons)


def _deb(arch: str) -> DebProbe:
    return DebProbe(package="x", version="1", arch=arch)


@pytest.mark.parametrize(
    "arch", ["amd64", "arm64", "all"],
)
def test_suggest_base_image_for_deb_supported_archs(arch: str) -> None:
    deb = _deb(arch)
    result = suggest_base_image(deb)
    assert result.image == "ubuntu:24.04"
    assert any(arch in r or "architecture-independent" in r for r in result.reasons)


@pytest.mark.parametrize("arch", ["i386", "armhf", "ppc64el"])
def test_suggest_base_image_for_deb_unsupported_archs_raises(arch: str) -> None:
    deb = _deb(arch)
    with pytest.raises(ValueError, match=arch):
        suggest_base_image(deb)
