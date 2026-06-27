"""Tests for containerizer.generate.readme."""

from __future__ import annotations

from containerizer.analyze.schema import (
    ExecutableInstaller,
    PolicyImage,
    PolicyJson,
    PolicyPort,
    PolicyRuntime,
    PolicyVolume,
)
from containerizer.generate.readme import render_readme


def _policy(
    *,
    warnings: list[str] | None = None,
    entrypoint: list[str] | None = None,
) -> PolicyJson:
    return PolicyJson(
        image=PolicyImage(
            base="ubuntu:24.04",
            installer=ExecutableInstaller(path="/installer"),
            apt_packages=[],
            post_install_cleanup=[],
            systemd_required=False,
            entrypoint=entrypoint or ["__UNSET__"],
        ),
        runtime=PolicyRuntime(
            volumes=[PolicyVolume(name="app-data", mount="/var/lib/app")],
            tmpfs=["/tmp"],
            binds_ro=["/etc/resolv.conf"],
            publish_ports=[PolicyPort(host=80, container=80, proto="tcp")],
            caps_add=["CAP_NET_BIND_SERVICE"],
            seccomp_syscalls=[0, 1],
            read_only_rootfs=False,
        ),
        warnings=warnings or [],
    )


def test_readme_has_title_with_name() -> None:
    text = render_readme(_policy(), "myapp", skipped=False, unknown_syscall_ids=[])
    assert text.startswith("# Containerizer output for myapp\n")


def test_readme_non_sentinel_lists_four_files() -> None:
    text = render_readme(_policy(), "myapp", skipped=False, unknown_syscall_ids=[])
    assert "Containerfile" in text
    assert "myapp.container" in text
    assert "seccomp.json" in text
    assert "README.md" in text
    assert "SKIPPED" not in text


def test_readme_sentinel_has_skipped_section() -> None:
    text = render_readme(
        _policy(warnings=["entrypoint is sentinel ['__UNSET__']; M4 must refuse this policy"]),
        "myapp",
        skipped=True,
        unknown_syscall_ids=[],
    )
    assert "## SKIPPED" in text
    assert "Containerfile" in text
    assert "myapp.container" in text
    assert "entrypoint is sentinel" in text


def test_readme_audit_trail_lists_policy_warnings() -> None:
    text = render_readme(
        _policy(warnings=["unknown_rw aggregate: /var/foo", "device aggregate: /dev/bar"]),
        "myapp",
        skipped=False,
        unknown_syscall_ids=[],
    )
    assert "unknown_rw aggregate: /var/foo" in text
    assert "device aggregate: /dev/bar" in text


def test_readme_unknown_syscalls_section_only_when_nonempty() -> None:
    text_with = render_readme(_policy(), "myapp", skipped=False, unknown_syscall_ids=[437, 999])
    assert "Unknown syscall IDs" in text_with
    assert "437" in text_with
    assert "999" in text_with

    text_without = render_readme(_policy(), "myapp", skipped=False, unknown_syscall_ids=[])
    assert "Unknown syscall IDs" not in text_without


def test_readme_runtime_allowlist_summary() -> None:
    text = render_readme(_policy(), "myapp", skipped=False, unknown_syscall_ids=[])
    assert "1 volume" in text or "volumes: 1" in text or "Volumes: 1" in text
    assert "/var/lib/app" in text
    assert "/etc/resolv.conf" in text
    assert "CAP_NET_BIND_SERVICE" in text


def test_readme_next_steps_mentions_podman_build_and_systemctl() -> None:
    text = render_readme(_policy(), "myapp", skipped=False, unknown_syscall_ids=[])
    assert "podman build" in text
    assert "systemctl --user" in text


def test_readme_ends_with_trailing_newline() -> None:
    text = render_readme(_policy(), "myapp", skipped=False, unknown_syscall_ids=[])
    assert text.endswith("\n")
