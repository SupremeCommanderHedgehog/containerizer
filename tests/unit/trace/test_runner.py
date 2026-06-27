"""Tests for trace.runner sidecar-file materialization."""

from __future__ import annotations

from pathlib import Path

from containerizer.trace.runner import TraceRunner


def _install_runner(output_dir: Path, installer: Path, **overrides: object) -> TraceRunner:
    return TraceRunner(
        image_tag="dummy:latest",
        installer=installer,
        output_dir=output_dir,
        **overrides,  # type: ignore[arg-type]
    )


def test_runner_writes_start_cmd_file_when_set(tmp_path: Path) -> None:
    installer = tmp_path / "i.bin"
    installer.write_text("x", encoding="utf-8")
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    runner = _install_runner(output_dir, installer, start_cmd="/etc/init.d/unifi start")

    runner._materialize_start_cmd_file()

    sidecar = output_dir / "START_CMD"
    assert sidecar.exists()
    assert sidecar.read_text(encoding="utf-8") == "/etc/init.d/unifi start"


def test_runner_omits_start_cmd_file_when_unset(tmp_path: Path) -> None:
    installer = tmp_path / "i.bin"
    installer.write_text("x", encoding="utf-8")
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    runner = _install_runner(output_dir, installer)  # start_cmd default = None

    runner._materialize_start_cmd_file()

    assert list(output_dir.iterdir()) == []


def test_run_materializes_installers_file(tmp_path: Path, monkeypatch) -> None:
    """INSTALLERS lists primary basename first, then extras."""
    primary = tmp_path / "primary.deb"
    primary.write_text("x", encoding="utf-8")
    extra = tmp_path / "extra.deb"
    extra.write_text("x", encoding="utf-8")
    out = tmp_path / "trace"
    out.mkdir()

    runner = TraceRunner(
        image_tag="test:tag",
        installer=primary,
        output_dir=out,
        extra_installers=(extra,),
    )

    def _no_op(argv, check=False):
        class _R:
            returncode = 0

        return _R()

    monkeypatch.setattr("containerizer.trace.runner.subprocess.run", _no_op)
    runner.run()

    text = (out / "INSTALLERS").read_text(encoding="utf-8")
    assert text == "primary.deb\nextra.deb\n"


def test_run_materializes_apt_keys_file(tmp_path: Path, monkeypatch) -> None:
    primary = tmp_path / "primary.deb"
    primary.write_text("x", encoding="utf-8")
    key = tmp_path / "mongodb.gpg"
    key.write_text("x", encoding="utf-8")
    out = tmp_path / "trace"
    out.mkdir()

    runner = TraceRunner(
        image_tag="test:tag",
        installer=primary,
        output_dir=out,
        apt_keys=(key,),
    )

    def _no_op(argv, check=False):
        class _R:
            returncode = 0

        return _R()

    monkeypatch.setattr("containerizer.trace.runner.subprocess.run", _no_op)
    runner.run()

    assert (out / "APT_KEYS").read_text(encoding="utf-8") == "mongodb.gpg\n"


def test_run_does_not_write_apt_keys_file_when_none(tmp_path: Path, monkeypatch) -> None:
    primary = tmp_path / "primary.deb"
    primary.write_text("x", encoding="utf-8")
    out = tmp_path / "trace"
    out.mkdir()

    runner = TraceRunner(
        image_tag="test:tag",
        installer=primary,
        output_dir=out,
    )

    def _no_op(argv, check=False):
        class _R:
            returncode = 0

        return _R()

    monkeypatch.setattr("containerizer.trace.runner.subprocess.run", _no_op)
    runner.run()

    assert not (out / "APT_KEYS").exists()
    # INSTALLERS still written (primary only).
    assert (out / "INSTALLERS").read_text(encoding="utf-8") == "primary.deb\n"
