"""Render PolicyJson into a Containerfile."""

from __future__ import annotations

import json

from containerizer.analyze.schema import DebInstaller, PolicyJson


def render_containerfile(policy: PolicyJson) -> str:
    """Render the policy as a Containerfile string with trailing newline.

    Dispatches on installer.kind: DebInstaller emits an apt-install layer
    that copies the .debs and any apt-keys/apt-sources; ExecutableInstaller
    emits the legacy single-executable RUN line.

    Sentinel-entrypoint policies are filtered upstream by cli.py — this
    function assumes a real entrypoint.
    """
    if isinstance(policy.image.installer, DebInstaller):
        return _render_deb(policy)
    return _render_executable(policy)


def _render_executable(policy: PolicyJson) -> str:
    lines: list[str] = [
        f"FROM {policy.image.base}",
        "",
        "COPY ./installer /installer",
        "",
    ]
    run_parts = ["RUN /installer"]
    for path in policy.image.post_install_cleanup:
        run_parts.append(f" && rm -rf {path}")
    lines.append(" \\\n".join(run_parts))
    lines.append("")
    lines.append(_entrypoint_line(policy))
    return "\n".join(lines) + "\n"


def _render_deb(policy: PolicyJson) -> str:
    assert isinstance(policy.image.installer, DebInstaller)  # for type narrowing
    image = policy.image
    deb_paths = image.installer.paths

    lines: list[str] = [
        f"FROM {image.base}",
        "ENV DEBIAN_FRONTEND=noninteractive",
        "",
    ]

    # apt-keys block (only when keys are present).
    if image.apt_keys:
        for key in image.apt_keys:
            lines.append(f"COPY ./apt-keys/{key} /etc/apt/keyrings/{key}")
        lines.append("")

    # sources block (only when sources are present).
    if image.apt_sources:
        sources_body = "\n".join(image.apt_sources)
        lines.append(
            "RUN install -d /etc/apt/sources.list.d \\\n"
            " && cat > /etc/apt/sources.list.d/containerizer.list <<'EOF'\n"
            f"{sources_body}\n"
            "EOF"
        )
        lines.append("")

    # Each .deb gets its own COPY line.
    for deb_path in deb_paths:
        basename = deb_path.rsplit("/", 1)[-1]
        lines.append(f"COPY ./installers/{basename} {deb_path}")
    lines.append("")

    # apt-get update && install + cleanup.
    install_target_lines = " \\\n      ".join(deb_paths)
    cleanup = " ".join(policy.image.post_install_cleanup)
    lines.append(
        "RUN set -eux \\\n"
        " && apt-get update \\\n"
        " && apt-get install -y --no-install-recommends \\\n"
        f"      {install_target_lines} \\\n"
        f" && rm -rf {cleanup}"
    )
    lines.append("")

    lines.append(_entrypoint_line(policy))
    return "\n".join(lines) + "\n"


def _entrypoint_line(policy: PolicyJson) -> str:
    entrypoint = (
        ["/sbin/init"] if policy.image.systemd_required else list(policy.image.entrypoint)
    )
    return f"ENTRYPOINT {json.dumps(entrypoint)}"
