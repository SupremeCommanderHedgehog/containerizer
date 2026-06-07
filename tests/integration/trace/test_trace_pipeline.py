"""End-to-end trace pipeline test against the synthetic fixture.

Marked @pytest.mark.integration; skipped by default. Run via:
    pytest -m integration
Requires podman + Linux kernel with eBPF/BTF.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]

_DUMP_DIR = Path("/tmp/trace-debug-dump")


def _dump_trace_dir(out: Path, *, reason: str) -> None:
    """Copy trace dir to a stable location and print summaries to stdout.

    pytest's tmp_path cleanup races the post-test workflow step, so we
    write artifacts somewhere it can't reach and also stream key files
    to stdout so they land in the CI log directly.
    """
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
def test_trace_pipeline_against_synthetic_fixture(tmp_path: Path) -> None:
    fixture = REPO_ROOT / "tests/fixtures/trace/synthetic-installer.sh"
    assert fixture.exists(), f"missing fixture: {fixture}"

    out = tmp_path / "trace"
    out.mkdir()

    try:
        result = subprocess.run(
            ["containerizer", "trace", str(fixture), "-o", str(out)],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=180,
        )
    except subprocess.TimeoutExpired as exc:
        _dump_trace_dir(out, reason=f"TimeoutExpired after {exc.timeout}s")
        raise
    if result.returncode != 0:
        _dump_trace_dir(out, reason=f"returncode={result.returncode}")
        assert result.returncode == 0, (result.stdout, result.stderr)

    try:
        assert (out / "COMPLETE").exists(), f"no COMPLETE marker; stderr was: {result.stderr}"
        assert (out / "install.log").stat().st_size > 0

        # FALLBACKS.json lists collectors that failed to attach. Tracked by
        # issue #75 follow-up: bcc tcpconnect/tcpaccept hit a kernel-header
        # mismatch (struct bpf_wq, BPF_LOAD_ACQ) on the GHA Ubuntu runner.
        fallbacks_path = out / "FALLBACKS.json"
        fallbacks = (
            json.loads(fallbacks_path.read_text())
            if fallbacks_path.exists() and fallbacks_path.stat().st_size > 0
            else {}
        )

        for collector in ("open", "bind", "connect", "accept", "syscalls", "capable"):
            path = out / f"{collector}.jsonl"
            assert path.exists(), f"missing {path}"
            if collector in fallbacks:
                continue
            assert path.stat().st_size > 0, f"empty {path}"

        # bpftrace auto-dumps any non-cleared map contents at script exit
        # (e.g. "@args[3429]: 140732759619824"), so filter to lines that
        # actually look like our JSON records.
        opens = [
            json.loads(line)
            for line in (out / "open.jsonl").read_text().splitlines()
            if line.startswith("{")
        ]
        assert any(rec.get("path") == "/etc/passwd" for rec in opens), (
            "expected /etc/passwd in open.jsonl"
        )
    except BaseException:
        _dump_trace_dir(out, reason="post-trace assertion failed")
        raise
