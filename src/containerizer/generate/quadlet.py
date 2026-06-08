"""Render PolicyJson into a systemd Quadlet `.container` unit."""

from __future__ import annotations

from containerizer.analyze.schema import PolicyJson


def render_quadlet(policy: PolicyJson, name: str) -> str:
    """Render policy.runtime as a Quadlet container unit string.

    Sections in fixed order (volumes -> tmpfs -> binds_ro -> ports -> caps ->
    flags -> seccomp) so golden diffs stay readable.
    """
    runtime = policy.runtime
    lines: list[str] = [
        "[Unit]",
        f"Description=Containerized {name}",
        "After=network-online.target",
        "Wants=network-online.target",
        "",
        "[Container]",
        f"Image={name}:latest",
        f"ContainerName={name}",
    ]

    for vol in runtime.volumes:
        lines.append(f"Volume={vol.name}:{vol.mount}")
    for path in runtime.tmpfs:
        lines.append(f"Tmpfs={path}")
    for path in runtime.binds_ro:
        lines.append(f"Volume={path}:{path}:ro")
    for port in runtime.publish_ports:
        lines.append(f"PublishPort={port.host}:{port.container}/{port.proto}")

    # Drops first (always includes ALL), then sorted adds.
    for cap in runtime.caps_drop:
        lines.append(f"DropCapability={cap}")
    for cap in sorted(runtime.caps_add):
        lines.append(f"AddCapability={cap}")

    lines.append(f"NoNewPrivileges={str(runtime.no_new_privileges).lower()}")
    lines.append(f"ReadOnly={str(runtime.read_only_rootfs).lower()}")
    lines.append(f"GlobalArgs=--security-opt seccomp=%h/.config/containers/seccomp/{name}.json")
    lines.append("")
    lines.append("[Install]")
    lines.append("WantedBy=default.target")
    return "\n".join(lines) + "\n"
