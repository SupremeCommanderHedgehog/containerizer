"""Containerizer CLI entry point."""

import click

from containerizer import __version__


@click.group()
@click.version_option(__version__, prog_name="containerizer")
def main() -> None:
    """Trace-and-learn containerizer."""


if __name__ == "__main__":
    main()
