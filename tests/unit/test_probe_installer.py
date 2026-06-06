"""Tests for installer kind detection and dispatch."""

from pathlib import Path

import pytest

from containerizer.probe.installer import (
    UnsupportedInstallerKind,
    detect_kind,
    probe,
)
from containerizer.probe.schema import InstallerKind


@pytest.fixture
def elf_path(fixtures_dir: Path) -> Path:
    return fixtures_dir / "probe" / "elf-dynamic-x86_64"


def test_detect_kind_elf(elf_path: Path) -> None:
    assert detect_kind(elf_path) is InstallerKind.elf


def test_detect_kind_unknown(tmp_path: Path) -> None:
    f = tmp_path / "mystery.bin"
    f.write_bytes(b"\x00" * 32)
    assert detect_kind(f) is InstallerKind.unknown


def test_probe_elf_round_trip(elf_path: Path) -> None:
    result = probe(elf_path)
    assert result.kind is InstallerKind.elf
    assert result.arch == "x86_64"
    assert result.elf is not None
    assert result.base_image.image.startswith("ubuntu:")


def test_probe_unsupported_kind_raises(tmp_path: Path) -> None:
    f = tmp_path / "wat.deb"
    f.write_bytes(b"!<arch>\n")  # ar magic; pretends to be .deb
    with pytest.raises(UnsupportedInstallerKind):
        probe(f)
