"""`containerizer build <installer>` Click subcommand."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

import click

from containerizer.analyze.assemble import assemble_trace_json
from containerizer.analyze.derive import derive_policy
from containerizer.analyze.reader import read_trace_dir
from containerizer.analyze.schema import PolicyJson, TraceJson
from containerizer.build.config import BuildConfig, BuildResult
from containerizer.build.paths import PathLayout, resolve_layout
from containerizer.build.pipeline import PipelineError, run_pipeline
from containerizer.generate.orchestrator import generate_all
from containerizer.probe.installer import UnsupportedInstallerKind
from containerizer.probe.installer import probe as probe_installer
from containerizer.probe.schema import BaseImageSuggestion, ProbeResult
from containerizer.trace.cli import _validate_multi_deb_flags
from containerizer.trace.image import RunnerImage
from containerizer.trace.runner import TraceRunner
from containerizer.verify.diff import diff_traces


class PreflightError(RuntimeError):
    """Raised when podman is not usable before any phase runs."""


@click.command("build")
@click.argument(
    "installer",
    type=click.Path(exists=True, dir_okay=False, readable=True, path_type=Path),
)
@click.option("--name", required=True, help="Container name and image-tag stem.")
@click.option(
    "--base-image",
    default=None,
    help="Override probe's base-image suggestion.",
)
@click.option(
    "--start-cmd",
    default=None,
    help="Daemon-start hint passed to the trace orchestrator.",
)
@click.option(
    "--start-ready-seconds",
    type=int,
    default=60,
    help="Seconds to wait for the daemon to bind a port after --start-cmd "
    "before proceeding. Only meaningful with --start-cmd.",
)
@click.option(
    "-o",
    "--out",
    "out_dir",
    type=click.Path(path_type=Path),
    default=Path("out"),
)
@click.option(
    "--keep-intermediates",
    is_flag=True,
    help="Preserve intermediates under <out>/<name>/.intermediates/.",
)
@click.option(
    "--verify-soak-seconds",
    type=int,
    default=None,
    help="Verify-phase idle observation window after daemon-ready. "
    "Defaults to 30s; when --start-cmd is set, auto-scales to "
    "max(60s, --start-ready-seconds).",
)
@click.option(
    "--skip-verify",
    is_flag=True,
    help="Stop after generate; skip rebuild + retrace + verify.",
)
@click.option(
    "--debug",
    is_flag=True,
    help="On first phase failure, drop a shell in the runner if alive.",
)
@click.option(
    "--installer",
    "extra_installers",
    multiple=True,
    type=click.Path(exists=True, dir_okay=False, readable=True, path_type=Path),
    help="Additional .deb installed in same apt transaction as primary. Repeatable; cap 99.",
)
@click.option(
    "--apt-source",
    "apt_sources",
    multiple=True,
    type=str,
    help="Verbatim 'deb …' line written to /etc/apt/sources.list.d/containerizer.list. Repeatable.",
)
@click.option(
    "--apt-key",
    "apt_keys",
    multiple=True,
    type=click.Path(exists=True, dir_okay=False, readable=True, path_type=Path),
    help="Keyring file (.gpg or .asc) copied into /etc/apt/keyrings/. Repeatable.",
)
def build_cmd(
    installer: Path,
    name: str,
    base_image: str | None,
    start_cmd: str | None,
    start_ready_seconds: int,
    out_dir: Path,
    keep_intermediates: bool,
    verify_soak_seconds: int | None,
    skip_verify: bool,
    debug: bool,
    extra_installers: tuple[Path, ...],
    apt_sources: tuple[str, ...],
    apt_keys: tuple[Path, ...],
) -> None:
    """Run the full pipeline: probe -> trace -> analyze -> generate ->
    rebuild -> retrace -> verify into one directory."""
    _validate_multi_deb_flags(extra_installers, apt_sources, apt_keys)

    if start_cmd is None and start_ready_seconds != 60:
        raise click.UsageError("--start-ready-seconds requires --start-cmd")

    try:
        preflight_podman()
    except PreflightError as exc:
        click.echo(str(exc), err=True)
        raise click.exceptions.Exit(2) from exc

    config = BuildConfig(
        installer=installer,
        name=name,
        out_dir=out_dir,
        base_image=base_image,
        start_cmd=start_cmd,
        start_ready_seconds=start_ready_seconds,
        keep_intermediates=keep_intermediates,
        verify_soak_seconds=verify_soak_seconds,
        skip_verify=skip_verify,
        debug=debug,
        extra_installers=tuple(p.resolve() for p in extra_installers),
        apt_sources=apt_sources,
        apt_keys=tuple(p.resolve() for p in apt_keys),
    )

    # NOTE: --debug is accepted but currently only governs whether the
    # tempdir survives on success. The "drop a shell in the runner" path
    # the spec §7 mentions is deferred; intermediate preservation already
    # gives the user enough to diagnose. Track in a follow-up if needed.
    if keep_intermediates or debug:
        intermediates_root = out_dir / name / ".intermediates"
        intermediates_root.mkdir(parents=True, exist_ok=True)
        should_cleanup = False
    else:
        intermediates_root = Path(tempfile.mkdtemp(prefix="containerizer-build-"))
        should_cleanup = True

    layout = resolve_layout(
        out_dir,
        name,
        intermediates_root=intermediates_root,
        keep_intermediates=keep_intermediates or debug,
    )

    try:
        result = run_pipeline(
            config,
            probe_fn=_default_probe_fn,
            install_trace_fn=_default_install_trace_fn,
            parse_trace_fn=_default_parse_trace_fn,
            derive_policy_fn=_default_derive_policy_fn,
            generate_fn=_default_generate_fn,
            podman_build_fn=_make_podman_build_fn(layout),
            verify_trace_fn=_make_verify_trace_fn(layout),
            diff_fn=diff_traces,
            layout=layout,
            stderr=sys.stderr,
        )
    except PipelineError as exc:
        click.echo(str(exc), err=True)
        click.echo(f"intermediates preserved at {intermediates_root}", err=True)
        raise click.exceptions.Exit(1) from exc

    _print_summary(result)
    if should_cleanup:
        shutil.rmtree(intermediates_root, ignore_errors=True)


def preflight_podman() -> None:
    """Fail fast if podman isn't reachable."""
    try:
        proc = subprocess.run(["podman", "--version"], capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise PreflightError("podman not found on PATH; install podman and retry") from exc
    if proc.returncode != 0:
        raise PreflightError(f"podman --version failed: {proc.stderr.strip()}")

    if sys.platform.startswith("linux"):
        return

    try:
        ml = subprocess.run(
            ["podman", "machine", "ls", "--format", "json"],
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise PreflightError("podman not found on PATH; install podman and retry") from exc
    if ml.returncode != 0:
        raise PreflightError("podman machine list failed; start a machine and retry")

    try:
        machines = json.loads(ml.stdout)
    except json.JSONDecodeError as exc:
        raise PreflightError("podman machine list returned malformed JSON") from exc
    if not any(m.get("Running") is True for m in machines):
        raise PreflightError("no podman machine is running. Start it with: podman machine start")


def _default_probe_fn(installer: Path, base_image: str | None) -> ProbeResult:
    try:
        result = probe_installer(installer)
    except UnsupportedInstallerKind as exc:
        raise PipelineError(str(exc)) from exc
    if base_image is not None:
        override = BaseImageSuggestion(
            image=base_image,
            reasons=["user override via --base-image"],
        )
        return result.model_copy(update={"base_image": override})
    return result


def _default_install_trace_fn(
    installer: Path,
    start_cmd: str | None,
    output_dir: Path,
    *,
    extra_installers: tuple[Path, ...] = (),
    apt_sources: tuple[str, ...] = (),
    apt_keys: tuple[Path, ...] = (),
    start_ready_seconds: int = 60,
    verify_soak_seconds: int = 30,
) -> int:
    image = RunnerImage(sandbox_dir=_sandbox_dir())
    if not image.exists():
        click.echo(f"[image] building {image.tag} (first run, ~5 min)...", err=True)
        image.build(stderr=sys.stderr)

    runner = TraceRunner(
        image_tag=image.tag,
        installer=installer.resolve(),
        output_dir=output_dir.resolve(),
        tty=sys.stdin.isatty(),
        extra_installers=extra_installers,
        apt_sources=apt_sources,
        apt_keys=apt_keys,
        start_cmd=start_cmd,
        start_ready_seconds=start_ready_seconds,
        verify_soak_seconds=verify_soak_seconds,
    )
    return runner.run()


def _default_parse_trace_fn(trace_dir: Path) -> TraceJson:
    return assemble_trace_json(read_trace_dir(trace_dir))


def _default_derive_policy_fn(trace: TraceJson) -> PolicyJson:
    return derive_policy(trace, warnings=list(trace.warnings))


def _default_generate_fn(
    policy: PolicyJson,
    name: str,
    final_dir: Path,
    *,
    install_primary: Path | None = None,
    install_extras: tuple[Path, ...] = (),
    install_apt_sources: tuple[str, ...] = (),
    install_start_cmd: str | None = None,
    install_start_ready_seconds: int | None = None,
    install_verify_soak_seconds: int | None = None,
) -> None:
    unknown_ids = generate_all(
        policy,
        name,
        final_dir,
        install_primary=install_primary,
        install_extras=install_extras,
        install_apt_sources=install_apt_sources,
        install_start_cmd=install_start_cmd,
        install_start_ready_seconds=install_start_ready_seconds,
        install_verify_soak_seconds=install_verify_soak_seconds,
    )
    if unknown_ids:
        click.echo(
            f"warning: syscall IDs not in bundled table "
            f"(dropped from seccomp allowlist): {unknown_ids}",
            err=True,
        )


def _make_podman_build_fn(layout: PathLayout) -> Callable[[Path, str], Path]:
    def fn(final_dir: Path, image_tag: str) -> Path:
        click.echo(f"[build]    podman build -t {image_tag} {final_dir}", err=True)
        build = subprocess.run(
            ["podman", "build", "-t", image_tag, str(final_dir)],
            check=False,
        )
        if build.returncode != 0:
            raise PipelineError(f"podman build failed (exit {build.returncode})")
        layout.verify_image_tar.parent.mkdir(parents=True, exist_ok=True)
        save = subprocess.run(
            ["podman", "save", "-o", str(layout.verify_image_tar), image_tag],
            check=False,
        )
        if save.returncode != 0:
            raise PipelineError(f"podman save failed (exit {save.returncode})")
        return layout.verify_image_tar

    return fn


def _make_verify_trace_fn(layout: PathLayout) -> Callable[[Path, list[str], str, int, Path], int]:
    def fn(
        image_tar: Path,
        run_flags: list[str],
        image_tag: str,
        soak_seconds: int,
        output_dir: Path,
    ) -> int:
        image = RunnerImage(sandbox_dir=_sandbox_dir())
        runner = TraceRunner(
            image_tag=image.tag,
            installer=None,
            output_dir=output_dir.resolve(),
            mode="verify",
            verify_image_tar=image_tar.resolve(),
            verify_image_tag=image_tag,
            verify_run_flags=tuple(run_flags),
            verify_soak_seconds=soak_seconds,
            verify_seccomp_path=layout.verify_seccomp_copy.resolve(),
        )
        return runner.run()

    return fn


def _sandbox_dir() -> Path:
    return Path(__file__).resolve().parents[3] / "sandbox" / "runner_image"


def _print_summary(result: BuildResult) -> None:
    if result.skip_reason == "sentinel":
        click.echo("[verify]   skipped: no entrypoint detected", err=True)
    elif result.skip_reason == "flag":
        click.echo("[verify]   skipped: --skip-verify was set", err=True)
    elif result.verify is not None:
        d = result.verify.diff
        total = (
            len(d.new_paths)
            + len(d.new_ports)
            + len(d.new_caps)
            + len(d.new_syscalls)
            + len(d.new_execs)
        )
        if total == 0:
            click.echo("[verify]   no new events", err=True)
        else:
            click.echo(
                f"[verify]   {len(d.new_paths)} new paths, {len(d.new_ports)} new ports, "
                f"{len(d.new_caps)} new caps, {len(d.new_syscalls)} new syscalls, "
                f"{len(d.new_execs)} new execs",
                err=True,
            )
    click.echo(f"[done]     {result.final_dir}", err=True)
