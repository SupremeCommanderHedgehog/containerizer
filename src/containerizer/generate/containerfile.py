"""Render PolicyJson into a Containerfile."""

from __future__ import annotations

import json

from containerizer.analyze.schema import PolicyJson


def render_containerfile(policy: PolicyJson) -> str:
    """Render the policy as a Containerfile string with trailing newline.

    apt_packages is always `[]` in M4; no apt install layer is emitted.
    Sentinel-entrypoint policies are filtered upstream by cli.py — this
    function assumes a real entrypoint.
    """
    lines: list[str] = [
        f"FROM {policy.image.base}",
        "",
        f"COPY ./installer {policy.image.installer_path}",
        "",
    ]
    run_parts = [f"RUN {policy.image.installer_path}"]
    for path in policy.image.post_install_cleanup:
        run_parts.append(f" && rm -rf {path}")
    lines.append(" \\\n".join(run_parts))
    lines.append("")

    entrypoint = ["/sbin/init"] if policy.image.systemd_required else list(policy.image.entrypoint)
    lines.append(f"ENTRYPOINT {json.dumps(entrypoint)}")
    return "\n".join(lines) + "\n"
