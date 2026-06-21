"""Unit tests for the trace-orchestrator.sh installer-kind dispatch."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ORCH = Path("sandbox/runner_image/trace-orchestrator.sh")


def _source_detect_kind(installer: Path) -> str:
    """Source the orchestrator's _detect_kind helper in a subshell and
    return its stdout for the given installer path.

    Extracts the function body with sed (start of `_detect_kind() ` through
    the next bare `}` line) and runs it in isolation without the rest of
    the orchestrator (which would require bpftrace + bcc + a real podman).
    """
    # Use POSIX-style paths so the f-string interpolation does not embed
    # Windows backslashes (which bash would interpret as escapes) when the
    # tests run under git-bash on Windows. The relative form is preserved.
    script = f"""
set -e
source <(sed -n '/^_detect_kind() /,/^}}$/p' {ORCH.as_posix()})
_detect_kind {Path(installer).as_posix()}
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
