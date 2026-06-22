"""Issue #105: ELF installer + --start-cmd symmetric wiring."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

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


@pytest.mark.integration
def test_elf_with_start_cmd_produces_runtime_observation(tmp_path: Path) -> None:
    """ELF installer is a no-op shell script that exits immediately; --start-cmd
    launches a nc listener; ready-poll observes LISTEN; soak captures activity."""
    installer = tmp_path / "install.sh"
    installer.write_text("#!/bin/sh\necho 'installed nothing'\nexit 0\n", encoding="utf-8")
    installer.chmod(0o755)

    out = tmp_path / "trace"
    out.mkdir()

    try:
        result = subprocess.run(
            [
                "containerizer",
                "trace",
                str(installer),
                "-o",
                str(out),
                "--start-cmd",
                "nc -l -p 9999 &",
                "--start-ready-seconds",
                "30",
                "--verify-soak-seconds",
                "5",
            ],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=900,
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
        assert (out / "COMPLETE").exists(), f"no COMPLETE marker; stderr:\n{result.stderr}"
        assert (out / "start.log").exists()
        assert (out / "start.exitcode").exists()
        assert (out / "start.exitcode").read_text().strip() == "0"
        bind = (out / "bind.jsonl").read_text(errors="replace")
        assert "9999" in bind, f"port 9999 not seen in bind.jsonl; head:\n{bind[:500]}"
    except AssertionError:
        _dump_trace_dir(out, reason="elf start-cmd assertion failure")
        raise
