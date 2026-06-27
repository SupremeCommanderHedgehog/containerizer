"""run_pipeline composition tests with fakes injected via the §5.6 seam."""

from __future__ import annotations

import io
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

from containerizer.analyze.derive import SENTINEL_ENTRYPOINT
from containerizer.analyze.schema import (
    ExecutableInstaller,
    PolicyImage,
    PolicyJson,
    PolicyRuntime,
    TraceJson,
    TracePhase,
)
from containerizer.build.config import BuildConfig
from containerizer.build.paths import PathLayout, resolve_layout
from containerizer.build.pipeline import (
    PipelineError,
    _stage_install_inputs,
    run_pipeline,
)
from containerizer.probe.schema import (
    BaseImageSuggestion,
    ElfProbe,
    InstallerKind,
    ProbeResult,
)
from containerizer.verify.schema import VerifyDiff, VerifyReport


def _trace_json(marker: str = "COMPLETE") -> TraceJson:
    empty = TracePhase(
        duration_s=0.0,
        paths=[],
        ports=[],
        outbound=[],
        caps=[],
        syscalls=[],
        execs=[],
    )
    return TraceJson(
        phase_marker_ns=1,
        marker=marker,  # type: ignore[arg-type]
        install=empty,
        runtime=empty,
        warnings=[],
    )


def _policy(entrypoint: list[str]) -> PolicyJson:
    return PolicyJson(
        image=PolicyImage(
            base="ubuntu:24.04",
            installer=ExecutableInstaller(path="/installer"),
            apt_packages=[],
            post_install_cleanup=[],
            systemd_required=True,
            entrypoint=entrypoint,
        ),
        runtime=PolicyRuntime(
            volumes=[],
            tmpfs=[],
            binds_ro=[],
            publish_ports=[],
            caps_add=[],
            seccomp_syscalls=[],
            read_only_rootfs=False,
        ),
    )


def _empty_verify_report() -> VerifyReport:
    return VerifyReport(
        original_marker="COMPLETE",
        observed_marker="COMPLETE",
        diff=VerifyDiff(new_paths=[], new_ports=[], new_caps=[], new_syscalls=[], new_execs=[]),
    )


def _probe_result() -> ProbeResult:
    return ProbeResult(
        kind=InstallerKind.elf,
        arch="x86_64",
        elf=ElfProbe(
            arch="x86_64",
            bit=64,
            endianness="little",
            interpreter="/lib64/ld-linux-x86-64.so.2",
            is_static=False,
            needed_libs=[],
            glibc_min="2.35",
        ),
        base_image=BaseImageSuggestion(image="ubuntu:24.04", reasons=["x86_64 + glibc 2.35"]),
    )


@dataclass
class Calls:
    order: list[str]


def _probe(c: Calls) -> Callable[[Path, str | None], ProbeResult]:
    def fn(installer: Path, base_image: str | None) -> ProbeResult:
        c.order.append("probe")
        return _probe_result()

    return fn


def _install_trace_writing_complete(c: Calls, layout: PathLayout) -> Callable[..., int]:
    def fn(
        installer: Path,
        start_cmd: str | None,
        output_dir: Path,
        **_kwargs: object,
    ) -> int:
        c.order.append("install_trace")
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "COMPLETE").write_text("", encoding="utf-8")
        return 0

    return fn


def _parse_trace(c: Calls) -> Callable[[Path], TraceJson]:
    def fn(trace_dir: Path) -> TraceJson:
        c.order.append(f"parse_trace:{trace_dir.name}")
        return _trace_json()

    return fn


def _derive_policy(c: Calls, policy: PolicyJson) -> Callable[..., PolicyJson]:
    def fn(trace: TraceJson, install_inputs: object = None) -> PolicyJson:
        c.order.append("derive_policy")
        return policy

    return fn


