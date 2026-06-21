# Issue #99 — Debian `.deb` installer support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** End-to-end `.deb` installer support: `containerizer build foo.deb --name foo` produces a hardened Containerfile + Quadlet + seccomp the same way it does for an ELF installer today. Closes #99.

**Architecture:** Probe parses control + data tar metadata via stdlib (no `python-debian` runtime dep) and emits a typed `DebProbe`. `suggest_base_image` becomes kind-dispatching (ELF or deb). `trace-orchestrator.sh` gains an installer-kind dispatch that, for `.deb`, runs the install workload inside a nested `ubuntu:24.04 --systemd=always` container so postinst's `systemctl start` works. Collectors run on the outer Fedora kernel and observe nested events natively. Apt/dpkg activity sits before `PHASE_MARKER` and is excluded from runtime policy by the analyzer's existing phase split.

**Tech Stack:** Python 3.11+, pydantic 2.x, stdlib `tarfile`, pytest, bash, Podman 4.x, Fedora 41 (runner image), Ubuntu 24.04 (nested install host). Spec: [`2026-06-20-containerizer-issue-99-deb-support.md`](../specs/2026-06-20-containerizer-issue-99-deb-support.md).

---

## Phasing Overview

| Phase | What | Hard gate |
|---|---|---|
| 1 | Probe: `probe_deb` + `DebProbe` + `suggest_base_image` deb dispatch | Unit tests green, mypy + ruff clean, coverage ≥90% |
| 2 | Orchestrator refactor: extract `run_elf_install` (no behavior change) | Existing `test_trace_pipeline` integration test still passes |
| 3 | Orchestrator dispatch + `run_deb_install` + extended trap | Shell unit tests (podman stub) pass |
| 4 | Integration tests: fixture-deb generator + trace + build end-to-end | `pytest -m integration` green in `trace-integration` CI job |
| 5 | Manual scenario 12 (nginx-light) | Optional; lands as a docs-only commit |

All commits signed with key `BE707B220C995478`, author `github.v5f9w@bitbucket.onl`.

---

## Pre-flight: branch setup

This plan ships as the **implementation PR**, separate from the docs PR that lands this plan + spec. Before starting Phase 1:

```bash
git fetch origin main
git checkout -b feat/issue-99-deb-support origin/main
```

All Phase 1-5 commits land on `feat/issue-99-deb-support`. The branch is pushed and the PR opened in Task 5.2.

---

## File Structure

**Files created:**
- `src/containerizer/probe/deb.py` — ar reader + control parser + systemd-unit discovery + `probe_deb`
- `tests/unit/test_probe_deb.py` — unit tests for the new probe module
- `tests/fixtures/probe/deb_helpers.py` — pure-Python fixture-deb generator (importable from any test)
- `tests/integration/trace/test_deb_pipeline.py` — install-mode trace integration against a fixture deb
- `tests/integration/build/test_build_deb.py` — end-to-end `containerizer build` integration against a fixture deb
- `tests/unit/test_orchestrator_dispatch.py` — pytest harness for `trace-orchestrator.sh` dispatch (mocks podman)
- `tests/fixtures/trace/podman-stub.sh` — recording stub used by the orchestrator dispatch test

**Files modified:**
- `src/containerizer/probe/schema.py` — add `DebProbe`; add `deb: DebProbe | None = None` to `ProbeResult`
- `src/containerizer/probe/installer.py` — dispatch `InstallerKind.deb` to `probe_deb()` instead of raising
- `src/containerizer/probe/base_image.py` — accept `ElfProbe | DebProbe`; new `_suggest_for_deb`
- `sandbox/runner_image/trace-orchestrator.sh` — extract existing install workload into `run_elf_install`; add `_detect_kind`, `run_deb_install`, dispatch case; extend INT/TERM trap inside `run_deb_install`
- `tests/unit/test_probe_base_image.py` — add deb dispatch tests
- `tests/unit/test_probe_installer.py` — replace "deb is unsupported" test with "deb is probed"

**Files unchanged:**
- `src/containerizer/trace/runner.py` — argv shape unchanged; `/installer` mount is still the contract
- `src/containerizer/analyze/*`, `src/containerizer/generate/*`, `src/containerizer/verify/*`, `src/containerizer/build/*` — kind-agnostic
- `sandbox/runner_image/Containerfile` — no image-build-time changes (pre-pull is at orchestrator runtime, see spec §3.3)

---

## Phase 1: Probe (`probe_deb` + schema + base image)

### Task 1.1: Add `DebProbe` to the probe schema (RED + GREEN)

**Files:**
- Modify: `src/containerizer/probe/schema.py`
- Create: `tests/unit/test_probe_schema.py` is already populated; extend it

- [ ] **Step 1: Add the failing test**

Edit `tests/unit/test_probe_schema.py`, append:

```python
from containerizer.probe.schema import DebProbe


def test_deb_probe_round_trips_through_json() -> None:
    probe = DebProbe(
        package="hello",
        version="2.10-3",
        arch="amd64",
        depends=["libc6 (>= 2.34)"],
        pre_depends=[],
        recommends=[],
        maintainer="Santiago Vila <sanvila@debian.org>",
        description="example package",
        systemd_units=["hello.service"],
    )
    blob = probe.model_dump_json()
    restored = DebProbe.model_validate_json(blob)
    assert restored == probe


def test_deb_probe_rejects_extra_fields() -> None:
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        DebProbe.model_validate(
            {
                "package": "x",
                "version": "1",
                "arch": "amd64",
                "extra_unwanted": True,
            }
        )
```

- [ ] **Step 2: Run test, verify it fails**

Run: `pytest tests/unit/test_probe_schema.py -v`
Expected: FAIL with `ImportError: cannot import name 'DebProbe'`.

- [ ] **Step 3: Add `DebProbe` to schema**

Edit `src/containerizer/probe/schema.py`, append before `class ProbeResult`:

```python
class DebProbe(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = 1
    package: str
    version: str
    arch: str
    depends: list[str] = Field(default_factory=list)
    pre_depends: list[str] = Field(default_factory=list)
    recommends: list[str] = Field(default_factory=list)
    maintainer: str | None = None
    description: str | None = None
    systemd_units: list[str] = Field(default_factory=list)
```

And add an optional `deb` field to `ProbeResult`:

```python
class ProbeResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = 1
    kind: InstallerKind
    arch: str | None = None
    elf: ElfProbe | None = None
    deb: DebProbe | None = None
    base_image: BaseImageSuggestion
```

- [ ] **Step 4: Run test, verify it passes**

