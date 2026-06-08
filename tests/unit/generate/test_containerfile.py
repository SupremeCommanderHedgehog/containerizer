"""Tests for analyze.generate.containerfile."""

from __future__ import annotations

from containerizer.analyze.schema import (
    PolicyImage,
    PolicyJson,
    PolicyRuntime,
)
from containerizer.generate.containerfile import render_containerfile


def _policy(
    *,
    systemd_required: bool,
    entrypoint: list[str],
    cleanup: list[str] | None = None,
) -> PolicyJson:
    return PolicyJson(
        image=PolicyImage(
            base="ubuntu:24.04",
            apt_packages=[],
            post_install_cleanup=cleanup or [],
            systemd_required=systemd_required,
            entrypoint=entrypoint,
        ),
        runtime=PolicyRuntime(
            volumes=[],
            tmpfs=[],
            binds_ro=[],
            publish_ports=[],
            caps_add=[],
            seccomp_syscalls=[],
            read_only_rootfs=False,
        ),
    )


def test_containerfile_minimal_argv_entrypoint() -> None:
    text = render_containerfile(
        _policy(
            systemd_required=False,
            entrypoint=["/opt/app/bin/app", "--config", "/etc/app.conf"],
        )
    )
    assert text.startswith("FROM ubuntu:24.04\n")
    assert "COPY ./installer /installer\n" in text
    assert "RUN /installer" in text
    assert 'ENTRYPOINT ["/opt/app/bin/app", "--config", "/etc/app.conf"]\n' in text


def test_containerfile_systemd_entrypoint_overrides_argv() -> None:
    text = render_containerfile(_policy(systemd_required=True, entrypoint=["/opt/app/bin/app"]))
    assert 'ENTRYPOINT ["/sbin/init"]\n' in text
    assert "/opt/app/bin/app" not in text


def test_containerfile_cleanup_lines_appended_to_run() -> None:
    text = render_containerfile(
        _policy(
            systemd_required=False,
            entrypoint=["/x"],
            cleanup=["/var/cache/apt/archives/*", "/installer"],
        )
    )
    assert (
        "RUN /installer \\\n && rm -rf /var/cache/apt/archives/* \\\n && rm -rf /installer\n"
        in text
    )


def test_containerfile_ends_with_trailing_newline() -> None:
    text = render_containerfile(_policy(systemd_required=False, entrypoint=["/x"]))
    assert text.endswith("\n")
