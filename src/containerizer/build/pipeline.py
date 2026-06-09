"""Compose the 7 (or 8, counting analyze-twice) build phases.

The pipeline owns intermediate-JSON persistence and the final-artifact
write paths (verify.json, the rewritten README). It does not parse Click
flags, create the tempdir, or render the stderr line-by-line summary --
build/cli.py does that around it.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Literal, TextIO

from containerizer.analyze.derive import SENTINEL_ENTRYPOINT
from containerizer.analyze.schema import PolicyJson, TraceJson
from containerizer.analyze.writer import write_policy_json, write_trace_json
from containerizer.build.config import BuildConfig, BuildResult
from containerizer.build.flags import podman_run_flags
from containerizer.build.paths import PathLayout
from containerizer.build.readme import rewrite_readme_with_verify
from containerizer.probe.schema import ProbeResult
from containerizer.verify.schema import VerifyReport
from containerizer.verify.writer import write_verify_json


class PipelineError(RuntimeError):
    """Raised when a phase fails in a way the orchestrator cannot recover from."""


def run_pipeline(
    config: BuildConfig,
    *,
    probe_fn: Callable[[Path, str | None], ProbeResult],
    install_trace_fn: Callable[[Path, str | None, Path], int],
    parse_trace_fn: Callable[[Path], TraceJson],
    derive_policy_fn: Callable[[TraceJson], PolicyJson],
    generate_fn: Callable[[PolicyJson, str, Path], None],
    podman_build_fn: Callable[[Path, str], Path],
    verify_trace_fn: Callable[[Path, list[str], str, int, Path], int],
    diff_fn: Callable[[TraceJson, TraceJson], VerifyReport],
    layout: PathLayout,
    stderr: TextIO,
) -> BuildResult:
    """Run the M6 build pipeline. Raises PipelineError on unrecoverable failures."""
    warnings: list[str] = []

    # 1. probe
    _say(stderr, "[probe]    probing installer")
    probe = probe_fn(config.installer, config.base_image)
    layout.probe_json.parent.mkdir(parents=True, exist_ok=True)
    layout.probe_json.write_text(probe.model_dump_json(indent=2) + "\n", encoding="utf-8")

    # 2. install trace
    _say(stderr, "[trace]    running installer trace")
    layout.trace_original_dir.mkdir(parents=True, exist_ok=True)
    install_trace_fn(config.installer, config.start_cmd, layout.trace_original_dir)
    marker = _read_install_marker(layout.trace_original_dir)
    if marker == "PARTIAL":
        warnings.append("install trace finalised as PARTIAL")

    # 3. analyze original
    _say(stderr, "[analyze]  parsing original trace")
    original_trace = parse_trace_fn(layout.trace_original_dir)
    layout.analyze_trace_json.parent.mkdir(parents=True, exist_ok=True)
    write_trace_json(original_trace, layout.analyze_trace_json)

    policy = derive_policy_fn(original_trace)
    write_policy_json(policy, layout.analyze_policy_json)

    # 4. generate
    _say(stderr, f"[generate] writing artifacts to {layout.final_dir}")
    layout.final_dir.mkdir(parents=True, exist_ok=True)
    generate_fn(policy, config.name, layout.final_dir)

    # 4a. sentinel
    if policy.image.entrypoint == [SENTINEL_ENTRYPOINT]:
        _rewrite_readme(layout.final_readme, verify=None, skip_reason="sentinel")
        return BuildResult(
            final_dir=layout.final_dir,
            intermediates_dir=layout.intermediates_dir,
            verify=None,
            skip_reason="sentinel",
            warnings=warnings,
        )

    # 4b. --skip-verify
    if config.skip_verify:
        _rewrite_readme(layout.final_readme, verify=None, skip_reason="flag")
        return BuildResult(
            final_dir=layout.final_dir,
            intermediates_dir=layout.intermediates_dir,
            verify=None,
            skip_reason="flag",
            warnings=warnings,
        )

    # 5. podman build + save
    image_tag = f"{config.name}:m6-verify"
    _say(stderr, f"[build]    podman build {layout.final_dir} -> {image_tag}")
    image_tar = podman_build_fn(layout.final_dir, image_tag)

    # 5a. copy seccomp into the bind-mount source
    layout.verify_seccomp_copy.parent.mkdir(parents=True, exist_ok=True)
    layout.verify_seccomp_copy.write_bytes(layout.final_seccomp.read_bytes())

    # 6. verify trace
    _say(
        stderr,
        f"[verify]   running generated image under strict policy "
        f"(soak {config.verify_soak_seconds}s)",
    )
    layout.trace_verify_dir.mkdir(parents=True, exist_ok=True)
    run_flags = podman_run_flags(policy)
    verify_trace_fn(
        image_tar,
        run_flags,
        image_tag,
        config.verify_soak_seconds,
        layout.trace_verify_dir,
    )

    verify_marker = _read_verify_marker(layout.trace_verify_dir)
    if verify_marker == "LOAD_FAILED":
        raise PipelineError(
            f"podman load failed inside the verify sandbox; see {layout.trace_verify_dir}"
        )
    if verify_marker == "READY_FAILED":
        raise PipelineError(
            "generated container failed to come up under strict policy; "
            f"see {layout.trace_verify_dir}"
        )
    if verify_marker == "RAN_AND_DIED":
        warnings.append(
            "verify-mode container RAN_AND_DIED: the daemon exited during soak; "
            "see verify.json for syscall denials and consider widening policy"
        )

    # 7. analyze verify
    verify_trace = parse_trace_fn(layout.trace_verify_dir)
    write_trace_json(verify_trace, layout.analyze_verify_trace_json)

    # 7a. diff
    report = diff_fn(original_trace, verify_trace)
    write_verify_json(report, layout.final_verify_json)

    # 7b. README rewrite
    _rewrite_readme(layout.final_readme, verify=report, skip_reason=None)

    return BuildResult(
        final_dir=layout.final_dir,
        intermediates_dir=layout.intermediates_dir,
        verify=report,
        skip_reason=None,
        warnings=warnings,
    )


def _say(stderr: TextIO, msg: str) -> None:
    stderr.write(msg + "\n")


def _read_install_marker(trace_dir: Path) -> Literal["COMPLETE", "PARTIAL"]:
    if (trace_dir / "COMPLETE").exists():
        return "COMPLETE"
    if (trace_dir / "PARTIAL").exists():
        return "PARTIAL"
    raise PipelineError(
        f"install trace did not finalise (no COMPLETE or PARTIAL marker) at {trace_dir}"
    )


def _read_verify_marker(
    trace_dir: Path,
) -> Literal["LOAD_FAILED", "READY_FAILED", "RAN_AND_DIED", "COMPLETE"]:
    # Precedence matters: RAN_AND_DIED scenarios also write COMPLETE, so we
    # must check RAN_AND_DIED before COMPLETE. LOAD_FAILED and READY_FAILED
    # are exclusive (they suppress COMPLETE) but ordered first for clarity.
    for marker in ("LOAD_FAILED", "READY_FAILED", "RAN_AND_DIED", "COMPLETE"):
        if (trace_dir / marker).exists():
            return marker
    raise PipelineError(f"verify trace did not finalise (no recognized marker) at {trace_dir}")


def _rewrite_readme(
    path: Path,
    *,
    verify: VerifyReport | None,
    skip_reason: Literal["sentinel", "flag"] | None,
) -> None:
    # Spec §7: README missing or unparseable -> raise so the caller can
    # surface "verify.json was written but README rewrite failed". The
    # generate phase wrote README, so a missing file here means something
    # external deleted it between phases -- worth a clear error.
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise PipelineError(
            f"README rewrite failed: {path} not found. "
            "verify.json was written but the Verify results section could not be appended; "
            "rerun build or hand-edit README."
        ) from exc
    new_text = rewrite_readme_with_verify(text, verify=verify, skip_reason=skip_reason)
    path.write_text(new_text, encoding="utf-8")
