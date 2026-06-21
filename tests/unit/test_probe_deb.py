"""Tests for the Debian .deb probe."""

from pathlib import Path

import pytest

from containerizer.probe.deb import (
    _discover_systemd_units,
    _extract_control,
    _iter_ar_members,
    _parse_control,
    probe_deb,
)
from tests.fixtures.probe.deb_helpers import build_minimal_deb


@pytest.fixture
def hello_deb(tmp_path: Path) -> Path:
    deb = tmp_path / "hello_2.10-3_amd64.deb"
    build_minimal_deb(deb)
    return deb


def test_iter_ar_members_yields_three_expected_files(hello_deb: Path) -> None:
    with hello_deb.open("rb") as fh:
        names = [m.name for m in _iter_ar_members(fh)]

    assert names == ["debian-binary", "control.tar.gz", "data.tar.gz"]


def test_iter_ar_members_rejects_missing_magic(tmp_path: Path) -> None:
    bogus = tmp_path / "not.deb"
    bogus.write_bytes(b"not an ar archive\n")
    with bogus.open("rb") as fh, pytest.raises(ValueError, match="ar magic"):
        list(_iter_ar_members(fh))


def test_parse_control_extracts_required_fields() -> None:
    text = (
        "Package: hello\n"
        "Version: 2.10-3\n"
        "Architecture: amd64\n"
        "Maintainer: A <a@b.c>\n"
        "Depends: libc6 (>= 2.34)\n"
        "Description: first line\n"
        " continuation 1\n"
        " continuation 2\n"
    )
    fields = _parse_control(text)
    assert fields["Package"] == "hello"
    assert fields["Version"] == "2.10-3"
    assert fields["Architecture"] == "amd64"
    assert fields["Depends"] == "libc6 (>= 2.34)"
    # Multi-line Description: first line + both continuation lines preserved.
    assert "first line" in fields["Description"]
    assert "continuation 1" in fields["Description"]
    assert "continuation 2" in fields["Description"]


def test_parse_control_stops_at_blank_line() -> None:
    text = "Package: a\nVersion: 1\n\nPackage: b\n"
    fields = _parse_control(text)
    assert fields["Package"] == "a"
    assert "b" not in fields.get("Package", "")


def test_extract_control_reads_control_file_from_hello_deb(hello_deb: Path) -> None:
    text = _extract_control(hello_deb)
    assert "Package: hello" in text
    assert "Architecture: amd64" in text


def test_discover_systemd_units_finds_lib_systemd_unit(hello_deb: Path) -> None:
    units = _discover_systemd_units(hello_deb)
    assert units == ["hello.service"]


def test_discover_systemd_units_empty_when_no_units(tmp_path: Path) -> None:
    bare = tmp_path / "bare.deb"
    build_minimal_deb(bare, systemd_unit=None)
    assert _discover_systemd_units(bare) == []


def test_discover_systemd_units_finds_units_in_usr_lib_and_dedups(
    tmp_path: Path,
) -> None:
    """Cover both the usr/lib/systemd/system/ branch and the
    deduplication branch in _discover_systemd_units."""
    deb = tmp_path / "multi_1_amd64.deb"
    build_minimal_deb(
        deb,
        package="multi",
        version="1",
        systemd_unit="alpha.service",  # under ./lib/systemd/system/
        extra_unit_paths=[
            "./usr/lib/systemd/system/beta.service",
            # duplicate basename of the default lib/.../alpha.service,
            # but at a different parent path — exercises basename dedup.
            "./usr/lib/systemd/system/alpha.service",
        ],
    )
    units = _discover_systemd_units(deb)
    assert units == ["alpha.service", "beta.service"]


def test_probe_deb_returns_populated_DebProbe(hello_deb: Path) -> None:
    probe = probe_deb(hello_deb)
    assert probe.package == "hello"
    assert probe.version == "2.10-3"
    assert probe.arch == "amd64"
    assert probe.depends == ["libc6 (>= 2.34)"]
    assert probe.pre_depends == []
    assert probe.recommends == []
    assert probe.maintainer == "Test <test@example.com>"
    # Description in fixture is "test package\n A test package for ..."
    # so the summary line is exactly "test package".
    assert probe.description == "test package"
    assert probe.systemd_units == ["hello.service"]


def test_probe_deb_handles_missing_optional_fields(tmp_path: Path) -> None:
    spartan = tmp_path / "spartan.deb"
    build_minimal_deb(spartan, depends="", systemd_unit=None)
    probe = probe_deb(spartan)
    assert probe.depends == []
    assert probe.systemd_units == []


def test_probe_deb_raises_on_missing_required_control_field(tmp_path: Path) -> None:
    """A control file without Package/Version/Architecture should produce
    a clear ValueError before pydantic, not a raw KeyError."""
    import io

    from tests.fixtures.probe.deb_helpers import _ar_append, _make_tar_gz

    deb = tmp_path / "broken.deb"
    control_tar = _make_tar_gz({"control": b"Version: 1\nArchitecture: amd64\n\n"})
    data_tar = _make_tar_gz({"./usr/bin/x": b"#!/bin/sh\n"})
    buf = io.BytesIO()
    buf.write(b"!<arch>\n")
    _ar_append(buf, "debian-binary", b"2.0\n")
    _ar_append(buf, "control.tar.gz", control_tar)
    _ar_append(buf, "data.tar.gz", data_tar)
    deb.write_bytes(buf.getvalue())

    with pytest.raises(ValueError, match="Package"):
        probe_deb(deb)
