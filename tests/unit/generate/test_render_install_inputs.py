"""Issue #102: README 'Install inputs' section."""

from __future__ import annotations

from pathlib import Path

from containerizer.analyze.schema import (
    ExecutableInstaller,
    PolicyImage,
    PolicyJson,
    PolicyRuntime,
)
from containerizer.generate.readme import _render_install_inputs, render_readme


def test_install_inputs_section_lists_primary_extras_sources() -> None:
    section = _render_install_inputs(
        primary=Path("/x/unifi_sysvinit_all.deb"),
        extras=(Path("/x/mongodb-org-server_8.0.7_amd64.deb"),),
        apt_sources=(
            "deb [signed-by=/etc/apt/keyrings/m.gpg] "
            "https://repo.mongodb.org/apt/ubuntu noble/mongodb-org/8.0 multiverse",
        ),
    )
    assert "## Install inputs" in section
    assert "unifi_sysvinit_all.deb" in section
    assert "mongodb-org-server_8.0.7_amd64.deb" in section
    # Bracket options stripped from rendered apt-source.
    assert "[signed-by=" not in section
    assert "[trusted=yes]" not in section
    assert "https://repo.mongodb.org/apt/ubuntu noble/mongodb-org/8.0 multiverse" in section


def test_install_inputs_section_omits_empty_subsections() -> None:
    section = _render_install_inputs(
        primary=Path("/x/unifi.deb"),
        extras=(),
        apt_sources=(),
    )
    assert "## Install inputs" in section
    assert "Primary installer" in section
    # No "Additional installers" or "apt sources" headings when empty.
    assert "Additional installers" not in section
    assert "apt sources" not in section


def test_install_inputs_returns_empty_string_when_nothing_to_render() -> None:
    section = _render_install_inputs(primary=None, extras=(), apt_sources=())
    assert section == ""


def test_install_inputs_section_renders_start_command_when_set() -> None:
    section = _render_install_inputs(
        primary=Path("/x/unifi.deb"),
        extras=(),
        apt_sources=(),
        start_cmd="/etc/init.d/mongod start && sleep 10 && /etc/init.d/unifi start",
        start_ready_seconds=120,
        verify_soak_seconds=60,
    )
    assert "Start command:" in section
    assert "/etc/init.d/mongod start && sleep 10 && /etc/init.d/unifi start" in section
    assert "Ready timeout: 120s" in section
    assert "Verify soak: 60s" in section


def test_install_inputs_section_omits_start_command_when_unset() -> None:
    section = _render_install_inputs(
        primary=Path("/x/unifi.deb"),
        extras=(),
        apt_sources=(),
    )
    assert "Start command:" not in section


def test_render_readme_includes_install_inputs_when_provided() -> None:
    """Smoke: render_readme wires install_inputs into the assembled README."""
    policy = PolicyJson(
        image=PolicyImage(
            base="ubuntu:24.04",
            installer=ExecutableInstaller(path="/installer"),
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
            seccomp_syscalls=[],
            read_only_rootfs=False,
        ),
        warnings=[],
    )
    text = render_readme(
        policy,
        name="unifi",
        skipped=True,
        unknown_syscall_ids=[],
        install_primary=Path("/x/unifi.deb"),
        install_extras=(Path("/x/mongo.deb"),),
        install_apt_sources=("deb http://repo noble main",),
    )
    assert "## Install inputs" in text
    assert "mongo.deb" in text
