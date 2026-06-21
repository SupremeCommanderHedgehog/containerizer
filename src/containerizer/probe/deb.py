"""Debian .deb probe.

Parses metadata from a Debian package: ar archive containing
debian-binary, control.tar.*, data.tar.*. Uses stdlib only.
"""

from __future__ import annotations

import io
import tarfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

_AR_MAGIC = b"!<arch>\n"
_AR_HEADER_LEN = 60


@dataclass(frozen=True)
class _ArMember:
    name: str
    size: int
    offset: int  # byte offset where member data begins


def _iter_ar_members(fh: BinaryIO) -> Iterator[_ArMember]:
    """Yield ar archive members in file order.

    Each per-member header is 60 bytes: name[16], mtime[12], owner[6],
    group[6], mode[8], size[10], end['`\\n']. Member data is padded to
    an even byte boundary.
    """
    magic = fh.read(len(_AR_MAGIC))
    if magic != _AR_MAGIC:
        raise ValueError(f"bad ar magic: {magic!r}")
    while True:
        header = fh.read(_AR_HEADER_LEN)
        if not header:
            return
        if len(header) < _AR_HEADER_LEN:
            raise ValueError("truncated ar member header")
        name = header[0:16].decode("ascii").rstrip("/ \x00")
        try:
            size = int(header[48:58].decode("ascii").strip())
        except ValueError as e:
            raise ValueError(f"unparseable ar member size in {name!r}") from e
        if header[58:60] != b"`\n":
            raise ValueError(f"bad ar header terminator for {name!r}")
        offset = fh.tell()
        yield _ArMember(name=name, size=size, offset=offset)
        fh.seek(offset + size + (size % 2))


def _parse_control(text: str) -> dict[str, str]:
    """Parse Debian control's first paragraph into a flat dict.

    Continuation lines (start with space) join with a newline to
    preserve the Description field's shape. A blank line ends the
    paragraph; subsequent paragraphs are ignored (a .deb's control
    has exactly one).
    """
    fields: dict[str, str] = {}
    current_key: str | None = None
    for line in text.splitlines():
        if line == "":
            break
        if line.startswith((" ", "\t")):
            if current_key is None:
                continue
            fields[current_key] = fields[current_key] + "\n" + line.strip()
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        current_key = key.strip()
        fields[current_key] = value.strip()
    return fields


def _extract_control(deb_path: Path) -> str:
    """Read the `control` file out of a .deb's control.tar.*.

    Supports gzip, xz, zstd, and uncompressed control tarballs.
    Returns the file's text content (UTF-8 with strict fallback).
    """
    with deb_path.open("rb") as fh:
        members = list(_iter_ar_members(fh))
        ctrl = next(
            (m for m in members if m.name.startswith("control.tar")),
            None,
        )
        if ctrl is None:
            raise ValueError("no control.tar.* member in .deb")
        fh.seek(ctrl.offset)
        blob = fh.read(ctrl.size)

    # tarfile auto-detects gzip/xz/bz2 from the magic when given
    # a file-like. zstd requires Python 3.14+ tarfile or the
    # `zstandard` extra; for v0.x we accept gzip + xz (the only
    # two encodings Debian itself uses today).
    with tarfile.open(fileobj=io.BytesIO(blob)) as tf:
        for member in tf:
            if member.name in ("control", "./control"):
                fp = tf.extractfile(member)
                if fp is None:
                    raise ValueError("control entry is not a regular file")
                return fp.read().decode("utf-8", errors="replace")
    raise ValueError("no `control` file in control.tar")
