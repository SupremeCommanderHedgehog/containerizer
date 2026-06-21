"""Integration: end-to-end `containerizer build foo.deb --name hello`.
Mirrors the subprocess pattern of test_build_smoke.py."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tests.fixtures.probe.deb_helpers import build_minimal_deb

pytestmark = pytest.mark.integration

_DUMP_DIR = Path("/tmp/trace-debug-dump")


def _dump_out_dir(out_dir: Path, *, reason: str) -> None:
    if _DUMP_DIR.exists():
        shutil.rmtree(_DUMP_DIR, ignore_errors=True)
    _DUMP_DIR.mkdir(parents=True, exist_ok=True)
    if out_dir.exists():
        for child in out_dir.rglob("*"):
            if child.is_file():
                rel = child.relative_to(out_dir)
                target = _DUMP_DIR / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                try:
                    shutil.copy2(child, target)
                except Exception as exc:  # pragma: no cover - best-effort
                    print(f"[dump] copy {child} failed: {exc}", file=sys.stderr)
    print(f"\n=== build out dir dump (reason: {reason}) ===", file=sys.stderr)
    print(f"=== source: {out_dir} ===", file=sys.stderr)
    print(f"=== saved to: {_DUMP_DIR} ===", file=sys.stderr)


@pytest.mark.integration
def test_build_produces_artifacts_for_minimal_deb(tmp_path: Path) -> None:
    deb = tmp_path / "hello_2.10-3_amd64.deb"
    build_minimal_deb(deb)
    out_dir = tmp_path / "out"

    try:
        result = subprocess.run(
            ["containerizer", "build", str(deb), "--name", "hello", "-o", str(out_dir)],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=900,
        )
    except subprocess.TimeoutExpired as exc:
        _dump_out_dir(out_dir, reason=f"TimeoutExpired after {exc.timeout}s")
        raise

    if result.returncode != 0:
        _dump_out_dir(out_dir, reason=f"returncode={result.returncode}")
        raise AssertionError(
            f"containerizer build exited {result.returncode}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )

    try:
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
    except AssertionError:
        _dump_out_dir(out_dir, reason="assertion failure")
        raise
