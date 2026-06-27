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
    # Default TraceRunner has tty=False -> CONTAINERIZER_INTERACTIVE=0,
    # which tells the orchestrator to skip the "press Enter" wait.
    assert "CONTAINERIZER_INTERACTIVE=0" in argv
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
    for both tty=True (interactive) and tty=False (CI/piped) cases.

    self.tty still affects argv via CONTAINERIZER_INTERACTIVE so the
    orchestrator inside the container can distinguish a real user TTY
    from a forced-by-systemd pty."""
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
        expected = f"CONTAINERIZER_INTERACTIVE={1 if tty_flag else 0}"
        assert expected in argv, f"expected {expected} when tty={tty_flag}; argv={argv}"


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


def test_verify_mode_rejects_extra_installers(tmp_path: Path) -> None:
    """Issue #102: extras only make sense in install mode."""
    image_tar = tmp_path / "image.tar"
    image_tar.write_bytes(b"\x00")
    seccomp = tmp_path / "seccomp.json"
    seccomp.write_text("{}")
    out = tmp_path / "out"
    out.mkdir()
    extra = tmp_path / "extra.deb"
    extra.write_bytes(b"!<arch>\n")

    with pytest.raises(ValueError, match="verify mode does not accept extra"):
        TraceRunner(
            image_tag="runner",
            installer=None,
            output_dir=out,
            mode="verify",
            verify_image_tar=image_tar,
            verify_image_tag="img:tag",
            verify_soak_seconds=10,
            verify_seccomp_path=seccomp,
            extra_installers=(extra,),
        )


def test_verify_mode_rejects_apt_sources(tmp_path: Path) -> None:
    image_tar = tmp_path / "image.tar"
    image_tar.write_bytes(b"\x00")
    seccomp = tmp_path / "seccomp.json"
    seccomp.write_text("{}")
    out = tmp_path / "out"
    out.mkdir()

    with pytest.raises(ValueError, match="verify mode does not accept extra"):
        TraceRunner(
            image_tag="runner",
            installer=None,
            output_dir=out,
            mode="verify",
            verify_image_tar=image_tar,
            verify_image_tag="img:tag",
            verify_soak_seconds=10,
            verify_seccomp_path=seccomp,
            apt_sources=("deb http://x noble main",),
        )


def test_install_argv_mounts_extras_zero_padded(tmp_path: Path) -> None:
    """Issue #102: extras land at /installer-NN.deb in user-supplied order."""
    installer = tmp_path / "primary.deb"
    installer.write_bytes(b"!<arch>\n")
    extra1 = tmp_path / "dep1.deb"
    extra1.write_bytes(b"!<arch>\n")
    extra2 = tmp_path / "dep2.deb"
    extra2.write_bytes(b"!<arch>\n")
    out = tmp_path / "out"
    out.mkdir()

    runner = TraceRunner(
        image_tag="runner",
        installer=installer,
        output_dir=out,
        mode="install",
        extra_installers=(extra1, extra2),
    )
    argv = runner.argv()

    assert f"{extra1.resolve()}:/installer-01.deb:ro" in argv
    assert f"{extra2.resolve()}:/installer-02.deb:ro" in argv
    # Primary stays where it was.
    assert f"{installer.resolve()}:/installer:ro" in argv


def test_install_argv_mounts_apt_keys_by_basename(tmp_path: Path) -> None:
    installer = tmp_path / "primary.deb"
    installer.write_bytes(b"!<arch>\n")
    key = tmp_path / "mongo.gpg"
    key.write_bytes(b"\x00")
    out = tmp_path / "out"
    out.mkdir()

    runner = TraceRunner(
        image_tag="runner",
        installer=installer,
        output_dir=out,
        mode="install",
        apt_keys=(key,),
    )
    argv = runner.argv()

    assert f"{key.resolve()}:/work/apt-keys/mongo.gpg:ro" in argv


def test_run_writes_apt_sources_list_to_output_dir(tmp_path: Path, monkeypatch) -> None:
    """Issue #102: apt_sources land in output_dir/apt-sources.list (file
    transport; env-var NUL truncation avoided)."""
    installer = tmp_path / "primary.deb"
    installer.write_bytes(b"!<arch>\n")
    out = tmp_path / "out"
    out.mkdir()

    runner = TraceRunner(
        image_tag="runner",
        installer=installer,
        output_dir=out,
        mode="install",
        apt_sources=("deb http://a noble main", "deb http://b noble main"),
    )

    # Don't actually exec podman; just trigger the materialize step.
    monkeypatch.setattr("subprocess.run", lambda *a, **kw: type("R", (), {"returncode": 0})())
    runner.run()

    sources_file = out / "apt-sources.list"
    assert sources_file.exists()
    text = sources_file.read_text(encoding="utf-8")
    assert text == "deb http://a noble main\ndeb http://b noble main\n"


def test_run_does_not_write_apt_sources_when_empty(tmp_path: Path, monkeypatch) -> None:
    """Single-installer flows produce no apt-sources.list."""
    installer = tmp_path / "primary.deb"
    installer.write_bytes(b"!<arch>\n")
    out = tmp_path / "out"
    out.mkdir()

    runner = TraceRunner(
        image_tag="runner",
        installer=installer,
        output_dir=out,
        mode="install",
    )

    monkeypatch.setattr("subprocess.run", lambda *a, **kw: type("R", (), {"returncode": 0})())
    runner.run()

    assert not (out / "apt-sources.list").exists()


