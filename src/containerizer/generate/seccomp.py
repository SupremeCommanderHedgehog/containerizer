"""Render PolicyJson into an OCI seccomp.json payload."""

from __future__ import annotations

import json

from containerizer.analyze.schema import PolicyJson
from containerizer.generate.syscall_table import SYSCALL_NAMES

DEFAULT_ACTION = "SCMP_ACT_ERRNO"
ALLOW_ACTION = "SCMP_ACT_ALLOW"
ARCHITECTURES = ["SCMP_ARCH_X86_64"]


def render_seccomp(policy: PolicyJson) -> tuple[bytes, list[int]]:
    """Render policy.runtime.seccomp_syscalls as an OCI seccomp profile.

    Returns (payload_bytes, unknown_ids). Unknown syscall IDs are dropped
    from the allowlist; the caller is responsible for surfacing them to
    the user (cli.py emits both a stderr warning and a README section).
    """
    names: list[str] = []
    unknown: list[int] = []
    for sysno in policy.runtime.seccomp_syscalls:
        name = SYSCALL_NAMES.get(sysno)
        if name is None:
            unknown.append(sysno)
        else:
            names.append(name)

    payload = {
        "defaultAction": DEFAULT_ACTION,
        "architectures": ARCHITECTURES,
        "syscalls": [{"names": sorted(names), "action": ALLOW_ACTION}],
    }
    text = json.dumps(payload, indent=2) + "\n"
    return text.encode("utf-8"), unknown