Run: `pytest tests/unit/test_probe_schema.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/containerizer/probe/schema.py tests/unit/test_probe_schema.py
git -c user.email="github.v5f9w@bitbucket.onl" -c user.signingkey=BE707B220C995478 commit -S -m "$(cat <<'EOF'
feat(probe): add DebProbe schema (#99)

Adds a frozen pydantic model for Debian .deb metadata: package,
version, architecture, Depends/Pre-Depends/Recommends as raw
strings, maintainer, first-line description, and systemd unit
basenames discovered in data.tar. ProbeResult gains an optional
deb field; the existing kind discriminator stays the source of
truth.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

### Task 1.2: `_iter_ar_members` ar reader (RED + GREEN)

**Files:**
- Create: `src/containerizer/probe/deb.py`
- Create: `tests/fixtures/probe/deb_helpers.py`
- Create: `tests/unit/test_probe_deb.py`

- [ ] **Step 1: Write the fixture-deb generator (helper used by every later test)**

Create `tests/fixtures/probe/deb_helpers.py`:

```python
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
) -> None:
    """Write a minimal but valid .deb to *path*."""
    control_fields = [
        f"Package: {package}",
        f"Version: {version}",
        f"Architecture: {architecture}",
        f"Maintainer: {maintainer}",
        f"Depends: {depends}",
        f"Description: {description}",
        "",
    ]
    control_tar = _make_tar_gz({"control": "\n".join(control_fields).encode()})

    data_entries: dict[str, bytes] = {
        "./usr/bin/hello": b"#!/bin/sh\necho hello\n",
    }
    if systemd_unit is not None:
        unit_body = (
            "[Unit]\nDescription=Hello service\n"
            "[Service]\nExecStart=/usr/bin/hello\n"
            "[Install]\nWantedBy=multi-user.target\n"
        )
        data_entries[f"./lib/systemd/system/{systemd_unit}"] = unit_body.encode()
    data_tar = _make_tar_gz(data_entries)

    buf = io.BytesIO()
    buf.write(b"!<arch>\n")
    _ar_append(buf, "debian-binary", b"2.0\n")
    _ar_append(buf, "control.tar.gz", control_tar)
    _ar_append(buf, "data.tar.gz", data_tar)
    path.write_bytes(buf.getvalue())
```

- [ ] **Step 2: Write the failing test for `_iter_ar_members`**

Create `tests/unit/test_probe_deb.py`:

```python
"""Tests for the Debian .deb probe."""

from pathlib import Path

import pytest

from tests.fixtures.probe.deb_helpers import build_minimal_deb


@pytest.fixture
def hello_deb(tmp_path: Path) -> Path:
    deb = tmp_path / "hello_2.10-3_amd64.deb"
    build_minimal_deb(deb)
    return deb


def test_iter_ar_members_yields_three_expected_files(hello_deb: Path) -> None:
    from containerizer.probe.deb import _iter_ar_members

    with hello_deb.open("rb") as fh:
        names = [m.name for m in _iter_ar_members(fh)]

    assert names == ["debian-binary", "control.tar.gz", "data.tar.gz"]


def test_iter_ar_members_rejects_missing_magic(tmp_path: Path) -> None:
    from containerizer.probe.deb import _iter_ar_members

    bogus = tmp_path / "not.deb"
    bogus.write_bytes(b"not an ar archive\n")
    with bogus.open("rb") as fh, pytest.raises(ValueError, match="ar magic"):
        list(_iter_ar_members(fh))
