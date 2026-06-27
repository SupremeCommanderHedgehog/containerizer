"""Integration: end-to-end trace of a fixture .deb via the
`containerizer trace` CLI. Mirrors the subprocess + dump pattern of
test_trace_pipeline.py so failures land in /tmp/trace-debug-dump for
the workflow's failure-artifact step.
"""

from __future__ import annotations

import json
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


@pytest.mark.integration
def test_deb_with_start_cmd_produces_non_sentinel_policy(tmp_path: Path) -> None:
    """Issue #105: --start-cmd fires a daemon, ready-poll observes LISTEN, soak
    captures runtime activity, analyzer derives a non-sentinel policy.

    Issue #110: entrypoint inference assertion added — when start_cmd is provided
    and systemd is not required, derive must emit ['bash', '-c', start_cmd] as
    the image entrypoint.
    """
    deb = tmp_path / "foo_1.0_amd64.deb"
    build_minimal_deb(
        deb,
        package="foo",
        version="1.0",
        depends="netcat-openbsd",
        systemd_unit=None,
        init_script_body=(
            "#!/bin/sh\n"
            'case "$1" in\n'
            "  start) (nc -l -p 9999 &) ; sleep 0.5 ;;\n"
            "  *) echo unsupported ;;\n"
            "esac\n"
        ),
    )

    out = tmp_path / "trace"
    out.mkdir()

    # Issue #110: derive lifts start_cmd into the image entrypoint when
    # systemd is not required. Use a named local so the assertion below can
    # reference the same string without duplicating the literal.
    start_cmd_string = "/etc/init.d/foo start"

    try:
        result = subprocess.run(
            [
                "containerizer",
                "trace",
                str(deb),
                "-o",
                str(out),
                "--start-cmd",
                start_cmd_string,
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

        # Issue #110: derive now lifts start_cmd into the image entrypoint when
        # systemd is not required. Run analyze on the trace dir and assert the
        # exact bash -c shape rather than "anything non-sentinel".
        analyze_out = tmp_path / "analyze"
        analyze_out.mkdir()
        analyze_result = subprocess.run(
            ["containerizer", "analyze", str(out), "-o", str(analyze_out)],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert analyze_result.returncode == 0, (
            f"containerizer analyze exited {analyze_result.returncode}\n"
            f"stdout:\n{analyze_result.stdout}\nstderr:\n{analyze_result.stderr}"
        )
        policy_path = analyze_out / "policy.json"
        assert policy_path.exists(), (
            f"containerizer analyze did not write policy.json. "
            f"analyze stdout:\n{analyze_result.stdout}\nstderr:\n{analyze_result.stderr}"
        )
        policy_data = json.loads(policy_path.read_text(encoding="utf-8"))
        entrypoint = policy_data.get("image", {}).get("entrypoint")
        assert entrypoint == ["bash", "-c", start_cmd_string], (
            f"expected entrypoint [\"bash\", \"-c\", {start_cmd_string!r}], "
            f"got {entrypoint!r}\n"
            f"full policy.json:\n{json.dumps(policy_data, indent=2)}"
        )
    except AssertionError:
        _dump_trace_dir(out, reason="start-cmd integration assertion failure")
        raise
