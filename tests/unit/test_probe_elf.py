"""Tests for ELF binary inspection."""

from pathlib import Path

import pytest

from containerizer.probe.elf import _resolve_arch, probe_elf


@pytest.fixture
def elf_path(fixtures_dir: Path) -> Path:
    return fixtures_dir / "probe" / "elf-dynamic-x86_64"


def test_probe_elf_basic(elf_path: Path) -> None:
    result = probe_elf(elf_path)
    assert result.arch == "x86_64"
    assert result.bit == 64
    assert result.endianness == "little"
    assert result.is_static is False
    assert result.interpreter is not None
    assert result.interpreter.endswith("ld-linux-x86-64.so.2")


def test_probe_elf_needed_libs_includes_libc(elf_path: Path) -> None:
    result = probe_elf(elf_path)
    assert any(name == "libc.so.6" for name in result.needed_libs)


def test_probe_elf_glibc_min_parseable(elf_path: Path) -> None:
    result = probe_elf(elf_path)
    assert result.glibc_min is not None
    major, minor = result.glibc_min.split(".")
    assert int(major) >= 2
    assert int(minor) >= 0


@pytest.mark.parametrize(
    ("e_machine", "elfclass", "expected"),
    [
        ("EM_X86_64", 64, "x86_64"),
        ("EM_AARCH64", 64, "aarch64"),
        ("EM_386", 32, "i386"),
        ("EM_PPC64", 64, "ppc64"),
        ("EM_PPC", 32, "ppc"),
        ("EM_RISCV", 64, "riscv64"),
        ("EM_RISCV", 32, "riscv32"),
        ("EM_FOOBAR", 64, "EM_FOOBAR"),
    ],
)
def test_resolve_arch(e_machine: str, elfclass: int, expected: str) -> None:
    assert _resolve_arch(e_machine, elfclass) == expected
