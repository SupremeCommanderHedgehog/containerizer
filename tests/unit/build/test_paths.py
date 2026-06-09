"""Layout resolution for build's per-phase paths (tempdir vs --keep-intermediates)."""

from __future__ import annotations

from pathlib import Path

from containerizer.build.paths import PathLayout, resolve_layout


def test_resolve_layout_default_uses_passed_intermediates_root() -> None:
    out = Path("/out")
    intermediates_root = Path("/tmp/build-xyz")
    layout = resolve_layout(
        out, "demo", intermediates_root=intermediates_root, keep_intermediates=False
    )

    assert layout.final_dir == Path("/out/demo")
    assert layout.intermediates_dir == intermediates_root
    assert layout.probe_json == Path("/tmp/build-xyz/probe.json")
    assert layout.trace_original_dir == Path("/tmp/build-xyz/trace/original")
    assert layout.trace_verify_dir == Path("/tmp/build-xyz/trace/verify")
    assert layout.analyze_trace_json == Path("/tmp/build-xyz/analyze/trace.json")
    assert layout.analyze_policy_json == Path("/tmp/build-xyz/analyze/policy.json")
    assert layout.analyze_verify_trace_json == Path("/tmp/build-xyz/analyze/verify-trace.json")
    assert layout.verify_image_tar == Path("/tmp/build-xyz/verify/image.tar")
    assert layout.verify_seccomp_copy == Path("/tmp/build-xyz/verify/seccomp.json")
    assert layout.final_containerfile == Path("/out/demo/Containerfile")
    assert layout.final_quadlet == Path("/out/demo/demo.container")
    assert layout.final_seccomp == Path("/out/demo/seccomp.json")
    assert layout.final_readme == Path("/out/demo/README.md")
    assert layout.final_verify_json == Path("/out/demo/verify.json")


def test_resolve_layout_keep_intermediates_routes_to_final_dir() -> None:
    layout = resolve_layout(
        Path("/out"), "demo", intermediates_root=Path("/ignored"), keep_intermediates=True
    )

    assert layout.intermediates_dir == Path("/out/demo/.intermediates")
    assert layout.probe_json == Path("/out/demo/.intermediates/probe.json")
    assert layout.trace_original_dir == Path("/out/demo/.intermediates/trace/original")
    assert layout.trace_verify_dir == Path("/out/demo/.intermediates/trace/verify")
    assert layout.verify_image_tar == Path("/out/demo/.intermediates/verify/image.tar")
    # Final dir paths are unaffected by keep_intermediates.
    assert layout.final_dir == Path("/out/demo")
    assert layout.final_verify_json == Path("/out/demo/verify.json")


def test_resolve_layout_is_pure() -> None:
    a = resolve_layout(
        Path("/out"), "demo", intermediates_root=Path("/tmp/build-xyz"), keep_intermediates=False
    )
    b = resolve_layout(
        Path("/out"), "demo", intermediates_root=Path("/tmp/build-xyz"), keep_intermediates=False
    )
    assert a == b
    assert isinstance(a, PathLayout)
