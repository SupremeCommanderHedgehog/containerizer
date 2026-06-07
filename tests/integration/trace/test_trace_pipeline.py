"""End-to-end trace pipeline test against the synthetic fixture.

Marked @pytest.mark.integration; skipped by default. Run via:
    pytest -m integration
Requires podman + Linux kernel with eBPF/BTF.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.integration
def test_trace_pipeline_against_synthetic_fixture(tmp_path: Path) -> None:
    fixture = REPO_ROOT / "tests/fixtures/trace/synthetic-installer.sh"
    assert fixture.exists(), f"missing fixture: {fixture}"

    out = tmp_path / "trace"
    out.mkdir()

    result = subprocess.run(
        ["containerizer", "trace", str(fixture), "-o", str(out)],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=1500,
    )
    assert result.returncode == 0, (result.stdout, result.stderr)

    assert (out / "COMPLETE").exists(), f"no COMPLETE marker; stderr was: {result.stderr}"
    assert (out / "install.log").stat().st_size > 0

    for collector in ("open", "bind", "connect", "accept", "syscalls", "capable"):
        path = out / f"{collector}.jsonl"
        assert path.exists(), f"missing {path}"
        assert path.stat().st_size > 0, f"empty {path}"

    opens = [
        json.loads(line) for line in (out / "open.jsonl").read_text().splitlines() if line.strip()
    ]
    assert any(rec.get("path") == "/etc/passwd" for rec in opens), (
        "expected /etc/passwd in open.jsonl"
    )
