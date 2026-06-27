"""End-to-end smoke tests for `containerizer generate`."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest
from click.testing import CliRunner

from containerizer.analyze.cli import analyze_cmd
from containerizer.analyze.schema import (
    ExecutableInstaller,
    PolicyImage,
    PolicyJson,
    PolicyPort,
    PolicyRuntime,
    PolicyVolume,
)
from containerizer.generate.cli import generate_cmd

REPO_ROOT = Path(__file__).resolve().parents[3]
RECORDED = REPO_ROOT / "tests" / "fixtures" / "trace" / "synthetic-recorded"
EXPECTED = REPO_ROOT / "tests" / "fixtures" / "generate" / "expected"


def _load_json(path: Path) -> dict[str, object]:
    return cast(dict[str, object], json.loads(path.read_text(encoding="utf-8")))


@pytest.fixture
def golden_seccomp() -> dict[str, object]:
    return _load_json(EXPECTED / "seccomp.json")


@pytest.fixture
def golden_readme() -> str:
    return (EXPECTED / "README.md").read_text(encoding="utf-8")


@pytest.fixture
def golden_containerfile() -> str:
    return (EXPECTED / "Containerfile").read_text(encoding="utf-8")


@pytest.fixture
def golden_quadlet() -> str:
    return (EXPECTED / "synthetic-os.container").read_text(encoding="utf-8")


def test_sentinel_smoke_from_synthetic_fixture(
    tmp_path: Path,
    golden_seccomp: dict[str, object],
    golden_readme: str,
) -> None:
    """Chain analyze -> generate on the M3 synthetic fixture.

    The synthetic fixture's runtime execs don't include any systemd comm, so
    the policy's entrypoint is the sentinel. Only seccomp + README should land.
    """
    analyze_out = tmp_path / "analyze-out"
    generate_out = tmp_path / "generate-out"
    runner = CliRunner()

    r1 = runner.invoke(analyze_cmd, [str(RECORDED), "-o", str(analyze_out)])
    assert r1.exit_code == 0, r1.output

    r2 = runner.invoke(
        generate_cmd,
        [str(analyze_out / "policy.json"), "-n", "synthetic-os", "-o", str(generate_out)],
    )
    assert r2.exit_code == 0, r2.output

    assert not (generate_out / "Containerfile").exists()
    assert not (generate_out / "synthetic-os.container").exists()

    actual_seccomp = _load_json(generate_out / "seccomp.json")
    assert actual_seccomp == golden_seccomp

    actual_readme = (generate_out / "README.md").read_text(encoding="utf-8")
    assert actual_readme == golden_readme


def test_full_emit_from_handcrafted_non_sentinel_policy(
    tmp_path: Path,
    golden_containerfile: str,
    golden_quadlet: str,
) -> None:
    """Construct a non-sentinel policy in-Python; assert all four files emit
    and that Containerfile + Quadlet match committed goldens.
    """
    policy = PolicyJson(
        image=PolicyImage(
            base="ubuntu:24.04",
            installer=ExecutableInstaller(path="/installer"),
            apt_packages=[],
            post_install_cleanup=["/var/cache/apt/archives/*", "/installer"],
            systemd_required=True,
            entrypoint=["/sbin/init"],
        ),
        runtime=PolicyRuntime(
            volumes=[PolicyVolume(name="app-data", mount="/var/lib/app")],
            tmpfs=["/tmp"],
            binds_ro=["/etc/resolv.conf"],
            publish_ports=[PolicyPort(host=8443, container=8443, proto="tcp")],
            caps_add=["CAP_NET_BIND_SERVICE"],
            seccomp_syscalls=[0, 1, 59],
            read_only_rootfs=False,
        ),
        warnings=[],
    )
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(policy.model_dump_json(indent=2) + "\n", encoding="utf-8")
    out = tmp_path / "out"

    result = CliRunner().invoke(
        generate_cmd, [str(policy_path), "-n", "synthetic-os", "-o", str(out)]
    )
    assert result.exit_code == 0, result.output

    assert (out / "Containerfile").exists()
    assert (out / "synthetic-os.container").exists()
    assert (out / "seccomp.json").exists()
    assert (out / "README.md").exists()

    assert (out / "Containerfile").read_text(encoding="utf-8") == golden_containerfile
    assert (out / "synthetic-os.container").read_text(encoding="utf-8") == golden_quadlet
