"""`containerizer trace <installer> -o <out>` Click subcommand."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import click

from containerizer.trace.image import RunnerImage
from containerizer.trace.runner import OutputDirNotEmpty, TraceRunner


def _sandbox_dir() -> Path:
    """Resolve sandbox/runner_image/ relative to the source tree.

    Assumes editable install (`pip install -e .`) so the runner image source
    is at <repo>/sandbox/runner_image/. Wheel-install support is out of M2.
    """
    return Path(__file__).resolve().parents[3] / "sandbox" / "runner_image"


def _podman_machine_is_running() -> bool:
    """Return True iff podman is usable.

    On Linux, podman runs natively and there is no "machine" — return True if
    the `podman` binary is on PATH (the actual usability check happens when
    podman is invoked later). On Windows / macOS, podman runs inside a
    Podman Desktop machine, so check that at least one machine reports
    State=Running.
    """
    if sys.platform.startswith("linux"):
        try:
            subprocess.run(
                ["podman", "--version"],
                check=False,
                capture_output=True,
                text=True,
            )
        except FileNotFoundError:
            return False
        return True

    try:
        result = subprocess.run(
            ["podman", "machine", "ls", "--format", "json"],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return False
    if result.returncode != 0:
        return False
    try:
        machines = json.loads(result.stdout)
    except json.JSONDecodeError:
        return False
    return any(m.get("Running") is True for m in machines)


@click.command("trace")
@click.argument(
    "installer",
    type=click.Path(exists=True, dir_okay=False, readable=True, path_type=Path),
)
@click.option(
    "-o",
    "--output-dir",
    required=True,
    type=click.Path(path_type=Path),
    help="Directory the trace JSONL streams + install.log + markers are written to.",
)
@click.option(
    "--force",
    is_flag=True,
    help="Overwrite output-dir if it already contains a COMPLETE / PARTIAL marker.",
)
def trace_cmd(installer: Path, output_dir: Path, force: bool) -> None:
    """Run INSTALLER inside the trace sandbox and capture observations."""
    if not _podman_machine_is_running():
        raise click.ClickException(
            "Podman machine is not running. Start it with: podman machine start"
        )

    output_dir.mkdir(parents=True, exist_ok=True)

    image = RunnerImage(sandbox_dir=_sandbox_dir())
    if not image.exists():
        click.echo(f"[image] building {image.tag} (first run, ~5 min)...", err=True)
        image.build(stderr=sys.stderr)

    runner = TraceRunner(
        image_tag=image.tag,
        installer=installer.resolve(),
        output_dir=output_dir.resolve(),
        # #95: propagate the host's actual stdin TTY status. Without this
        # runner.py defaults self.tty to False, sets
        # CONTAINERIZER_INTERACTIVE=0 in the container, and the orchestrator
        # under systemd-PID-1 takes the non-interactive branch even when the
        # user is sitting at a terminal -- which means bash auto-redirects
        # the backgrounded installer's stdin to /dev/null and Y/N prompts
        # (example-app etc.) abort with empty input. build/cli.py already wires
        # this; trace/cli.py was the asymmetric path.
        tty=sys.stdin.isatty(),
    )
    try:
        runner.validate_output_dir(force=force)
    except OutputDirNotEmpty as exc:
        raise click.ClickException(str(exc)) from exc

    exit_code = runner.run()
    _print_summary(output_dir, exit_code=exit_code)


def _print_summary(output_dir: Path, *, exit_code: int) -> None:
    """Post-run summary: marker + per-collector counts + fallback notice."""
    complete = (output_dir / "COMPLETE").exists()
    partial = (output_dir / "PARTIAL").exists()
    if not complete and not partial:
        raise click.ClickException(
            f"Trace did not finalise. Inspect {output_dir}/install.log and "
            f"{output_dir}/*.err for collector errors."
        )

    marker = "COMPLETE" if complete else "PARTIAL"
    click.echo(f"marker: {marker}")
    for name in ("open", "bind", "connect", "accept", "syscalls", "capable"):
        path = output_dir / f"{name}.jsonl"
        count = sum(1 for _ in path.open()) if path.exists() else 0
        click.echo(f"{name:<10}{count:>10} events")
    click.echo(f"trace at {output_dir}  (next: containerizer analyze, not yet implemented)")

    fallbacks = output_dir / "FALLBACKS.json"
    if fallbacks.exists() and fallbacks.stat().st_size > 0:
        click.echo("")
        click.echo("WARNING: one or more collectors fell back to strace:", err=True)
        click.echo(fallbacks.read_text(encoding="utf-8"), err=True)

    if exit_code != 0:
        # Under systemd-PID-1 (#90) the container exit code reflects whatever
        # signal systemd-shutdown took to power off (commonly 130 SIGINT or
        # 143 SIGTERM), not the orchestrator's success. The marker is the
        # source of truth; surface the code as diagnostic noise rather than
        # erroring out when the orchestrator finalised cleanly.
        click.echo(
            f"NOTE: podman exited with code {exit_code} (marker {marker}); "
            f"treating marker as authoritative.",
            err=True,
        )
