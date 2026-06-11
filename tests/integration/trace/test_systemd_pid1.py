"""End-to-end test that the runner image boots systemd as PID 1 (#90).

Marked @pytest.mark.integration; skipped by default. Run via:
    pytest tests/integration/trace/test_systemd_pid1.py -v -m integration
Requires podman + Linux kernel with eBPF/BTF.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.integration
def test_loginctl_installer_succeeds_under_systemd_pid1(tmp_path: Path) -> None:
    """If systemd is NOT PID 1, loginctl fails with 'System has not been
    booted with systemd as init system'. This test fails the same way the
    UniFi installer did pre-#90."""
    fixture = REPO_ROOT / "tests/fixtures/trace/loginctl-installer.sh"
    assert fixture.exists(), f"missing fixture: {fixture}"

    out = tmp_path / "trace"
    out.mkdir()

    result = subprocess.run(
        ["containerizer", "trace", str(fixture), "-o", str(out)],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=180,
    )

    # Container must exit cleanly (systemd OnSuccess=poweroff.target).
    assert result.returncode == 0, (
        f"containerizer trace exited {result.returncode}\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )

    # Orchestrator must finalise COMPLETE (installer exited 0).
    assert (out / "COMPLETE").exists(), f"no COMPLETE marker; stderr was:\n{result.stderr}"

    # Installer's own success line must appear in install.log (or stdout
    # if the interactive branch fired -- this test runs non-interactive
    # via stdin=DEVNULL, so install.log is the relevant artifact).
    install_log = out / "install.log"
    if install_log.exists():
        log_text = install_log.read_text(encoding="utf-8", errors="replace")
        assert "systemd-logind OK" in log_text, (
            f"loginctl reachability check did not pass; install.log:\n{log_text}"
        )
        assert "system bus OK" in log_text


@pytest.mark.integration
def test_runner_image_entrypoint_is_sbin_init(tmp_path: Path) -> None:
    """Belt-and-braces: inspect the built image and confirm ENTRYPOINT
    is /sbin/init. Cheap, catches Containerfile regressions."""
    # The image tag the containerizer trace path builds; mirror the same
    # naming convention image.py uses (sha-prefix based). We just need
    # *some* image with the same Containerfile; the trace command will
    # build it on first run, so trigger that first.
    result = subprocess.run(
        ["containerizer", "trace", "--help"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0

    images = subprocess.run(
        ["podman", "images", "--format", "{{.Repository}}:{{.Tag}}"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    runner_images = [line for line in images.stdout.splitlines() if "containerizer-runner" in line]
    if not runner_images:
        pytest.skip("no runner image built yet; this test runs after another integration test")

    inspect = subprocess.run(
        ["podman", "inspect", "--format", "{{json .Config.Entrypoint}}", runner_images[0]],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert inspect.returncode == 0
    assert "/sbin/init" in inspect.stdout, (
        f"image {runner_images[0]} entrypoint is {inspect.stdout!r}, expected /sbin/init"
    )
