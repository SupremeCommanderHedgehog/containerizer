"""`containerizer analyze <trace-dir> -o <out-dir>` Click subcommand."""

from __future__ import annotations

from pathlib import Path

import click

from containerizer.analyze.assemble import assemble_trace_json
from containerizer.analyze.derive import derive_policy
from containerizer.analyze.reader import read_install_inputs, read_trace_dir
from containerizer.analyze.writer import write_policy_json, write_trace_json


@click.command("analyze")
@click.argument(
    "trace_dir",
    type=click.Path(exists=True, file_okay=False, dir_okay=True, readable=True, path_type=Path),
)
@click.option(
    "-o",
    "--output-dir",
    required=True,
    type=click.Path(path_type=Path),
    help="Directory the trace.json and policy.json are written to.",
)
def analyze_cmd(trace_dir: Path, output_dir: Path) -> None:
    """Analyze TRACE_DIR (produced by `containerizer trace`) and emit
    trace.json + policy.json."""
    output_dir.mkdir(parents=True, exist_ok=True)
    bundle = read_trace_dir(trace_dir)
    trace = assemble_trace_json(bundle)
    install_inputs = read_install_inputs(trace_dir)
    policy = derive_policy(
        trace,
        install_inputs=install_inputs,
        warnings=list(trace.warnings),
    )
    write_trace_json(trace, output_dir / "trace.json")
    write_policy_json(policy, output_dir / "policy.json")
    click.echo(f"wrote {output_dir / 'trace.json'} and {output_dir / 'policy.json'}")
