"""Derive PolicyJson from TraceJson. All policy decisions live here."""

from __future__ import annotations

from containerizer.analyze.schema import (
    PolicyImage,
    PolicyJson,
    PolicyPort,
    PolicyRuntime,
    PolicyVolume,
    TraceJson,
    TracePath,
)

SENTINEL_ENTRYPOINT = "__UNSET__"
SYSTEMD_COMMS = frozenset({"systemd", "systemctl", "init", "systemd-tmpfiles"})


def derive_policy(
    trace: TraceJson,
    *,
    probe_base: str = "ubuntu:24.04",
    warnings: list[str] | None = None,
) -> PolicyJson:
    """Turn a normalized TraceJson into a PolicyJson the M4 generator can consume."""
    runtime = trace.runtime

    # Volumes from persistent_rw paths. Disambiguate name collisions by
    # prepending the parent's leaf component.
    persistent = [p for p in runtime.paths if p.class_ == "persistent_rw"]
    volumes = _derive_volumes(persistent)

    tmpfs = sorted({p.path for p in runtime.paths if p.class_ == "ephemeral_rw"})
    binds_ro = sorted({p.path for p in runtime.paths if p.class_ == "host_config_ro"})

    publish_ports = [
        PolicyPort(host=p.port, container=p.port, proto=p.proto)
        for p in runtime.ports
        if p.proto in ("tcp", "udp")
    ]

    systemd_required = systemd_required_for(trace)
    start_cmd = trace.start_cmd or None  # defensive: empty string -> None

    # Copy so callers' list is not mutated when we append a warning below.
    final_warnings: list[str] = list(warnings or [])
    if systemd_required:
        entrypoint = ["/sbin/init"]
        if start_cmd:
            final_warnings.append(
                "start_cmd ignored: systemd detected as required; "
                "using /sbin/init as entrypoint"
            )
    elif start_cmd:
        entrypoint = ["bash", "-c", start_cmd]
    else:
        entrypoint = [SENTINEL_ENTRYPOINT]

    return PolicyJson(
        image=PolicyImage(
            base=probe_base,
            apt_packages=[],
            installer_path="/installer",
            post_install_cleanup=["/var/cache/apt/archives/*", "/installer"],
            systemd_required=systemd_required,
            entrypoint=entrypoint,
        ),
        runtime=PolicyRuntime(
            volumes=volumes,
            tmpfs=tmpfs,
            binds_ro=binds_ro,
            publish_ports=publish_ports,
            caps_add=runtime.caps,
            seccomp_syscalls=runtime.syscalls,
            read_only_rootfs=False,
        ),
        warnings=final_warnings,
    )


def _derive_volumes(persistent_paths: list[TracePath]) -> list[PolicyVolume]:
    """Name each volume ``<leaf>-data``; disambiguate collisions with parent leaf.

    Per spec §5.6: ``/var/lib/unifi`` and ``/var/log/unifi`` both want
    ``unifi-data``. The first (sorted by path) keeps the bare ``unifi-data``;
    the others get the parent leaf prepended (``log-unifi-data``).
    """
    by_name: dict[str, list[str]] = {}
    for p in persistent_paths:
        leaf = p.path.rstrip("/").rsplit("/", 1)[-1]
        name = f"{leaf}-data"
        by_name.setdefault(name, []).append(p.path)

    out: list[PolicyVolume] = []
    for name, paths in by_name.items():
        if len(paths) == 1:
            out.append(PolicyVolume(name=name, mount=paths[0]))
            continue
        # Collision — keep the first (sorted) as the bare name; disambiguate
        # the rest by prepending the parent's leaf component.
        for i, path in enumerate(sorted(paths)):
            if i == 0:
                out.append(PolicyVolume(name=name, mount=path))
                continue
            parts = path.rstrip("/").split("/")
            parent_leaf = parts[-2] if len(parts) >= 2 else "root"
            leaf = parts[-1]
            uniq = f"{parent_leaf}-{leaf}-data"
            out.append(PolicyVolume(name=uniq, mount=path))
    out.sort(key=lambda v: v.mount)
    return out


def systemd_required_for(trace: TraceJson) -> bool:
    """True if the trace implies a systemd-managed daemon (spec §5.5).

    Public so callers (e.g., the cli warning surface) can compute the same
    truth value derive_policy uses, without depending on a private name.
    """
    runtime_execs = set(trace.runtime.execs)
    if runtime_execs & SYSTEMD_COMMS:
        return True
    # Or any persistent_rw write to /etc/systemd/system/ during install
    for p in trace.install.paths:
        if p.class_ == "persistent_rw" and p.path.startswith("/etc/systemd/system"):
            return True
    return False
