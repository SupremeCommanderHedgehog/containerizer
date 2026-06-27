"""Tests for containerizer.generate.quadlet."""

from __future__ import annotations

from containerizer.analyze.schema import (
    ExecutableInstaller,
    PolicyImage,
    PolicyJson,
    PolicyPort,
    PolicyRuntime,
    PolicyVolume,
)
from containerizer.generate.quadlet import render_quadlet

_IMAGE = PolicyImage(
    base="ubuntu:24.04",
    installer=ExecutableInstaller(path="/installer"),
    apt_packages=[],
    post_install_cleanup=[],
    systemd_required=False,
    entrypoint=["/opt/app/bin/app"],
)


def _runtime(
    *,
    volumes: list[PolicyVolume] | None = None,
    tmpfs: list[str] | None = None,
    binds_ro: list[str] | None = None,
    ports: list[PolicyPort] | None = None,
    caps_add: list[str] | None = None,
) -> PolicyRuntime:
    return PolicyRuntime(
        volumes=volumes or [],
        tmpfs=tmpfs or [],
        binds_ro=binds_ro or [],
        publish_ports=ports or [],
        caps_add=caps_add or [],
        seccomp_syscalls=[],
        read_only_rootfs=False,
    )


def _policy(runtime: PolicyRuntime) -> PolicyJson:
    return PolicyJson(image=_IMAGE, runtime=runtime)


def test_quadlet_has_required_sections() -> None:
    text = render_quadlet(_policy(_runtime()), "myapp")
    assert "[Unit]" in text
    assert "[Container]" in text
    assert "[Install]" in text
    assert "Image=myapp:latest" in text
    assert "ContainerName=myapp" in text
    assert "WantedBy=default.target" in text


def test_quadlet_volumes_render_one_line_each() -> None:
    text = render_quadlet(
        _policy(
            _runtime(
                volumes=[
                    PolicyVolume(name="app-data", mount="/var/lib/app"),
                    PolicyVolume(name="app-logs", mount="/var/log/app"),
                ]
            )
        ),
        "myapp",
    )
    assert "Volume=app-data:/var/lib/app" in text
    assert "Volume=app-logs:/var/log/app" in text


def test_quadlet_tmpfs_renders_one_line_each() -> None:
    text = render_quadlet(_policy(_runtime(tmpfs=["/tmp", "/run"])), "myapp")
    assert "Tmpfs=/tmp" in text
    assert "Tmpfs=/run" in text


def test_quadlet_binds_ro_use_volume_ro_syntax() -> None:
    text = render_quadlet(
        _policy(_runtime(binds_ro=["/etc/resolv.conf"])),
        "myapp",
    )
    assert "Volume=/etc/resolv.conf:/etc/resolv.conf:ro" in text


def test_quadlet_publish_ports() -> None:
    text = render_quadlet(
        _policy(_runtime(ports=[PolicyPort(host=8443, container=8443, proto="tcp")])),
        "myapp",
    )
    assert "PublishPort=8443:8443/tcp" in text


def test_quadlet_drops_all_then_adds_sorted() -> None:
    text = render_quadlet(
        _policy(_runtime(caps_add=["CAP_NET_BIND_SERVICE", "CAP_CHOWN"])),
        "myapp",
    )
    drop_line = text.index("DropCapability=ALL")
    chown_line = text.index("AddCapability=CAP_CHOWN")
    bind_line = text.index("AddCapability=CAP_NET_BIND_SERVICE")
    assert drop_line < chown_line < bind_line  # drops before adds, adds sorted


def test_quadlet_security_flags() -> None:
    text = render_quadlet(_policy(_runtime()), "myapp")
    assert "NoNewPrivileges=true" in text
    assert "ReadOnly=false" in text


def test_quadlet_seccomp_global_args() -> None:
    text = render_quadlet(_policy(_runtime()), "myapp")
    assert "GlobalArgs=--security-opt seccomp=%h/.config/containers/seccomp/myapp.json" in text


def test_quadlet_ends_with_trailing_newline() -> None:
    text = render_quadlet(_policy(_runtime()), "myapp")
    assert text.endswith("\n")
