"""Pydantic shape for BuildConfig including #102 multi-deb fields."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from containerizer.build.config import BuildConfig


def _cfg(**overrides) -> BuildConfig:
    base: dict = {
        "installer": Path("/tmp/foo.deb"),
        "name": "foo",
        "out_dir": Path("/tmp/out"),
    }
    base.update(overrides)
    return BuildConfig(**base)


def test_build_config_defaults_multi_deb_fields_to_empty() -> None:
    cfg = _cfg()
    assert cfg.extra_installers == ()
    assert cfg.apt_sources == ()
    assert cfg.apt_keys == ()


def test_build_config_accepts_multi_deb_fields() -> None:
    cfg = _cfg(
        extra_installers=(Path("/tmp/dep.deb"),),
        apt_sources=("deb http://x noble main",),
        apt_keys=(Path("/tmp/mongo.gpg"),),
    )
    assert cfg.extra_installers == (Path("/tmp/dep.deb"),)
    assert cfg.apt_sources == ("deb http://x noble main",)
    assert cfg.apt_keys == (Path("/tmp/mongo.gpg"),)


def test_build_config_rejects_extra_kwargs() -> None:
    with pytest.raises(ValidationError):
        _cfg(unknown_field="x")
