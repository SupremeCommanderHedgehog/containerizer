"""Tests for the TraceRunner class."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from containerizer.trace.runner import OutputDirNotEmpty, TraceRunner


def test_argv_is_the_podman_run_command(tmp_path: Path) -> None:
    installer = tmp_path / "install.sh"
    installer.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    output = tmp_path / "trace"
    output.mkdir()

    runner = TraceRunner(
        image_tag="localhost/containerizer-runner:sha-abc12345",
        installer=installer,
        output_dir=output,
    )

    argv = runner.argv()
    assert argv[:2] == ["podman", "run"]
    assert "--rm" in argv
    assert "-i" in argv
    assert "-t" in argv
    assert "--privileged" in argv
    assert "--pid=host" not in argv
    assert "--systemd=always" in argv
    assert "-v" in argv
    assert "/sys/kernel/debug:/sys/kernel/debug" in argv
    assert "/sys/kernel/tracing:/sys/kernel/tracing" in argv
    assert "/sys/kernel/btf:/sys/kernel/btf" in argv
    assert "/lib/modules:/lib/modules:ro" in argv
    assert "/usr/src:/usr/src:ro" in argv
    assert f"{installer.resolve()}:/installer:ro" in argv
    assert f"{output.resolve()}:/work/trace" in argv
    # Mode + installer path now flow via env vars, not positional argv.
    assert "CONTAINERIZER_MODE=install" in argv
    assert "CONTAINERIZER_INSTALLER=/installer" in argv
    # The image tag is the last token; no trailing positional command.
    assert argv[-1] == "localhost/containerizer-runner:sha-abc12345"


def test_output_dir_with_complete_marker_is_rejected_without_force(tmp_path: Path) -> None:
    installer = tmp_path / "install.sh"
    installer.write_text("", encoding="utf-8")
    output = tmp_path / "trace"
    output.mkdir()
    (output / "COMPLETE").write_text("", encoding="utf-8")

    with pytest.raises(OutputDirNotEmpty):
        TraceRunner(
            image_tag="localhost/containerizer-runner:sha-abc12345",
            installer=installer,
            output_dir=output,
        ).validate_output_dir(force=False)


def test_output_dir_with_complete_marker_is_accepted_with_force(tmp_path: Path) -> None:
    installer = tmp_path / "install.sh"
    installer.write_text("", encoding="utf-8")
    output = tmp_path / "trace"
    output.mkdir()
    (output / "COMPLETE").write_text("", encoding="utf-8")

    TraceRunner(
        image_tag="localhost/containerizer-runner:sha-abc12345",
        installer=installer,
        output_dir=output,
    ).validate_output_dir(force=True)


def test_output_dir_with_partial_marker_is_also_blocked(tmp_path: Path) -> None:
    installer = tmp_path / "install.sh"
    installer.write_text("", encoding="utf-8")
    output = tmp_path / "trace"
    output.mkdir()
    (output / "PARTIAL").write_text("", encoding="utf-8")

    with pytest.raises(OutputDirNotEmpty):
        TraceRunner(
            image_tag="localhost/containerizer-runner:sha-abc12345",
            installer=installer,
            output_dir=output,
        ).validate_output_dir(force=False)


@patch("containerizer.trace.runner.subprocess.run")
def test_run_calls_subprocess_with_argv(mock_run: MagicMock, tmp_path: Path) -> None:
    mock_run.return_value.returncode = 0
    installer = tmp_path / "install.sh"
    installer.write_text("", encoding="utf-8")
    output = tmp_path / "trace"
    output.mkdir()

    runner = TraceRunner(
        image_tag="localhost/containerizer-runner:sha-abc12345",
        installer=installer,
        output_dir=output,
    )
    assert runner.run() == 0
    mock_run.assert_called_once_with(runner.argv(), check=False)


def test_verify_mode_argv_includes_image_tar_and_env_vars(tmp_path: Path) -> None:
    image_tar = tmp_path / "image.tar"
    image_tar.write_bytes(b"x")
    seccomp = tmp_path / "seccomp.json"
    seccomp.write_text("{}", encoding="utf-8")
    out = tmp_path / "verify-trace"

    runner = TraceRunner(
        image_tag="runner:latest",
        installer=None,
        output_dir=out,
        mode="verify",
        verify_image_tar=image_tar,
        verify_image_tag="demo:m6-verify",
        verify_run_flags=("--cap-drop=ALL", "--read-only"),
        verify_soak_seconds=15,
        verify_seccomp_path=seccomp,
    )
    argv = runner.argv()

    # Mode flows via env var, not argv positional.
    assert "--mode" not in argv
    assert "CONTAINERIZER_MODE=verify" in argv
    # Verify mode does NOT set CONTAINERIZER_INSTALLER.
    assert not any(a.startswith("CONTAINERIZER_INSTALLER=") for a in argv)

    assert f"{image_tar.resolve()}:/work/verify/image.tar:ro" in argv
    assert f"{seccomp.resolve()}:/work/verify/seccomp.json:ro" in argv
    assert any(a == "VERIFY_IMAGE_TAG=demo:m6-verify" for a in argv)
    assert any(a == "VERIFY_SOAK_SECONDS=15" for a in argv)
    # VERIFY_RUN_FLAGS is one env var carrying the whole arg list, space-joined.
    assert any(a.startswith("VERIFY_RUN_FLAGS=--cap-drop=ALL --read-only") for a in argv)
    # Verify mode is non-interactive in spirit (no user input), but the
    # systemd-PID-1 trace unit still needs a pty wired to /dev/console,
    # so -i -t are present in argv. The pty just sees EOF.
    assert "-i" in argv
    assert "-t" in argv
    # The original /installer mount is NOT present in verify mode.
    assert not any(":/installer:" in a for a in argv)
    # --pid=host is gone in #90; --systemd=always is present.
    assert "--pid=host" not in argv
    assert "--systemd=always" in argv
    # The image tag is the last token; no trailing positional command.
    assert argv[-1] == "runner:latest"


def test_install_mode_unchanged(tmp_path: Path) -> None:
    installer = tmp_path / "installer.sh"
    installer.write_text("echo hi", encoding="utf-8")
    out = tmp_path / "install-trace"

    runner = TraceRunner(
        image_tag="runner:latest",
        installer=installer,
        output_dir=out,
    )
    argv = runner.argv()
    # Default mode is "install"; argv shape stable across both M2 and #90.
    assert "-i" in argv
    assert any(":/installer:ro" in a for a in argv)
    # Mode flows via env var, not argv.
    assert "--mode" not in argv
    assert "CONTAINERIZER_MODE=install" in argv


def test_verify_mode_validates_required_fields(tmp_path: Path) -> None:
    out = tmp_path / "vt"
    with pytest.raises(ValueError, match="verify mode requires"):
        TraceRunner(
            image_tag="runner:latest",
            installer=None,
            output_dir=out,
            mode="verify",
            # missing verify_* fields
        )


def test_install_mode_validates_installer_present(tmp_path: Path) -> None:
    out = tmp_path / "it"
    with pytest.raises(ValueError, match="install mode requires installer"):
        TraceRunner(
            image_tag="runner:latest",
            installer=None,
            output_dir=out,
        )


def test_install_mode_always_allocates_tty(tmp_path: Path) -> None:
    """#90: systemd-PID-1 wires the trace unit's stdio to /dev/console,
    which only exists when podman allocates a pty. -t is unconditional
    for both tty=True (interactive) and tty=False (CI/piped) cases."""
    installer = tmp_path / "installer.sh"
    installer.write_text("echo hi", encoding="utf-8")
    out = tmp_path / "trace"

    for tty_flag in (True, False):
        runner = TraceRunner(
            image_tag="runner:latest",
            installer=installer,
            output_dir=out,
            tty=tty_flag,
        )
        argv = runner.argv()
        assert "-i" in argv
        assert "-t" in argv, f"-t missing when tty={tty_flag}"
        # The standard idiom is "-i" then "-t" so podman parses it as `-it`.
        i_idx = argv.index("-i")
        t_idx = argv.index("-t")
        assert abs(i_idx - t_idx) == 1


def test_verify_mode_also_allocates_tty(tmp_path: Path) -> None:
    """#90: verify mode also runs under systemd-PID-1, so it also needs
    a pty for the trace unit's /dev/console wiring. The tty kwarg is
    a no-op (verify is non-interactive) but -i -t are still required."""
    image_tar = tmp_path / "image.tar"
    image_tar.write_bytes(b"x")
    seccomp = tmp_path / "seccomp.json"
    seccomp.write_text("{}", encoding="utf-8")
    out = tmp_path / "verify-trace"

    runner = TraceRunner(
        image_tag="runner:latest",
        installer=None,
        output_dir=out,
        mode="verify",
        verify_image_tar=image_tar,
        verify_image_tag="demo:m6-verify",
        verify_soak_seconds=15,
        verify_seccomp_path=seccomp,
        tty=True,
    )
    argv = runner.argv()
    assert "-i" in argv
    assert "-t" in argv