```

- [ ] **Step 3: Run, verify it fails**

Run: `pytest tests/unit/test_probe_deb.py -v`
Expected: FAIL with `ImportError: cannot import name '_iter_ar_members'`.

- [ ] **Step 4: Implement `_iter_ar_members`**

Create `src/containerizer/probe/deb.py`:

```python
"""Debian .deb probe.

Parses metadata from a Debian package: ar archive containing
debian-binary, control.tar.*, data.tar.*. Uses stdlib only.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Iterator

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
```

- [ ] **Step 5: Run, verify both tests pass**

Run: `pytest tests/unit/test_probe_deb.py -v`
Expected: PASS on both tests.

- [ ] **Step 6: Commit**

```bash
git add src/containerizer/probe/deb.py tests/unit/test_probe_deb.py tests/fixtures/probe/deb_helpers.py
git -c user.email="github.v5f9w@bitbucket.onl" -c user.signingkey=BE707B220C995478 commit -S -m "$(cat <<'EOF'
feat(probe): ar reader + fixture-deb generator (#99)

Stdlib-only ar archive iterator for .deb parsing, plus a pure
Python fixture builder so unit tests don't depend on having
dpkg-deb installed. The fixture builds debian-binary +
control.tar.gz + data.tar.gz in an ar wrapper, matching what
dpkg-deb -b would emit.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

### Task 1.3: `_parse_control` + `_extract_control` (RED + GREEN)

**Files:**
- Modify: `src/containerizer/probe/deb.py`
- Modify: `tests/unit/test_probe_deb.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_probe_deb.py`:

```python
def test_parse_control_extracts_required_fields() -> None:
    from containerizer.probe.deb import _parse_control

    text = (
        "Package: hello\n"
        "Version: 2.10-3\n"
        "Architecture: amd64\n"
        "Maintainer: A <a@b.c>\n"
        "Depends: libc6 (>= 2.34)\n"
        "Description: first line\n"
        " continuation 1\n"
        " continuation 2\n"
    )
    fields = _parse_control(text)
    assert fields["Package"] == "hello"
    assert fields["Version"] == "2.10-3"
    assert fields["Architecture"] == "amd64"
    assert fields["Depends"] == "libc6 (>= 2.34)"
    # Multi-line Description: first line + continuation lines preserved.
    assert "first line" in fields["Description"]
    assert "continuation 1" in fields["Description"]


def test_parse_control_stops_at_blank_line() -> None:
    from containerizer.probe.deb import _parse_control

    text = "Package: a\nVersion: 1\n\nPackage: b\n"
    fields = _parse_control(text)
    assert fields["Package"] == "a"
    assert "b" not in fields.get("Package", "")


def test_extract_control_reads_control_file_from_hello_deb(hello_deb: Path) -> None:
    from containerizer.probe.deb import _extract_control

    text = _extract_control(hello_deb)
    assert "Package: hello" in text
    assert "Architecture: amd64" in text
```

- [ ] **Step 2: Run, verify they fail**

Run: `pytest tests/unit/test_probe_deb.py -v -k "control"`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement both helpers**

Append to `src/containerizer/probe/deb.py`:

```python
import tarfile


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
    import io

    with tarfile.open(fileobj=io.BytesIO(blob)) as tf:
        for member in tf:
            if member.name in ("control", "./control"):
                fp = tf.extractfile(member)
                if fp is None:
                    raise ValueError("control entry is not a regular file")
                return fp.read().decode("utf-8", errors="replace")
    raise ValueError("no `control` file in control.tar")
```

- [ ] **Step 4: Run, verify they pass**

Run: `pytest tests/unit/test_probe_deb.py -v`
Expected: PASS on all tests.

- [ ] **Step 5: Commit**

```bash
git add src/containerizer/probe/deb.py tests/unit/test_probe_deb.py
git -c user.email="github.v5f9w@bitbucket.onl" -c user.signingkey=BE707B220C995478 commit -S -m "$(cat <<'EOF'
feat(probe): control file extraction + RFC822 parser (#99)

_extract_control reads control.tar.* out of a .deb's ar archive
and returns the `control` file text. _parse_control turns that
text into a flat dict, joining continuation lines so Description
keeps its multi-line shape.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

### Task 1.4: `_discover_systemd_units` (RED + GREEN)

**Files:**
- Modify: `src/containerizer/probe/deb.py`
- Modify: `tests/unit/test_probe_deb.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_probe_deb.py`:

```python
def test_discover_systemd_units_finds_lib_systemd_unit(hello_deb: Path) -> None:
    from containerizer.probe.deb import _discover_systemd_units

    units = _discover_systemd_units(hello_deb)
    assert units == ["hello.service"]


def test_discover_systemd_units_empty_when_no_units(tmp_path: Path) -> None:
    from containerizer.probe.deb import _discover_systemd_units
    from tests.fixtures.probe.deb_helpers import build_minimal_deb

    bare = tmp_path / "bare.deb"
    build_minimal_deb(bare, systemd_unit=None)
    assert _discover_systemd_units(bare) == []
```

- [ ] **Step 2: Run, verify they fail**

Run: `pytest tests/unit/test_probe_deb.py -v -k "discover"`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement `_discover_systemd_units`**

Append to `src/containerizer/probe/deb.py`:

```python
def _discover_systemd_units(deb_path: Path) -> list[str]:
    """Scan data.tar.* for systemd unit files under lib/systemd/system/
    or usr/lib/systemd/system/. Returns basenames sorted for determinism.
    """
    import io

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
            name = member.name.lstrip("./")
            if name.startswith("lib/systemd/system/") or name.startswith(
                "usr/lib/systemd/system/"
            ):
                basename = name.rsplit("/", 1)[-1]
                if basename and basename not in units:
                    units.append(basename)
    return sorted(units)
```

- [ ] **Step 4: Run, verify they pass**

Run: `pytest tests/unit/test_probe_deb.py -v`
Expected: PASS on all tests.

- [ ] **Step 5: Commit**

```bash
git add src/containerizer/probe/deb.py tests/unit/test_probe_deb.py
git -c user.email="github.v5f9w@bitbucket.onl" -c user.signingkey=BE707B220C995478 commit -S -m "$(cat <<'EOF'
feat(probe): discover systemd units inside data.tar (#99)

Walks the .deb's data.tar.* and records basenames of any unit
files shipped under lib/systemd/system/ or usr/lib/systemd/system/.
The probe surfaces these so the generated README can mention what
service the install will register, without driving runtime policy
(which comes from trace events only).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

### Task 1.5: `probe_deb()` top-level (RED + GREEN)

**Files:**
- Modify: `src/containerizer/probe/deb.py`
- Modify: `tests/unit/test_probe_deb.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_probe_deb.py`:

```python
def test_probe_deb_returns_populated_DebProbe(hello_deb: Path) -> None:
    from containerizer.probe.deb import probe_deb

    probe = probe_deb(hello_deb)
    assert probe.package == "hello"
    assert probe.version == "2.10-3"
    assert probe.arch == "amd64"
    assert probe.depends == ["libc6 (>= 2.34)"]
    assert probe.maintainer == "Test <test@example.com>"
    assert probe.description is not None and probe.description.startswith("test package")
    assert probe.systemd_units == ["hello.service"]


def test_probe_deb_handles_missing_optional_fields(tmp_path: Path) -> None:
    from containerizer.probe.deb import probe_deb
    from tests.fixtures.probe.deb_helpers import build_minimal_deb

    spartan = tmp_path / "spartan.deb"
    build_minimal_deb(spartan, depends="", systemd_unit=None)
    probe = probe_deb(spartan)
    assert probe.depends == []
    assert probe.systemd_units == []
```

- [ ] **Step 2: Run, verify it fails**

Run: `pytest tests/unit/test_probe_deb.py -v -k "probe_deb"`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement `probe_deb`**

Append to `src/containerizer/probe/deb.py`:

```python
from containerizer.probe.schema import DebProbe


def probe_deb(path: Path) -> DebProbe:
    """Parse a Debian .deb and return a typed DebProbe."""
    text = _extract_control(path)
    fields = _parse_control(text)

    def _split(value: str) -> list[str]:
        return [s.strip() for s in value.split(",") if s.strip()] if value else []

    description = fields.get("Description")
    if description is not None:
        # Keep only the first paragraph; multi-line description's
        # first newline already separates summary from extended text.
        description = description.splitlines()[0] if description else None

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
```

- [ ] **Step 4: Run, verify it passes**

Run: `pytest tests/unit/test_probe_deb.py -v`
Expected: PASS on all tests.

- [ ] **Step 5: Commit**

```bash
git add src/containerizer/probe/deb.py tests/unit/test_probe_deb.py
git -c user.email="github.v5f9w@bitbucket.onl" -c user.signingkey=BE707B220C995478 commit -S -m "$(cat <<'EOF'
feat(probe): probe_deb top-level (#99)

Assembles _extract_control + _parse_control + _discover_systemd_units
into a typed DebProbe. Required fields (Package, Version,
Architecture) raise on absence via the pydantic model. Optional
Depends/Pre-Depends/Recommends are split on commas; Description's
first paragraph is kept as a single-line summary.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

### Task 1.6: Dispatch `InstallerKind.deb` in `installer.probe()` (RED + GREEN)

**Files:**
- Modify: `src/containerizer/probe/installer.py`
- Modify: `tests/unit/test_probe_installer.py`

- [ ] **Step 1: Replace the "deb is unsupported" assertion**

In `tests/unit/test_probe_installer.py`, replace `test_probe_unsupported_kind_raises` with:

```python
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
```

- [ ] **Step 2: Run, verify both fail**

Run: `pytest tests/unit/test_probe_installer.py -v -k "deb or unsupported"`
Expected: FAIL — `probe(deb)` still raises `UnsupportedInstallerKind`.

- [ ] **Step 3: Add deb dispatch in installer.py**

In `src/containerizer/probe/installer.py`, add the import:

```python
from containerizer.probe.deb import probe_deb
```

Replace the body of `probe()`:

```python
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
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/unit/test_probe_installer.py -v`
Expected: `test_probe_deb_returns_DebProbe` still **fails** because `suggest_base_image` does not yet accept `DebProbe`. That's wired in Task 1.7. The test for rpm passes.

- [ ] **Step 5: Skip the deb test temporarily and commit**

Don't commit yet — go straight to Task 1.7. The two changes (dispatch + base image) land together so no commit ships a broken intermediate state.

---

### Task 1.7: `suggest_base_image` accepts `DebProbe` (RED + GREEN, includes 1.6 cleanup)

**Files:**
- Modify: `src/containerizer/probe/base_image.py`
- Modify: `tests/unit/test_probe_base_image.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_probe_base_image.py`:

```python
from containerizer.probe.schema import DebProbe


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
```

- [ ] **Step 2: Run, verify the new tests fail**

Run: `pytest tests/unit/test_probe_base_image.py -v -k "deb"`
Expected: FAIL — `suggest_base_image(DebProbe)` doesn't dispatch.

- [ ] **Step 3: Make `suggest_base_image` kind-dispatching**

Replace `src/containerizer/probe/base_image.py` with:

```python
"""Base-image suggestion derived from probe metadata.

