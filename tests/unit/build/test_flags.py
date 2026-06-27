"""Strict-policy `podman run` flag derivation from PolicyJson."""

from __future__ import annotations

from containerizer.analyze.schema import (
    ExecutableInstaller,
    PolicyImage,
    PolicyJson,
    PolicyPort,
    PolicyRuntime,
    PolicyVolume,
)
from containerizer.build.flags import podman_run_flags


def _policy(runtime: PolicyRuntime, *, entrypoint: list[str] | None = None) -> PolicyJson:
    return PolicyJson(
        image=PolicyImage(
            base="ubuntu:24.04",
            installer=ExecutableInstaller(path="/installer"),
            apt_packages=[],
            post_install_cleanup=[],
            systemd_required=True,
            entrypoint=entrypoint or ["/sbin/init"],
        ),
        runtime=runtime,
    )


def test_minimum_viable_flags() -> None:
    runtime = PolicyRuntime(
        volumes=[],
        tmpfs=[],
        binds_ro=[],
        publish_ports=[],
        caps_add=[],
        seccomp_syscalls=[],
        read_only_rootfs=False,
        no_new_privileges=False,
    )
    flags = podman_run_flags(_policy(runtime))

    assert "--cap-drop=ALL" in flags
    assert "--security-opt" in flags
    assert "seccomp=/work/verify/seccomp.json" in flags
    assert "--read-only" not in flags
    assert not any(f.startswith("--cap-add") for f in flags)


def test_caps_add_each_become_cap_add_flag() -> None:
    runtime = PolicyRuntime(
        volumes=[],
        tmpfs=[],
        binds_ro=[],
        publish_ports=[],
        caps_add=["CAP_NET_BIND_SERVICE", "CAP_CHOWN"],
        seccomp_syscalls=[],
        read_only_rootfs=False,
        no_new_privileges=False,
    )
    flags = podman_run_flags(_policy(runtime))
    assert "--cap-add=CAP_NET_BIND_SERVICE" in flags
    assert "--cap-add=CAP_CHOWN" in flags


def test_tmpfs_entries_become_tmpfs_flags() -> None:
    runtime = PolicyRuntime(
        volumes=[],
        tmpfs=["/tmp", "/run"],
        binds_ro=[],
        publish_ports=[],
        caps_add=[],
        seccomp_syscalls=[],
        read_only_rootfs=False,
        no_new_privileges=False,
    )
    flags = podman_run_flags(_policy(runtime))
    assert "--tmpfs" in flags
    assert "/tmp" in flags
    assert "/run" in flags


def test_binds_ro_become_ro_volumes() -> None:
    runtime = PolicyRuntime(
        volumes=[],
        tmpfs=[],
        binds_ro=["/etc/resolv.conf"],
        publish_ports=[],
        caps_add=[],
        seccomp_syscalls=[],
        read_only_rootfs=False,
        no_new_privileges=False,
    )
    flags = podman_run_flags(_policy(runtime))
    assert "-v" in flags
    assert "/etc/resolv.conf:/etc/resolv.conf:ro" in flags


def test_volumes_become_anonymous_volume_args() -> None:
    runtime = PolicyRuntime(
        volumes=[PolicyVolume(name="data", mount="/var/lib/data")],
        tmpfs=[],
        binds_ro=[],
        publish_ports=[],
        caps_add=[],
        seccomp_syscalls=[],
        read_only_rootfs=False,
        no_new_privileges=False,
    )
    flags = podman_run_flags(_policy(runtime))
    assert "data:/var/lib/data" in flags


def test_publish_ports_become_p_flags() -> None:
    runtime = PolicyRuntime(
        volumes=[],
        tmpfs=[],
        binds_ro=[],
        publish_ports=[PolicyPort(host=8443, container=8443, proto="tcp")],
        caps_add=[],
        seccomp_syscalls=[],
        read_only_rootfs=False,
        no_new_privileges=False,
    )
    flags = podman_run_flags(_policy(runtime))
    assert "-p" in flags
    assert "8443:8443/tcp" in flags


def test_read_only_rootfs_emits_read_only_flag() -> None:
    runtime = PolicyRuntime(
        volumes=[],
        tmpfs=[],
        binds_ro=[],
        publish_ports=[],
        caps_add=[],
        seccomp_syscalls=[],
        read_only_rootfs=True,
        no_new_privileges=False,
    )
    flags = podman_run_flags(_policy(runtime))
    assert "--read-only" in flags


def test_no_new_privileges_emits_security_opt() -> None:
    runtime = PolicyRuntime(
        volumes=[],
        tmpfs=[],
        binds_ro=[],
        publish_ports=[],
        caps_add=[],
        seccomp_syscalls=[],
        read_only_rootfs=False,
        no_new_privileges=True,
    )
    flags = podman_run_flags(_policy(runtime))
    # one of the --security-opt slots carries "no-new-privileges"
    assert any(f == "no-new-privileges" for f in flags)


def test_sentinel_entrypoint_returns_empty_list() -> None:
    runtime = PolicyRuntime(
        volumes=[],
        tmpfs=[],
        binds_ro=[],
        publish_ports=[],
        caps_add=[],
        seccomp_syscalls=[],
        read_only_rootfs=False,
        no_new_privileges=False,
    )
    flags = podman_run_flags(_policy(runtime, entrypoint=["__UNSET__"]))
    assert flags == []
