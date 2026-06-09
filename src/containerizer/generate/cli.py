"""`containerizer generate <policy.json> -n <name> -o <out-dir>` Click subcommand."""

from __future__ import annotations

from pathlib import Path

import click

from containerizer.analyze.derive import SENTINEL_ENTRYPOINT
from containerizer.analyze.schema import PolicyJson
from containerizer.generate.orchestrator import generate_all


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
    policy = PolicyJson.model_validate_json(policy_path.read_text(encoding="utf-8"))
    sentinel = policy.image.entrypoint == [SENTINEL_ENTRYPOINT]

    unknown_ids = generate_all(policy, name, output_dir)

    if sentinel:
        click.echo(f"sentinel entrypoint detected — skipping Containerfile and {name}.container")

    if unknown_ids:
        click.echo(
            f"warning: syscall IDs not in bundled table "
            f"(dropped from seccomp allowlist): {unknown_ids}",
            err=True,
        )
