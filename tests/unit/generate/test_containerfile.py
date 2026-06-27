"""Tests for containerizer.generate.containerfile."""

from __future__ import annotations

from containerizer.analyze.schema import (
    DebInstaller,
    ExecutableInstaller,
    InstallerSpec,
    PolicyImage,
    PolicyJson,
    PolicyRuntime,
)
from containerizer.generate.containerfile import render_containerfile


def _policy(
    *,
    systemd_required: bool,
    entrypoint: list[str],
    installer: InstallerSpec | None = None,
    apt_sources: list[str] | None = None,
    apt_keys: list[str] | None = None,
    cleanup: list[str] | None = None,
) -> PolicyJson:
    return PolicyJson(
        image=PolicyImage(
            base="ubuntu:24.04",
            installer=installer or ExecutableInstaller(path="/installer"),
            apt_sources=apt_sources or [],
            apt_keys=apt_keys or [],
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


# --- Executable installer (legacy path) ---


def test_containerfile_executable_minimal() -> None:
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


def test_containerfile_executable_systemd_entrypoint_overrides_argv() -> None:
    text = render_containerfile(_policy(systemd_required=True, entrypoint=["/opt/app/bin/app"]))
    assert 'ENTRYPOINT ["/sbin/init"]\n' in text
    assert "/opt/app/bin/app" not in text


def test_containerfile_executable_cleanup_lines_appended_to_run() -> None:
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


# --- Deb installer (new path) ---


def test_containerfile_deb_single() -> None:
    text = render_containerfile(
        _policy(
            systemd_required=False,
            entrypoint=["/usr/sbin/foo"],
            installer=DebInstaller(paths=["/tmp/foo.deb"]),
            cleanup=["/tmp/*.deb", "/var/lib/apt/lists/*", "/var/cache/apt/archives/*"],
        )
    )
    assert text.startswith("FROM ubuntu:24.04\n")
    assert "ENV DEBIAN_FRONTEND=noninteractive\n" in text
    assert "COPY ./installers/foo.deb /tmp/foo.deb\n" in text
    assert "apt-get install -y --no-install-recommends" in text
    assert "/tmp/foo.deb" in text
    assert "rm -rf /tmp/*.deb /var/lib/apt/lists/* /var/cache/apt/archives/*" in text
    assert 'ENTRYPOINT ["/usr/sbin/foo"]\n' in text
    # No COPY ./installer for the deb path.
    assert "COPY ./installer /installer" not in text


def test_containerfile_deb_multi_with_apt_source_and_key() -> None:
    text = render_containerfile(
        _policy(
            systemd_required=False,
            entrypoint=["/usr/bin/unifi-start"],
            installer=DebInstaller(
                paths=[
                    "/tmp/unifi_sysvinit_all.deb",
                    "/tmp/mongodb-org-server_8.0.26_amd64.deb",
                ],
            ),
            apt_sources=[
                "deb [signed-by=/etc/apt/keyrings/mongodb.gpg] "
                "https://repo.mongodb.org/apt/ubuntu noble/mongodb-org/8.0 multiverse"
            ],
            apt_keys=["mongodb.gpg"],
            cleanup=["/tmp/*.deb", "/var/lib/apt/lists/*", "/var/cache/apt/archives/*"],
        )
    )
    assert "COPY ./apt-keys/mongodb.gpg /etc/apt/keyrings/mongodb.gpg\n" in text
    assert (
        "deb [signed-by=/etc/apt/keyrings/mongodb.gpg] "
        "https://repo.mongodb.org/apt/ubuntu noble/mongodb-org/8.0 multiverse"
    ) in text
    assert "COPY ./installers/unifi_sysvinit_all.deb /tmp/unifi_sysvinit_all.deb\n" in text
    assert (
        "COPY ./installers/mongodb-org-server_8.0.26_amd64.deb "
        "/tmp/mongodb-org-server_8.0.26_amd64.deb\n"
    ) in text
    # Both .debs in the apt-get install line.
    assert "/tmp/unifi_sysvinit_all.deb" in text
    assert "/tmp/mongodb-org-server_8.0.26_amd64.deb" in text


def test_containerfile_deb_apt_source_without_key() -> None:
    text = render_containerfile(
        _policy(
            systemd_required=False,
            entrypoint=["/x"],
            installer=DebInstaller(paths=["/tmp/foo.deb"]),
            apt_sources=["deb http://example/x noble main"],
            cleanup=["/tmp/*.deb"],
        )
    )
    # Sources are present.
    assert "deb http://example/x noble main" in text
    # No apt-keys COPY block.
    assert "COPY ./apt-keys/" not in text


def test_containerfile_deb_no_sources_no_keys() -> None:
    text = render_containerfile(
        _policy(
            systemd_required=False,
            entrypoint=["/x"],
            installer=DebInstaller(paths=["/tmp/foo.deb"]),
            cleanup=["/tmp/*.deb"],
        )
    )
    # No sources block, no keys block.
    assert "/etc/apt/sources.list.d/containerizer.list" not in text
    assert "COPY ./apt-keys/" not in text
    # apt-get install still runs.
    assert "apt-get install -y --no-install-recommends \\\n      /tmp/foo.deb" in text


def test_containerfile_deb_systemd_uses_sbin_init_entrypoint() -> None:
    text = render_containerfile(
        _policy(
            systemd_required=True,
            entrypoint=["/usr/sbin/whatever"],
            installer=DebInstaller(paths=["/tmp/foo.deb"]),
            cleanup=["/tmp/*.deb"],
        )
    )
    assert 'ENTRYPOINT ["/sbin/init"]\n' in text
    assert "/usr/sbin/whatever" not in text
