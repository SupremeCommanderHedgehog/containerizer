"""Containerizer CLI entry point."""

from __future__ import annotations

from pathlib import Path

import click

from containerizer import __version__
from containerizer.probe.installer import UnsupportedInstallerKind
from containerizer.probe.installer import probe as probe_installer


@click.group()
@click.version_option(__version__, prog_name="containerizer")
def main() -> None:
    """Trace-and-learn containerizer."""


@main.command("probe")
@click.argument(
    "installer",
    type=click.Path(exists=True, dir_okay=False, path_type=Path, readable=True),
)
@click.option(
    "-o",
    "--output",
    type=click.Path(dir_okay=False, path_type=Path, writable=True),
    default=None,
    help="Write probe JSON to this file instead of stdout.",
)
def probe_cmd(installer: Path, output: Path | None) -> None:
    """Statically analyse INSTALLER and emit a probe JSON document."""
    try:
        result = probe_installer(installer)
    except UnsupportedInstallerKind as exc:
        raise click.ClickException(str(exc)) from exc
    payload = result.model_dump_json(indent=2)
    if output is None:
        click.echo(payload)
    else:
        output.write_text(payload + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
