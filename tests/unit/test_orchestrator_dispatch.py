"""Unit tests for the trace-orchestrator.sh installer-kind dispatch."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ORCH = Path("sandbox/runner_image/trace-orchestrator.sh")


def _source_detect_kind(installer: Path) -> str:
    """Source the orchestrator's _detect_kind helper in a subshell and
    return its stdout for the given installer path.

    Extracts the function body with sed (start of `_detect_kind() ` through
    the next bare `}` line) and runs it in isolation without the rest of
    the orchestrator (which would require bpftrace + bcc + a real podman).
    """
    # Use POSIX-style paths so the f-string interpolation does not embed
    # Windows backslashes (which bash would interpret as escapes) when the
    # tests run under git-bash on Windows. The relative form is preserved.
    script = f"""
set -e
source <(sed -n '/^_detect_kind() /,/^}}$/p' {ORCH.as_posix()})
_detect_kind {Path(installer).as_posix()}
"""
    result = subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash required")
def test_detect_kind_recognises_elf(tmp_path: Path) -> None:
    elf = tmp_path / "x"
    elf.write_bytes(b"\x7fELF" + b"\x00" * 32)
    assert _source_detect_kind(elf) == "elf"


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash required")
def test_detect_kind_recognises_deb(tmp_path: Path) -> None:
    deb = tmp_path / "x.deb"
    deb.write_bytes(b"!<arch>\n" + b"\x00" * 32)
    assert _source_detect_kind(deb) == "deb"


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash required")
def test_detect_kind_unknown(tmp_path: Path) -> None:
    other = tmp_path / "x"
    other.write_bytes(b"\x00" * 32)
    assert _source_detect_kind(other) == "unknown"


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash required")
def test_run_deb_install_invokes_expected_podman_argv(tmp_path: Path) -> None:
    """Source run_deb_install with a podman stub on PATH and verify the
    recorded argv contains pull, run -d, exec, stop."""

    deb = tmp_path / "x.deb"
    deb.write_bytes(b"!<arch>\n" + b"\x00" * 32)
    log = tmp_path / "podman-stub.log"
    trace_dir = tmp_path / "trace"
    trace_dir.mkdir()

    stub_dir = tmp_path / "stub"
    stub_dir.mkdir()
    shutil.copy("tests/fixtures/trace/podman-stub.sh", stub_dir / "podman")
    (stub_dir / "podman").chmod(0o755)

    env = {
        **os.environ,
        "PATH": f"{stub_dir.as_posix()}:{os.environ['PATH']}",
        "PODMAN_STUB_LOG": str(log),
        "INSTALLER": str(deb),
        "TRACE_DIR": str(trace_dir),
    }

    script = f"""
set -e
# Define a no-op finalize_marker so run_deb_install can call it
# without depending on the rest of the orchestrator.
finalize_marker() {{ : ; }}
# Source only run_deb_install from the orchestrator script.
source <(awk '/^run_deb_install\\(\\) /,/^}}$/' {ORCH.as_posix()})
run_deb_install
"""
    subprocess.run(
        ["bash", "-c", script],
        env=env,
        check=True,
    )

    recorded = log.read_text().splitlines()
    joined = "\n".join(recorded)
    assert "pull docker.io/library/ubuntu:24.04" in joined
    assert "run -d --rm --name deb-install" in joined
    assert "--privileged" in joined
    assert "sleep infinity" in joined
    assert "exec deb-install" in joined
    assert "stop -t 10 deb-install" in joined
    # Diagnostic dump (#99) should fire unconditionally, recording at least
    # the `ps -a` probe in the stub log.
    assert "ps -a" in joined
    # Issue #102: install command always includes the zero-padded glob even
    # when no extras were mounted (shopt -s nullglob inside the inner bash -c
    # collapses it to empty).
    assert "/installer-??.deb" in joined


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash required")
def test_run_deb_install_apt_prep_copies_keys_and_writes_sources(
    tmp_path: Path,
) -> None:
    """Issue #102: with CONTAINERIZER_APT_SOURCES set and /work/apt-keys/*
    mounted, the prep step copies keys into /etc/apt/keyrings/ and writes
    the sources file. The install command uses the zero-padded glob to pick
    up the extras."""

    deb = tmp_path / "x.deb"
    deb.write_bytes(b"!<arch>\n" + b"\x00" * 32)
    log = tmp_path / "podman-stub.log"
    trace_dir = tmp_path / "trace"
    trace_dir.mkdir()

    # Fake key fixture mounted at /work/apt-keys/test.gpg (host-side path is
    # a tmp_path file; we tell the orchestrator about it via a fake glob
    # base dir overridden through PATH or by symlinking under tmp_path).
    # The orchestrator's loop uses literal `/work/apt-keys/*` so we create
    # that path on the test host (only safe under Linux/bash; on Windows
    # git-bash maps it to a relative path under the bash root, which is
    # acceptable because nullglob still collapses to empty if not present).
    # For the test, we instead point the orchestrator at a stubbed dir by
    # making the function source operate against tmp_path. The simplest
    # cross-platform approach: stage extras + keys in a tmp dir and have
    # the script use bind variables. Since the orchestrator hardcodes
    # /work/apt-keys, we assert against the inner-`bash -c` substring,
    # which the podman stub records verbatim.
    stub_dir = tmp_path / "stub"
    stub_dir.mkdir()
    shutil.copy("tests/fixtures/trace/podman-stub.sh", stub_dir / "podman")
    (stub_dir / "podman").chmod(0o755)

    env = {
        **os.environ,
        "PATH": f"{stub_dir.as_posix()}:{os.environ['PATH']}",
        "PODMAN_STUB_LOG": str(log),
        "INSTALLER": str(deb),
        "TRACE_DIR": str(trace_dir),
    }

    # Set CONTAINERIZER_APT_SOURCES from within bash to avoid Windows
    # subprocess rejecting embedded NUL chars in env. The $'\x00' is a
    # bash ANSI-C-quoted NUL byte.
    src_a = "deb https://example.com/repo stable main"
    src_b = "deb-src https://example.com/repo stable main"
    sources_literal = f"$'{src_a}\\x00{src_b}'"
    script = f"""
set -e
export CONTAINERIZER_APT_SOURCES={sources_literal}
finalize_marker() {{ : ; }}
source <(awk '/^run_deb_install\\(\\) /,/^}}$/' {ORCH.as_posix()})
run_deb_install
"""
    subprocess.run(
        ["bash", "-c", script],
        env=env,
        check=True,
    )

    recorded = log.read_text().splitlines()
    joined = "\n".join(recorded)
    # Already-covered shape:
    assert "exec deb-install" in joined
    # Issue #102 additions: the apt-prep `bash -c` body is recorded by the
    # stub verbatim, so we can search the inline script text.
    assert "/etc/apt/keyrings/" in joined  # keyring copy target
    assert "containerizer.list" in joined  # sources file write
    assert "/work/apt-keys" in joined  # source dir mention
    assert "/installer-??.deb" in joined  # zero-padded glob in install cmd
    # File-based apt-sources transport (was env var, NUL-truncated):
    assert "apt-sources.list" in joined
