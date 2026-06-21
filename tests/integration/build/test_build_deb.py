"""Integration: end-to-end `containerizer build foo.deb --name hello`.

Mirrors the subprocess pattern of test_build_smoke.py's CLI-shaped peer
(test_deb_pipeline.py for trace). Asserts the four generated artifacts
land under <out>/<name>/ and that the Containerfile picked the
ubuntu:24.04 base image surfaced by the .deb probe.
"""

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

    # resolve_layout puts final artifacts under <out>/<name>/.
    artifacts_dir = out_dir / "hello"
    containerfile = artifacts_dir / "Containerfile"
    quadlet = artifacts_dir / "hello.container"
    seccomp = artifacts_dir / "seccomp.json"
    readme = artifacts_dir / "README.md"

    assert containerfile.exists(), f"missing {containerfile}"
    assert quadlet.exists(), f"missing {quadlet}"
    assert seccomp.exists(), f"missing {seccomp}"
    assert readme.exists(), f"missing {readme}"
    assert "ubuntu:24.04" in containerfile.read_text(encoding="utf-8")
