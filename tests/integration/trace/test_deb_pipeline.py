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