def _generate(c: Calls, layout: PathLayout) -> Callable[..., None]:
    def fn(
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
        c.order.append("generate")
        final_dir.mkdir(parents=True, exist_ok=True)
        (final_dir / "Containerfile").write_text("FROM scratch\n", encoding="utf-8")
        (final_dir / f"{name}.container").write_text("[Container]\n", encoding="utf-8")
        (final_dir / "seccomp.json").write_text("{}\n", encoding="utf-8")
        (final_dir / "README.md").write_text(
            "# Containerizer output for demo\n\n## Next steps\n\n(...)\n",
            encoding="utf-8",
        )

    return fn


def _podman_build(c: Calls, layout: PathLayout) -> Callable[[Path, str], Path]:
    def fn(final_dir: Path, image_tag: str) -> Path:
        c.order.append("podman_build")
        layout.verify_image_tar.parent.mkdir(parents=True, exist_ok=True)
        layout.verify_image_tar.write_bytes(b"fake-tarball")
        return layout.verify_image_tar

    return fn


def _verify_trace_writing_complete(
    c: Calls,
) -> Callable[[Path, list[str], str, int, Path], int]:
    def fn(
        image_tar: Path,
        run_flags: list[str],
        image_tag: str,
        soak_seconds: int,
        output_dir: Path,
    ) -> int:
        c.order.append("verify_trace")
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "COMPLETE").write_text("", encoding="utf-8")
        return 0

    return fn


def _diff(c: Calls) -> Callable[[TraceJson, TraceJson], VerifyReport]:
    def fn(original: TraceJson, observed: TraceJson) -> VerifyReport:
        c.order.append("diff")
        return _empty_verify_report()

    return fn


def _build_layout(tmp_path: Path) -> PathLayout:
    return resolve_layout(
        tmp_path / "out",
        "demo",
        intermediates_root=tmp_path / "inter",
        keep_intermediates=False,
    )


def _cfg(tmp_path: Path, **overrides: object) -> BuildConfig:
    installer = tmp_path / "installer.bin"
    if not installer.exists():
        installer.write_text("x", encoding="utf-8")
    base: dict[str, object] = dict(
        installer=installer,
        name="demo",
        out_dir=tmp_path / "out",
    )
    base.update(overrides)
    return BuildConfig(**base)  # type: ignore[arg-type]


def test_happy_path_invokes_all_phases_in_order(tmp_path: Path) -> None:
    calls = Calls(order=[])
    layout = _build_layout(tmp_path)
    layout.intermediates_dir.mkdir(parents=True, exist_ok=True)

    result = run_pipeline(
        _cfg(tmp_path),
        probe_fn=_probe(calls),
        install_trace_fn=_install_trace_writing_complete(calls, layout),
        parse_trace_fn=_parse_trace(calls),
        derive_policy_fn=_derive_policy(calls, _policy(["/sbin/init"])),
        generate_fn=_generate(calls, layout),
        podman_build_fn=_podman_build(calls, layout),
        verify_trace_fn=_verify_trace_writing_complete(calls),
        diff_fn=_diff(calls),
        layout=layout,
        stderr=io.StringIO(),
    )

    assert calls.order == [
        "probe",
        "install_trace",
        "parse_trace:original",
        "derive_policy",
        "generate",
        "podman_build",
        "verify_trace",
        "parse_trace:verify",
        "diff",
    ]
    assert result.verify is not None
    assert result.skip_reason is None
    assert layout.final_verify_json.exists()
    assert layout.final_readme.read_text(encoding="utf-8").find("## Verify results") != -1


def test_sentinel_skip_short_circuits_after_generate(tmp_path: Path) -> None:
    calls = Calls(order=[])
    layout = _build_layout(tmp_path)
    layout.intermediates_dir.mkdir(parents=True, exist_ok=True)

    result = run_pipeline(
        _cfg(tmp_path),
        probe_fn=_probe(calls),
        install_trace_fn=_install_trace_writing_complete(calls, layout),
        parse_trace_fn=_parse_trace(calls),
        derive_policy_fn=_derive_policy(calls, _policy([SENTINEL_ENTRYPOINT])),
        generate_fn=_generate(calls, layout),
        podman_build_fn=_podman_build(calls, layout),
        verify_trace_fn=_verify_trace_writing_complete(calls),
        diff_fn=_diff(calls),
        layout=layout,
        stderr=io.StringIO(),
    )

    assert "podman_build" not in calls.order
    assert "verify_trace" not in calls.order
    assert "diff" not in calls.order
    assert result.skip_reason == "sentinel"
    assert result.verify is None
    assert not layout.final_verify_json.exists()
    readme = layout.final_readme.read_text(encoding="utf-8")
    assert "Verify skipped: no entrypoint detected" in readme


