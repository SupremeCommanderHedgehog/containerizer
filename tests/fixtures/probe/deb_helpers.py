"""Build a minimal Debian .deb in-memory for tests.

Layout: ar archive with three members in order:
  1. debian-binary    -- text, '2.0\n'
  2. control.tar.gz   -- tarball with a `control` file
  3. data.tar.gz      -- tarball with the package payload

ar member header (60 bytes):
  name[16] mtime[12] owner[6] group[6] mode[8] size[10] end['`\n']
"""

from __future__ import annotations

import io
import tarfile
import time
from pathlib import Path


def _ar_header(name: str, size: int) -> bytes:
    # ar field widths per the BSD/SysV variant Debian uses. Names that
    # fit in 16 bytes are space-padded; this fixture never needs the
    # GNU extended-name table.
    return (
        name.ljust(16).encode("ascii")
        + str(int(time.time())).ljust(12).encode("ascii")
        + b"0     "
        + b"0     "
        + b"100644  "
        + str(size).ljust(10).encode("ascii")
        + b"`\n"
    )


def _ar_append(out: io.BytesIO, name: str, data: bytes) -> None:
    out.write(_ar_header(name, len(data)))
    out.write(data)
    if len(data) % 2 == 1:
        out.write(b"\n")  # padding to even byte boundary


def _make_tar_gz(entries: dict[str, bytes]) -> bytes:
    """Build a tar.gz with the given path -> bytes mapping."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for path, content in entries.items():
            info = tarfile.TarInfo(name=path)
            info.size = len(content)
            info.mode = 0o644
            tf.addfile(info, io.BytesIO(content))
    return buf.getvalue()


def _make_tar_gz_with_modes(entries: dict[str, tuple[bytes, int]]) -> bytes:
    """Build a tar.gz where each entry is (content, mode)."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for path, (content, mode) in entries.items():
            info = tarfile.TarInfo(name=path)
            info.size = len(content)
            info.mode = mode
            tf.addfile(info, io.BytesIO(content))
    return buf.getvalue()


def build_minimal_deb(
    path: Path,
    *,
    package: str = "hello",
    version: str = "2.10-3",
    architecture: str = "amd64",
    depends: str = "libc6 (>= 2.34)",
    maintainer: str = "Test <test@example.com>",
    description: str = "test package\n A test package for containerizer.",
    systemd_unit: str | None = "hello.service",
    extra_unit_paths: list[str] | None = None,
    init_script_body: str | None = None,
    postinst_body: str | None = None,
) -> None:
    """Write a minimal but valid .deb to *path*.

    Issue #105: optional init_script_body installs an executable
    /etc/init.d/<package> with the supplied body. postinst_body adds a
    DEBIAN/postinst script (rendered into control.tar.gz, executable).
    """
    control_fields = [
        f"Package: {package}",
        f"Version: {version}",
        f"Architecture: {architecture}",
        f"Maintainer: {maintainer}",
        f"Depends: {depends}",
        f"Description: {description}",
        "",
    ]
    control_entries: dict[str, bytes] = {"control": "\n".join(control_fields).encode()}
    if postinst_body is not None:
        control_entries["postinst"] = postinst_body.encode()
    control_tar = _make_tar_gz_with_modes(
        {p: (b, 0o755 if p == "postinst" else 0o644) for p, b in control_entries.items()}
    )

    # Issue #102: payload path includes the package name so two fixture debs
    # installed in the same apt transaction don't collide on a shared
    # `/usr/bin/hello` (dpkg refuses to overwrite a file from a different
    # package). Single-deb tests are unaffected because the existing tests
    # assert against the systemd unit name, not the bin path.
    data_entries: dict[str, tuple[bytes, int]] = {
        f"./usr/bin/{package}": (b"#!/bin/sh\necho hello\n", 0o755),
    }
    if systemd_unit is not None:
        unit_body = (
            "[Unit]\nDescription=Hello service\n"
            "[Service]\nExecStart=/usr/bin/hello\n"
            "[Install]\nWantedBy=multi-user.target\n"
        )
        data_entries[f"./lib/systemd/system/{systemd_unit}"] = (unit_body.encode(), 0o644)
    if extra_unit_paths:
        extra_body = (
            "[Unit]\nDescription=Extra service\n"
            "[Service]\nExecStart=/usr/bin/true\n"
            "[Install]\nWantedBy=multi-user.target\n"
        )
        for ep in extra_unit_paths:
            data_entries[ep] = (extra_body.encode(), 0o644)
    if init_script_body is not None:
        data_entries[f"./etc/init.d/{package}"] = (init_script_body.encode(), 0o755)
    data_tar = _make_tar_gz_with_modes(data_entries)

    buf = io.BytesIO()
    buf.write(b"!<arch>\n")
    _ar_append(buf, "debian-binary", b"2.0\n")
    _ar_append(buf, "control.tar.gz", control_tar)
    _ar_append(buf, "data.tar.gz", data_tar)
    path.write_bytes(buf.getvalue())
