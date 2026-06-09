"""End-to-end smoke test for build/pipeline.run_pipeline.

Podman-touching seams are faked; everything else is real. Catches
integration issues between paths.py, flags.py, readme.py, the real M3
analyzer (over committed fixtures), the real M4 generators, the real M5
diff, and the README rewrite.

The committed synthetic-recorded fixture's runtime execs do not include
any systemd comm, so it would normally produce a sentinel policy and
short-circuit the pipeline before verify. To exercise the full pipeline
(verify, diff, README rewrite with real results), the install-trace fake
copies the fixture in and appends a single execve event with comm
"systemd" at a runtime ts -- enough to flip systemd_required_for and
yield a non-sentinel entrypoint.
"""

from __future__ import annotations

import io
import json
import shutil
from collections.abc import Callable
from pathlib import Path

from containerizer.analyze.assemble import assemble_trace_json
from containerizer.analyze.derive import derive_policy
from containerizer.analyze.reader import read_trace_dir
from containerizer.analyze.schema import PolicyJson, TraceJson
from containerizer.build.config import BuildConfig
from containerizer.build.paths import resolve_layout
from containerizer.build.pipeline import run_pipeline
from containerizer.generate.orchestrator import generate_all
from containerizer.probe.schema import (
    BaseImageSuggestion,
    ElfProbe,
    InstallerKind,
    ProbeResult,
)
from containerizer.verify.diff import diff_traces

REPO_ROOT = Path(__file__).resolve().parents[3]
SYNTH = REPO_ROOT / "tests" / "fixtures" / "trace" / "synthetic-recorded"

# PHASE_MARKER in the fixture is monotonic_ns: 1000. Inject systemd
# execve well past that so split_phases lands it in runtime.
_SYSTEMD_EXECVE_EVENT = {
    "pid": 12,
    "comm": "systemd",
    "syscall_id": 59,
    "count": 1,
    "first_ts_ns": 5000,
}


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
        base_image=BaseImageSuggestion(
            image="ubuntu:24.04",
            reasons=["x86_64 + glibc 2.35"],
        ),
    )


def _fake_probe(installer: Path, base_image: str | None) -> ProbeResult:
    return _probe_result()


def _copy_synth_into(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for src in SYNTH.iterdir():
        if src.is_file():
            shutil.copy2(src, output_dir / src.name)


def _append_jsonl(path: Path, event: dict[str, object]) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event) + "\n")


def _fake_install_trace(installer: Path, start_cmd: str | None, output_dir: Path) -> int:
    _copy_synth_into(output_dir)
    # Inject a runtime-phase systemd execve so derive_policy yields a
    # non-sentinel entrypoint and the pipeline runs to verify.
    _append_jsonl(output_dir / "syscalls.jsonl", _SYSTEMD_EXECVE_EVENT)
    return 0


def _fake_verify_trace(
    image_tar: Path,
    run_flags: list[str],
    image_tag: str,
    soak_seconds: int,
    output_dir: Path,
) -> int:
    _copy_synth_into(output_dir)
    # Match install-trace's systemd injection so it's not flagged as new,
    # and add one extra syscall id so the diff has a deterministic entry.
    _append_jsonl(output_dir / "syscalls.jsonl", _SYSTEMD_EXECVE_EVENT)
    extra_syscall = {
        "pid": 1234,
        "comm": "systemd",
        "syscall_id": 437,
        "count": 1,
        "first_ts_ns": 9000,
    }
    _append_jsonl(output_dir / "syscalls.jsonl", extra_syscall)
    return 0


def _fake_podman_build(verify_image_tar: Path) -> Callable[[Path, str], Path]:
    def fn(final_dir: Path, image_tag: str) -> Path:
        verify_image_tar.parent.mkdir(parents=True, exist_ok=True)
        verify_image_tar.write_bytes(b"fake-tarball")
        return verify_image_tar

    return fn


def _real_parse_trace(trace_dir: Path) -> TraceJson:
    return assemble_trace_json(read_trace_dir(trace_dir))


def _real_derive_policy(trace: TraceJson) -> PolicyJson:
    return derive_policy(trace, warnings=list(trace.warnings))


def _real_generate(policy: PolicyJson, name: str, final_dir: Path) -> None:
    generate_all(policy, name, final_dir)


def _cfg(tmp_path: Path, **overrides: object) -> BuildConfig:
    installer = tmp_path / "installer.bin"
    installer.write_text("x", encoding="utf-8")
    base: dict[str, object] = {
        "installer": installer,
        "name": "demo",
        "out_dir": tmp_path / "out",
    }
    base.update(overrides)
    return BuildConfig(**base)  # type: ignore[arg-type]


def test_full_pipeline_with_fakes_produces_expected_final_dir(tmp_path: Path) -> None:
    layout = resolve_layout(
        tmp_path / "out",
        "demo",
        intermediates_root=tmp_path / "inter",
        keep_intermediates=False,
    )
    layout.intermediates_dir.mkdir(parents=True, exist_ok=True)

    result = run_pipeline(
        _cfg(tmp_path),
        probe_fn=_fake_probe,
        install_trace_fn=_fake_install_trace,
        parse_trace_fn=_real_parse_trace,
        derive_policy_fn=_real_derive_policy,
        generate_fn=_real_generate,
        podman_build_fn=_fake_podman_build(layout.verify_image_tar),
        verify_trace_fn=_fake_verify_trace,
        diff_fn=diff_traces,
        layout=layout,
        stderr=io.StringIO(),
    )

    # Injecting the systemd execve flipped the policy off the sentinel
    # branch, so verify ran to completion.
    assert result.skip_reason is None
    assert result.verify is not None

    # Full M4 artifact set landed.
    assert layout.final_seccomp.exists()
    assert layout.final_readme.exists()
    assert layout.final_containerfile.exists()
    assert layout.final_quadlet.exists()
    assert layout.final_verify_json.exists()

    # README has the populated Verify results section.
    readme = layout.final_readme.read_text(encoding="utf-8")
    assert "## Verify results" in readme

    # verify.json carries the injected syscall 437 as a new event.
    payload = json.loads(layout.final_verify_json.read_text(encoding="utf-8"))
    assert 437 in payload["diff"]["new_syscalls"]


def test_keep_intermediates_preserves_intermediates_subtree(tmp_path: Path) -> None:
    layout = resolve_layout(
        tmp_path / "out",
        "demo",
        intermediates_root=tmp_path / "ignored",
        keep_intermediates=True,
    )
    layout.intermediates_dir.mkdir(parents=True, exist_ok=True)

    run_pipeline(
        _cfg(tmp_path, keep_intermediates=True),
        probe_fn=_fake_probe,
        install_trace_fn=_fake_install_trace,
        parse_trace_fn=_real_parse_trace,
        derive_policy_fn=_real_derive_policy,
        generate_fn=_real_generate,
        podman_build_fn=_fake_podman_build(layout.verify_image_tar),
        verify_trace_fn=_fake_verify_trace,
        diff_fn=diff_traces,
        layout=layout,
        stderr=io.StringIO(),
    )

    inter = tmp_path / "out" / "demo" / ".intermediates"
    assert inter.exists()
    assert (inter / "probe.json").exists()
    # COMPLETE or PARTIAL marker; one will exist.
    assert (inter / "trace" / "original" / "COMPLETE").exists() or (
        inter / "trace" / "original" / "PARTIAL"
    ).exists()
    assert (inter / "analyze" / "trace.json").exists()
    assert (inter / "analyze" / "policy.json").exists()
    assert (inter / "analyze" / "verify-trace.json").exists()
    assert (inter / "verify" / "image.tar").exists()
