"""Render the human-readable README audit trail for a generated policy."""

from __future__ import annotations

from containerizer.analyze.schema import PolicyJson, PolicyRuntime


def render_readme(
    policy: PolicyJson,
    name: str,
    *,
    skipped: bool,
    unknown_syscall_ids: list[int],
) -> str:
    """Render the README.md describing the generated artifacts.

    Sections (in order):
      - Title
      - SKIPPED (only if sentinel)
      - What was generated
      - Audit trail (policy.warnings)
      - Runtime allowlist (volumes, tmpfs, binds_ro, ports, caps, syscalls)
      - Unknown syscall IDs (only when non-empty)
      - Next steps
    """
    runtime = policy.runtime
    sections: list[str] = [f"# Containerizer output for {name}\n"]

    if skipped:
        sections.append(
            "## SKIPPED\n\n"
            f"`Containerfile` and `{name}.container` were NOT generated because the "
            f"policy's entrypoint is the sentinel `['__UNSET__']`. The seccomp profile "
            f"and this README still ship so you can diff future runs.\n\n"
            "Relevant warning:\n\n" + _render_sentinel_warning(policy.warnings) + "\n"
        )

    sections.append(_render_what_was_generated(name, skipped))
    sections.append(_render_audit_trail(policy.warnings))
    sections.append(_render_runtime_allowlist(runtime))
    if unknown_syscall_ids:
        sections.append(_render_unknown_syscalls(unknown_syscall_ids))
    sections.append(_render_next_steps(name))

    return "\n".join(sections).rstrip() + "\n"


def _render_what_was_generated(name: str, skipped: bool) -> str:
    if skipped:
        files = ["- `seccomp.json`", "- `README.md` (this file)"]
    else:
        files = [
            "- `Containerfile`",
            f"- `{name}.container`",
            "- `seccomp.json`",
            "- `README.md` (this file)",
        ]
    return "## What was generated\n\n" + "\n".join(files) + "\n"


def _render_audit_trail(warnings: list[str]) -> str:
    body = "## Audit trail\n\n"
    if not warnings:
        return body + "(no warnings from the analyzer)\n"
    return body + "\n".join(f"- {w}" for w in warnings) + "\n"


def _render_runtime_allowlist(runtime: PolicyRuntime) -> str:
    lines = [
        "## Runtime allowlist",
        "",
        f"- Volumes: {len(runtime.volumes)}",
    ]
    for vol in runtime.volumes:
        lines.append(f"  - `{vol.name}` -> `{vol.mount}`")
    lines.append(f"- Tmpfs: {len(runtime.tmpfs)}")
    for path in runtime.tmpfs:
        lines.append(f"  - `{path}`")
    lines.append(f"- Read-only binds: {len(runtime.binds_ro)}")
    for path in runtime.binds_ro:
        lines.append(f"  - `{path}`")
    lines.append(f"- Published ports: {len(runtime.publish_ports)}")
    for port in runtime.publish_ports:
        lines.append(f"  - `{port.host}:{port.container}/{port.proto}`")
    lines.append(f"- Added capabilities: {len(runtime.caps_add)}")
    for cap in sorted(runtime.caps_add):
        lines.append(f"  - `{cap}`")
    lines.append(f"- Seccomp syscalls allowed: {len(runtime.seccomp_syscalls)}")
    return "\n".join(lines) + "\n"


def _render_unknown_syscalls(unknown: list[int]) -> str:
    return (
        "## Unknown syscall IDs\n\n"
        "The following syscall IDs were in the policy but not in the bundled lookup "
        "table; they were dropped from the seccomp allowlist. Consider running "
        "`python sandbox/regen_syscall_table.py` to refresh:\n\n"
        + "\n".join(f"- `{sysno}`" for sysno in unknown)
        + "\n"
    )


def _render_next_steps(name: str) -> str:
    return (
        "## Next steps\n\n"
        "```sh\n"
        "# Build the image:\n"
        f"podman build -t {name}:latest .\n"
        "\n"
        "# Install seccomp profile + Quadlet unit:\n"
        "mkdir -p ~/.config/containers/seccomp ~/.config/containers/systemd\n"
        f"cp seccomp.json ~/.config/containers/seccomp/{name}.json\n"
        f"cp {name}.container ~/.config/containers/systemd/\n"
        "\n"
        "# Start under systemd --user:\n"
        "systemctl --user daemon-reload\n"
        f"systemctl --user start {name}.service\n"
        "```\n"
    )


def _render_sentinel_warning(warnings: list[str]) -> str:
    for w in warnings:
        if "sentinel" in w:
            return f"> {w}"
    return "> (sentinel warning text not found in policy.warnings)"
