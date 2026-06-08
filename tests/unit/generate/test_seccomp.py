"""Tests for analyze.generate.seccomp."""

from __future__ import annotations

import json

from containerizer.analyze.schema import (
    PolicyImage,
    PolicyJson,
    PolicyRuntime,
)
from containerizer.generate.seccomp import render_seccomp


def _policy(syscalls: list[int]) -> PolicyJson:
    return PolicyJson(
        image=PolicyImage(
            base="ubuntu:24.04",
            apt_packages=[],
            post_install_cleanup=[],
            systemd_required=False,
            entrypoint=["__UNSET__"],
        ),
        runtime=PolicyRuntime(
            volumes=[],
            tmpfs=[],
            binds_ro=[],
            publish_ports=[],
            caps_add=[],
            seccomp_syscalls=syscalls,
            read_only_rootfs=False,
        ),
    )


def test_empty_allowlist_renders_oci_shape() -> None:
    payload, unknown = render_seccomp(_policy([]))
    obj = json.loads(payload)
    assert obj["defaultAction"] == "SCMP_ACT_ERRNO"
    assert obj["architectures"] == ["SCMP_ARCH_X86_64"]
    assert obj["syscalls"] == [{"names": [], "action": "SCMP_ACT_ALLOW"}]
    assert unknown == []


def test_known_ids_resolve_to_sorted_names() -> None:
    payload, unknown = render_seccomp(_policy([59, 1, 0]))  # execve, write, read
    obj = json.loads(payload)
    assert obj["syscalls"][0]["names"] == ["execve", "read", "write"]
    assert unknown == []


def test_unknown_ids_dropped_and_returned() -> None:
    payload, unknown = render_seccomp(_policy([0, 99999]))
    obj = json.loads(payload)
    assert obj["syscalls"][0]["names"] == ["read"]
    assert unknown == [99999]


def test_payload_is_pretty_printed_with_trailing_newline() -> None:
    payload, _ = render_seccomp(_policy([0]))
    text = payload.decode("utf-8")
    assert text.endswith("\n")
    assert "  " in text  # indented JSON
