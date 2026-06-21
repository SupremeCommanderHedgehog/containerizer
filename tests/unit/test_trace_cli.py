"""Tests for the `containerizer trace` Click subcommand."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from containerizer.cli import main
from containerizer.trace.cli import _podman_machine_is_running
from containerizer.trace.runner import OutputDirNotEmpty


def test_trace_help_lists_required_options() -> None:
    result = CliRunner().invoke(main, ["trace", "--help"])
    assert result.exit_code == 0
    assert "Statically analyse" not in result.output  # not the probe help
    assert "-o" in result.output or "--output-dir" in result.output
    assert "--force" in result.output


@patch("containerizer.trace.cli._podman_machine_is_running")
def test_trace_refuses_when_podman_machine_is_not_running(
    mock_machine: MagicMock, tmp_path: Path
) -> None:
    mock_machine.return_value = False
    installer = tmp_path / "fake-installer"
    installer.write_bytes(b"\x00")
    output = tmp_path / "out"

    result = CliRunner().invoke(main, ["trace", str(installer), "-o", str(output)])
    assert result.exit_code != 0
    assert "podman machine" in result.output.lower()
    assert "start" in result.output.lower()


def test_trace_propagates_stdin_isatty_to_runner(tmp_path: Path) -> None:
    """#95: trace/cli.py must propagate sys.stdin.isatty() to TraceRunner so
    runner.py sets CONTAINERIZER_INTERACTIVE=1 when the user is at a
    terminal. Without this the orchestrator inside the runner takes the
    non-interactive branch and bash auto-redirects the backgrounded
    installer's stdin to /dev/null, breaking Y/N prompts (e.g. example-app).
    build/cli.py already wires this; trace/cli.py was the asymmetric path.

    Mirrors the test pattern build's test_install_trace_fn_passes_tty_from_stdin_isatty
    uses: invoke the underlying callback directly so CliRunner's stdin
    replacement doesn't mask the patched sys.stdin.isatty.
    """
    from containerizer.trace import cli as trace_cli_module
    from containerizer.trace.cli import trace_cmd

    installer = tmp_path / "fake-installer"
    installer.write_bytes(b"\x00")
    output = tmp_path / "out"
    output.mkdir()
    (output / "COMPLETE").write_text("", encoding="utf-8")

    captured: dict[str, object] = {}

    class FakeRunner:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

        def validate_output_dir(self, *, force: bool) -> None:
            return None

        def run(self) -> int:
            return 0

    class FakeImage:
        tag = "runner:fake"

        def __init__(self, *, sandbox_dir: Path) -> None:
            pass

        def exists(self) -> bool:
            return True

    from contextlib import ExitStack

    def _invoke(isatty_value: bool) -> None:
        with ExitStack() as stack:
            stack.enter_context(patch.object(trace_cli_module, "TraceRunner", FakeRunner))
            stack.enter_context(patch.object(trace_cli_module, "RunnerImage", FakeImage))
            stack.enter_context(
                patch.object(trace_cli_module, "_podman_machine_is_running", return_value=True)
            )
            stack.enter_context(
                patch.object(trace_cli_module.sys.stdin, "isatty", return_value=isatty_value)
            )
            trace_cmd.callback(
                installer=installer,
                output_dir=output,
                force=False,
                extra_installers=(),
                apt_sources=(),
                apt_keys=(),
            )

    # Terminal case: tty=True must reach the runner.
    _invoke(True)
    assert captured.get("tty") is True, f"trace/cli.py did not pass tty=True; captured={captured}"

    # CI/piped case: tty=False must reach the runner.
    captured.clear()
    _invoke(False)
    assert captured.get("tty") is False, (
        f"trace/cli.py passed tty=True when stdin was not a TTY; captured={captured}"
    )


@patch("containerizer.trace.cli.TraceRunner")
@patch("containerizer.trace.cli.RunnerImage")
@patch("containerizer.trace.cli._podman_machine_is_running")
def test_trace_builds_image_when_missing(
    mock_machine: MagicMock,
    mock_image_cls: MagicMock,
    mock_runner_cls: MagicMock,
    tmp_path: Path,
) -> None:
    mock_machine.return_value = True
    image = MagicMock()
    image.exists.return_value = False
    image.tag = "localhost/containerizer-runner:sha-abcdef12"
    mock_image_cls.return_value = image

    runner = MagicMock()
    runner.run.return_value = 0
    mock_runner_cls.return_value = runner

    installer = tmp_path / "fake-installer"
    installer.write_bytes(b"\x00")
    output = tmp_path / "out"
    output.mkdir()
    (output / "COMPLETE").write_text("", encoding="utf-8")  # written by orchestrator

    result = CliRunner().invoke(main, ["trace", str(installer), "-o", str(output)])
    assert result.exit_code == 0
    image.build.assert_called_once()


@patch("containerizer.trace.cli.TraceRunner")
@patch("containerizer.trace.cli.RunnerImage")
@patch("containerizer.trace.cli._podman_machine_is_running")
def test_trace_skips_build_when_image_exists(
    mock_machine: MagicMock,
    mock_image_cls: MagicMock,
    mock_runner_cls: MagicMock,
    tmp_path: Path,
) -> None:
    mock_machine.return_value = True
    image = MagicMock()
    image.exists.return_value = True
    image.tag = "localhost/containerizer-runner:sha-abcdef12"
    mock_image_cls.return_value = image

    runner = MagicMock()
    runner.run.return_value = 0
    mock_runner_cls.return_value = runner

    installer = tmp_path / "fake-installer"
    installer.write_bytes(b"\x00")
    output = tmp_path / "out"
    output.mkdir()
    (output / "COMPLETE").write_text("", encoding="utf-8")

    result = CliRunner().invoke(main, ["trace", str(installer), "-o", str(output)])
    assert result.exit_code == 0
    image.build.assert_not_called()


@patch("containerizer.trace.cli.TraceRunner")
@patch("containerizer.trace.cli.RunnerImage")
@patch("containerizer.trace.cli._podman_machine_is_running")
def test_trace_reports_partial_marker(
    mock_machine: MagicMock,
    mock_image_cls: MagicMock,
    mock_runner_cls: MagicMock,
    tmp_path: Path,
) -> None:
    mock_machine.return_value = True
    image = MagicMock()
    image.exists.return_value = True
    image.tag = "localhost/containerizer-runner:sha-abcdef12"
    mock_image_cls.return_value = image

    runner = MagicMock()
    runner.run.return_value = 0
    mock_runner_cls.return_value = runner

    installer = tmp_path / "fake-installer"
    installer.write_bytes(b"\x00")
    output = tmp_path / "out"
    output.mkdir()
    (output / "PARTIAL").write_text("", encoding="utf-8")

    result = CliRunner().invoke(main, ["trace", str(installer), "-o", str(output)])
    assert result.exit_code == 0
    assert "PARTIAL" in result.output


@patch("containerizer.trace.cli.TraceRunner")
@patch("containerizer.trace.cli.RunnerImage")
@patch("containerizer.trace.cli._podman_machine_is_running")
def test_trace_refuses_when_output_dir_already_has_marker(
    mock_machine: MagicMock,
    mock_image_cls: MagicMock,
    mock_runner_cls: MagicMock,
    tmp_path: Path,
) -> None:
    mock_machine.return_value = True
    image = MagicMock()
    image.exists.return_value = True
    image.tag = "localhost/containerizer-runner:sha-abcdef12"
    mock_image_cls.return_value = image

    runner = MagicMock()
    runner.validate_output_dir.side_effect = OutputDirNotEmpty("already has COMPLETE")
    mock_runner_cls.return_value = runner

    installer = tmp_path / "fake-installer"
    installer.write_bytes(b"\x00")
    output = tmp_path / "out"
    output.mkdir()

    result = CliRunner().invoke(main, ["trace", str(installer), "-o", str(output)])
    assert result.exit_code != 0
    assert "already has COMPLETE" in result.output
    runner.run.assert_not_called()


@patch("containerizer.trace.cli.TraceRunner")
@patch("containerizer.trace.cli.RunnerImage")
@patch("containerizer.trace.cli._podman_machine_is_running")
def test_trace_errors_when_no_marker_is_written(
    mock_machine: MagicMock,
    mock_image_cls: MagicMock,
    mock_runner_cls: MagicMock,
    tmp_path: Path,
) -> None:
    mock_machine.return_value = True
    image = MagicMock()
    image.exists.return_value = True
    image.tag = "localhost/containerizer-runner:sha-abcdef12"
    mock_image_cls.return_value = image

    runner = MagicMock()
    runner.run.return_value = 0
    mock_runner_cls.return_value = runner

    installer = tmp_path / "fake-installer"
    installer.write_bytes(b"\x00")
    output = tmp_path / "out"
    output.mkdir()  # no COMPLETE/PARTIAL written

    result = CliRunner().invoke(main, ["trace", str(installer), "-o", str(output)])
    assert result.exit_code != 0
    assert "did not finalise" in result.output


@patch("containerizer.trace.cli.TraceRunner")
@patch("containerizer.trace.cli.RunnerImage")
@patch("containerizer.trace.cli._podman_machine_is_running")
def test_trace_warns_on_fallbacks_and_notes_nonzero_exit(
    mock_machine: MagicMock,
    mock_image_cls: MagicMock,
    mock_runner_cls: MagicMock,
    tmp_path: Path,
) -> None:
    """Under systemd-PID-1 (#90) the container exit code reflects shutdown
    signal noise, not orchestrator success. The CLI must trust the marker:
    PARTIAL/COMPLETE means the orchestrator finalised, so the CLI exits 0
    and surfaces the podman exit code as a diagnostic note rather than an
    error. Pre-#90 this path raised; the rename captures the new contract."""
    mock_machine.return_value = True
    image = MagicMock()
    image.exists.return_value = True
    image.tag = "localhost/containerizer-runner:sha-abcdef12"
    mock_image_cls.return_value = image

    runner = MagicMock()
    runner.run.return_value = 7  # nonzero podman exit
    mock_runner_cls.return_value = runner

    installer = tmp_path / "fake-installer"
    installer.write_bytes(b"\x00")
    output = tmp_path / "out"
    output.mkdir()
    (output / "PARTIAL").write_text("", encoding="utf-8")
    (output / "FALLBACKS.json").write_text('{"open": "strace"}', encoding="utf-8")
    # also create a populated jsonl to exercise the count branch
    (output / "open.jsonl").write_text("{}\n{}\n", encoding="utf-8")

    result = CliRunner().invoke(main, ["trace", str(installer), "-o", str(output)])
    assert result.exit_code == 0
    assert "fell back to strace" in result.output
    assert "podman exited with code 7" in result.output
    assert "treating marker as authoritative" in result.output


@patch("containerizer.trace.cli.subprocess.run")
@patch("containerizer.trace.cli.sys.platform", "win32")
def test_podman_machine_is_running_true_when_a_machine_reports_running(
    mock_run: MagicMock,
) -> None:
    mock_run.return_value = MagicMock(returncode=0, stdout='[{"Running": true}]')
    assert _podman_machine_is_running() is True


@patch("containerizer.trace.cli.subprocess.run")
@patch("containerizer.trace.cli.sys.platform", "win32")
def test_podman_machine_is_running_false_when_no_machine_is_running(
    mock_run: MagicMock,
) -> None:
    mock_run.return_value = MagicMock(returncode=0, stdout='[{"Running": false}]')
    assert _podman_machine_is_running() is False


@patch("containerizer.trace.cli.subprocess.run")
@patch("containerizer.trace.cli.sys.platform", "win32")
def test_podman_machine_is_running_false_when_podman_is_not_installed(
    mock_run: MagicMock,
) -> None:
    mock_run.side_effect = FileNotFoundError
    assert _podman_machine_is_running() is False


@patch("containerizer.trace.cli.subprocess.run")
@patch("containerizer.trace.cli.sys.platform", "win32")
def test_podman_machine_is_running_false_when_command_fails(
    mock_run: MagicMock,
) -> None:
    mock_run.return_value = MagicMock(returncode=1, stdout="")
    assert _podman_machine_is_running() is False


@patch("containerizer.trace.cli.subprocess.run")
@patch("containerizer.trace.cli.sys.platform", "win32")
def test_podman_machine_is_running_false_when_output_is_not_json(
    mock_run: MagicMock,
) -> None:
    mock_run.return_value = MagicMock(returncode=0, stdout="not-json")
    assert _podman_machine_is_running() is False


@patch("containerizer.trace.cli.subprocess.run")
@patch("containerizer.trace.cli.sys.platform", "linux")
def test_podman_machine_is_running_returns_true_on_linux_when_podman_present(
    mock_run: MagicMock,
) -> None:
    from containerizer.trace.cli import _podman_machine_is_running

    mock_run.return_value.returncode = 0
    assert _podman_machine_is_running() is True
    # Should call `podman --version`, not `podman machine ls`.
    args = mock_run.call_args.args[0]
    assert args == ["podman", "--version"]


@patch("containerizer.trace.cli.subprocess.run", side_effect=FileNotFoundError)
@patch("containerizer.trace.cli.sys.platform", "linux")
def test_podman_machine_is_running_returns_false_on_linux_when_podman_missing(
    mock_run: MagicMock,
) -> None:
    from containerizer.trace.cli import _podman_machine_is_running

    assert _podman_machine_is_running() is False


def test_trace_cli_accepts_installer_apt_source_apt_key(tmp_path: Path, monkeypatch) -> None:
    """Issue #102: parse + plumb the three new flags."""
    from click.testing import CliRunner

    from containerizer.trace import cli as trace_cli

    monkeypatch.setattr(trace_cli, "_podman_machine_is_running", lambda: True)

    primary = tmp_path / "primary.deb"
    primary.write_bytes(b"!<arch>\n")
    extra = tmp_path / "extra.deb"
    extra.write_bytes(b"!<arch>\n")
    key = tmp_path / "mongo.gpg"
    key.write_bytes(b"\x00")
    out = tmp_path / "out"

    captured: dict[str, object] = {}

    class FakeImage:
        tag = "fake-tag"

        def __init__(self, sandbox_dir):
            pass

        def exists(self):
            return True

    class FakeRunner:
        def __init__(self, **kw):
            captured.update(kw)
            self.output_dir = kw["output_dir"]

        def validate_output_dir(self, *, force):
            pass

        def run(self):
            return 0

    monkeypatch.setattr(trace_cli, "RunnerImage", FakeImage)
    monkeypatch.setattr(trace_cli, "TraceRunner", FakeRunner)
    monkeypatch.setattr(trace_cli, "_print_summary", lambda *a, **kw: None)

    result = CliRunner().invoke(
        trace_cli.trace_cmd,
        [
            str(primary),
            "-o",
            str(out),
            "--installer",
            str(extra),
            "--apt-source",
            "deb http://x noble main",
            "--apt-key",
            str(key),
        ],
    )
    assert result.exit_code == 0, result.output
    assert captured["extra_installers"] == (extra.resolve(),)
    assert captured["apt_sources"] == ("deb http://x noble main",)
    assert captured["apt_keys"] == (key.resolve(),)


def test_trace_cli_rejects_apt_source_not_starting_with_deb(tmp_path: Path, monkeypatch) -> None:
    from click.testing import CliRunner

    from containerizer.trace import cli as trace_cli

    monkeypatch.setattr(trace_cli, "_podman_machine_is_running", lambda: True)

    primary = tmp_path / "primary.deb"
    primary.write_bytes(b"!<arch>\n")
    out = tmp_path / "out"

    result = CliRunner().invoke(
        trace_cli.trace_cmd,
        [
            str(primary),
            "-o",
            str(out),
            "--apt-source",
            "apt-get install nginx",
        ],
    )
    assert result.exit_code != 0
    assert "must start with 'deb '" in result.output


def test_trace_cli_rejects_apt_key_with_wrong_extension(tmp_path: Path, monkeypatch) -> None:
    from click.testing import CliRunner

    from containerizer.trace import cli as trace_cli

    monkeypatch.setattr(trace_cli, "_podman_machine_is_running", lambda: True)

    primary = tmp_path / "primary.deb"
    primary.write_bytes(b"!<arch>\n")
    weird = tmp_path / "key.txt"
    weird.write_text("not a keyring")
    out = tmp_path / "out"

    result = CliRunner().invoke(
        trace_cli.trace_cmd,
        [
            str(primary),
            "-o",
            str(out),
            "--apt-key",
            str(weird),
        ],
    )
    assert result.exit_code != 0
    assert "must end in .gpg or .asc" in result.output


def test_trace_cli_caps_extra_installers_at_99(tmp_path: Path, monkeypatch) -> None:
    from click.testing import CliRunner

    from containerizer.trace import cli as trace_cli

    monkeypatch.setattr(trace_cli, "_podman_machine_is_running", lambda: True)

    primary = tmp_path / "primary.deb"
    primary.write_bytes(b"!<arch>\n")
    extras = []
    for i in range(100):
        p = tmp_path / f"e{i}.deb"
        p.write_bytes(b"!<arch>\n")
        extras.append(p)
    out = tmp_path / "out"

    args = [str(primary), "-o", str(out)]
    for e in extras:
        args.extend(["--installer", str(e)])

    result = CliRunner().invoke(trace_cli.trace_cmd, args)
    assert result.exit_code != 0
    assert "cap is 99" in result.output
