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


def test_detect_kind_deb(tmp_path: Path) -> None:
    f = tmp_path / "x.deb"
    f.write_bytes(b"!<arch>\n" + b"\x00" * 32)
    assert detect_kind(f) is InstallerKind.deb


def test_detect_kind_rpm(tmp_path: Path) -> None:
    f = tmp_path / "x.rpm"
    f.write_bytes(b"\xed\xab\xee\xdb" + b"\x00" * 32)
    assert detect_kind(f) is InstallerKind.rpm


def test_detect_kind_shell(tmp_path: Path) -> None:
    f = tmp_path / "install.sh"
    f.write_bytes(b"#!/bin/sh\necho hi\n")
    assert detect_kind(f) is InstallerKind.shell


def test_detect_kind_tarball_gzip(tmp_path: Path) -> None:
    f = tmp_path / "x.tar.gz"
    f.write_bytes(b"\x1f\x8b" + b"\x00" * 32)
    assert detect_kind(f) is InstallerKind.tarball


def test_detect_kind_tarball_xz(tmp_path: Path) -> None:
    f = tmp_path / "x.tar.xz"
    f.write_bytes(b"\xfd7zXZ\x00" + b"\x00" * 32)
    assert detect_kind(f) is InstallerKind.tarball


def test_detect_kind_tarball_ustar(tmp_path: Path) -> None:
    f = tmp_path / "x.tar"
    # POSIX tar header: 257 bytes of file metadata, then "ustar" at offset 257.
    head = bytearray(b"\x00" * 257)
    head += b"ustar\x0000"
    head += b"\x00" * (512 - len(head))
    f.write_bytes(bytes(head))
    assert detect_kind(f) is InstallerKind.tarball


def test_detect_kind_appimage(tmp_path: Path) -> None:
    f = tmp_path / "x.AppImage"
    # ELF header with the AppImage marker (AI\x02) in the first 32 bytes.
    f.write_bytes(b"\x7fELF" + b"\x00" * 4 + b"AI\x02" + b"\x00" * 32)
    assert detect_kind(f) is InstallerKind.appimage


def test_probe_elf_round_trip(elf_path: Path) -> None:
    result = probe(elf_path)
    assert result.kind is InstallerKind.elf
    assert result.arch == "x86_64"
    assert result.elf is not None
    assert result.base_image.image.startswith("ubuntu:")


def test_probe_deb_returns_DebProbe(tmp_path: Path) -> None:
    from tests.fixtures.probe.deb_helpers import build_minimal_deb

    deb = tmp_path / "x.deb"
    build_minimal_deb(deb)
    result = probe(deb)
    assert result.kind is InstallerKind.deb
    assert result.deb is not None
    assert result.deb.package == "hello"
    assert result.elf is None
    assert result.base_image.image.startswith("ubuntu:")


def test_probe_unsupported_kind_still_raises_for_rpm(tmp_path: Path) -> None:
    f = tmp_path / "x.rpm"
    f.write_bytes(b"\xed\xab\xee\xdb" + b"\x00" * 32)
    with pytest.raises(UnsupportedInstallerKind):
        probe(f)
