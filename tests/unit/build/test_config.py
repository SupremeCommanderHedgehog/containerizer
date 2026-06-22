"""Pydantic round-trip + frozen invariants for BuildConfig and BuildResult."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from containerizer.build.config import BuildConfig, BuildResult
from containerizer.verify.schema import VerifyDiff, VerifyReport


def test_build_config_round_trip_defaults() -> None:
    cfg = BuildConfig(installer=Path("/tmp/x"), name="demo", out_dir=Path("out"))

    assert cfg.schema_version == 1
    assert cfg.base_image is None
    assert cfg.start_cmd is None
    assert cfg.keep_intermediates is False
    assert cfg.verify_soak_seconds is None  # Issue #105: sentinel default
    assert cfg.skip_verify is False
    assert cfg.debug is False

    payload = cfg.model_dump_json()
    cfg2 = BuildConfig.model_validate_json(payload)
    assert cfg2 == cfg


def test_build_config_is_frozen() -> None:
    cfg = BuildConfig(installer=Path("/tmp/x"), name="demo", out_dir=Path("out"))
    with pytest.raises(ValidationError):
        cfg.name = "changed"


def test_build_config_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError):
        BuildConfig(
            installer=Path("/tmp/x"),
            name="demo",
            out_dir=Path("out"),
            mystery_flag=True,  # type: ignore[call-arg]
        )


def test_build_config_defaults_multi_deb_fields_to_empty() -> None:
    """Issue #102: empty-tuple defaults keep single-installer flows unchanged."""
    cfg = BuildConfig(installer=Path("/tmp/x"), name="demo", out_dir=Path("out"))
    assert cfg.extra_installers == ()
    assert cfg.apt_sources == ()
    assert cfg.apt_keys == ()


def test_build_config_accepts_multi_deb_fields() -> None:
    """Issue #102: extras / apt-sources / apt-keys round-trip cleanly."""
    cfg = BuildConfig(
        installer=Path("/tmp/x"),
        name="demo",
        out_dir=Path("out"),
        extra_installers=(Path("/tmp/dep.deb"),),
        apt_sources=("deb http://x noble main",),
        apt_keys=(Path("/tmp/mongo.gpg"),),
    )
    assert cfg.extra_installers == (Path("/tmp/dep.deb"),)
    assert cfg.apt_sources == ("deb http://x noble main",)
    assert cfg.apt_keys == (Path("/tmp/mongo.gpg"),)


def test_build_result_round_trip_with_verify() -> None:
    report = VerifyReport(
        original_marker="COMPLETE",
        observed_marker="COMPLETE",
        diff=VerifyDiff(new_paths=[], new_ports=[], new_caps=[], new_syscalls=[], new_execs=[]),
    )
    result = BuildResult(
        final_dir=Path("./out/demo"),
        intermediates_dir=None,
        verify=report,
    )

    assert result.schema_version == 1
    assert result.skip_reason is None
    assert result.warnings == []
    assert result.verify == report

    payload = result.model_dump_json()
    result2 = BuildResult.model_validate_json(payload)
    assert result2 == result


def test_build_result_round_trip_sentinel_skip() -> None:
    result = BuildResult(
        final_dir=Path("./out/demo"),
        intermediates_dir=None,
        verify=None,
        skip_reason="sentinel",
        warnings=["entrypoint sentinel; verify skipped"],
    )

    payload = result.model_dump_json()
    result2 = BuildResult.model_validate_json(payload)
    assert result2 == result
    assert result2.skip_reason == "sentinel"


def test_build_config_defaults_start_ready_seconds_to_60() -> None:
    cfg = BuildConfig(installer=Path("/tmp/x"), name="demo", out_dir=Path("out"))
    assert cfg.start_ready_seconds == 60


def test_build_config_verify_soak_defaults_to_none_sentinel() -> None:
    """Pipeline distinguishes 'user explicitly set 30' from 'user didn't set anything'
    so the auto-scale can fire only when no override was given."""
    cfg = BuildConfig(installer=Path("/tmp/x"), name="demo", out_dir=Path("out"))
    assert cfg.verify_soak_seconds is None


def test_effective_verify_soak_returns_30_when_no_start_cmd_and_no_override() -> None:
    cfg = BuildConfig(installer=Path("/tmp/x"), name="demo", out_dir=Path("out"))
    assert cfg.effective_verify_soak_seconds == 30


def test_effective_verify_soak_uses_explicit_override_when_set() -> None:
    cfg = BuildConfig(
        installer=Path("/tmp/x"),
        name="demo",
        out_dir=Path("out"),
        verify_soak_seconds=15,
    )
    assert cfg.effective_verify_soak_seconds == 15


def test_effective_verify_soak_uses_explicit_override_even_with_start_cmd() -> None:
    cfg = BuildConfig(
        installer=Path("/tmp/x"),
        name="demo",
        out_dir=Path("out"),
        start_cmd="/etc/init.d/foo start",
        start_ready_seconds=120,
        verify_soak_seconds=10,
    )
    assert cfg.effective_verify_soak_seconds == 10


def test_effective_verify_soak_autoscales_to_60_with_start_cmd_and_low_ready() -> None:
    cfg = BuildConfig(
        installer=Path("/tmp/x"),
        name="demo",
        out_dir=Path("out"),
        start_cmd="/etc/init.d/foo start",
        start_ready_seconds=30,
    )
    assert cfg.effective_verify_soak_seconds == 60


def test_effective_verify_soak_autoscales_to_start_ready_when_larger() -> None:
    cfg = BuildConfig(
        installer=Path("/tmp/x"),
        name="demo",
        out_dir=Path("out"),
        start_cmd="/etc/init.d/foo start",
        start_ready_seconds=120,
    )
    assert cfg.effective_verify_soak_seconds == 120
