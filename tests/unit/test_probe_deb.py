"""Tests for the Debian .deb probe."""

from pathlib import Path

import pytest

from tests.fixtures.probe.deb_helpers import build_minimal_deb


@pytest.fixture
def hello_deb(tmp_path: Path) -> Path:
    deb = tmp_path / "hello_2.10-3_amd64.deb"
    build_minimal_deb(deb)
    return deb


def test_iter_ar_members_yields_three_expected_files(hello_deb: Path) -> None:
    from containerizer.probe.deb import _iter_ar_members

    with hello_deb.open("rb") as fh:
        names = [m.name for m in _iter_ar_members(fh)]

    assert names == ["debian-binary", "control.tar.gz", "data.tar.gz"]


def test_iter_ar_members_rejects_missing_magic(tmp_path: Path) -> None:
    from containerizer.probe.deb import _iter_ar_members

    bogus = tmp_path / "not.deb"
    bogus.write_bytes(b"not an ar archive\n")
    with bogus.open("rb") as fh, pytest.raises(ValueError, match="ar magic"):
        list(_iter_ar_members(fh))
