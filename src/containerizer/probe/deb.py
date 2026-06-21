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

from containerizer.probe.schema import DebProbe

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

    Supports gzip and xz control tarballs (the two encodings Debian
    itself ships today). zstd support depends on the runtime's
    tarfile (3.14+) and is not guaranteed.

    Decodes bytes as UTF-8 with `errors="replace"` so a corrupted
    control file still produces parseable text rather than raising;
    callers see U+FFFD for any invalid sequences.
    """
    with deb_path.open("rb") as fh:
        members = list(_iter_ar_members(fh))
        ctrl = next(
            (m for m in members if m.name.startswith("control.tar")),
            None,
        )
        if ctrl is None:
            raise ValueError(f"no control.tar.* member in .deb: {deb_path}")
        fh.seek(ctrl.offset)
        blob = fh.read(ctrl.size)

    # tarfile auto-detects gzip/xz/bz2 from the magic when given a file-like.
    with tarfile.open(fileobj=io.BytesIO(blob)) as tf:
        for member in tf:
            if member.name in ("control", "./control"):
                fp = tf.extractfile(member)
                if fp is None:
                    raise ValueError(f"control entry is not a regular file: {deb_path}")
                return fp.read().decode("utf-8", errors="replace")
    raise ValueError(f"no `control` file in control.tar of {deb_path}")


def _discover_systemd_units(deb_path: Path) -> list[str]:
    """Scan data.tar.* for systemd unit files under lib/systemd/system/
    or usr/lib/systemd/system/. Returns basenames sorted for determinism.
    """
    with deb_path.open("rb") as fh:
        members = list(_iter_ar_members(fh))
        data = next(
            (m for m in members if m.name.startswith("data.tar")),
            None,
        )
        if data is None:
            return []
        fh.seek(data.offset)
        blob = fh.read(data.size)

    units: list[str] = []
    with tarfile.open(fileobj=io.BytesIO(blob)) as tf:
        for member in tf:
            if not member.isfile():
                continue
            name = member.name.removeprefix("./")
            if name.startswith("lib/systemd/system/") or name.startswith("usr/lib/systemd/system/"):
                basename = name.rsplit("/", 1)[-1]
                if basename and basename not in units:
                    units.append(basename)
    return sorted(units)


_REQUIRED_CONTROL_FIELDS = ("Package", "Version", "Architecture")


def probe_deb(path: Path) -> DebProbe:
    """Parse a Debian .deb and return a typed DebProbe."""
    text = _extract_control(path)
    fields = _parse_control(text)

    missing = [k for k in _REQUIRED_CONTROL_FIELDS if k not in fields]
    if missing:
        raise ValueError(f"control file missing required fields {missing}: {path}")

    def _split(value: str) -> list[str]:
        return [s.strip() for s in value.split(",") if s.strip()] if value else []

    # Truncate Description to its summary line. Treat an empty
    # Description: field the same as a missing one so the empty
    # string doesn't sneak through `splitlines()[0]` (which would
    # IndexError on []).
    description: str | None = fields.get("Description") or None
    if description is not None:
        description = description.splitlines()[0]

    return DebProbe(
        package=fields["Package"],
        version=fields["Version"],
        arch=fields["Architecture"],
        depends=_split(fields.get("Depends", "")),
        pre_depends=_split(fields.get("Pre-Depends", "")),
        recommends=_split(fields.get("Recommends", "")),
        maintainer=fields.get("Maintainer"),
        description=description,
        systemd_units=_discover_systemd_units(path),
    )