The picker is intentionally conservative: choose an Ubuntu LTS whose glibc
is new enough to run the binary (ELF), or whose package universe matches the
deb's declared architecture (Debian package).
"""

from __future__ import annotations

from containerizer.probe.schema import BaseImageSuggestion, DebProbe, ElfProbe


def suggest_base_image(probe: ElfProbe | DebProbe) -> BaseImageSuggestion:
    if isinstance(probe, DebProbe):
        return _suggest_for_deb(probe)
    return _suggest_for_elf(probe)


_SUPPORTED_DEB_ARCHS = {"amd64", "arm64", "all"}


def _suggest_for_deb(deb: DebProbe) -> BaseImageSuggestion:
    if deb.arch not in _SUPPORTED_DEB_ARCHS:
        raise ValueError(
            f"unsupported .deb architecture {deb.arch!r}; supported: "
            f"{sorted(_SUPPORTED_DEB_ARCHS)}"
        )
    reasons: list[str] = []
    if deb.arch == "all":
        reasons.append("architecture-independent deb; picked ubuntu:24.04 LTS")
    else:
        reasons.append(f"deb architecture {deb.arch}; picked ubuntu:24.04 LTS")
    return BaseImageSuggestion(image="ubuntu:24.04", reasons=reasons)


def _suggest_for_elf(elf: ElfProbe) -> BaseImageSuggestion:
    reasons: list[str] = []
    image = _pick_for_glibc(elf.glibc_min, reasons)
    reasons.append(f"architecture: {elf.arch}")
    return BaseImageSuggestion(image=image, reasons=reasons)


def _pick_for_glibc(glibc_min: str | None, reasons: list[str]) -> str:
    if glibc_min is None:
        reasons.append("no glibc requirement detected; picked ubuntu:24.04")
        return "ubuntu:24.04"
    try:
        major_s, minor_s = glibc_min.split(".", 1)
        major = int(major_s)
        minor = int(minor_s)
    except (ValueError, AttributeError):
        reasons.append(f"could not parse glibc version '{glibc_min}'; picked ubuntu:24.04")
        return "ubuntu:24.04"
    if (major, minor) > (2, 35):
        reasons.append(f"glibc {glibc_min} requires Ubuntu 24.04 LTS or newer")
        return "ubuntu:24.04"
    if (major, minor) >= (2, 31):
        reasons.append(f"glibc {glibc_min} fits Ubuntu 22.04 LTS")
        return "ubuntu:22.04"
    reasons.append(f"glibc {glibc_min} fits Ubuntu 20.04 LTS")
    return "ubuntu:20.04"
```

- [ ] **Step 4: Run all probe tests**

Run: `pytest tests/unit/test_probe_base_image.py tests/unit/test_probe_installer.py tests/unit/test_probe_deb.py tests/unit/test_probe_schema.py -v`
Expected: PASS on every test, including the deb dispatch from Task 1.6.

- [ ] **Step 5: Lint + typecheck**

Run: `ruff check src tests && mypy src`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/containerizer/probe/installer.py src/containerizer/probe/base_image.py tests/unit/test_probe_installer.py tests/unit/test_probe_base_image.py
git -c user.email="github.v5f9w@bitbucket.onl" -c user.signingkey=BE707B220C995478 commit -S -m "$(cat <<'EOF'
feat(probe): wire .deb through probe() + base-image dispatch (#99)

probe() now dispatches InstallerKind.deb to probe_deb and returns
a populated ProbeResult.deb. suggest_base_image becomes
kind-dispatching: ELF keeps the existing glibc-based logic, deb
picks ubuntu:24.04 for amd64/arm64/all and raises ValueError for
unsupported archs (i386, armhf, ppc64el, ...). RPM still raises
UnsupportedInstallerKind.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Phase 2: Orchestrator refactor (extract `run_elf_install`)

### Task 2.1: Extract install workload into `run_elf_install` (refactor only)

**Files:**
- Modify: `sandbox/runner_image/trace-orchestrator.sh`

This is a pure refactor: the existing install workload (current lines 146-228) moves into a `run_elf_install` function. The if/else mode-dispatch stays. Behavior must be byte-for-byte identical.

- [ ] **Step 1: Edit the orchestrator**

In `sandbox/runner_image/trace-orchestrator.sh`, replace the block from line 146 (`if [[ "$MODE" == "install" ]]; then`) through line 228 (`echo "trace-orchestrator: COMPLETE" >&2`) with:

```bash
run_elf_install() {
    # ---- existing M2 install-mode workload, extracted into a function
    # so Phase 3 can dispatch between ELF and .deb installer kinds.
    echo "trace-orchestrator: running installer $INSTALLER" >&2

    if [[ -n "${CONTAINERIZER_INTERACTIVE:-}" ]]; then
        interactive="${CONTAINERIZER_INTERACTIVE}"
    elif [[ -t 1 ]]; then
        interactive=1
    else
        interactive=0
    fi

    if [[ "$interactive" == 1 ]]; then
        "$INSTALLER" <&0 &
        installer_pid="$!"
    else
        exec 3> >(tee "$TRACE_DIR/install.log")
        "$INSTALLER" >&3 2>&3 &
        installer_pid="$!"
        exec 3>&-
    fi

    for name in "${!fallbacks[@]}"; do
        # shellcheck disable=SC2086
        strace -f -o "$TRACE_DIR/$name.fallback.log" ${domain[$name]} -p "$installer_pid" 2>/dev/null &
        collector_pids+=("$!")
    done

    install_rc=0
    wait "$installer_pid" || install_rc=$?
    echo "$install_rc" > "$TRACE_DIR/installer.exitcode"

    if (( install_rc != 0 )); then
        echo "failed" > "$TRACE_DIR/install.status"
        echo "trace-orchestrator: installer exited non-zero ($install_rc); finalising PARTIAL" >&2
        finalize_marker PARTIAL
        exit 0
    fi
    awk '{split($1,a,"."); printf "monotonic_ns: %s%09d\n", a[1], a[2]*10000000}' /proc/uptime \
        > "$TRACE_DIR/PHASE_MARKER"

    if [[ "$interactive" == 1 ]]; then
        echo "trace-orchestrator: installer complete. exercise the software, then press <Enter> here to finalise (or close stdin)." >&2
        read -r _ || true
    else
        echo "trace-orchestrator: installer complete (non-interactive); finalising" >&2
    fi
    finalize_marker COMPLETE
    echo "trace-orchestrator: COMPLETE" >&2
}

if [[ "$MODE" == "install" ]]; then
    run_elf_install
else
    # ---- M6 verify-mode workload ----
    echo "trace-orchestrator: dispatching to verify-orchestrator (mode=verify)" >&2
    /usr/local/bin/verify-orchestrator.sh || true
    if (( ${#collector_pids[@]} > 0 )); then
        for pid in "${collector_pids[@]}"; do
            kill -TERM "$pid" 2>/dev/null || true
        done
        sleep 1
        for pid in "${collector_pids[@]}"; do
            kill -KILL "$pid" 2>/dev/null || true
        done
    fi
    echo "trace-orchestrator: verify mode complete" >&2
fi
```

- [ ] **Step 2: Shellcheck**

Run: `shellcheck sandbox/runner_image/trace-orchestrator.sh`
Expected: clean (same warnings as before the refactor; this PR doesn't tighten anything new).

- [ ] **Step 3: Run the existing trace-pipeline integration test as a regression gate**

Run: `pytest tests/integration/trace/test_trace_pipeline.py -v -m integration`
Expected: PASS. The synthetic ELF installer behaves exactly as before because the refactor preserved every line of the workload.

If this test is skipped because the run isn't inside the trace-integration CI environment, run it via the existing rebuild-runner-image route documented in `MANUAL.md` (or wait for the CI gate in Phase 4 to catch any regression).

- [ ] **Step 4: Commit**

```bash
git add sandbox/runner_image/trace-orchestrator.sh
git -c user.email="github.v5f9w@bitbucket.onl" -c user.signingkey=BE707B220C995478 commit -S -m "$(cat <<'EOF'
refactor(trace): extract install workload into run_elf_install (#99)

Pure refactor: moves the existing M2 install-mode workload into a
run_elf_install bash function so Phase 3 can wire a sibling
run_deb_install behind a magic-bytes dispatch. Behavior is
byte-for-byte identical. Validated against the existing
trace-pipeline integration test before commit.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Phase 3: Orchestrator dispatch + `run_deb_install`

### Task 3.1: Podman stub for orchestrator unit tests

**Files:**
- Create: `tests/fixtures/trace/podman-stub.sh`

- [ ] **Step 1: Write the stub**

Create `tests/fixtures/trace/podman-stub.sh`:

```bash
#!/usr/bin/env bash
# Recording stub used by tests/unit/test_orchestrator_dispatch.py.
# Echoes its argv (one line per call) to $PODMAN_STUB_LOG and exits 0.
# When the first arg is "exec", echo to /tmp/install.log to mimic apt's
# stdout going to install.log via the orchestrator's redirect.
set -euo pipefail
log="${PODMAN_STUB_LOG:-/tmp/podman-stub.log}"
printf 'podman'; for a in "$@"; do printf ' %q' "$a"; done; printf '\n' >> "$log"

case "${1:-}" in
    pull)
        # pretend to pull
        ;;
    run)
        # `run -d --rm --name ... ubuntu:24.04` -- print a fake CID.
        echo "stub-cid-$$"
        ;;
    exec)
        # pretend apt-get install succeeded
        ;;
    stop)
        ;;
    *)
        ;;
esac
exit 0
```

- [ ] **Step 2: Make it executable + commit (will be referenced by Task 3.4's test)**

```bash
chmod +x tests/fixtures/trace/podman-stub.sh
git add tests/fixtures/trace/podman-stub.sh
git -c user.email="github.v5f9w@bitbucket.onl" -c user.signingkey=BE707B220C995478 commit -S -m "$(cat <<'EOF'
test(trace): podman recording stub for orchestrator unit tests (#99)

Used by tests/unit/test_orchestrator_dispatch.py to assert the
.deb dispatch produces the right podman argv without actually
hitting podman. Logs each invocation to $PODMAN_STUB_LOG so tests
can grep for "run -d", "exec", "stop" boundaries.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3.2: `_detect_kind` shell helper (RED + GREEN)

**Files:**
- Modify: `sandbox/runner_image/trace-orchestrator.sh`
- Create: `tests/unit/test_orchestrator_dispatch.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_orchestrator_dispatch.py`:

```python
"""Unit tests for the trace-orchestrator.sh installer-kind dispatch."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ORCH = Path("sandbox/runner_image/trace-orchestrator.sh")


