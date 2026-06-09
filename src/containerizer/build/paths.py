"""Resolve per-phase paths for a single `build` invocation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PathLayout:
    """Every path the orchestrator needs, resolved from (out, name, flags)."""

    final_dir: Path
    intermediates_dir: Path
    probe_json: Path
    trace_original_dir: Path
    trace_verify_dir: Path
    analyze_trace_json: Path
    analyze_policy_json: Path
    analyze_verify_trace_json: Path
    verify_image_tar: Path
    verify_seccomp_copy: Path
    final_containerfile: Path
    final_quadlet: Path
    final_seccomp: Path
    final_readme: Path
    final_verify_json: Path


def resolve_layout(
    out: Path,
    name: str,
    *,
    intermediates_root: Path,
    keep_intermediates: bool,
) -> PathLayout:
    """Compute the per-phase path layout.

    `intermediates_root` is honored only when `keep_intermediates` is False;
    otherwise intermediates live under `final_dir / ".intermediates"` so they
    survive successful runs.
    """
    final_dir = out / name
    intermediates_dir = final_dir / ".intermediates" if keep_intermediates else intermediates_root

    return PathLayout(
        final_dir=final_dir,
        intermediates_dir=intermediates_dir,
        probe_json=intermediates_dir / "probe.json",
        trace_original_dir=intermediates_dir / "trace" / "original",
        trace_verify_dir=intermediates_dir / "trace" / "verify",
        analyze_trace_json=intermediates_dir / "analyze" / "trace.json",
        analyze_policy_json=intermediates_dir / "analyze" / "policy.json",
        analyze_verify_trace_json=intermediates_dir / "analyze" / "verify-trace.json",
        verify_image_tar=intermediates_dir / "verify" / "image.tar",
        verify_seccomp_copy=intermediates_dir / "verify" / "seccomp.json",
        final_containerfile=final_dir / "Containerfile",
        final_quadlet=final_dir / f"{name}.container",
        final_seccomp=final_dir / "seccomp.json",
        final_readme=final_dir / "README.md",
        final_verify_json=final_dir / "verify.json",
    )
