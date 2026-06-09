"""Derive strict-policy `podman run` flags from a PolicyJson.

The verify pass needs the same hardening the M4 Quadlet expresses
declaratively, but in argv form so we can `podman run` it inside the
trace-runner sandbox. The flags returned here mirror M4's quadlet.py
output one-for-one.
"""

from __future__ import annotations

from containerizer.analyze.derive import SENTINEL_ENTRYPOINT
from containerizer.analyze.schema import PolicyJson


def podman_run_flags(policy: PolicyJson) -> list[str]:
    """Return the argv tail of a strict-policy `podman run` for the verify pass.

    Empty list on sentinel entrypoint (defense-in-depth; caller is expected
    to short-circuit before invoking this).
    """
    if policy.image.entrypoint == [SENTINEL_ENTRYPOINT]:
        return []

    flags: list[str] = ["--cap-drop=ALL"]

    for cap in policy.runtime.caps_add:
        flags.append(f"--cap-add={cap}")

    if policy.runtime.read_only_rootfs:
        flags.append("--read-only")

    if policy.runtime.no_new_privileges:
        flags.extend(["--security-opt", "no-new-privileges"])

    # The seccomp profile is bind-mounted into the runner at the path below.
    flags.extend(["--security-opt", "seccomp=/work/verify/seccomp.json"])

    for path in policy.runtime.tmpfs:
        flags.extend(["--tmpfs", path])

    for bind in policy.runtime.binds_ro:
        flags.extend(["-v", f"{bind}:{bind}:ro"])

    for vol in policy.runtime.volumes:
        flags.extend(["-v", f"{vol.name}:{vol.mount}"])

    for port in policy.runtime.publish_ports:
        flags.extend(["-p", f"{port.host}:{port.container}/{port.proto}"])

    return flags