def _source_detect_kind(installer: Path) -> str:
    """Source the orchestrator and invoke _detect_kind in a subshell.

    We can't run the full orchestrator (it requires bpftrace + bcc),
    but we can source it up to and including the helper definitions
    and then call _detect_kind directly.
    """
    script = f"""
set -e
# Strip the orchestrator's `set -euo pipefail` and run-from-top
# guard, then define a no-op main and load just the helpers.
source <(sed -n '/^_detect_kind() /,/^}}$/p' {ORCH})
_detect_kind {installer!s}
"""
    result = subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash required")
def test_detect_kind_recognises_elf(tmp_path: Path) -> None:
    elf = tmp_path / "x"
    elf.write_bytes(b"\x7fELF" + b"\x00" * 32)
    assert _source_detect_kind(elf) == "elf"


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash required")
def test_detect_kind_recognises_deb(tmp_path: Path) -> None:
    deb = tmp_path / "x.deb"
    deb.write_bytes(b"!<arch>\n" + b"\x00" * 32)
    assert _source_detect_kind(deb) == "deb"


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash required")
def test_detect_kind_unknown(tmp_path: Path) -> None:
    other = tmp_path / "x"
    other.write_bytes(b"\x00" * 32)
    assert _source_detect_kind(other) == "unknown"
