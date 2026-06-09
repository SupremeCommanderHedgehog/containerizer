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
    assert cfg.verify_soak_seconds == 30
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
