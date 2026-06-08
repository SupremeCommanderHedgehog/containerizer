"""`containerizer analyze <trace-dir> -o <out-dir>` Click subcommand."""

from __future__ import annotations

from pathlib import Path

import click

from containerizer.analyze.caps import aggregate_caps
from containerizer.analyze.derive import derive_policy
from containerizer.analyze.execs import aggregate_execs
from containerizer.analyze.paths import classify_runtime
from containerizer.analyze.phases import split_phases
from containerizer.analyze.ports import aggregate_ports
from containerizer.analyze.reader import TraceBundle, read_trace_dir
from containerizer.analyze.schema import TraceJson, TracePhase
from containerizer.analyze.syscalls import aggregate_syscalls
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
    trace = _assemble_trace_json(bundle)
    policy = derive_policy(trace)
    write_trace_json(trace, output_dir / "trace.json")
    write_policy_json(policy, output_dir / "policy.json")
    click.echo(f"wrote {output_dir / 'trace.json'} and {output_dir / 'policy.json'}")


def _assemble_trace_json(bundle: TraceBundle) -> TraceJson:
    open_install, open_runtime = split_phases(
        bundle.events["open"], phase_marker_ns=bundle.phase_marker_ns, marker=bundle.marker
    )
    bind_install, bind_runtime = split_phases(
        bundle.events["bind"], phase_marker_ns=bundle.phase_marker_ns, marker=bundle.marker
    )
    sys_install, sys_runtime = split_phases(
        bundle.events["syscalls"], phase_marker_ns=bundle.phase_marker_ns, marker=bundle.marker
    )
    # connect.jsonl outbound rollup is deferred to M5 — split for symmetry's
    # sake would just produce two unused lists, so skip the call entirely.
    capable_install, capable_runtime = split_phases(
        bundle.events["capable"], phase_marker_ns=bundle.phase_marker_ns, marker=bundle.marker
    )

    warnings = list(bundle.warnings)
    # FALLBACKS reasons surface as warnings too.
    for collector, info in bundle.fallbacks.items():
        warnings.append(
            f"collector {collector}: fellback to {info.get('fallback', '?')} "
            f"(reason: {info.get('reason', '?')})"
        )

    install = TracePhase(
        duration_s=0.0,  # M3 doesn't compute durations; M5 will.
        paths=classify_runtime(open_install),  # use same classifier; install paths included
        ports=aggregate_ports(bind_install),
        outbound=[],  # outbound aggregation comes from connect runtime only in M3
        caps=aggregate_caps(capable_install),
        syscalls=aggregate_syscalls(sys_install),
        execs=aggregate_execs(sys_install),
    )
    runtime = TracePhase(
        duration_s=0.0,
        paths=classify_runtime(open_runtime),
        ports=aggregate_ports(bind_runtime),
        outbound=[],  # spec §2 defers connect_runtime outbound rollup to M5.
        caps=aggregate_caps(capable_runtime),
        syscalls=aggregate_syscalls(sys_runtime),
        execs=aggregate_execs(sys_runtime),
    )

    return TraceJson(
        phase_marker_ns=bundle.phase_marker_ns,
        marker=bundle.marker,
        install=install,
        runtime=runtime,
        warnings=warnings,
    )