def test_skip_verify_flag_short_circuits_after_generate(tmp_path: Path) -> None:
    calls = Calls(order=[])
    layout = _build_layout(tmp_path)
    layout.intermediates_dir.mkdir(parents=True, exist_ok=True)

    result = run_pipeline(
        _cfg(tmp_path, skip_verify=True),
        probe_fn=_probe(calls),
        install_trace_fn=_install_trace_writing_complete(calls, layout),
        parse_trace_fn=_parse_trace(calls),
        derive_policy_fn=_derive_policy(calls, _policy(["/sbin/init"])),
        generate_fn=_generate(calls, layout),
        podman_build_fn=_podman_build(calls, layout),
        verify_trace_fn=_verify_trace_writing_complete(calls),
        diff_fn=_diff(calls),
        layout=layout,
        stderr=io.StringIO(),
    )

    assert "podman_build" not in calls.order
    assert result.skip_reason == "flag"
    assert "Verify skipped: `--skip-verify` was set." in layout.final_readme.read_text(
        encoding="utf-8"
    )


def test_install_trace_neither_complete_nor_partial_raises(tmp_path: Path) -> None:
    calls = Calls(order=[])
    layout = _build_layout(tmp_path)
    layout.intermediates_dir.mkdir(parents=True, exist_ok=True)

    def install_no_marker(
        installer: Path,
        start_cmd: str | None,
        output_dir: Path,
        **_kwargs: object,
    ) -> int:
        calls.order.append("install_trace")
        layout.trace_original_dir.mkdir(parents=True, exist_ok=True)
        return 1

    with pytest.raises(PipelineError, match="trace did not finalise"):
        run_pipeline(
            _cfg(tmp_path),
            probe_fn=_probe(calls),
            install_trace_fn=install_no_marker,
            parse_trace_fn=_parse_trace(calls),
            derive_policy_fn=_derive_policy(calls, _policy(["/sbin/init"])),
            generate_fn=_generate(calls, layout),
            podman_build_fn=_podman_build(calls, layout),
            verify_trace_fn=_verify_trace_writing_complete(calls),
            diff_fn=_diff(calls),
            layout=layout,
            stderr=io.StringIO(),
        )


def test_install_trace_partial_marker_emits_warning(tmp_path: Path) -> None:
    calls = Calls(order=[])
    layout = _build_layout(tmp_path)
    layout.intermediates_dir.mkdir(parents=True, exist_ok=True)

    def install_partial(
        installer: Path,
        start_cmd: str | None,
        output_dir: Path,
        **_kwargs: object,
    ) -> int:
        calls.order.append("install_trace")
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "PARTIAL").write_text("", encoding="utf-8")
        return 0

    result = run_pipeline(
        _cfg(tmp_path),
        probe_fn=_probe(calls),
        install_trace_fn=install_partial,
        parse_trace_fn=_parse_trace(calls),
        derive_policy_fn=_derive_policy(calls, _policy(["/sbin/init"])),
        generate_fn=_generate(calls, layout),
        podman_build_fn=_podman_build(calls, layout),
        verify_trace_fn=_verify_trace_writing_complete(calls),
        diff_fn=_diff(calls),
        layout=layout,
        stderr=io.StringIO(),
    )
    assert any("PARTIAL" in w for w in result.warnings)


def test_trace_warnings_surface_to_stderr_and_result(tmp_path: Path) -> None:
    """trace.warnings (e.g., 'collector connect: missing .jsonl; fallback recorded')
    must reach stderr at parse time so the user notices data gaps, and must
    also be carried in BuildResult.warnings so the CLI summary can echo them."""
    calls = Calls(order=[])
    layout = _build_layout(tmp_path)
    layout.intermediates_dir.mkdir(parents=True, exist_ok=True)

    def parse_with_warnings(trace_dir: Path) -> TraceJson:
        calls.order.append(f"parse_trace:{trace_dir.name}")
        empty = TracePhase(
            duration_s=0.0,
            paths=[],
            ports=[],
            outbound=[],
            caps=[],
            syscalls=[],
            execs=[],
        )
        warnings = (
            [
                "collector connect: missing .jsonl; fallback recorded "
                "(ERROR: Include headers with missing type definitions ...)",
                "collector accept: missing .jsonl; fallback recorded (unknown)",
            ]
            if trace_dir.name == "original"
            else []
        )
        return TraceJson(
            phase_marker_ns=1,
            marker="COMPLETE",
            install=empty,
            runtime=empty,
            warnings=warnings,
        )

    stderr = io.StringIO()
    result = run_pipeline(
        _cfg(tmp_path),
        probe_fn=_probe(calls),
        install_trace_fn=_install_trace_writing_complete(calls, layout),
        parse_trace_fn=parse_with_warnings,
        derive_policy_fn=_derive_policy(calls, _policy(["/sbin/init"])),
        generate_fn=_generate(calls, layout),
        podman_build_fn=_podman_build(calls, layout),
        verify_trace_fn=_verify_trace_writing_complete(calls),
        diff_fn=_diff(calls),
        layout=layout,
        stderr=stderr,
    )

    out = stderr.getvalue()
    assert "collector connect" in out
    assert "collector accept" in out
    assert "[analyze]" in out
    assert any("collector connect" in w for w in result.warnings)
    assert any("collector accept" in w for w in result.warnings)