def test_install_mode_accepts_start_cmd_and_ready_seconds(tmp_path: Path) -> None:
    installer = tmp_path / "install.sh"
    installer.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    output = tmp_path / "trace"
    output.mkdir()

    runner = TraceRunner(
        image_tag="runner:latest",
        installer=installer,
        output_dir=output,
        start_cmd="/etc/init.d/foo start",
        start_ready_seconds=90,
    )
    assert runner.start_cmd == "/etc/init.d/foo start"
    assert runner.start_ready_seconds == 90


def test_install_mode_defaults_start_cmd_to_none_and_ready_to_60(tmp_path: Path) -> None:
    installer = tmp_path / "install.sh"
    installer.write_text("", encoding="utf-8")
    output = tmp_path / "trace"
    output.mkdir()

    runner = TraceRunner(
        image_tag="runner:latest",
        installer=installer,
        output_dir=output,
    )
    assert runner.start_cmd is None
    assert runner.start_ready_seconds == 60


def test_verify_mode_rejects_start_cmd(tmp_path: Path) -> None:
    image_tar = tmp_path / "image.tar"
    image_tar.write_bytes(b"x")
    seccomp = tmp_path / "seccomp.json"
    seccomp.write_text("{}", encoding="utf-8")
    out = tmp_path / "verify-trace"

    with pytest.raises(ValueError, match="verify mode does not accept"):
        TraceRunner(
            image_tag="runner:latest",
            installer=None,
            output_dir=out,
            mode="verify",
            verify_image_tar=image_tar,
            verify_image_tag="generated:tag",
            verify_soak_seconds=30,
            verify_seccomp_path=seccomp,
            start_cmd="/etc/init.d/foo start",
        )


def test_install_argv_includes_start_cmd_env_when_set(tmp_path: Path) -> None:
    installer = tmp_path / "install.sh"
    installer.write_text("", encoding="utf-8")
    output = tmp_path / "trace"
    output.mkdir()

    runner = TraceRunner(
        image_tag="runner:latest",
        installer=installer,
        output_dir=output,
        start_cmd="/etc/init.d/foo start && sleep 1",
        start_ready_seconds=90,
    )
    argv = runner.argv()
    assert "CONTAINERIZER_START_CMD=/etc/init.d/foo start && sleep 1" in argv
    assert "CONTAINERIZER_START_READY_SECONDS=90" in argv


def test_install_argv_omits_start_cmd_env_when_unset(tmp_path: Path) -> None:
    installer = tmp_path / "install.sh"
    installer.write_text("", encoding="utf-8")
    output = tmp_path / "trace"
    output.mkdir()

    runner = TraceRunner(
        image_tag="runner:latest",
        installer=installer,
        output_dir=output,
    )
    argv = runner.argv()
    assert not any(a.startswith("CONTAINERIZER_START_CMD=") for a in argv)
    assert not any(a.startswith("CONTAINERIZER_START_READY_SECONDS=") for a in argv)


def test_install_argv_always_includes_verify_soak_env(tmp_path: Path) -> None:
    installer = tmp_path / "install.sh"
    installer.write_text("", encoding="utf-8")
    output = tmp_path / "trace"
    output.mkdir()

    runner = TraceRunner(
        image_tag="runner:latest",
        installer=installer,
        output_dir=output,
        verify_soak_seconds=45,
    )
    argv = runner.argv()
    assert "CONTAINERIZER_VERIFY_SOAK_SECONDS=45" in argv


def test_run_writes_start_cmd_to_output_dir(tmp_path, monkeypatch) -> None:
    """Issue #110: run() materializes START_CMD before exec when start_cmd set."""
    installer = tmp_path / "primary.deb"
    installer.write_bytes(b"!<arch>\n")
    out = tmp_path / "out"
    out.mkdir()

    runner = TraceRunner(
        image_tag="runner",
        installer=installer,
        output_dir=out,
        mode="install",
        start_cmd="/etc/init.d/unifi start",
    )

    monkeypatch.setattr("subprocess.run", lambda *a, **kw: type("R", (), {"returncode": 0})())
    rc = runner.run()

    assert rc == 0
    assert (out / "START_CMD").read_text(encoding="utf-8") == "/etc/init.d/unifi start"


def test_run_omits_start_cmd_when_unset(tmp_path, monkeypatch) -> None:
    """Issue #110: run() does not create START_CMD when start_cmd is None."""
    installer = tmp_path / "primary.deb"
    installer.write_bytes(b"!<arch>\n")
    out = tmp_path / "out"
    out.mkdir()

    runner = TraceRunner(
        image_tag="runner",
        installer=installer,
        output_dir=out,
        mode="install",
    )

    monkeypatch.setattr("subprocess.run", lambda *a, **kw: type("R", (), {"returncode": 0})())
    rc = runner.run()

    assert rc == 0
    assert not (out / "START_CMD").exists()
