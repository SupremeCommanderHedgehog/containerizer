"""Installer kind detection and probe dispatch.

ELF binaries and Debian `.deb` packages are supported. Other kinds
(RPM, AppImage, shell, tarball) are detected so the CLI can surface
a clear error, but probing them raises ``UnsupportedInstallerKind``
until later milestones add their parsers.
"""

from __future__ import annotations

from pathlib import Path

from containerizer.probe.base_image import suggest_base_image
from containerizer.probe.deb import probe_deb
from containerizer.probe.elf import probe_elf
from containerizer.probe.schema import InstallerKind, ProbeResult


class UnsupportedInstallerKind(NotImplementedError):
    """Raised when the installer kind is detected but not yet supported."""

    def __init__(self, kind: InstallerKind, path: Path) -> None:
        super().__init__(f"installer kind {kind.value!r} is not yet supported: {path}")
        self.kind = kind
        self.path = path


_ELF_MAGIC = b"\x7fELF"
_AR_MAGIC = b"!<arch>\n"
_RPM_MAGIC = b"\xed\xab\xee\xdb"
_TAR_MAGIC = b"ustar"
_GZIP_MAGIC = b"\x1f\x8b"
_XZ_MAGIC = b"\xfd7zXZ\x00"
_APPIMAGE_MAGIC = b"AI\x02"


def detect_kind(path: Path) -> InstallerKind:
    """Identify the installer kind from its magic bytes and naming hints."""
    with path.open("rb") as fh:
        head = fh.read(512)
    if head.startswith(_ELF_MAGIC):
        if _APPIMAGE_MAGIC in head[:32]:
            return InstallerKind.appimage
        return InstallerKind.elf
    if head.startswith(_AR_MAGIC):
        return InstallerKind.deb
    if head.startswith(_RPM_MAGIC):
        return InstallerKind.rpm
    if head.startswith(b"#!"):
        return InstallerKind.shell
    if head.startswith(_GZIP_MAGIC) or head.startswith(_XZ_MAGIC) or _TAR_MAGIC in head[:512]:
        return InstallerKind.tarball
    return InstallerKind.unknown


def probe(path: Path) -> ProbeResult:
    """Probe *path* and return a typed ``ProbeResult``."""
    kind = detect_kind(path)
    if kind is InstallerKind.elf:
        elf = probe_elf(path)
        base = suggest_base_image(elf)
        return ProbeResult(kind=kind, arch=elf.arch, elf=elf, base_image=base)
    if kind is InstallerKind.deb:
        deb = probe_deb(path)
        base = suggest_base_image(deb)
        return ProbeResult(kind=kind, arch=deb.arch, deb=deb, base_image=base)
    raise UnsupportedInstallerKind(kind, path)
