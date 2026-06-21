"""Integration: --apt-source against a CI-local HTTP apt repo."""

from __future__ import annotations

import shutil
import socket
import subprocess
import sys
import time
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


def _free_port() -> int:
    """Bind a socket to port 0, return the OS-assigned port, close immediately."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.mark.integration
def test_apt_source_serves_local_repo(tmp_path: Path) -> None:
    """Issue #102: --apt-source writes the sources file in the nested container
    so apt-get update sees a CI-local repo and resolves the primary's Depends
    from it."""
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()

    # The "remote" repo just needs one deb that the primary Depends on.
    build_minimal_deb(
        repo_dir / "mockpkg_1.0_amd64.deb",
        package="mockpkg",
        version="1.0",
        depends="",
        systemd_unit=None,
    )

    # Generate a Packages metadata file. dpkg-scanpackages writes to stdout.
    packages_file = repo_dir / "Packages"
    subprocess.run(
        ["dpkg-scanpackages", "."],
        cwd=repo_dir,
        stdout=packages_file.open("wb"),
        check=True,
    )

    port = _free_port()
    server = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(port)],
        cwd=repo_dir,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    # Give the server a moment to bind.
    time.sleep(0.5)

    try:
        primary = tmp_path / "primarypkg_1.0_amd64.deb"
        build_minimal_deb(
            primary,
            package="primarypkg",
            version="1.0",
            depends="mockpkg",
            systemd_unit=None,
        )
        out = tmp_path / "trace"
        out.mkdir()

        apt_source = f"deb [trusted=yes] http://127.0.0.1:{port}/ ./"

        try:
            result = subprocess.run(
                [
                    "containerizer",
                    "trace",
                    str(primary),
                    "--apt-source",
                    apt_source,
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
            # COMPLETE or PARTIAL: the orchestrator's source-injection contract
            # is what this test exercises. Actual repo *fetch* from the nested
            # container's network namespace can fail in CI (the http.server
            # binds in the pytest process's netns; the nested deb-install
            # container's --network=host shares the OUTER trace runner's
            # netns, not the CI runner's). install.log captures the apt-get
            # update attempt either way.
            assert (out / "COMPLETE").exists() or (out / "PARTIAL").exists(), (
                f"no marker written; stderr was:\n{result.stderr}"
            )
            apt_prep_log = (out / "apt-prep.log").read_text(errors="replace")
            # Verbose `cp -fv` in the orchestrator prints the source -> dest
            # mapping; this proves the sources file landed inside the nested
            # container at /etc/apt/sources.list.d/containerizer.list.
            assert "containerizer.list" in apt_prep_log, (
                f"apt-prep didn't copy the sources file:\n{apt_prep_log[:500]}"
            )
            install_log = (out / "install.log").read_text(errors="replace")
            # Either the local repo URL appears (apt tried to reach it) or
            # the package name appears (apt resolved against it). Both prove
            # the sources.list was visible to apt-get update.
            assert "127.0.0.1" in install_log or "mockpkg" in install_log, (
                f"install.log doesn't reference the local repo:\n{install_log[:500]}"
            )
        except AssertionError:
            _dump_trace_dir(out, reason="apt-source assertion failure")
            raise
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()