def test_verify_trace_ready_failed_raises(tmp_path: Path) -> None:
    calls = Calls(order=[])
    layout = _build_layout(tmp_path)
    layout.intermediates_dir.mkdir(parents=True, exist_ok=True)

    def ready_failed(
        image_tar: Path,
        run_flags: list[str],
        image_tag: str,
        soak_seconds: int,
        output_dir: Path,
    ) -> int:
        calls.order.append("verify_trace")
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "READY_FAILED").write_text("", encoding="utf-8")
        return 1

    with pytest.raises(PipelineError, match="failed to come up"):
        run_pipeline(
            _cfg(tmp_path),
            probe_fn=_probe(calls),
            install_trace_fn=_install_trace_writing_complete(calls, layout),
            parse_trace_fn=_parse_trace(calls),
            derive_policy_fn=_derive_policy(calls, _policy(["/sbin/init"])),
            generate_fn=_generate(calls, layout),
            podman_build_fn=_podman_build(calls, layout),
            verify_trace_fn=ready_failed,
            diff_fn=_diff(calls),
            layout=layout,
            stderr=io.StringIO(),
        )


def test_verify_trace_load_failed_raises(tmp_path: Path) -> None:
    calls = Calls(order=[])
    layout = _build_layout(tmp_path)
    layout.intermediates_dir.mkdir(parents=True, exist_ok=True)

    def load_failed(
        image_tar: Path,
        run_flags: list[str],
        image_tag: str,
        soak_seconds: int,
        output_dir: Path,
    ) -> int:
        calls.order.append("verify_trace")
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "LOAD_FAILED").write_text("", encoding="utf-8")
        return 1

    with pytest.raises(PipelineError, match="podman load failed"):
        run_pipeline(
            _cfg(tmp_path),
            probe_fn=_probe(calls),
            install_trace_fn=_install_trace_writing_complete(calls, layout),
            parse_trace_fn=_parse_trace(calls),
            derive_policy_fn=_derive_policy(calls, _policy(["/sbin/init"])),
            generate_fn=_generate(calls, layout),
            podman_build_fn=_podman_build(calls, layout),
            verify_trace_fn=load_failed,
            diff_fn=_diff(calls),
            layout=layout,
            stderr=io.StringIO(),
        )


def test_verify_trace_no_recognized_marker_raises(tmp_path: Path) -> None:
    calls = Calls(order=[])
    layout = _build_layout(tmp_path)
    layout.intermediates_dir.mkdir(parents=True, exist_ok=True)

    def no_marker(
        image_tar: Path,
        run_flags: list[str],
        image_tag: str,
        soak_seconds: int,
        output_dir: Path,
    ) -> int:
        calls.order.append("verify_trace")
        output_dir.mkdir(parents=True, exist_ok=True)
        # No marker file at all.
        return 0

    with pytest.raises(PipelineError, match="no recognized marker"):
        run_pipeline(
            _cfg(tmp_path),
            probe_fn=_probe(calls),
            install_trace_fn=_install_trace_writing_complete(calls, layout),
            parse_trace_fn=_parse_trace(calls),
            derive_policy_fn=_derive_policy(calls, _policy(["/sbin/init"])),
            generate_fn=_generate(calls, layout),
            podman_build_fn=_podman_build(calls, layout),
            verify_trace_fn=no_marker,
            diff_fn=_diff(calls),
            layout=layout,
            stderr=io.StringIO(),
        )


