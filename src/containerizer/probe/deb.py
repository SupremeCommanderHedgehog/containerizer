"""Debian .deb probe.

Parses metadata from a Debian package: ar archive containing
debian-binary, control.tar.*, data.tar.*. Uses stdlib only.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
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
