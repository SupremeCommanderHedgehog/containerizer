"""Integration: end-to-end trace of a fixture .deb via the
`containerizer trace` CLI. Mirrors the subprocess + dump pattern of
test_trace_pipeline.py so failures land in /tmp/trace-debug-dump for
the workflow's failure-artifact step.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tests.fixtures.probe.deb_helpers import build_minimal_deb

pytestmark = pytest.mark.integration

_DUMP_DIR = Path("/tmp/trace-debug-dump")


def _dump_trace_dir(out: Path, *, reason: str) -> None:
    if _DUMP_DIR.exists():
        shutil.rmtree(_DUMP_DIR, ignore_errors=True)
    _DUMP_DIR.mkdir(parents=True, exist_ok=True)
    if out.exists():
        for child in out.iterdir():
            target = _DUMP_DIR / child.name
            try:
                shutil.copy2(child, target)
            except Exception as exc:  # pragma: no cover - best-effort
                print(f"[dump] copy {child} failed: {exc}", file=sys.stderr)
    print(f"\n=== trace dir dump (reason: {reason}) ===", file=sys.stderr)
    print(f"=== source: {out} ===", file=sys.stderr)
    print(f"=== saved to: {_DUMP_DIR} ===", file=sys.stderr)
    if out.exists():
        for child in sorted(out.iterdir()):
            size = child.stat().st_size if child.is_file() else 0
            print(f"  {child.name}  ({size} bytes)", file=sys.stderr)


@pytest.mark.integration
def test_trace_completes_for_minimal_deb(tmp_path: Path) -> None:
    deb = tmp_path / "hello_2.10-3_amd64.deb"
    build_minimal_deb(deb)

    out = tmp_path / "trace"
    out.mkdir()

    try:
        result = subprocess.run(
            ["containerizer", "trace", str(deb), "-o", str(out)],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=600,
        )
    except subprocess.TimeoutExpired as exc:
        _dump_trace_dir(out, reason=f"TimeoutExpired after {exc.timeout}s")
        raise

    if result.returncode != 0:
        _dump_trace_dir(out, reason=f"returncode={result.returncode}")
        raise AssertionError(
            f"containerizer trace exited {result.returncode}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )

    try:
        # Either COMPLETE (apt succeeded + non-interactive finalise) or
        # PARTIAL (network failure or collector attach failure). Either
        # proves the magic-bytes dispatch landed in run_deb_install.
        assert (out / "COMPLETE").exists() or (out / "PARTIAL").exists(), (
            f"no marker written; stderr was:\n{result.stderr}"
        )

        # install.log should mention apt activity, confirming
        # run_deb_install ran rather than run_elf_install.
        install_log = out / "install.log"
        if install_log.exists():
            log = install_log.read_text(errors="replace")
            assert "apt" in log.lower() or "dpkg" in log.lower(), (
                f"install.log doesn't look like an apt run:\n{log[:500]}"
            )
    except AssertionError:
        _dump_trace_dir(out, reason="assertion failure")
        raise


@pytest.mark.integration
def test_multi_deb_install_satisfies_dep(tmp_path: Path) -> None:
    """Issue #102: primary that Depends: dep_pkg gets resolved when --installer
    supplies dep_pkg.deb in the same transaction."""
    dep = tmp_path / "deppkg_1.0_amd64.deb"
    build_minimal_deb(
        dep,
        package="deppkg",
        version="1.0",
        depends="",
        systemd_unit=None,
    )
    primary = tmp_path / "primarypkg_1.0_amd64.deb"
    build_minimal_deb(
        primary,
        package="primarypkg",
        version="1.0",
        depends="deppkg",
        systemd_unit=None,
    )

    out = tmp_path / "trace"
    out.mkdir()

    try:
        result = subprocess.run(
            [
                "containerizer",
                "trace",
                str(primary),
                "--installer",
                str(dep),
                "-o",
                str(out),
            ],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=600,
        )
    except subprocess.TimeoutExpired as exc:
        _dump_trace_dir(out, reason=f"TimeoutExpired after {exc.timeout}s")
        raise

    if result.returncode != 0:
        _dump_trace_dir(out, reason=f"returncode={result.returncode}")
        raise AssertionError(
            f"containerizer trace exited {result.returncode}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )

    try:
        assert (out / "COMPLETE").exists(), f"no COMPLETE marker; stderr was:\n{result.stderr}"
        install_log = (out / "install.log").read_text(errors="replace")
        assert "primarypkg" in install_log, install_log[:500]
        assert "deppkg" in install_log, install_log[:500]
    except AssertionError:
        _dump_trace_dir(out, reason="multi-deb assertion failure")
        raise
