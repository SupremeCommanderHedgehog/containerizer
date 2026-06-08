"""`containerizer verify --original <a> --observed <b> -o <out-dir>` Click subcommand."""

from __future__ import annotations

from pathlib import Path

import click

from containerizer.analyze.schema import TraceJson
from containerizer.verify.diff import diff_traces
from containerizer.verify.writer import write_verify_json


@click.command("verify")
@click.option(
    "--original",
    "original_path",
    required=True,
    type=click.Path(exists=True, dir_okay=False, readable=True, path_type=Path),
    help="Path to the original trace.json (baseline).",
)
@click.option(
    "--observed",
    "observed_path",
    required=True,
    type=click.Path(exists=True, dir_okay=False, readable=True, path_type=Path),
    help="Path to the observed trace.json (the new run to compare).",
)
@click.option(
    "-o",
    "--output-dir",
    required=True,
    type=click.Path(path_type=Path),
    help="Directory to write verify.json to.",
)
def verify_cmd(original_path: Path, observed_path: Path, output_dir: Path) -> None:
    """Diff OBSERVED trace.json against ORIGINAL trace.json. Emit verify.json.

    Exit 0 if observed runtime is a subset of original runtime; 1 if any new
    events are present; 2 on operational errors (missing/malformed inputs).
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    original = TraceJson.model_validate_json(original_path.read_text(encoding="utf-8"))
    observed = TraceJson.model_validate_json(observed_path.read_text(encoding="utf-8"))

    report = diff_traces(original, observed)
    write_verify_json(report, output_dir / "verify.json")

    d = report.diff
    total = (
        len(d.new_paths)
        + len(d.new_ports)
        + len(d.new_caps)
        + len(d.new_syscalls)
        + len(d.new_execs)
    )
    if total == 0:
        click.echo("verify: no new events", err=True)
        return

    click.echo(
        f"verify: {len(d.new_paths)} new paths, {len(d.new_ports)} new ports, "
        f"{len(d.new_caps)} new caps, {len(d.new_syscalls)} new syscalls, "
        f"{len(d.new_execs)} new execs",
        err=True,
    )
    raise click.exceptions.Exit(1)
