"""`containerizer generate <policy.json> -n <name> -o <out-dir>` Click subcommand."""

from __future__ import annotations

from pathlib import Path

import click

from containerizer.analyze.schema import PolicyJson
from containerizer.generate.containerfile import render_containerfile
from containerizer.generate.quadlet import render_quadlet
from containerizer.generate.readme import render_readme
from containerizer.generate.seccomp import render_seccomp

SENTINEL_ENTRYPOINT = "__UNSET__"


@click.command("generate")
@click.argument(
    "policy_path",
    type=click.Path(exists=True, dir_okay=False, readable=True, path_type=Path),
)
@click.option(
    "-n",
    "--name",
    required=True,
    help="Short name for the generated unit (used in filenames and Quadlet identifiers).",
)
@click.option(
    "-o",
    "--output-dir",
    required=True,
    type=click.Path(path_type=Path),
    help="Directory to write the generated artifacts to.",
)
def generate_cmd(policy_path: Path, name: str, output_dir: Path) -> None:
    """Render Containerfile + Quadlet + seccomp + README from POLICY_PATH."""
    output_dir.mkdir(parents=True, exist_ok=True)
    policy = PolicyJson.model_validate_json(policy_path.read_text(encoding="utf-8"))
    sentinel = policy.image.entrypoint == [SENTINEL_ENTRYPOINT]

    seccomp_bytes, unknown_ids = render_seccomp(policy)
    (output_dir / "seccomp.json").write_bytes(seccomp_bytes)

    readme = render_readme(policy, name, skipped=sentinel, unknown_syscall_ids=unknown_ids)
    (output_dir / "README.md").write_text(readme, encoding="utf-8")

    if sentinel:
        click.echo(f"sentinel entrypoint detected — skipping Containerfile and {name}.container")
    else:
        (output_dir / "Containerfile").write_text(render_containerfile(policy), encoding="utf-8")
        (output_dir / f"{name}.container").write_text(
            render_quadlet(policy, name), encoding="utf-8"
        )

    if unknown_ids:
        click.echo(
            f"warning: syscall IDs not in bundled table "
            f"(dropped from seccomp allowlist): {unknown_ids}",
            err=True,
        )