```

- [ ] **Step 2: Run, verify it fails**

Run: `pytest tests/unit/test_orchestrator_dispatch.py -v`
Expected: FAIL — `_detect_kind` not defined in orchestrator.

- [ ] **Step 3: Add `_detect_kind` to the orchestrator**

In `sandbox/runner_image/trace-orchestrator.sh`, add immediately after the `finalize_marker` function definition (currently around line 105):

```bash
_detect_kind() {
    # Echo one of: elf, deb, unknown. Reads the first 8 bytes.
    local path="$1"
    local head
    head=$(dd if="$path" bs=8 count=1 2>/dev/null)
    if [[ "$head" == $'\x7fELF'* ]]; then
        echo "elf"
        return
    fi
    if [[ "$head" == "!<arch>"$'\n'* ]]; then
        echo "deb"
        return
    fi
    echo "unknown"
}
```

- [ ] **Step 4: Run, verify it passes**

Run: `pytest tests/unit/test_orchestrator_dispatch.py -v`
Expected: PASS on all three tests.

- [ ] **Step 5: Commit**

```bash
git add sandbox/runner_image/trace-orchestrator.sh tests/unit/test_orchestrator_dispatch.py
git -c user.email="github.v5f9w@bitbucket.onl" -c user.signingkey=BE707B220C995478 commit -S -m "$(cat <<'EOF'
feat(trace): _detect_kind shell helper for orchestrator dispatch (#99)

Reads the first 8 bytes of /installer and echoes elf / deb /
unknown. Matches the host-side detect_kind() in installer.py;
duplication is acceptable for a single magic-bytes check. Wired
into the dispatch case in the next commit.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3.3: `run_deb_install` skeleton + dispatch

**Files:**
- Modify: `sandbox/runner_image/trace-orchestrator.sh`

- [ ] **Step 1: Add `run_deb_install` to the orchestrator**

In `sandbox/runner_image/trace-orchestrator.sh`, immediately after the `run_elf_install` function added in Task 2.1, add:

```bash
run_deb_install() {
    # First-run pull of ubuntu:24.04. Subsequent runs hit the cached image.
    # The pull is on the install side of PHASE_MARKER so it does not
    # appear in runtime policy.
    podman pull docker.io/library/ubuntu:24.04 > "$TRACE_DIR/deb-pull.log" 2>&1

    # Start a long-lived nested ubuntu container with systemd as PID 1
    # so postinst's `systemctl start <unit>` works. --network=host
    # shares the nested container's netns with the outer trace runner;
    # the user reaches the nested daemon via `podman exec deb-install`.
    podman run -d --rm --name deb-install \
        --systemd=always --privileged \
        --network=host \
        -v "$INSTALLER:/installer:ro" \
        docker.io/library/ubuntu:24.04 \
        > "$TRACE_DIR/deb-install.cid" 2> "$TRACE_DIR/deb-install.err"

    # Extend the INT/TERM trap so Ctrl-C during install does not leak
    # the nested container. The outer trap from line ~107 still fires
    # finalize_marker PARTIAL; this stop runs first.
    trap 'podman stop -t 2 deb-install >/dev/null 2>&1 || true; finalize_marker PARTIAL; exit 0' INT TERM

    # Sync apt + install /installer inside the nested container. apt is
    # foreground; no `<&0` redirect needed (#95's issue applies only
    # to backgrounded interactive installers).
    podman exec deb-install bash -c '
        export DEBIAN_FRONTEND=noninteractive
        apt-get update &&
        apt-get install -y /installer
    ' > "$TRACE_DIR/install.log" 2>&1
    install_rc=$?
    echo "$install_rc" > "$TRACE_DIR/installer.exitcode"

    if (( install_rc != 0 )); then
        echo "failed" > "$TRACE_DIR/install.status"
        podman stop -t 5 deb-install >/dev/null 2>&1 || true
        echo "trace-orchestrator: deb install failed (rc=$install_rc); finalising PARTIAL" >&2
        finalize_marker PARTIAL
        exit 0
    fi

    awk '{split($1,a,"."); printf "monotonic_ns: %s%09d\n", a[1], a[2]*10000000}' /proc/uptime \
        > "$TRACE_DIR/PHASE_MARKER"

    if [[ -n "${CONTAINERIZER_INTERACTIVE:-}" ]]; then
        interactive="${CONTAINERIZER_INTERACTIVE}"
    elif [[ -t 1 ]]; then
        interactive=1
    else
        interactive=0
    fi

    if [[ "$interactive" == 1 ]]; then
        echo "trace-orchestrator: deb installed. exercise the software (podman exec deb-install <cmd>), then press <Enter> here to finalise." >&2
        read -r _ || true
    else
        echo "trace-orchestrator: deb installed (non-interactive); finalising" >&2
    fi

    podman stop -t 10 deb-install >/dev/null 2>&1 || true
    finalize_marker COMPLETE
    echo "trace-orchestrator: COMPLETE" >&2
}
```

- [ ] **Step 2: Replace the unconditional `run_elf_install` call with a dispatch**

In `sandbox/runner_image/trace-orchestrator.sh`, find the block:

```bash
if [[ "$MODE" == "install" ]]; then
    run_elf_install
else
```

and replace it with:

```bash
if [[ "$MODE" == "install" ]]; then
    INSTALLER_KIND="$(_detect_kind "$INSTALLER")"
    echo "trace-orchestrator: installer kind=$INSTALLER_KIND" >&2
    case "$INSTALLER_KIND" in
        elf)
            run_elf_install
            ;;
        deb)
            run_deb_install
            ;;
        *)
            echo "trace-orchestrator: unsupported installer kind: $INSTALLER_KIND" >&2
            finalize_marker PARTIAL
            exit 0
            ;;
    esac
else
```

- [ ] **Step 3: Shellcheck**

Run: `shellcheck sandbox/runner_image/trace-orchestrator.sh`
Expected: clean.

- [ ] **Step 4: Commit**

```bash
git add sandbox/runner_image/trace-orchestrator.sh
git -c user.email="github.v5f9w@bitbucket.onl" -c user.signingkey=BE707B220C995478 commit -S -m "$(cat <<'EOF'
feat(trace): run_deb_install + magic-bytes dispatch (#99)

trace-orchestrator now branches by installer kind: ELF keeps the
existing direct-exec path; .deb spins up a nested ubuntu:24.04
container under --systemd=always, apt installs the deb via podman
exec, writes PHASE_MARKER, then waits (interactive) or finalises
(CI) per CONTAINERIZER_INTERACTIVE.

The INT/TERM trap is extended inside run_deb_install so Ctrl-C
stops the nested container before writing PARTIAL.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3.4: Add a podman-stub unit test for `run_deb_install` argv

**Files:**
- Modify: `tests/unit/test_orchestrator_dispatch.py`

- [ ] **Step 1: Add the failing test**

Append to `tests/unit/test_orchestrator_dispatch.py`:

```python
import os


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash required")
def test_run_deb_install_invokes_expected_podman_argv(tmp_path: Path) -> None:
    """Source the orchestrator with a podman stub on PATH and verify
    the recorded argv contains pull, run -d, exec, stop."""

    deb = tmp_path / "x.deb"
    deb.write_bytes(b"!<arch>\n" + b"\x00" * 32)
    log = tmp_path / "podman-stub.log"
    trace_dir = tmp_path / "trace"
    trace_dir.mkdir()

    stub_dir = tmp_path / "stub"
    stub_dir.mkdir()
    shutil.copy("tests/fixtures/trace/podman-stub.sh", stub_dir / "podman")
    (stub_dir / "podman").chmod(0o755)

    env = {
        **os.environ,
        "PATH": f"{stub_dir}:{os.environ['PATH']}",
        "PODMAN_STUB_LOG": str(log),
        "INSTALLER": str(deb),
        "TRACE_DIR": str(trace_dir),
    }

    script = f"""
set -e
# Define no-op finalize_marker so run_deb_install can call it
# without depending on the rest of the orchestrator.
finalize_marker() {{ : ; }}
# Source only run_deb_install from the orchestrator script.
source <(awk '/^run_deb_install\\(\\) /,/^}}$/' {ORCH})
run_deb_install
"""
    subprocess.run(
        ["bash", "-c", script],
        env=env,
        check=True,
    )

    recorded = log.read_text().splitlines()
    joined = "\n".join(recorded)
    assert "pull docker.io/library/ubuntu:24.04" in joined
    assert "run -d --rm --name deb-install" in joined
    assert "--systemd=always" in joined
    assert "exec deb-install" in joined
    assert "stop -t 10 deb-install" in joined
```

- [ ] **Step 2: Run, verify it passes**

Run: `pytest tests/unit/test_orchestrator_dispatch.py -v -k "podman_argv"`
Expected: PASS. If it fails, fix `run_deb_install` (not the test).

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_orchestrator_dispatch.py
git -c user.email="github.v5f9w@bitbucket.onl" -c user.signingkey=BE707B220C995478 commit -S -m "$(cat <<'EOF'
test(trace): assert run_deb_install podman argv shape (#99)

Sources run_deb_install with a recording podman stub on PATH and
verifies the dispatch produces pull -> run -d --rm --name
deb-install --systemd=always -> exec deb-install apt-get install
-> stop. Catches regressions in the dispatch without needing a
full trace-runner image.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Phase 4: Integration tests

### Task 4.1: Trace integration test for `.deb`

**Files:**
- Create: `tests/integration/trace/test_deb_pipeline.py`

- [ ] **Step 1: Write the test**

Create `tests/integration/trace/test_deb_pipeline.py`:

```python
"""Integration: end-to-end trace of a fixture .deb via the
`containerizer trace` CLI. Mirrors the subprocess pattern used by
test_systemd_pid1.py (no direct use of TraceRunner / RunnerImage).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tests.fixtures.probe.deb_helpers import build_minimal_deb

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.integration
def test_trace_completes_for_minimal_deb(tmp_path: Path) -> None:
    deb = tmp_path / "hello_2.10-3_amd64.deb"
    build_minimal_deb(deb)

    out = tmp_path / "trace"
    out.mkdir()

    result = subprocess.run(
        ["containerizer", "trace", str(deb), "-o", str(out)],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=600,
    )

    assert result.returncode == 0, (
        f"containerizer trace exited {result.returncode}\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )

    # Either COMPLETE (apt succeeded + non-interactive finalise) or
    # PARTIAL (network failure or collector attach failure). Either
    # proves the magic-bytes dispatch landed in run_deb_install.
    assert (out / "COMPLETE").exists() or (out / "PARTIAL").exists(), (
        f"no marker written; stderr was:\n{result.stderr}"
    )

    # install.log should mention apt activity, confirming run_deb_install
    # ran rather than run_elf_install.
    install_log = out / "install.log"
    if install_log.exists():
        log = install_log.read_text(errors="replace")
        assert "apt" in log.lower() or "dpkg" in log.lower(), (
            f"install.log doesn't look like an apt run:\n{log[:500]}"
        )
```

- [ ] **Step 2: Verify the test runs locally (or in CI)**

This test is marked `integration` and only runs under `pytest -m integration`. Run it via the existing rebuild path (same flow as `test_systemd_pid1.py`):

Run: `pytest tests/integration/trace/test_deb_pipeline.py -v -m integration`
Expected: PASS, OR a deterministic skip if the local environment lacks podman + Linux kernel.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/trace/test_deb_pipeline.py
git -c user.email="github.v5f9w@bitbucket.onl" -c user.signingkey=BE707B220C995478 commit -S -m "$(cat <<'EOF'
test(trace): integration test for .deb trace pipeline (#99)

Builds a minimal fixture deb via deb_helpers and runs the full
TraceRunner against it under the systemd-PID-1 runner image. CI
acceptance: COMPLETE or PARTIAL marker written; if COMPLETE, the
analyzer's trace.json populates. Proves the magic-bytes dispatch
reaches run_deb_install and the nested apt install completes.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4.2: Build integration test for `.deb`

**Files:**
- Create: `tests/integration/build/test_build_deb.py`

- [ ] **Step 1: Write the test**

Create `tests/integration/build/test_build_deb.py`:

```python
"""Integration: end-to-end `containerizer build foo.deb --name hello`.
Mirrors the subprocess pattern (CLI-driven, no direct imports of
build.pipeline)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tests.fixtures.probe.deb_helpers import build_minimal_deb

pytestmark = pytest.mark.integration


@pytest.mark.integration
def test_build_produces_artifacts_for_minimal_deb(tmp_path: Path) -> None:
    deb = tmp_path / "hello_2.10-3_amd64.deb"
    build_minimal_deb(deb)
    out_dir = tmp_path / "out"

    result = subprocess.run(
        ["containerizer", "build", str(deb), "--name", "hello", "-o", str(out_dir)],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=900,
    )
    assert result.returncode == 0, (
        f"containerizer build exited {result.returncode}\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )

    name_dir = out_dir / "hello"
    containerfile = name_dir / "Containerfile"
    quadlet = name_dir / "hello.container"
    seccomp = name_dir / "seccomp.json"
    readme = name_dir / "README.md"

    assert containerfile.exists(), f"missing {containerfile}"
    assert quadlet.exists(), f"missing {quadlet}"
    assert seccomp.exists(), f"missing {seccomp}"
    assert readme.exists(), f"missing {readme}"
    assert "ubuntu:24.04" in containerfile.read_text()
```

- [ ] **Step 2: Run + verify**

Run: `pytest tests/integration/build/test_build_deb.py -v -m integration`
Expected: PASS.

Verify the output directory layout against `tests/integration/build/test_build_smoke.py` (existing ELF-based build smoke). If `containerizer build`'s `-o` flag places artifacts directly in `out_dir` (not `out_dir/<name>/`), adjust `name_dir = out_dir`. Read `src/containerizer/build/pipeline.py:run_pipeline` and the build CLI for the exact layout.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/build/test_build_deb.py
git -c user.email="github.v5f9w@bitbucket.onl" -c user.signingkey=BE707B220C995478 commit -S -m "$(cat <<'EOF'
test(build): integration test for .deb build pipeline (#99)

End-to-end `containerizer build foo.deb --name foo` against a
fixture deb. Asserts that Containerfile, Quadlet, seccomp.json,
and README.md all land in the output directory and that the
generated Containerfile picks the ubuntu:24.04 base image.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4.3: Wire deb tests into the `trace-integration` CI job (if not auto-discovered)

**Files:**
- Read: `.github/workflows/trace-integration.yml`
- Possibly modify: `.github/workflows/trace-integration.yml`

- [ ] **Step 1: Read the existing workflow**

Run: `cat .github/workflows/trace-integration.yml`

Look for the pytest invocation. If it's `pytest -m integration tests/integration/`, the new tests are picked up automatically — no edit needed; just confirm and skip to Step 3.

If the invocation lists individual test files (less likely), add the two new paths:

```yaml
        run: |
          pytest -m integration \
            tests/integration/trace/test_trace_pipeline.py \
            tests/integration/trace/test_systemd_pid1.py \
            tests/integration/trace/test_deb_pipeline.py \
            tests/integration/build/test_build_deb.py
```

- [ ] **Step 2: If edited, commit**

```bash
git add .github/workflows/trace-integration.yml
git -c user.email="github.v5f9w@bitbucket.onl" -c user.signingkey=BE707B220C995478 commit -S -m "$(cat <<'EOF'
ci(trace-integration): include .deb integration tests (#99)

Adds test_deb_pipeline.py and test_build_deb.py to the trace
integration matrix so the .deb dispatch is exercised end-to-end
on every push.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 3: Push the branch and open the PR**

```bash
git push -u origin feat/issue-99-deb-support
gh pr create --repo SupremeCommanderHedgehog/containerizer \
  --title "feat(probe,trace): Debian .deb installer support" \
  --body "$(cat <<'EOF'
## Summary
- Probe parses .deb metadata (Package, Version, Arch, Depends, systemd units) via stdlib ar + tarfile (no python-debian dep)
- suggest_base_image is kind-dispatching; .deb amd64/arm64/all → ubuntu:24.04
- trace-orchestrator.sh dispatches on /installer's magic bytes; .deb runs apt install inside a nested ubuntu:24.04 --systemd=always container so postinst's systemctl start works
- Existing analyze/generate/verify/build pipeline consumes the trace unchanged

## Test plan
- [x] Unit: probe_deb, _parse_control, _discover_systemd_units, base_image deb dispatch
- [x] Unit: orchestrator _detect_kind, run_deb_install argv via podman stub
- [x] Integration (CI): trace pipeline against fixture deb
- [x] Integration (CI): build pipeline against fixture deb
- [ ] Manual: scenario 12 (nginx-light end-to-end) — follow-up commit

Closes #99.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Phase 5: Manual scenario 12 (optional)

### Task 5.1: Document a real-package smoke test

**Files:**
- Modify: `MANUAL.md`

- [ ] **Step 1: Append a scenario 12 section to `MANUAL.md`**

Open `MANUAL.md` and append:

```markdown
## Scenario 12 — nginx-light Debian package end-to-end

**Status:** TODO — exercise once #99 lands on main.

**Steps:**
1. Download `nginx-light` for amd64: `apt download nginx-light` on a fresh Debian/Ubuntu host, or grab the `.deb` from packages.debian.org/bookworm/nginx-light.
2. From PowerShell on Windows:
   ```pwsh
   PS> containerizer build .\nginx-light_*_amd64.deb --name nginx
   ```
3. When the orchestrator prints "exercise the software, then press Enter":
   - From a second shell: `podman exec deb-install curl -sI http://localhost/`.
   - Confirm HTTP 200 / nginx response banner.
   - Press Enter in the main shell.
4. Verify `out/nginx/` contains `Containerfile`, `nginx.container`, `seccomp.json`, `README.md`.
5. `podman build out/nginx -t nginx-test` then `podman run --rm -p 8080:80 nginx-test`; `curl http://localhost:8080/` from the host.

**Acceptance:** the generated image starts cleanly under strict policy and serves the index page.
```

- [ ] **Step 2: Commit**

```bash
git add MANUAL.md
git -c user.email="github.v5f9w@bitbucket.onl" -c user.signingkey=BE707B220C995478 commit -S -m "$(cat <<'EOF'
docs(manual): scenario 12 nginx-light end-to-end (#99)

Captures the real-world smoke test pattern for a .deb-based daemon:
download nginx-light, run containerizer build, smoke-test via
podman exec on the nested container, then rebuild the generated
image under strict policy and verify it serves traffic.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Self-review checklist (run before declaring done)

- [ ] `pytest tests/unit -v` — all green
- [ ] `pytest -m integration tests/integration/ -v` — all green in CI
- [ ] `ruff check src tests` — clean
- [ ] `mypy src` — clean
- [ ] `shellcheck sandbox/runner_image/trace-orchestrator.sh` — no new warnings
- [ ] `git log feat/issue-99-deb-support --oneline` reads as a coherent story (probe → refactor → dispatch → tests → docs)
- [ ] Every commit signed (`git log --show-signature feat/issue-99-deb-support | grep -c "Good signature"` equals commit count)
- [ ] PR description references #99 and links the spec