def test_missing_readme_after_generate_raises_clear_error(tmp_path: Path) -> None:
    calls = Calls(order=[])
    layout = _build_layout(tmp_path)
    layout.intermediates_dir.mkdir(parents=True, exist_ok=True)

    def generate_without_readme(
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
        calls.order.append("generate")
        final_dir.mkdir(parents=True, exist_ok=True)
        (final_dir / "Containerfile").write_text("FROM scratch\n", encoding="utf-8")
        (final_dir / f"{name}.container").write_text("[Container]\n", encoding="utf-8")
        (final_dir / "seccomp.json").write_text("{}\n", encoding="utf-8")
        # Intentionally do NOT write README.md to exercise the missing-file
        # path on the post-verify rewrite.

    with pytest.raises(PipelineError, match="README rewrite failed"):
        run_pipeline(
            _cfg(tmp_path),
            probe_fn=_probe(calls),
            install_trace_fn=_install_trace_writing_complete(calls, layout),
            parse_trace_fn=_parse_trace(calls),
            derive_policy_fn=_derive_policy(calls, _policy(["/sbin/init"])),
            generate_fn=generate_without_readme,
            podman_build_fn=_podman_build(calls, layout),
            verify_trace_fn=_verify_trace_writing_complete(calls),
            diff_fn=_diff(calls),
            layout=layout,
            stderr=io.StringIO(),
        )
    # verify.json must still be preserved per spec §7's invariant.
    assert layout.final_verify_json.exists()


def test_verify_trace_ran_and_died_continues_with_warning(tmp_path: Path) -> None:
    calls = Calls(order=[])
    layout = _build_layout(tmp_path)
    layout.intermediates_dir.mkdir(parents=True, exist_ok=True)

    def died(
        image_tar: Path,
        run_flags: list[str],
        image_tag: str,
        soak_seconds: int,
        output_dir: Path,
    ) -> int:
        calls.order.append("verify_trace")
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "RAN_AND_DIED").write_text("", encoding="utf-8")
        (output_dir / "COMPLETE").write_text("", encoding="utf-8")
        return 0

    result = run_pipeline(
        _cfg(tmp_path),
        probe_fn=_probe(calls),
        install_trace_fn=_install_trace_writing_complete(calls, layout),
        parse_trace_fn=_parse_trace(calls),
        derive_policy_fn=_derive_policy(calls, _policy(["/sbin/init"])),
        generate_fn=_generate(calls, layout),
        podman_build_fn=_podman_build(calls, layout),
        verify_trace_fn=died,
        diff_fn=_diff(calls),
        layout=layout,
        stderr=io.StringIO(),
    )
    assert result.verify is not None
    assert any("RAN_AND_DIED" in w or "exited during soak" in w for w in result.warnings)
    assert "diff" in calls.order


def test_pipeline_passes_multi_deb_fields_to_install_trace_fn(tmp_path: Path) -> None:
    """Issue #102: run_pipeline must thread BuildConfig.extra_installers,
    apt_sources, and apt_keys through to the ORIGINAL install_trace_fn
    invocation as keyword arguments. The sentinel-entrypoint policy makes
    the pipeline short-circuit before verify, so we only see the original
    install call (which is what should receive these fields)."""
    calls = Calls(order=[])
    layout = _build_layout(tmp_path)
    layout.intermediates_dir.mkdir(parents=True, exist_ok=True)

    extra = tmp_path / "extra.deb"
    extra.write_text("x", encoding="utf-8")
    key = tmp_path / "repo.gpg"
    key.write_text("x", encoding="utf-8")
    sources = ("deb http://x noble main",)

    captured: dict[str, object] = {}

    def install_capturing(
        installer: Path,
        start_cmd: str | None,
        output_dir: Path,
        **kwargs: object,
    ) -> int:
        calls.order.append("install_trace")
        captured.update(kwargs)
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "COMPLETE").write_text("", encoding="utf-8")
        return 0

    cfg = _cfg(
        tmp_path,
        extra_installers=(extra,),
        apt_sources=sources,
        apt_keys=(key,),
    )

    run_pipeline(
        cfg,
        probe_fn=_probe(calls),
        install_trace_fn=install_capturing,
        parse_trace_fn=_parse_trace(calls),
        derive_policy_fn=_derive_policy(calls, _policy([SENTINEL_ENTRYPOINT])),
        generate_fn=_generate(calls, layout),
        podman_build_fn=_podman_build(calls, layout),
        verify_trace_fn=_verify_trace_writing_complete(calls),
        diff_fn=_diff(calls),
        layout=layout,
        stderr=io.StringIO(),
    )

    assert captured == {
        "extra_installers": (extra,),
        "apt_sources": sources,
        "apt_keys": (key,),
        "start_ready_seconds": 60,
        "verify_soak_seconds": 30,
    }
    # Sentinel policy means verify is skipped -- install_trace runs exactly
    # once (for the ORIGINAL trace) and never again for verify retrace.
    assert calls.order.count("install_trace") == 1
    assert "verify_trace" not in calls.order


