"""Tests for the Debian .deb probe."""

from pathlib import Path

import pytest

from containerizer.probe.deb import (
    _extract_control,
    _iter_ar_members,
    _parse_control,
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
