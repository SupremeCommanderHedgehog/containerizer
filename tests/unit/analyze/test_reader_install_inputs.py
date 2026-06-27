"""Tests for analyze.reader.read_install_inputs."""

from __future__ import annotations

from pathlib import Path

from containerizer.analyze.reader import InstallInputs, read_install_inputs


def test_empty_trace_dir_returns_empty_install_inputs(tmp_path: Path) -> None:
    assert read_install_inputs(tmp_path) == InstallInputs()


def test_installers_file_read_as_basenames_in_order(tmp_path: Path) -> None:
    (tmp_path / "INSTALLERS").write_text(
        "unifi_sysvinit_all.deb\nmongodb-org-server_8.0.26_amd64.deb\n",
        encoding="utf-8",
    )
    out = read_install_inputs(tmp_path)
    assert out.installers == (
        "unifi_sysvinit_all.deb",
        "mongodb-org-server_8.0.26_amd64.deb",
    )


def test_apt_sources_file_read_verbatim(tmp_path: Path) -> None:
    (tmp_path / "apt-sources.list").write_text(
        "deb http://example/x noble main\ndeb http://example/y noble main\n",
        encoding="utf-8",
    )
    out = read_install_inputs(tmp_path)
    assert out.apt_sources == (
        "deb http://example/x noble main",
        "deb http://example/y noble main",
    )


def test_apt_keys_file_read_as_basenames(tmp_path: Path) -> None:
    (tmp_path / "APT_KEYS").write_text("mongodb.gpg\nexample.asc\n", encoding="utf-8")
    out = read_install_inputs(tmp_path)
    assert out.apt_keys == ("mongodb.gpg", "example.asc")


def test_blank_lines_are_skipped(tmp_path: Path) -> None:
    (tmp_path / "INSTALLERS").write_text("a.deb\n\nb.deb\n", encoding="utf-8")
    out = read_install_inputs(tmp_path)
    assert out.installers == ("a.deb", "b.deb")


def test_inputs_dataclass_is_immutable() -> None:
    import dataclasses

    inputs = InstallInputs(installers=("a.deb",))
    assert dataclasses.is_dataclass(inputs)
    # frozen=True means fields can't be reassigned.
    try:
        inputs.installers = ("b.deb",)  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        return
    raise AssertionError("InstallInputs should be frozen")
