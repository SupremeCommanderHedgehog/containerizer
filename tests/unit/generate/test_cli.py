"""Tests for the `containerizer generate` Click subcommand."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from containerizer.analyze.schema import (
    ExecutableInstaller,
    PolicyImage,
    PolicyJson,
    PolicyPort,
    PolicyRuntime,
    PolicyVolume,
)
from containerizer.generate.cli import generate_cmd


def _write_policy(
    path: Path,
    *,
    entrypoint: list[str],
    caps_add: list[str] | None = None,
    syscalls: list[int] | None = None,
) -> None:
    policy = PolicyJson(
        image=PolicyImage(
            base="ubuntu:24.04",
            installer=ExecutableInstaller(path="/installer"),
            apt_packages=[],
            post_install_cleanup=["/installer"],
            systemd_required=False,
            entrypoint=entrypoint,
        ),
        runtime=PolicyRuntime(
            volumes=[PolicyVolume(name="app-data", mount="/var/lib/app")],
            tmpfs=["/tmp"],
            binds_ro=["/etc/resolv.conf"],
            publish_ports=[PolicyPort(host=80, container=80, proto="tcp")],
            caps_add=caps_add or [],
            seccomp_syscalls=syscalls or [],
            read_only_rootfs=False,
        ),
        warnings=[],
    )
    path.write_text(policy.model_dump_json(indent=2) + "\n", encoding="utf-8")


def test_generate_happy_path_emits_four_files(tmp_path: Path) -> None:
    policy_path = tmp_path / "policy.json"
    _write_policy(policy_path, entrypoint=["/opt/app/bin/app"], syscalls=[0, 1, 59])
    out = tmp_path / "out"

    result = CliRunner().invoke(generate_cmd, [str(policy_path), "-n", "myapp", "-o", str(out)])
    assert result.exit_code == 0, result.output

    assert (out / "Containerfile").exists()
    assert (out / "myapp.container").exists()
    assert (out / "seccomp.json").exists()
    assert (out / "README.md").exists()

    assert (out / "Containerfile").read_text(encoding="utf-8").startswith("FROM ubuntu:24.04")
    seccomp = json.loads((out / "seccomp.json").read_text(encoding="utf-8"))
    assert seccomp["defaultAction"] == "SCMP_ACT_ERRNO"


def test_generate_sentinel_skips_containerfile_and_quadlet(tmp_path: Path) -> None:
    policy_path = tmp_path / "policy.json"
    _write_policy(policy_path, entrypoint=["__UNSET__"])
    out = tmp_path / "out"

    result = CliRunner().invoke(generate_cmd, [str(policy_path), "-n", "myapp", "-o", str(out)])
    assert result.exit_code == 0, result.output

    assert not (out / "Containerfile").exists()
    assert not (out / "myapp.container").exists()
    assert (out / "seccomp.json").exists()
    assert (out / "README.md").exists()

    readme = (out / "README.md").read_text(encoding="utf-8")
    assert "SKIPPED" in readme
    assert "sentinel" in result.output.lower()


def test_generate_unknown_syscall_warns_on_stderr(tmp_path: Path) -> None:
    policy_path = tmp_path / "policy.json"
    _write_policy(policy_path, entrypoint=["/x"], syscalls=[0, 99999])
    out = tmp_path / "out"

    # Click 8.2+ splits stderr by default (the `mix_stderr` kwarg was removed
    # in 8.2). `result.stderr` is always available without extra setup.
    result = CliRunner().invoke(generate_cmd, [str(policy_path), "-n", "myapp", "-o", str(out)])
    assert result.exit_code == 0, result.output
    assert "99999" in result.stderr


def test_generate_missing_policy_file_errors(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        generate_cmd, [str(tmp_path / "nope.json"), "-n", "x", "-o", str(tmp_path / "out")]
    )
    assert result.exit_code != 0


def test_main_cli_lists_generate() -> None:
    from containerizer.cli import main

    result = CliRunner().invoke(main, ["--help"])
    assert "generate" in result.output