def test_pipeline_threads_start_cmd_and_effective_soak_to_install_trace_fn(tmp_path: Path) -> None:
    """Issue #105: pipeline must forward start_ready_seconds and the resolved
    effective_verify_soak_seconds to install_trace_fn."""
    calls = Calls(order=[])
    layout = _build_layout(tmp_path)
    layout.intermediates_dir.mkdir(parents=True, exist_ok=True)

    captured: dict[str, object] = {}

    def install_capturing(
        installer: Path,
        start_cmd: str | None,
        output_dir: Path,
        **kwargs: object,
    ) -> int:
        calls.order.append("install_trace")
        captured.update(kwargs)
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "COMPLETE").write_text("", encoding="utf-8")
        return 0

    cfg = _cfg(
        tmp_path,
        start_cmd="/etc/init.d/foo start",
        start_ready_seconds=90,
    )

    run_pipeline(
        cfg,
        probe_fn=_probe(calls),
        install_trace_fn=install_capturing,
        parse_trace_fn=_parse_trace(calls),
        derive_policy_fn=_derive_policy(calls, _policy([SENTINEL_ENTRYPOINT])),
        generate_fn=_generate(calls, layout),
        podman_build_fn=_podman_build(calls, layout),
        verify_trace_fn=_verify_trace_writing_complete(calls),
        diff_fn=_diff(calls),
        layout=layout,
        stderr=io.StringIO(),
    )

    assert captured.get("start_ready_seconds") == 90
    assert captured.get("verify_soak_seconds") == 90  # auto-scaled from start_ready_seconds
    # Sentinel policy means verify is skipped -- install_trace runs exactly
    # once (for the ORIGINAL trace) and never again for verify retrace.
    assert calls.order.count("install_trace") == 1
    assert "verify_trace" not in calls.order


def test_stage_install_inputs_executable_copies_to_installer(tmp_path: Path) -> None:
    primary = tmp_path / "src" / "primary.bin"
    primary.parent.mkdir()
    primary.write_text("X", encoding="utf-8")
    final = tmp_path / "final"
    final.mkdir()

    _stage_install_inputs(
        final_dir=final,
        installer=primary,
        extra_installers=(),
        apt_keys=(),
    )

    assert (final / "installer").read_text(encoding="utf-8") == "X"
    assert not (final / "installers").exists()
    assert not (final / "apt-keys").exists()


def test_stage_install_inputs_deb_copies_to_installers_subdir(tmp_path: Path) -> None:
    primary = tmp_path / "src" / "foo.deb"
    primary.parent.mkdir()
    primary.write_text("DEB", encoding="utf-8")
    extra = tmp_path / "src" / "bar.deb"
    extra.write_text("EXTRA", encoding="utf-8")
    final = tmp_path / "final"
    final.mkdir()

    _stage_install_inputs(
        final_dir=final,
        installer=primary,
        extra_installers=(extra,),
        apt_keys=(),
    )

    assert (final / "installers" / "foo.deb").read_text(encoding="utf-8") == "DEB"
    assert (final / "installers" / "bar.deb").read_text(encoding="utf-8") == "EXTRA"
    assert not (final / "installer").exists()


def test_stage_install_inputs_apt_keys_copied_to_subdir(tmp_path: Path) -> None:
    primary = tmp_path / "src" / "foo.deb"
    primary.parent.mkdir()
    primary.write_text("DEB", encoding="utf-8")
    key = tmp_path / "src" / "mongodb.gpg"
    key.write_text("KEY", encoding="utf-8")
    final = tmp_path / "final"
    final.mkdir()

    _stage_install_inputs(
        final_dir=final,
        installer=primary,
        extra_installers=(),
        apt_keys=(key,),
    )

    assert (final / "apt-keys" / "mongodb.gpg").read_text(encoding="utf-8") == "KEY"


def test_stage_install_inputs_no_apt_keys_skips_keys_subdir(tmp_path: Path) -> None:
    primary = tmp_path / "src" / "foo.bin"
    primary.parent.mkdir()
    primary.write_text("X", encoding="utf-8")
    final = tmp_path / "final"
    final.mkdir()

    _stage_install_inputs(
        final_dir=final,
        installer=primary,
        extra_installers=(),
        apt_keys=(),
    )

    assert not (final / "apt-keys").exists()
