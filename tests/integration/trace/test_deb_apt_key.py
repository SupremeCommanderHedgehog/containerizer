"""Integration: --apt-key copies keyring into /etc/apt/keyrings inside the
nested container."""

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
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.mark.integration
def test_apt_key_copies_keyring_into_etc_apt_keyrings(tmp_path: Path) -> None:
    """Issue #102: --apt-key file lands at /etc/apt/keyrings/<basename> inside
    the nested install container. Asserts wiring only; does not verify a real
    signed repo (that's MANUAL scenario 13)."""
    # Throwaway "keyring": any byte sequence. apt-prep just copies the file;
    # signature verification happens at apt-get-update time and we use
    # [trusted=yes] in apt-source to bypass it.
    key = tmp_path / "mockrepo.gpg"
    key.write_bytes(b"not a real keyring; apt won't verify with [trusted=yes]")

    # Tiny local repo for apt-get update to talk to.
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    build_minimal_deb(
        repo_dir / "mockpkg_1.0_amd64.deb",
        package="mockpkg",
        version="1.0",
        depends="",
        systemd_unit=None,
    )
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
    time.sleep(0.5)

    try:
        primary = tmp_path / "primarypkg_1.0_amd64.deb"
        build_minimal_deb(
            primary,
            package="primarypkg",
            version="1.0",
            depends="",
            systemd_unit=None,
        )
        out = tmp_path / "trace"
        out.mkdir()

        # [trusted=yes] keeps the test focused on the wiring (file mount + copy)
        # rather than GPG verification.
        apt_source = f"deb [trusted=yes] http://127.0.0.1:{port}/ ./"

        try:
            result = subprocess.run(
                [
                    "containerizer",
                    "trace",
                    str(primary),
                    "--apt-source",
                    apt_source,
                    "--apt-key",
                    str(key),
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
            assert (out / "COMPLETE").exists() or (out / "PARTIAL").exists(), (
                f"no marker written; stderr was:\n{result.stderr}"
            )
            apt_prep_log = (out / "apt-prep.log").read_text(errors="replace")
            # The apt-prep block runs `cp -f /work/apt-keys/* /etc/apt/keyrings/`.
            # Look for evidence: either the keyring filename or the keyrings dir.
            assert "mockrepo.gpg" in apt_prep_log or "keyrings" in apt_prep_log, (
                f"apt-prep didn't seem to handle the keyring:\n{apt_prep_log[:500]}"
            )
        except AssertionError:
            _dump_trace_dir(out, reason="apt-key assertion failure")
            raise
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()
