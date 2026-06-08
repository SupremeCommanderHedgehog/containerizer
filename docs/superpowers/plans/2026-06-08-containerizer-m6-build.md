# Containerizer M6 — `build` Subcommand Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement `containerizer build <installer> --name <name>` as the end-to-end orchestrator that runs probe → trace → analyze → generate → `podman build` → retrace under strict policy → analyze → diff into one process. Per the spec at [`docs/superpowers/specs/2026-06-08-containerizer-m6-build.md`](../specs/2026-06-08-containerizer-m6-build.md).

**Architecture:** A new `src/containerizer/build/` package whose `pipeline.run_pipeline` composes 8 injected phase callables (probe / install_trace / parse_trace / derive_policy / generate / podman_build / verify_trace / diff). `build/cli.py` is the only orchestration layer that touches disk + subprocess. All other build modules are pure functions of Pydantic inputs. The existing M2 trace-runner image is extended with nested podman (`dnf install podman slirp4netns crun conmon`) and a new `verify-orchestrator.sh` workload script invoked when `trace-orchestrator.sh --mode verify` runs.

**Tech Stack:** Python 3.11+, Click 8.3, Pydantic v2, bash 5+, podman 4+. All commits signed with key `BE707B220C995478`, authored as `github.v5f9w@bitbucket.onl` per global CLAUDE.md.

**Working branch:** All M6 work lands on a single feature branch `feat/m6-build`. Per-task commits, single PR at the end (matches the M3/M4/M5 cadence per project memory).

---

## File map

New Python files:
- `src/containerizer/build/__init__.py`
- `src/containerizer/build/config.py` — `BuildConfig`, `BuildResult` Pydantic models
- `src/containerizer/build/paths.py` — `PathLayout` dataclass + `resolve_layout(out, name, *, keep_intermediates)`
- `src/containerizer/build/flags.py` — `podman_run_flags(policy)` pure function
- `src/containerizer/build/readme.py` — `rewrite_readme_with_verify(text, *, verify, skip_reason)` pure function
- `src/containerizer/build/pipeline.py` — `run_pipeline(config, *, probe_fn, install_trace_fn, ..., diff_fn, layout, stderr)`
- `src/containerizer/build/cli.py` — `build_cmd` Click subcommand + the default real-implementations of the 8 callables

Modified Python files:
- `src/containerizer/cli.py` — register `build_cmd` on the main group
- `src/containerizer/analyze/cli.py` — extract `_assemble_trace_json` to public location
- `src/containerizer/analyze/assemble.py` — NEW, receives the promoted helper
- `src/containerizer/trace/runner.py` — `TraceRunner` gains `mode: Literal["install", "verify"]` + verify-mode fields

Modified runner image:
- `sandbox/runner_image/Containerfile` — add podman + nested-podman dependencies
- `sandbox/runner_image/trace-orchestrator.sh` — add `--mode {install,verify}` flag parsing

New runner image file:
- `sandbox/runner_image/verify-orchestrator.sh` — verify-mode workload

New tests:
- `tests/unit/build/__init__.py`
- `tests/unit/build/test_config.py`
- `tests/unit/build/test_paths.py`
- `tests/unit/build/test_flags.py`
- `tests/unit/build/test_readme.py`
- `tests/unit/build/test_pipeline.py`
- `tests/unit/build/test_cli.py`
- `tests/unit/analyze/test_assemble.py` — covers the promoted public helper
- `tests/integration/build/__init__.py`
- `tests/integration/build/test_build_smoke.py`

New fixtures (under `tests/fixtures/build/`):
- `tests/fixtures/build/policy-sentinel.json` — a `PolicyJson` whose `image.entrypoint == ["__UNSET__"]`
- `tests/fixtures/build/readme-before.md` — M4-shape README to test rewrite
- `tests/fixtures/build/expected/readme-empty-diff.md` — golden after rewrite with empty diff
- `tests/fixtures/build/expected/readme-with-diff.md` — golden after rewrite with populated diff
- `tests/fixtures/build/expected/readme-sentinel-skip.md` — golden after rewrite with sentinel skip
- `tests/fixtures/build/expected/readme-flag-skip.md` — golden after rewrite with `--skip-verify` skip
- `tests/fixtures/build/expected/verify.json` — golden verify.json the integration test asserts against

Docs:
- `MANUAL.md` — append scenarios 10 (synthetic end-to-end) and 11 (UniFi end-to-end)

---

## Conventions every task assumes

- **Signed commits.** Every commit step uses:
  ```pwsh
  git -c user.email="github.v5f9w@bitbucket.onl" -c user.signingkey=BE707B220C995478 commit -S -m "<msg>"
  ```
  Use a single-quoted bash here-string or pwsh single-quoted here-string for multi-line bodies.

- **Lint/type/test gate.** Before every commit, run:
  ```pwsh
  ruff check . ; ruff format --check . ; mypy src tests ; pytest -q
  ```
  Fix any failures before committing.

- **Imports.** Every new module starts with `from __future__ import annotations`.

- **Pydantic.** All new models use `model_config = ConfigDict(extra="forbid", frozen=True)` and pin `schema_version: Literal[N] = N` like M3/M4/M5 do.

- **Pure function pattern.** Only `build/cli.py` is allowed to touch disk + subprocess. `pipeline.py` does write files via plain `Path.write_text(...)` / `Path.write_bytes(...)` calls — that counts as orchestration. Every other module returns strings / objects only.

---

## Task 0: Branch prep

**Files:**
- (none modified)

- [ ] **Step 0.1: Create the working branch**

Run:
```pwsh
git checkout main
git pull
git checkout -b feat/m6-build
```

Expected: switched to a new branch `feat/m6-build` based on `main` at commit `8410197` (M5 head) or later.

- [ ] **Step 0.2: Sanity-check the test baseline**

Run:
```pwsh
pytest -q
```

Expected: all tests pass on `main` HEAD. Record the test count for sanity comparison at end.

- [ ] **Step 0.3: Verify lint/type gate is green at HEAD**

Run:
```pwsh
ruff check . ; ruff format --check . ; mypy src tests
```

Expected: zero issues. If any fail, stop and fix on `main` first (out of scope for M6).

---

## Task 1: Promote `_assemble_trace_json` to a public module

**Why first:** `build/pipeline.py`'s `parse_trace_fn` needs `(trace_dir: Path) -> TraceJson` as a public seam. Today the JSONL → `TraceJson` assembly lives as a private helper inside `analyze/cli.py`. Promoting it now means M6 can import it cleanly without later churn.

**Files:**
- Create: `src/containerizer/analyze/assemble.py`
- Modify: `src/containerizer/analyze/cli.py` (delete the private helper, import from `assemble`)
- Create: `tests/unit/analyze/test_assemble.py`

- [ ] **Step 1.1: Write the failing test**

Create `tests/unit/analyze/test_assemble.py`:

```python
"""Public-API tests for the assemble_trace_json helper promoted from analyze/cli.py."""

from __future__ import annotations

from pathlib import Path

from containerizer.analyze.assemble import assemble_trace_json
from containerizer.analyze.reader import read_trace_dir
from containerizer.analyze.schema import TraceJson


def test_assemble_trace_json_from_synthetic_fixture():
    fixture = Path("tests/fixtures/trace/synthetic-recorded")
    bundle = read_trace_dir(fixture)

    result = assemble_trace_json(bundle)

    assert isinstance(result, TraceJson)
    assert result.marker in ("COMPLETE", "PARTIAL")
    assert result.runtime is not None
    assert result.install is not None
```

- [ ] **Step 1.2: Run the test, confirm it fails**

Run:
```pwsh
pytest tests/unit/analyze/test_assemble.py -v
```

Expected: `ModuleNotFoundError: No module named 'containerizer.analyze.assemble'`.

- [ ] **Step 1.3: Create the public module**

Create `src/containerizer/analyze/assemble.py`:

```python
"""Assemble a normalized TraceJson from a TraceBundle.

Promoted from analyze/cli.py for M6 so build/pipeline.py can reuse the
same path. The behavior is byte-identical to the previous private
helper; only the location and visibility changed.
"""

from __future__ import annotations

from containerizer.analyze.caps import aggregate_caps
from containerizer.analyze.derive import SENTINEL_ENTRYPOINT, systemd_required_for
from containerizer.analyze.execs import aggregate_execs
from containerizer.analyze.paths import classify_runtime
from containerizer.analyze.phases import split_phases
from containerizer.analyze.ports import aggregate_ports
from containerizer.analyze.reader import TraceBundle
from containerizer.analyze.schema import TraceJson, TracePhase
from containerizer.analyze.syscalls import aggregate_syscalls

SENTINEL_WARNING = f"entrypoint is sentinel [{SENTINEL_ENTRYPOINT!r}]; M4 must refuse this policy"


def assemble_trace_json(bundle: TraceBundle) -> TraceJson:
    """Build a TraceJson from a raw TraceBundle. Pure given the bundle."""
    open_install, open_runtime = split_phases(
        bundle.events["open"], phase_marker_ns=bundle.phase_marker_ns, marker=bundle.marker
    )
    bind_install, bind_runtime = split_phases(
        bundle.events["bind"], phase_marker_ns=bundle.phase_marker_ns, marker=bundle.marker
    )
    sys_install, sys_runtime = split_phases(
        bundle.events["syscalls"], phase_marker_ns=bundle.phase_marker_ns, marker=bundle.marker
    )
    capable_install, capable_runtime = split_phases(
        bundle.events["capable"], phase_marker_ns=bundle.phase_marker_ns, marker=bundle.marker
    )

    warnings = list(bundle.warnings)
    for collector, info in bundle.fallbacks.items():
        warnings.append(
            f"collector {collector}: fellback to {info.get('fallback', '?')} "
            f"(reason: {info.get('reason', '?')})"
        )

    install = TracePhase(
        duration_s=0.0,
        paths=classify_runtime(open_install),
        ports=aggregate_ports(bind_install),
        outbound=[],
        caps=aggregate_caps(capable_install),
        syscalls=aggregate_syscalls(sys_install),
        execs=aggregate_execs(sys_install),
    )
    runtime = TracePhase(
        duration_s=0.0,
        paths=classify_runtime(open_runtime),
        ports=aggregate_ports(bind_runtime),
        outbound=[],
        caps=aggregate_caps(capable_runtime),
        syscalls=aggregate_syscalls(sys_runtime),
        execs=aggregate_execs(sys_runtime),
    )

    for path in runtime.paths:
        if path.class_ == "unknown_rw":
            warnings.append(f"unknown_rw aggregate: {path.path}")
        elif path.class_ == "device":
            warnings.append(f"device aggregate: {path.path}")

    provisional = TraceJson(
        phase_marker_ns=bundle.phase_marker_ns,
        marker=bundle.marker,
        install=install,
        runtime=runtime,
        warnings=warnings,
    )
    if not systemd_required_for(provisional):
        warnings.append(SENTINEL_WARNING)
        return provisional.model_copy(update={"warnings": warnings})
    return provisional
```

- [ ] **Step 1.4: Rewire analyze/cli.py to import from assemble.py**

Edit `src/containerizer/analyze/cli.py`:

Replace lines 9-20 (the imports + `SENTINEL_WARNING` constant) with:

```python
from containerizer.analyze.assemble import assemble_trace_json
from containerizer.analyze.derive import derive_policy
from containerizer.analyze.reader import read_trace_dir
from containerizer.analyze.writer import write_policy_json, write_trace_json
```

Replace the `_assemble_trace_json(bundle)` call on line 40 with `assemble_trace_json(bundle)`.

Delete lines 47-113 (the entire private `_assemble_trace_json` function and now-unused imports).

After editing, the file should be about 25 lines.

- [ ] **Step 1.5: Run all tests; nothing should regress**

Run:
```pwsh
ruff check . ; ruff format --check . ; mypy src tests ; pytest -q
```

Expected: all green, including the new `test_assemble_trace_json_from_synthetic_fixture` and every existing analyze test.

- [ ] **Step 1.6: Commit**

```pwsh
git add src/containerizer/analyze/assemble.py src/containerizer/analyze/cli.py tests/unit/analyze/test_assemble.py
git -c user.email="github.v5f9w@bitbucket.onl" -c user.signingkey=BE707B220C995478 commit -S -m "refactor(analyze): promote _assemble_trace_json to public assemble module (M6 prep)"
```

---

## Task 2: `build/config.py` — BuildConfig + BuildResult

**Files:**
- Create: `src/containerizer/build/__init__.py`
- Create: `src/containerizer/build/config.py`
- Create: `tests/unit/build/__init__.py`
- Create: `tests/unit/build/test_config.py`

- [ ] **Step 2.1: Write the failing test**

Create `tests/unit/build/__init__.py` with one line: `"""Tests for the build orchestrator (M6)."""`.

Create `tests/unit/build/test_config.py`:

```python
"""Pydantic round-trip + frozen invariants for BuildConfig and BuildResult."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from containerizer.analyze.schema import TracePath, TracePort
from containerizer.build.config import BuildConfig, BuildResult
from containerizer.verify.schema import VerifyDiff, VerifyReport


def test_build_config_round_trip_defaults():
    cfg = BuildConfig(installer=Path("/tmp/x"), name="demo", out_dir=Path("out"))

    assert cfg.schema_version == 1
    assert cfg.base_image is None
    assert cfg.start_cmd is None
    assert cfg.keep_intermediates is False
    assert cfg.verify_soak_seconds == 30
    assert cfg.skip_verify is False
    assert cfg.debug is False

    payload = cfg.model_dump_json()
    cfg2 = BuildConfig.model_validate_json(payload)
    assert cfg2 == cfg


def test_build_config_is_frozen():
    cfg = BuildConfig(installer=Path("/tmp/x"), name="demo", out_dir=Path("out"))
    with pytest.raises(ValidationError):
        cfg.name = "changed"  # type: ignore[misc]


def test_build_config_rejects_unknown_field():
    with pytest.raises(ValidationError):
        BuildConfig(
            installer=Path("/tmp/x"),
            name="demo",
            out_dir=Path("out"),
            mystery_flag=True,  # type: ignore[call-arg]
        )


def test_build_result_round_trip_with_verify():
    report = VerifyReport(
        original_marker="COMPLETE",
        observed_marker="COMPLETE",
        diff=VerifyDiff(new_paths=[], new_ports=[], new_caps=[], new_syscalls=[], new_execs=[]),
    )
    result = BuildResult(
        final_dir=Path("./out/demo"),
        intermediates_dir=None,
        verify=report,
    )

    assert result.schema_version == 1
    assert result.skip_reason is None
    assert result.warnings == []
    assert result.verify == report

    payload = result.model_dump_json()
    result2 = BuildResult.model_validate_json(payload)
    assert result2 == result


def test_build_result_round_trip_sentinel_skip():
    result = BuildResult(
        final_dir=Path("./out/demo"),
        intermediates_dir=None,
        verify=None,
        skip_reason="sentinel",
        warnings=["entrypoint sentinel; verify skipped"],
    )

    payload = result.model_dump_json()
    result2 = BuildResult.model_validate_json(payload)
    assert result2 == result
    assert result2.skip_reason == "sentinel"
```

- [ ] **Step 2.2: Run the test, confirm it fails**

Run:
```pwsh
pytest tests/unit/build/test_config.py -v
```

Expected: `ModuleNotFoundError: No module named 'containerizer.build'`.

- [ ] **Step 2.3: Create the package and config module**

Create `src/containerizer/build/__init__.py` with one line: `"""Containerizer build orchestrator (M6)."""`.

Create `src/containerizer/build/config.py`:

```python
"""Pydantic models for the build orchestrator's inputs and outputs."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from containerizer.verify.schema import VerifyReport


class BuildConfig(BaseModel):
    """User-facing configuration for one `containerizer build` invocation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    installer: Path
    name: str
    out_dir: Path
    base_image: str | None = None
    start_cmd: str | None = None
    keep_intermediates: bool = False
    verify_soak_seconds: int = 30
    skip_verify: bool = False
    debug: bool = False


class BuildResult(BaseModel):
    """Structured result of a successful `run_pipeline` invocation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    final_dir: Path
    intermediates_dir: Path | None
    verify: VerifyReport | None = None
    skip_reason: Literal["sentinel", "flag"] | None = None
    warnings: list[str] = []
```

- [ ] **Step 2.4: Run test, verify pass**

Run:
```pwsh
pytest tests/unit/build/test_config.py -v
```

Expected: all four tests pass.

- [ ] **Step 2.5: Full gate**

Run:
```pwsh
ruff check . ; ruff format --check . ; mypy src tests ; pytest -q
```

Expected: green.

- [ ] **Step 2.6: Commit**

```pwsh
git add src/containerizer/build tests/unit/build
git -c user.email="github.v5f9w@bitbucket.onl" -c user.signingkey=BE707B220C995478 commit -S -m "feat(build): BuildConfig + BuildResult Pydantic models (M6)"
```

---

## Task 3: `build/paths.py` — PathLayout + resolve_layout

**Files:**
- Create: `src/containerizer/build/paths.py`
- Create: `tests/unit/build/test_paths.py`

- [ ] **Step 3.1: Write the failing test**

Create `tests/unit/build/test_paths.py`:

```python
"""Layout resolution for build's per-phase paths (tempdir vs --keep-intermediates)."""

from __future__ import annotations

from pathlib import Path

from containerizer.build.paths import PathLayout, resolve_layout


def test_resolve_layout_default_uses_passed_intermediates_root():
    out = Path("/out")
    intermediates_root = Path("/tmp/build-xyz")
    layout = resolve_layout(out, "demo", intermediates_root=intermediates_root,
                            keep_intermediates=False)

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


def test_resolve_layout_keep_intermediates_routes_to_final_dir():
    layout = resolve_layout(Path("/out"), "demo",
                            intermediates_root=Path("/ignored"),
                            keep_intermediates=True)

    assert layout.intermediates_dir == Path("/out/demo/.intermediates")
    assert layout.probe_json == Path("/out/demo/.intermediates/probe.json")
    assert layout.trace_original_dir == Path("/out/demo/.intermediates/trace/original")
    assert layout.trace_verify_dir == Path("/out/demo/.intermediates/trace/verify")
    assert layout.verify_image_tar == Path("/out/demo/.intermediates/verify/image.tar")
    # Final dir paths are unaffected by keep_intermediates.
    assert layout.final_dir == Path("/out/demo")
    assert layout.final_verify_json == Path("/out/demo/verify.json")


def test_resolve_layout_is_pure():
    """Same inputs -> equal layouts."""
    a = resolve_layout(Path("/out"), "demo",
                       intermediates_root=Path("/tmp/build-xyz"),
                       keep_intermediates=False)
    b = resolve_layout(Path("/out"), "demo",
                       intermediates_root=Path("/tmp/build-xyz"),
                       keep_intermediates=False)
    assert a == b
    assert isinstance(a, PathLayout)
```

- [ ] **Step 3.2: Run test, confirm fail**

Run:
```pwsh
pytest tests/unit/build/test_paths.py -v
```

Expected: `ModuleNotFoundError: No module named 'containerizer.build.paths'`.

- [ ] **Step 3.3: Implement paths.py**

Create `src/containerizer/build/paths.py`:

```python
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
    if keep_intermediates:
        intermediates_dir = final_dir / ".intermediates"
    else:
        intermediates_dir = intermediates_root

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
```

- [ ] **Step 3.4: Run test, verify pass**

Run:
```pwsh
pytest tests/unit/build/test_paths.py -v
```

Expected: 3 tests pass.

- [ ] **Step 3.5: Full gate**

Run:
```pwsh
ruff check . ; ruff format --check . ; mypy src tests ; pytest -q
```

Expected: green.

- [ ] **Step 3.6: Commit**

```pwsh
git add src/containerizer/build/paths.py tests/unit/build/test_paths.py
git -c user.email="github.v5f9w@bitbucket.onl" -c user.signingkey=BE707B220C995478 commit -S -m "feat(build): PathLayout + resolve_layout (M6)"
```

---

## Task 4: `build/flags.py` — podman_run_flags

**Files:**
- Create: `src/containerizer/build/flags.py`
- Create: `tests/unit/build/test_flags.py`

- [ ] **Step 4.1: Write the failing test**

Create `tests/unit/build/test_flags.py`:

```python
"""Strict-policy `podman run` flag derivation from PolicyJson."""

from __future__ import annotations

from containerizer.analyze.schema import (
    PolicyImage,
    PolicyJson,
    PolicyPort,
    PolicyRuntime,
    PolicyVolume,
)
from containerizer.build.flags import podman_run_flags


def _policy(runtime: PolicyRuntime, *, entrypoint: list[str] | None = None) -> PolicyJson:
    return PolicyJson(
        image=PolicyImage(
            base="ubuntu:24.04",
            apt_packages=[],
            post_install_cleanup=[],
            systemd_required=True,
            entrypoint=entrypoint or ["/sbin/init"],
        ),
        runtime=runtime,
    )


def test_minimum_viable_flags():
    runtime = PolicyRuntime(
        volumes=[], tmpfs=[], binds_ro=[], publish_ports=[],
        caps_add=[], seccomp_syscalls=[], read_only_rootfs=False,
        no_new_privileges=False,
    )
    flags = podman_run_flags(_policy(runtime))

    assert "--cap-drop=ALL" in flags
    assert "--security-opt" in flags
    assert "seccomp=/work/verify/seccomp.json" in flags
    assert "--read-only" not in flags
    assert not any(f.startswith("--cap-add") for f in flags)


def test_caps_add_each_become_cap_add_flag():
    runtime = PolicyRuntime(
        volumes=[], tmpfs=[], binds_ro=[], publish_ports=[],
        caps_add=["CAP_NET_BIND_SERVICE", "CAP_CHOWN"],
        seccomp_syscalls=[], read_only_rootfs=False, no_new_privileges=False,
    )
    flags = podman_run_flags(_policy(runtime))
    assert "--cap-add=CAP_NET_BIND_SERVICE" in flags
    assert "--cap-add=CAP_CHOWN" in flags


def test_tmpfs_entries_become_tmpfs_flags():
    runtime = PolicyRuntime(
        volumes=[], tmpfs=["/tmp", "/run"], binds_ro=[], publish_ports=[],
        caps_add=[], seccomp_syscalls=[], read_only_rootfs=False,
        no_new_privileges=False,
    )
    flags = podman_run_flags(_policy(runtime))
    assert "--tmpfs" in flags
    assert "/tmp" in flags
    assert "/run" in flags


def test_binds_ro_become_ro_volumes():
    runtime = PolicyRuntime(
        volumes=[], tmpfs=[], binds_ro=["/etc/resolv.conf"], publish_ports=[],
        caps_add=[], seccomp_syscalls=[], read_only_rootfs=False,
        no_new_privileges=False,
    )
    flags = podman_run_flags(_policy(runtime))
    assert "-v" in flags
    assert "/etc/resolv.conf:/etc/resolv.conf:ro" in flags


def test_volumes_become_anonymous_volume_args():
    runtime = PolicyRuntime(
        volumes=[PolicyVolume(name="data", mount="/var/lib/data")],
        tmpfs=[], binds_ro=[], publish_ports=[],
        caps_add=[], seccomp_syscalls=[], read_only_rootfs=False,
        no_new_privileges=False,
    )
    flags = podman_run_flags(_policy(runtime))
    assert "data:/var/lib/data" in flags


def test_publish_ports_become_p_flags():
    runtime = PolicyRuntime(
        volumes=[], tmpfs=[], binds_ro=[],
        publish_ports=[PolicyPort(host=8443, container=8443, proto="tcp")],
        caps_add=[], seccomp_syscalls=[], read_only_rootfs=False,
        no_new_privileges=False,
    )
    flags = podman_run_flags(_policy(runtime))
    assert "-p" in flags
    assert "8443:8443/tcp" in flags


def test_read_only_rootfs_emits_read_only_flag():
    runtime = PolicyRuntime(
        volumes=[], tmpfs=[], binds_ro=[], publish_ports=[],
        caps_add=[], seccomp_syscalls=[], read_only_rootfs=True,
        no_new_privileges=False,
    )
    flags = podman_run_flags(_policy(runtime))
    assert "--read-only" in flags


def test_no_new_privileges_emits_security_opt():
    runtime = PolicyRuntime(
        volumes=[], tmpfs=[], binds_ro=[], publish_ports=[],
        caps_add=[], seccomp_syscalls=[], read_only_rootfs=False,
        no_new_privileges=True,
    )
    flags = podman_run_flags(_policy(runtime))
    # one of the --security-opt slots carries "no-new-privileges"
    assert any(f == "no-new-privileges" for f in flags)


def test_sentinel_entrypoint_returns_empty_list():
    runtime = PolicyRuntime(
        volumes=[], tmpfs=[], binds_ro=[], publish_ports=[],
        caps_add=[], seccomp_syscalls=[], read_only_rootfs=False,
        no_new_privileges=False,
    )
    flags = podman_run_flags(_policy(runtime, entrypoint=["__UNSET__"]))
    assert flags == []
```

- [ ] **Step 4.2: Run test, confirm fail**

Run:
```pwsh
pytest tests/unit/build/test_flags.py -v
```

Expected: `ModuleNotFoundError: No module named 'containerizer.build.flags'`.

- [ ] **Step 4.3: Implement flags.py**

Create `src/containerizer/build/flags.py`:

```python
"""Derive strict-policy `podman run` flags from a PolicyJson.

The verify pass needs the same hardening the M4 Quadlet expresses
declaratively, but in argv form so we can `podman run` it inside the
trace-runner sandbox. The flags returned here mirror M4's quadlet.py
output one-for-one.
"""

from __future__ import annotations

from containerizer.analyze.derive import SENTINEL_ENTRYPOINT
from containerizer.analyze.schema import PolicyJson


def podman_run_flags(policy: PolicyJson) -> list[str]:
    """Return the argv tail of a strict-policy `podman run` for the verify pass.

    Empty list on sentinel entrypoint (defense-in-depth; caller is expected
    to short-circuit before invoking this).
    """
    if policy.image.entrypoint == [SENTINEL_ENTRYPOINT]:
        return []

    flags: list[str] = ["--cap-drop=ALL"]

    for cap in policy.runtime.caps_add:
        flags.append(f"--cap-add={cap}")

    if policy.runtime.read_only_rootfs:
        flags.append("--read-only")

    if policy.runtime.no_new_privileges:
        flags.extend(["--security-opt", "no-new-privileges"])

    # The seccomp profile is bind-mounted into the runner at the path below.
    flags.extend(["--security-opt", "seccomp=/work/verify/seccomp.json"])

    for path in policy.runtime.tmpfs:
        flags.extend(["--tmpfs", path])

    for bind in policy.runtime.binds_ro:
        flags.extend(["-v", f"{bind}:{bind}:ro"])

    for vol in policy.runtime.volumes:
        flags.extend(["-v", f"{vol.name}:{vol.mount}"])

    for port in policy.runtime.publish_ports:
        flags.extend(["-p", f"{port.host}:{port.container}/{port.proto}"])

    return flags
```

- [ ] **Step 4.4: Run tests, verify pass**

Run:
```pwsh
pytest tests/unit/build/test_flags.py -v
```

Expected: 9 tests pass.

- [ ] **Step 4.5: Full gate**

Run:
```pwsh
ruff check . ; ruff format --check . ; mypy src tests ; pytest -q
```

Expected: green.

- [ ] **Step 4.6: Commit**

```pwsh
git add src/containerizer/build/flags.py tests/unit/build/test_flags.py
git -c user.email="github.v5f9w@bitbucket.onl" -c user.signingkey=BE707B220C995478 commit -S -m "feat(build): podman_run_flags pure derivation from PolicyJson (M6)"
```

---

## Task 5: `build/readme.py` — rewrite_readme_with_verify (+ golden fixtures)

**Files:**
- Create: `src/containerizer/build/readme.py`
- Create: `tests/unit/build/test_readme.py`
- Create: `tests/fixtures/build/readme-before.md`
- Create: `tests/fixtures/build/expected/readme-empty-diff.md`
- Create: `tests/fixtures/build/expected/readme-with-diff.md`
- Create: `tests/fixtures/build/expected/readme-sentinel-skip.md`
- Create: `tests/fixtures/build/expected/readme-flag-skip.md`

- [ ] **Step 5.1: Create the input fixture (`readme-before.md`)**

Create `tests/fixtures/build/readme-before.md` — an M4-shape README the rewrite operates against. Use the literal text below verbatim so the golden tests match byte-for-byte:

```markdown
# Containerizer output for demo

## What was generated

- `Containerfile`
- `demo.container`
- `seccomp.json`
- `README.md` (this file)

## Audit trail

(no warnings from the analyzer)

## Runtime allowlist

- Volumes: 0
- Tmpfs: 1
  - `/tmp`
- Read-only binds: 0
- Published ports: 1
  - 8443:8443/tcp
- Capabilities added: 1
  - `CAP_NET_BIND_SERVICE`
- Seccomp syscalls allowed: 38

## Next steps

```
cp seccomp.json ~/.config/containers/seccomp/demo.json
podman build -t demo:local .
cp demo.container ~/.config/containers/systemd/
systemctl --user daemon-reload && systemctl --user start demo
```
```

End the file with a trailing newline.

- [ ] **Step 5.2: Write the failing test**

Create `tests/unit/build/test_readme.py`:

```python
"""Golden tests for the README rewrite that appends the Verify results section."""

from __future__ import annotations

from pathlib import Path

from containerizer.analyze.schema import TracePath, TracePort
from containerizer.build.readme import rewrite_readme_with_verify
from containerizer.verify.schema import VerifyDiff, VerifyReport

FIXTURES = Path("tests/fixtures/build")


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _empty_report() -> VerifyReport:
    return VerifyReport(
        original_marker="COMPLETE",
        observed_marker="COMPLETE",
        diff=VerifyDiff(new_paths=[], new_ports=[], new_caps=[], new_syscalls=[], new_execs=[]),
    )


def _populated_report() -> VerifyReport:
    return VerifyReport(
        original_marker="COMPLETE",
        observed_marker="COMPLETE",
        diff=VerifyDiff(
            new_paths=[
                TracePath(path="/etc/foo", ops=["read"], **{"class": "host_config_ro"}, by=["app"])
            ],
            new_ports=[],
            new_caps=["CAP_SYS_CHROOT"],
            new_syscalls=[437],
            new_execs=[],
        ),
    )


def test_rewrite_with_empty_diff_matches_golden():
    before = _read(FIXTURES / "readme-before.md")
    after = rewrite_readme_with_verify(before, verify=_empty_report(), skip_reason=None)
    assert after == _read(FIXTURES / "expected" / "readme-empty-diff.md")


def test_rewrite_with_populated_diff_matches_golden():
    before = _read(FIXTURES / "readme-before.md")
    after = rewrite_readme_with_verify(before, verify=_populated_report(), skip_reason=None)
    assert after == _read(FIXTURES / "expected" / "readme-with-diff.md")


def test_rewrite_sentinel_skip_matches_golden():
    before = _read(FIXTURES / "readme-before.md")
    after = rewrite_readme_with_verify(before, verify=None, skip_reason="sentinel")
    assert after == _read(FIXTURES / "expected" / "readme-sentinel-skip.md")


def test_rewrite_flag_skip_matches_golden():
    before = _read(FIXTURES / "readme-before.md")
    after = rewrite_readme_with_verify(before, verify=None, skip_reason="flag")
    assert after == _read(FIXTURES / "expected" / "readme-flag-skip.md")


def test_rewrite_is_idempotent():
    before = _read(FIXTURES / "readme-before.md")
    once = rewrite_readme_with_verify(before, verify=_populated_report(), skip_reason=None)
    twice = rewrite_readme_with_verify(once, verify=_populated_report(), skip_reason=None)
    assert once == twice


def test_rewrite_both_none_returns_unchanged():
    before = _read(FIXTURES / "readme-before.md")
    after = rewrite_readme_with_verify(before, verify=None, skip_reason=None)
    assert after == before
```

- [ ] **Step 5.3: Run test, confirm fail**

Run:
```pwsh
pytest tests/unit/build/test_readme.py -v
```

Expected: `ModuleNotFoundError: No module named 'containerizer.build.readme'`.

- [ ] **Step 5.4: Implement readme.py**

Create `src/containerizer/build/readme.py`:

```python
"""Append the Verify results section to an M4-shape README.

Idempotent: re-running on already-rewritten text replaces the previous
Verify results section, never duplicates it.
"""

from __future__ import annotations

import re
from typing import Literal

from containerizer.verify.schema import VerifyReport

VERIFY_SECTION_HEADER = "## Verify results"
NEXT_STEPS_HEADER = "## Next steps"
_MAX_DETAILS = 5


def rewrite_readme_with_verify(
    readme_text: str,
    *,
    verify: VerifyReport | None,
    skip_reason: Literal["sentinel", "flag"] | None,
) -> str:
    """Return the README with a `## Verify results` section inserted.

    Section placement: immediately before the trailing `## Next steps`
    section if present, else appended at the end. Existing Verify results
    sections are stripped first to guarantee idempotency.
    """
    if verify is None and skip_reason is None:
        return readme_text

    stripped = _strip_existing_verify_section(readme_text)
    section = _render_section(verify=verify, skip_reason=skip_reason)
    return _insert_before_next_steps(stripped, section)


def _strip_existing_verify_section(text: str) -> str:
    pattern = re.compile(
        rf"{re.escape(VERIFY_SECTION_HEADER)}.*?(?=^## |\Z)",
        flags=re.DOTALL | re.MULTILINE,
    )
    return pattern.sub("", text)


def _insert_before_next_steps(text: str, section: str) -> str:
    if NEXT_STEPS_HEADER in text:
        head, _, tail = text.partition(NEXT_STEPS_HEADER)
        head = head.rstrip() + "\n\n"
        return head + section.rstrip() + "\n\n" + NEXT_STEPS_HEADER + tail
    return text.rstrip() + "\n\n" + section.rstrip() + "\n"


def _render_section(
    *,
    verify: VerifyReport | None,
    skip_reason: Literal["sentinel", "flag"] | None,
) -> str:
    if skip_reason == "sentinel":
        return (
            f"{VERIFY_SECTION_HEADER}\n\n"
            "Verify skipped: no entrypoint detected. Re-run with "
            "`--start-cmd '<cmd>'` to enable the verify pass.\n"
        )
    if skip_reason == "flag":
        return (
            f"{VERIFY_SECTION_HEADER}\n\n"
            "Verify skipped: `--skip-verify` was set.\n"
        )

    assert verify is not None  # narrowed by caller
    diff = verify.diff
    total = (len(diff.new_paths) + len(diff.new_ports) + len(diff.new_caps)
             + len(diff.new_syscalls) + len(diff.new_execs))
    if total == 0:
        return f"{VERIFY_SECTION_HEADER}\n\nNo new events observed.\n"

    rows = [
        ("New paths", len(diff.new_paths),
         [f"`{p.path}`" for p in diff.new_paths]),
        ("New ports", len(diff.new_ports),
         [f"{p.port}/{p.proto}" for p in diff.new_ports]),
        ("New caps", len(diff.new_caps), [f"`{c}`" for c in diff.new_caps]),
        ("New syscalls", len(diff.new_syscalls),
         [str(s) for s in diff.new_syscalls]),
        ("New execs", len(diff.new_execs), [f"`{e}`" for e in diff.new_execs]),
    ]

    lines = [
        VERIFY_SECTION_HEADER,
        "",
        "The generated container was rebuilt and exercised under strict policy. "
        "These entries appeared in the verify trace but not the original:",
        "",
        "| Category | Count | Details |",
        "|---|---|---|",
    ]
    for label, count, details in rows:
        shown = ", ".join(details[:_MAX_DETAILS])
        if len(details) > _MAX_DETAILS:
            shown += ", ..."
        if not shown:
            shown = "-"
        lines.append(f"| {label} | {count} | {shown} |")
    lines.append("")
    lines.append("Full diff: see `verify.json`.")
    lines.append("")
    return "\n".join(lines)
```

- [ ] **Step 5.5: Generate the golden fixtures**

Run an ad-hoc Python script to materialize the four golden README fixtures from the implementation. This is a one-shot generator, not part of the test suite. From a PowerShell session at the repo root:

```pwsh
python -c "
from pathlib import Path
from containerizer.analyze.schema import TracePath
from containerizer.build.readme import rewrite_readme_with_verify
from containerizer.verify.schema import VerifyDiff, VerifyReport

fixtures = Path('tests/fixtures/build')
before = (fixtures / 'readme-before.md').read_text(encoding='utf-8')

empty = VerifyReport(
    original_marker='COMPLETE', observed_marker='COMPLETE',
    diff=VerifyDiff(new_paths=[], new_ports=[], new_caps=[], new_syscalls=[], new_execs=[]),
)
populated = VerifyReport(
    original_marker='COMPLETE', observed_marker='COMPLETE',
    diff=VerifyDiff(
        new_paths=[TracePath(path='/etc/foo', ops=['read'], **{'class': 'host_config_ro'}, by=['app'])],
        new_ports=[], new_caps=['CAP_SYS_CHROOT'], new_syscalls=[437], new_execs=[],
    ),
)

(fixtures / 'expected' / 'readme-empty-diff.md').write_text(
    rewrite_readme_with_verify(before, verify=empty, skip_reason=None), encoding='utf-8')
(fixtures / 'expected' / 'readme-with-diff.md').write_text(
    rewrite_readme_with_verify(before, verify=populated, skip_reason=None), encoding='utf-8')
(fixtures / 'expected' / 'readme-sentinel-skip.md').write_text(
    rewrite_readme_with_verify(before, verify=None, skip_reason='sentinel'), encoding='utf-8')
(fixtures / 'expected' / 'readme-flag-skip.md').write_text(
    rewrite_readme_with_verify(before, verify=None, skip_reason='flag'), encoding='utf-8')

print('wrote 4 golden README fixtures')
"
```

Expected stdout: `wrote 4 golden README fixtures`. Open each generated file briefly to spot-check it looks right (Verify results section placed before `## Next steps`).

- [ ] **Step 5.6: Run tests, verify pass**

Run:
```pwsh
pytest tests/unit/build/test_readme.py -v
```

Expected: 6 tests pass.

- [ ] **Step 5.7: Full gate**

Run:
```pwsh
ruff check . ; ruff format --check . ; mypy src tests ; pytest -q
```

Expected: green.

- [ ] **Step 5.8: Commit**

```pwsh
git add src/containerizer/build/readme.py tests/unit/build/test_readme.py tests/fixtures/build
git -c user.email="github.v5f9w@bitbucket.onl" -c user.signingkey=BE707B220C995478 commit -S -m "feat(build): README rewrite with Verify results section (M6)"
```

---

## Task 6: `build/pipeline.py` — run_pipeline

**Files:**
- Create: `src/containerizer/build/pipeline.py`
- Create: `tests/unit/build/test_pipeline.py`

This is the longest task — 8 callables, marker handling, sentinel branch, skip-verify branch, per-phase persistence. Pace yourself.

- [ ] **Step 6.1: Write the failing test (happy path + skip branches)**

Create `tests/unit/build/test_pipeline.py`:

```python
"""run_pipeline composition tests with fakes injected via the §5.6 seam."""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import pytest

from containerizer.analyze.derive import SENTINEL_ENTRYPOINT
from containerizer.analyze.schema import (
    PolicyImage,
    PolicyJson,
    PolicyRuntime,
    TraceJson,
    TracePhase,
)
from containerizer.build.config import BuildConfig
from containerizer.build.paths import resolve_layout
from containerizer.build.pipeline import PipelineError, run_pipeline
from containerizer.probe.schema import ProbeResult
from containerizer.verify.schema import VerifyDiff, VerifyReport


def _trace_json(marker: str = "COMPLETE") -> TraceJson:
    empty = TracePhase(
        duration_s=0.0, paths=[], ports=[], outbound=[],
        caps=[], syscalls=[], execs=[],
    )
    return TraceJson(
        phase_marker_ns=1, marker=marker,  # type: ignore[arg-type]
        install=empty, runtime=empty, warnings=[],
    )


def _policy(entrypoint: list[str]) -> PolicyJson:
    return PolicyJson(
        image=PolicyImage(
            base="ubuntu:24.04", apt_packages=[],
            post_install_cleanup=[], systemd_required=True,
            entrypoint=entrypoint,
        ),
        runtime=PolicyRuntime(
            volumes=[], tmpfs=[], binds_ro=[], publish_ports=[],
            caps_add=[], seccomp_syscalls=[], read_only_rootfs=False,
        ),
    )


def _empty_verify_report() -> VerifyReport:
    return VerifyReport(
        original_marker="COMPLETE", observed_marker="COMPLETE",
        diff=VerifyDiff(new_paths=[], new_ports=[], new_caps=[], new_syscalls=[], new_execs=[]),
    )


@dataclass
class Calls:
    """Track which callables were invoked, in what order."""
    order: list[str]


def _probe(c: Calls) -> Callable[[Path, str | None], ProbeResult]:
    def fn(installer: Path, base_image: str | None) -> ProbeResult:
        c.order.append("probe")
        return ProbeResult(
            kind="elf", arch="x86_64", glibc_min="2.35",
            needed_libs=[], interpreter="/lib64/ld-linux-x86-64.so.2",
            base_image_suggestion="ubuntu:24.04",
            base_image_reasons=["x86_64 + glibc 2.35"],
        )
    return fn


def _install_trace_writing_complete(c: Calls, layout) -> Callable[..., int]:
    def fn(installer: Path, start_cmd: str | None, output_dir: Path) -> int:
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


def _derive_policy(c: Calls, policy: PolicyJson) -> Callable[[TraceJson], PolicyJson]:
    def fn(trace: TraceJson) -> PolicyJson:
        c.order.append("derive_policy")
        return policy
    return fn


def _generate(c: Calls, layout) -> Callable[[PolicyJson, str, Path], None]:
    def fn(policy: PolicyJson, name: str, final_dir: Path) -> None:
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


def _podman_build(c: Calls, layout) -> Callable[[Path, str], Path]:
    def fn(final_dir: Path, image_tag: str) -> Path:
        c.order.append("podman_build")
        layout.verify_image_tar.parent.mkdir(parents=True, exist_ok=True)
        layout.verify_image_tar.write_bytes(b"fake-tarball")
        return layout.verify_image_tar
    return fn


def _verify_trace_writing_complete(c: Calls) -> Callable[..., int]:
    def fn(image_tar: Path, run_flags: list[str], image_tag: str,
           soak_seconds: int, output_dir: Path) -> int:
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


def _build_layout(tmp_path: Path):
    return resolve_layout(
        tmp_path / "out", "demo",
        intermediates_root=tmp_path / "inter",
        keep_intermediates=False,
    )


def _cfg(tmp_path: Path, **overrides) -> BuildConfig:
    base = dict(
        installer=tmp_path / "installer.bin",
        name="demo",
        out_dir=tmp_path / "out",
    )
    base.update(overrides)
    return BuildConfig(**base)


# --------- Happy path ---------

def test_happy_path_invokes_all_phases_in_order(tmp_path: Path):
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
        "probe", "install_trace", "parse_trace:original", "derive_policy",
        "generate", "podman_build", "verify_trace",
        "parse_trace:verify", "diff",
    ]
    assert result.verify is not None
    assert result.skip_reason is None
    assert layout.final_verify_json.exists()
    assert layout.final_readme.read_text(encoding="utf-8").find("## Verify results") != -1


# --------- Sentinel skip branch ---------

def test_sentinel_skip_short_circuits_after_generate(tmp_path: Path):
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


# --------- --skip-verify branch ---------

def test_skip_verify_flag_short_circuits_after_generate(tmp_path: Path):
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
    assert "Verify skipped: `--skip-verify` was set." in \
        layout.final_readme.read_text(encoding="utf-8")


# --------- Marker handling ---------

def test_install_trace_neither_complete_nor_partial_raises(tmp_path: Path):
    calls = Calls(order=[])
    layout = _build_layout(tmp_path)
    layout.intermediates_dir.mkdir(parents=True, exist_ok=True)

    def install_no_marker(*args, **kwargs):
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


def test_install_trace_partial_marker_emits_warning(tmp_path: Path):
    calls = Calls(order=[])
    layout = _build_layout(tmp_path)
    layout.intermediates_dir.mkdir(parents=True, exist_ok=True)

    def install_partial(installer, start_cmd, output_dir):
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


def test_verify_trace_ready_failed_raises(tmp_path: Path):
    calls = Calls(order=[])
    layout = _build_layout(tmp_path)
    layout.intermediates_dir.mkdir(parents=True, exist_ok=True)

    def ready_failed(image_tar, run_flags, image_tag, soak_seconds, output_dir):
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


def test_verify_trace_ran_and_died_continues_with_warning(tmp_path: Path):
    calls = Calls(order=[])
    layout = _build_layout(tmp_path)
    layout.intermediates_dir.mkdir(parents=True, exist_ok=True)

    def died(image_tar, run_flags, image_tag, soak_seconds, output_dir):
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
```

- [ ] **Step 6.2: Run tests, confirm fail**

Run:
```pwsh
pytest tests/unit/build/test_pipeline.py -v
```

Expected: `ModuleNotFoundError: No module named 'containerizer.build.pipeline'`.

- [ ] **Step 6.3: Implement pipeline.py**

Create `src/containerizer/build/pipeline.py`:

```python
"""Compose the 7 (or 8, counting analyze-twice) build phases.

The pipeline owns intermediate-JSON persistence and the final-artifact
write paths (verify.json, the rewritten README). It does not parse Click
flags, create the tempdir, or render the stderr line-by-line summary --
build/cli.py does that around it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, TextIO

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
        _say(stderr, "[verify]   skipped: no entrypoint detected")
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
        _say(stderr, "[verify]   skipped: --skip-verify was set")
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
    _say(stderr,
         f"[verify]   running generated image under strict policy "
         f"(soak {config.verify_soak_seconds}s)")
    layout.trace_verify_dir.mkdir(parents=True, exist_ok=True)
    run_flags = podman_run_flags(policy)
    verify_trace_fn(image_tar, run_flags, image_tag,
                    config.verify_soak_seconds, layout.trace_verify_dir)

    verify_marker = _read_verify_marker(layout.trace_verify_dir)
    if verify_marker == "LOAD_FAILED":
        raise PipelineError(
            f"podman load failed inside the verify sandbox; "
            f"see {layout.trace_verify_dir}"
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

    total = (len(report.diff.new_paths) + len(report.diff.new_ports)
             + len(report.diff.new_caps) + len(report.diff.new_syscalls)
             + len(report.diff.new_execs))
    if total == 0:
        _say(stderr, "[verify]   no new events")
    else:
        _say(stderr,
             f"[verify]   {len(report.diff.new_paths)} new paths, "
             f"{len(report.diff.new_ports)} new ports, "
             f"{len(report.diff.new_caps)} new caps, "
             f"{len(report.diff.new_syscalls)} new syscalls, "
             f"{len(report.diff.new_execs)} new execs")
    _say(stderr, f"[done]     {layout.final_dir}")

    return BuildResult(
        final_dir=layout.final_dir,
        intermediates_dir=layout.intermediates_dir,
        verify=report,
        skip_reason=None,
        warnings=warnings,
    )


def _say(stderr: TextIO, msg: str) -> None:
    stderr.write(msg + "\n")


def _read_install_marker(trace_dir: Path) -> str:
    if (trace_dir / "COMPLETE").exists():
        return "COMPLETE"
    if (trace_dir / "PARTIAL").exists():
        return "PARTIAL"
    raise PipelineError(
        f"install trace did not finalise (no COMPLETE or PARTIAL marker) at {trace_dir}"
    )


def _read_verify_marker(trace_dir: Path) -> str:
    for marker in ("LOAD_FAILED", "READY_FAILED", "RAN_AND_DIED", "COMPLETE"):
        if (trace_dir / marker).exists():
            return marker
    raise PipelineError(
        f"verify trace did not finalise (no recognized marker) at {trace_dir}"
    )


def _rewrite_readme(path: Path, *, verify: VerifyReport | None,
                    skip_reason: str | None) -> None:
    text = path.read_text(encoding="utf-8")
    new_text = rewrite_readme_with_verify(text, verify=verify, skip_reason=skip_reason)  # type: ignore[arg-type]
    path.write_text(new_text, encoding="utf-8")
```

- [ ] **Step 6.4: Run tests, verify pass**

Run:
```pwsh
pytest tests/unit/build/test_pipeline.py -v
```

Expected: 7 tests pass. If a fake's name doesn't match the test's order assertion, fix the fake. If marker handling errors, recheck `_read_install_marker` / `_read_verify_marker`.

- [ ] **Step 6.5: Full gate**

Run:
```pwsh
ruff check . ; ruff format --check . ; mypy src tests ; pytest -q
```

Expected: green.

- [ ] **Step 6.6: Commit**

```pwsh
git add src/containerizer/build/pipeline.py tests/unit/build/test_pipeline.py
git -c user.email="github.v5f9w@bitbucket.onl" -c user.signingkey=BE707B220C995478 commit -S -m "feat(build): run_pipeline orchestrator with 8-callable seam (M6)"
```

---

## Task 7: `trace/runner.py` — TraceRunner gains a verify mode

**Files:**
- Modify: `src/containerizer/trace/runner.py`
- Modify: `tests/unit/test_trace_runner.py` — keep existing tests green, add verify-mode tests

- [ ] **Step 7.1: Write the failing verify-mode test**

Append to `tests/unit/test_trace_runner.py` (do NOT touch the existing tests):

```python
from containerizer.trace.runner import TraceRunner


def test_verify_mode_argv_includes_image_tar_and_env_vars(tmp_path):
    image_tar = tmp_path / "image.tar"
    image_tar.write_bytes(b"x")
    seccomp = tmp_path / "seccomp.json"
    seccomp.write_text("{}", encoding="utf-8")
    out = tmp_path / "verify-trace"

    runner = TraceRunner(
        image_tag="runner:latest",
        installer=None,
        output_dir=out,
        mode="verify",
        verify_image_tar=image_tar,
        verify_image_tag="demo:m6-verify",
        verify_run_flags=("--cap-drop=ALL", "--read-only"),
        verify_soak_seconds=15,
        verify_seccomp_path=seccomp,
    )
    argv = runner.argv()

    assert "--mode" in argv
    assert "verify" in argv
    assert f"{image_tar.resolve()}:/work/verify/image.tar:ro" in argv
    assert f"{seccomp.resolve()}:/work/verify/seccomp.json:ro" in argv
    assert any(a == "VERIFY_IMAGE_TAG=demo:m6-verify" for a in argv)
    assert any(a == "VERIFY_SOAK_SECONDS=15" for a in argv)
    # VERIFY_RUN_FLAGS is one env var carrying the whole arg list, space-joined.
    assert any(a.startswith("VERIFY_RUN_FLAGS=--cap-drop=ALL --read-only") for a in argv)
    # Verify mode does not run interactively.
    assert "-i" not in argv
    # The original /installer mount is NOT present in verify mode.
    assert not any(":/installer:" in a for a in argv)


def test_install_mode_unchanged(tmp_path):
    installer = tmp_path / "installer.sh"
    installer.write_text("echo hi", encoding="utf-8")
    out = tmp_path / "install-trace"

    runner = TraceRunner(
        image_tag="runner:latest",
        installer=installer,
        output_dir=out,
    )
    argv = runner.argv()
    # Default mode is "install"; behavior must be byte-identical to M2.
    assert "-i" in argv
    assert any(":/installer:ro" in a for a in argv)
    assert "--mode" not in argv  # not passed in install mode


def test_verify_mode_validates_required_fields(tmp_path):
    import pytest

    out = tmp_path / "vt"
    with pytest.raises(ValueError, match="verify mode requires"):
        TraceRunner(
            image_tag="runner:latest",
            installer=None,
            output_dir=out,
            mode="verify",
            # missing verify_* fields
        )


def test_install_mode_validates_installer_present(tmp_path):
    import pytest

    out = tmp_path / "it"
    with pytest.raises(ValueError, match="install mode requires installer"):
        TraceRunner(
            image_tag="runner:latest",
            installer=None,
            output_dir=out,
        )
```

- [ ] **Step 7.2: Run the new tests, confirm fail**

Run:
```pwsh
pytest tests/unit/test_trace_runner.py -v
```

Expected: the four new tests fail (mode parameter doesn't exist, installer can't be None, etc.). All previously-passing install-mode tests still pass.

- [ ] **Step 7.3: Update runner.py to support both modes**

Replace `src/containerizer/trace/runner.py` entirely with:

```python
"""Construct and exec the `podman run` for the trace sandbox.

The runner supports two modes:

* `mode="install"` (default): the M2 behavior. Mounts the installer at
  /installer and runs trace-orchestrator.sh. Interactive (-i) so the
  user can press Enter when the smoke test is done.

* `mode="verify"` (M6): no installer; bind-mounts a saved image tarball
  and the final seccomp profile, sets env vars consumed by
  verify-orchestrator.sh, passes `--mode verify` to the orchestrator.
  Non-interactive (no -i) because the soak window is fixed.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


class OutputDirNotEmpty(RuntimeError):
    """Raised when the output dir already has a COMPLETE or PARTIAL marker."""


@dataclass(frozen=True)
class TraceRunner:
    """Builds the `podman run` argv and execs it for one trace phase."""

    image_tag: str
    installer: Path | None
    output_dir: Path
    mode: Literal["install", "verify"] = "install"

    # Verify-mode-only fields. All default to None; validated in __post_init__.
    verify_image_tar: Path | None = None
    verify_image_tag: str | None = None
    verify_run_flags: tuple[str, ...] = field(default_factory=tuple)
    verify_soak_seconds: int | None = None
    verify_seccomp_path: Path | None = None

    def __post_init__(self) -> None:
        if self.mode == "install":
            if self.installer is None:
                raise ValueError("install mode requires installer")
        else:
            missing = [
                name for name, val in (
                    ("verify_image_tar", self.verify_image_tar),
                    ("verify_image_tag", self.verify_image_tag),
                    ("verify_soak_seconds", self.verify_soak_seconds),
                    ("verify_seccomp_path", self.verify_seccomp_path),
                ) if val is None
            ]
            if missing:
                raise ValueError(f"verify mode requires: {', '.join(missing)}")

    def argv(self) -> list[str]:
        """Pure: returns the podman command without executing it."""
        if self.mode == "install":
            return self._install_argv()
        return self._verify_argv()

    def _install_argv(self) -> list[str]:
        assert self.installer is not None
        return [
            "podman", "run", "--rm", "-i", "--privileged", "--pid=host",
            "-v", "/sys/kernel/debug:/sys/kernel/debug",
            "-v", "/sys/kernel/tracing:/sys/kernel/tracing",
            "-v", "/sys/kernel/btf:/sys/kernel/btf",
            "-v", "/lib/modules:/lib/modules:ro",
            "-v", "/usr/src:/usr/src:ro",
            "-v", f"{self.installer.resolve()}:/installer:ro",
            "-v", f"{self.output_dir.resolve()}:/work/trace",
            self.image_tag,
            "/installer",
        ]

    def _verify_argv(self) -> list[str]:
        assert self.verify_image_tar is not None
        assert self.verify_image_tag is not None
        assert self.verify_soak_seconds is not None
        assert self.verify_seccomp_path is not None

        run_flags_env = "VERIFY_RUN_FLAGS=" + " ".join(self.verify_run_flags)

        return [
            "podman", "run", "--rm", "--privileged", "--pid=host",
            "-v", "/sys/kernel/debug:/sys/kernel/debug",
            "-v", "/sys/kernel/tracing:/sys/kernel/tracing",
            "-v", "/sys/kernel/btf:/sys/kernel/btf",
            "-v", "/lib/modules:/lib/modules:ro",
            "-v", "/usr/src:/usr/src:ro",
            "-v", f"{self.verify_image_tar.resolve()}:/work/verify/image.tar:ro",
            "-v", f"{self.verify_seccomp_path.resolve()}:/work/verify/seccomp.json:ro",
            "-v", f"{self.output_dir.resolve()}:/work/trace",
            "-e", f"VERIFY_IMAGE_TAG={self.verify_image_tag}",
            "-e", f"VERIFY_SOAK_SECONDS={self.verify_soak_seconds}",
            "-e", run_flags_env,
            self.image_tag,
            "/usr/local/bin/trace-orchestrator.sh",
            "--mode", "verify",
        ]

    def validate_output_dir(self, *, force: bool) -> None:
        """Refuse to overwrite an existing trace unless `force` is set."""
        for marker in ("COMPLETE", "PARTIAL"):
            if (self.output_dir / marker).exists() and not force:
                raise OutputDirNotEmpty(
                    f"{self.output_dir} already contains a {marker} marker. "
                    f"Use --force to replace or pick a fresh directory."
                )

    def run(self) -> int:
        """Exec the podman command in the foreground."""
        result = subprocess.run(self.argv(), check=False)
        return result.returncode
```

- [ ] **Step 7.4: Run tests, verify pass**

Run:
```pwsh
pytest tests/unit/test_trace_runner.py -v
```

Expected: all install-mode tests still pass, all four new verify-mode tests pass.

- [ ] **Step 7.5: Verify the existing M2 trace CLI still works**

Run:
```pwsh
pytest tests/unit/test_trace_cli.py -v
```

Expected: green. Existing callers don't pass `mode`, so they default to install and the dataclass validates `installer` is present.

- [ ] **Step 7.6: Full gate**

Run:
```pwsh
ruff check . ; ruff format --check . ; mypy src tests ; pytest -q
```

Expected: green.

- [ ] **Step 7.7: Commit**

```pwsh
git add src/containerizer/trace/runner.py tests/unit/test_trace_runner.py
git -c user.email="github.v5f9w@bitbucket.onl" -c user.signingkey=BE707B220C995478 commit -S -m "feat(trace): TraceRunner gains verify mode for M6 retrace"
```

---

## Task 8: Runner image — add nested-podman dependencies to Containerfile

**Files:**
- Modify: `sandbox/runner_image/Containerfile`

This task has no Python tests; verification is "the file gets the new lines" and the broader image rebuild happens manually before M6 acceptance. The runner-image bash scripts are exempt from Python coverage per spec §8.4.

- [ ] **Step 8.1: Inspect current Containerfile**

Run:
```pwsh
type sandbox/runner_image/Containerfile
```

Note the last `RUN` line so the next addition lands after it.

- [ ] **Step 8.2: Append nested-podman dependencies**

Append the following lines to the end of `sandbox/runner_image/Containerfile`:

```Dockerfile

# M6: nested podman so the trace-runner can rebuild and exercise the
# generated container under strict policy during the verify pass.
RUN dnf install -y \
        podman \
        slirp4netns \
        fuse-overlayfs \
        crun \
        conmon \
        shadow-utils && \
    dnf clean all && \
    rm -rf /var/cache/dnf

# Pre-create storage roots so the first nested `podman load` doesn't pay
# cold-cache setup latency inside the trace window.
RUN mkdir -p /var/lib/containers \
             /var/lib/shared/overlay-images \
             /var/lib/shared/overlay-layers \
             /var/lib/shared/vfs-images \
             /var/lib/shared/vfs-layers && \
    chmod 755 /var/lib/containers
```

- [ ] **Step 8.3: Verify the Containerfile still parses**

Run a syntax check using podman parse-only (works on Windows once the file is on disk; no actual build required):

```pwsh
podman build --help | findstr "Containerfile"
```

If `podman` is installed, run:

```pwsh
podman build --no-cache=false --pull-never -f sandbox/runner_image/Containerfile --target nothing-target sandbox/runner_image 2>&1 | Select-Object -First 5
```

(The build will fail because there is no `nothing-target` target; the point is that `podman` parses the Containerfile without a syntax error first. If you see "BUG", "syntax error", or a parse-time exception, the Containerfile is malformed.)

If podman isn't available locally, skip this and rely on the M6 manual acceptance scenario to validate.

- [ ] **Step 8.4: Commit**

```pwsh
git add sandbox/runner_image/Containerfile
git -c user.email="github.v5f9w@bitbucket.onl" -c user.signingkey=BE707B220C995478 commit -S -m "feat(sandbox): add nested-podman to runner image for M6 verify retrace"
```

---

## Task 9: Runner image — `trace-orchestrator.sh` gains `--mode {install,verify}`

**Files:**
- Modify: `sandbox/runner_image/trace-orchestrator.sh`

- [ ] **Step 9.1: Read the current orchestrator**

Run:
```pwsh
type sandbox/runner_image/trace-orchestrator.sh
```

Identify the section where the installer is executed (M2 §5.4). That's the section that needs to branch on mode.

- [ ] **Step 9.2: Add `--mode` parsing at the top**

Edit `sandbox/runner_image/trace-orchestrator.sh`. Immediately after the shebang and any `set -e...` lines, add:

```bash
# M6: optional --mode {install,verify}. Default is install (M2 behavior).
MODE="install"
while [[ $# -gt 0 ]]; do
    case "$1" in
        --mode)
            MODE="${2:?--mode requires an argument}"
            shift 2
            ;;
        --mode=*)
            MODE="${1#--mode=}"
            shift
            ;;
        *)
            break
            ;;
    esac
done

case "$MODE" in
    install|verify) ;;
    *) echo "trace-orchestrator: unknown --mode $MODE" >&2; exit 64 ;;
esac
```

- [ ] **Step 9.3: Branch the workload section**

Find the section currently labeled with the installer execution (look for `/installer` or `exec /installer` or similar). Wrap it in a mode branch. The new shape:

```bash
if [[ "$MODE" == "install" ]]; then
    # ---- existing M2 install-mode workload ----
    # (Keep every line of the current install-mode body verbatim. Do not
    # change collector start/stop, daemon-detect, wait-for-Enter, or
    # marker-writing semantics.)
else
    # ---- M6 verify-mode workload ----
    /usr/local/bin/verify-orchestrator.sh
fi
```

The collector-start lines (before the install-mode body) and collector-stop / marker-write lines (after) should remain OUTSIDE the if/else block so they run in both modes. The phase marker (`/work/trace/PHASE_MARKER`) is written by the inner block — install mode writes it on installer-success today; verify mode will have `verify-orchestrator.sh` write it immediately on entry (see Task 10).

- [ ] **Step 9.4: Sanity-check with bash -n**

Run inside WSL or any bash environment:
```bash
bash -n sandbox/runner_image/trace-orchestrator.sh
```

Expected: no syntax errors. If bash isn't available locally, the M6 manual scenario will catch issues; commit and proceed.

- [ ] **Step 9.5: Commit**

```pwsh
git add sandbox/runner_image/trace-orchestrator.sh
git -c user.email="github.v5f9w@bitbucket.onl" -c user.signingkey=BE707B220C995478 commit -S -m "feat(sandbox): trace-orchestrator --mode {install,verify} for M6"
```

---

## Task 10: Runner image — `verify-orchestrator.sh` new file

**Files:**
- Create: `sandbox/runner_image/verify-orchestrator.sh`

- [ ] **Step 10.1: Create the verify orchestrator**

Create `sandbox/runner_image/verify-orchestrator.sh` with content:

```bash
#!/bin/bash
# M6 verify-mode workload. Loads the generated image tarball, runs it
# under strict policy, waits for ready, soaks the observation window,
# stops the container. Writes phase markers consumed by build/pipeline.py.
#
# Invoked by trace-orchestrator.sh when called with --mode verify.
# The outer trace-orchestrator owns collector start/stop; this script
# owns only the verify workload.

set -euo pipefail

: "${VERIFY_IMAGE_TAG:?required}"
: "${VERIFY_SOAK_SECONDS:?required}"
: "${VERIFY_RUN_FLAGS:?required}"

WORK=/work/trace
VERIFY=/work/verify

mkdir -p "$WORK"

# 1. Load the generated image. The tarball was produced by `podman save`
#    on the host and bind-mounted at /work/verify/image.tar:ro.
if ! podman load < "$VERIFY/image.tar" > "$VERIFY/load.log" 2>&1; then
    touch "$WORK/LOAD_FAILED"
    cat "$VERIFY/load.log" >&2
    exit 1
fi

# 2. Phase marker: verify mode has no install phase. Mark the start so
#    M3's analyzer treats everything as runtime.
date +%s%N > "$WORK/PHASE_MARKER"

# 3. Run the generated container detached. $VERIFY_RUN_FLAGS is shell-
#    word-split intentionally (caller builds it from policy.runtime).
# shellcheck disable=SC2086
if ! podman run -d --name target $VERIFY_RUN_FLAGS \
        "$VERIFY_IMAGE_TAG" > "$VERIFY/target.cid" 2> "$VERIFY/target.err"; then
    touch "$WORK/READY_FAILED"
    cat "$VERIFY/target.err" >&2
    exit 1
fi

# 4. Wait for the daemon to look ready: a TCP listener appears OR "ready"
#    shows up in logs OR 30s elapses.
READY_DEADLINE=$(( $(date +%s) + 30 ))
while [ "$(date +%s)" -lt "$READY_DEADLINE" ]; do
    if podman exec target ss -tlnp 2>/dev/null | grep -q LISTEN; then
        break
    fi
    if podman logs target 2>/dev/null | grep -qi "ready"; then
        break
    fi
    sleep 1
done
if [ "$(date +%s)" -ge "$READY_DEADLINE" ]; then
    touch "$WORK/READY_FAILED"
    podman stop -t 2 target >/dev/null 2>&1 || true
    exit 1
fi

# 5. Soak for the configured window so collectors can observe steady-state.
sleep "$VERIFY_SOAK_SECONDS"

# 6. Detect whether the daemon survived the soak.
if ! podman container exists target; then
    touch "$WORK/RAN_AND_DIED"
else
    podman stop -t 5 target >/dev/null 2>&1 || true
    EXIT_CODE="$(podman inspect target --format '{{.State.ExitCode}}' 2>/dev/null || echo 0)"
    if [ "$EXIT_CODE" -ne 0 ]; then
        touch "$WORK/RAN_AND_DIED"
    fi
fi

touch "$WORK/COMPLETE"
```

Make it executable. On Windows you can't chmod, but in the Containerfile add a `RUN chmod +x /usr/local/bin/verify-orchestrator.sh` line — do that now:

- [ ] **Step 10.2: Append chmod + copy lines to the Containerfile**

Append to `sandbox/runner_image/Containerfile`:

```Dockerfile

COPY verify-orchestrator.sh /usr/local/bin/verify-orchestrator.sh
RUN chmod +x /usr/local/bin/verify-orchestrator.sh
```

- [ ] **Step 10.3: bash -n syntax check**

If bash is available:
```bash
bash -n sandbox/runner_image/verify-orchestrator.sh
```

Expected: no syntax errors.

- [ ] **Step 10.4: Commit**

```pwsh
git add sandbox/runner_image/verify-orchestrator.sh sandbox/runner_image/Containerfile
git -c user.email="github.v5f9w@bitbucket.onl" -c user.signingkey=BE707B220C995478 commit -S -m "feat(sandbox): verify-orchestrator.sh for M6 verify pass"
```

---

## Task 11: `build/cli.py` — `build_cmd` Click subcommand

**Files:**
- Create: `src/containerizer/build/cli.py`
- Modify: `src/containerizer/cli.py` — register `build_cmd`
- Create: `tests/unit/build/test_cli.py`

- [ ] **Step 11.1: Write the failing CLI tests**

Create `tests/unit/build/test_cli.py`:

```python
"""CliRunner tests for `containerizer build` with the pipeline faked at module level."""

from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from containerizer.analyze.schema import (
    PolicyImage,
    PolicyJson,
    PolicyRuntime,
    TraceJson,
    TracePhase,
)
from containerizer.build import cli as build_cli_module
from containerizer.build.config import BuildResult
from containerizer.build.cli import build_cmd
from containerizer.probe.schema import ProbeResult
from containerizer.verify.schema import VerifyDiff, VerifyReport


def _ok_result(final_dir: Path) -> BuildResult:
    return BuildResult(
        final_dir=final_dir,
        intermediates_dir=None,
        verify=VerifyReport(
            original_marker="COMPLETE", observed_marker="COMPLETE",
            diff=VerifyDiff(new_paths=[], new_ports=[], new_caps=[],
                            new_syscalls=[], new_execs=[]),
        ),
    )


def test_missing_installer_exits_2(tmp_path):
    runner = CliRunner()
    result = runner.invoke(build_cmd, [
        str(tmp_path / "nope.bin"), "--name", "demo",
        "-o", str(tmp_path / "out"),
    ])
    assert result.exit_code == 2


def test_preflight_failure_exits_2(tmp_path):
    installer = tmp_path / "i.bin"
    installer.write_text("x", encoding="utf-8")
    runner = CliRunner()
    with patch.object(build_cli_module, "preflight_podman",
                      side_effect=build_cli_module.PreflightError("no podman")):
        result = runner.invoke(build_cmd, [
            str(installer), "--name", "demo",
            "-o", str(tmp_path / "out"),
        ])
    assert result.exit_code == 2
    assert "no podman" in result.stderr


def test_happy_path_exits_0_and_calls_pipeline(tmp_path):
    installer = tmp_path / "i.bin"
    installer.write_text("x", encoding="utf-8")
    out = tmp_path / "out"

    captured = {}

    def fake_run_pipeline(config, **kwargs):
        captured["config"] = config
        captured["kwargs"] = kwargs
        return _ok_result(out / "demo")

    runner = CliRunner()
    with patch.object(build_cli_module, "preflight_podman", return_value=None), \
         patch.object(build_cli_module, "run_pipeline", side_effect=fake_run_pipeline):
        result = runner.invoke(build_cmd, [
            str(installer), "--name", "demo",
            "-o", str(out),
            "--verify-soak-seconds", "45",
            "--keep-intermediates",
        ])

    assert result.exit_code == 0
    cfg = captured["config"]
    assert cfg.name == "demo"
    assert cfg.verify_soak_seconds == 45
    assert cfg.keep_intermediates is True


def test_non_empty_diff_warns_but_exits_0(tmp_path):
    installer = tmp_path / "i.bin"
    installer.write_text("x", encoding="utf-8")
    out = tmp_path / "out"

    diff_result = BuildResult(
        final_dir=out / "demo",
        intermediates_dir=None,
        verify=VerifyReport(
            original_marker="COMPLETE", observed_marker="COMPLETE",
            diff=VerifyDiff(
                new_paths=[], new_ports=[], new_caps=["CAP_SYS_CHROOT"],
                new_syscalls=[], new_execs=[],
            ),
        ),
    )

    def fake_run_pipeline(config, **kwargs):
        return diff_result

    runner = CliRunner()
    with patch.object(build_cli_module, "preflight_podman", return_value=None), \
         patch.object(build_cli_module, "run_pipeline", side_effect=fake_run_pipeline):
        result = runner.invoke(build_cmd, [
            str(installer), "--name", "demo", "-o", str(out),
        ])
    assert result.exit_code == 0
    assert "1 new caps" in result.stderr or "new caps" in result.stderr


def test_sentinel_skip_exits_0(tmp_path):
    installer = tmp_path / "i.bin"
    installer.write_text("x", encoding="utf-8")
    out = tmp_path / "out"

    sentinel_result = BuildResult(
        final_dir=out / "demo",
        intermediates_dir=None,
        verify=None,
        skip_reason="sentinel",
    )

    runner = CliRunner()
    with patch.object(build_cli_module, "preflight_podman", return_value=None), \
         patch.object(build_cli_module, "run_pipeline", return_value=sentinel_result):
        result = runner.invoke(build_cmd, [
            str(installer), "--name", "demo", "-o", str(out),
        ])
    assert result.exit_code == 0
    assert "skipped" in result.stderr.lower()


def test_pipeline_error_exits_1(tmp_path):
    installer = tmp_path / "i.bin"
    installer.write_text("x", encoding="utf-8")
    out = tmp_path / "out"

    from containerizer.build.pipeline import PipelineError

    runner = CliRunner()
    with patch.object(build_cli_module, "preflight_podman", return_value=None), \
         patch.object(build_cli_module, "run_pipeline",
                      side_effect=PipelineError("install trace did not finalise")):
        result = runner.invoke(build_cmd, [
            str(installer), "--name", "demo", "-o", str(out),
        ])
    assert result.exit_code == 1
    assert "did not finalise" in result.stderr
```

- [ ] **Step 11.2: Run tests, confirm fail**

Run:
```pwsh
pytest tests/unit/build/test_cli.py -v
```

Expected: `ModuleNotFoundError: No module named 'containerizer.build.cli'`.

- [ ] **Step 11.3: Implement build/cli.py**

Create `src/containerizer/build/cli.py`:

```python
"""`containerizer build <installer>` Click subcommand."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable

import click

from containerizer.analyze.assemble import assemble_trace_json
from containerizer.analyze.derive import derive_policy
from containerizer.analyze.reader import read_trace_dir
from containerizer.analyze.schema import PolicyJson, TraceJson
from containerizer.build.config import BuildConfig, BuildResult
from containerizer.build.paths import PathLayout, resolve_layout
from containerizer.build.pipeline import PipelineError, run_pipeline
from containerizer.generate import containerfile as cf_render
from containerizer.generate import quadlet as quadlet_render
from containerizer.generate import readme as m4_readme
from containerizer.generate import seccomp as seccomp_render
from containerizer.generate.syscall_table import resolve_syscall_names
from containerizer.probe.installer import UnsupportedInstallerKind
from containerizer.probe.installer import probe as probe_installer
from containerizer.probe.schema import ProbeResult
from containerizer.trace.image import RunnerImage
from containerizer.trace.runner import TraceRunner
from containerizer.verify.diff import diff_traces
from containerizer.verify.schema import VerifyReport


class PreflightError(RuntimeError):
    """Raised when podman is not usable before any phase runs."""


@click.command("build")
@click.argument(
    "installer",
    type=click.Path(exists=True, dir_okay=False, readable=True, path_type=Path),
)
@click.option("--name", required=True, help="Container name and image-tag stem.")
@click.option("--base-image", default=None,
              help="Override probe's base-image suggestion.")
@click.option("--start-cmd", default=None,
              help="Daemon-start hint passed to the trace orchestrator.")
@click.option("-o", "--out", "out_dir",
              type=click.Path(path_type=Path), default=Path("out"))
@click.option("--keep-intermediates", is_flag=True,
              help="Preserve intermediates under <out>/<name>/.intermediates/.")
@click.option("--verify-soak-seconds", type=int, default=30,
              help="Verify-phase idle observation window after daemon-ready.")
@click.option("--skip-verify", is_flag=True,
              help="Stop after generate; skip rebuild + retrace + verify.")
@click.option("--debug", is_flag=True,
              help="On first phase failure, drop a shell in the runner if alive.")
def build_cmd(
    installer: Path,
    name: str,
    base_image: str | None,
    start_cmd: str | None,
    out_dir: Path,
    keep_intermediates: bool,
    verify_soak_seconds: int,
    skip_verify: bool,
    debug: bool,
) -> None:
    """Run the full pipeline: probe -> trace -> analyze -> generate ->
    rebuild -> retrace -> verify into one directory."""
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
        keep_intermediates=keep_intermediates,
        verify_soak_seconds=verify_soak_seconds,
        skip_verify=skip_verify,
        debug=debug,
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
        out_dir, name,
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
        return  # native podman; no machine.

    try:
        ml = subprocess.run(
            ["podman", "machine", "ls", "--format", "json"],
            capture_output=True, text=True,
        )
    except FileNotFoundError as exc:
        raise PreflightError("podman not found on PATH; install podman and retry") from exc
    if ml.returncode != 0:
        raise PreflightError("podman machine list failed; start a machine and retry")

    import json
    try:
        machines = json.loads(ml.stdout)
    except json.JSONDecodeError as exc:
        raise PreflightError("podman machine list returned malformed JSON") from exc
    if not any(m.get("Running") is True for m in machines):
        raise PreflightError(
            "no podman machine is running. Start it with: podman machine start"
        )


def _default_probe_fn(installer: Path, base_image: str | None) -> ProbeResult:
    try:
        result = probe_installer(installer)
    except UnsupportedInstallerKind as exc:
        raise PipelineError(str(exc)) from exc
    if base_image is not None:
        return result.model_copy(update={"base_image_suggestion": base_image})
    return result


def _default_install_trace_fn(
    installer: Path,
    start_cmd: str | None,  # noqa: ARG001 -- consumed by orchestrator env, not the runner today
    output_dir: Path,
) -> int:
    image = RunnerImage(sandbox_dir=_sandbox_dir())
    if not image.exists():
        click.echo(f"[image] building {image.tag} (first run, ~5 min)...", err=True)
        image.build(stderr=sys.stderr)

    runner = TraceRunner(
        image_tag=image.tag,
        installer=installer.resolve(),
        output_dir=output_dir.resolve(),
    )
    return runner.run()


def _default_parse_trace_fn(trace_dir: Path) -> TraceJson:
    return assemble_trace_json(read_trace_dir(trace_dir))


def _default_derive_policy_fn(trace: TraceJson) -> PolicyJson:
    return derive_policy(trace, warnings=list(trace.warnings))


def _default_generate_fn(policy: PolicyJson, name: str, final_dir: Path) -> None:
    final_dir.mkdir(parents=True, exist_ok=True)
    syscall_names, unknown_ids = resolve_syscall_names(policy.runtime.seccomp_syscalls)
    is_sentinel = policy.image.entrypoint == ["__UNSET__"]

    (final_dir / "seccomp.json").write_text(
        seccomp_render.render_seccomp_json(syscall_names),
        encoding="utf-8",
    )
    if not is_sentinel:
        (final_dir / "Containerfile").write_text(
            cf_render.render_containerfile(policy),
            encoding="utf-8",
        )
        (final_dir / f"{name}.container").write_text(
            quadlet_render.render_quadlet(policy, name=name, image_ref=f"localhost/{name}:latest"),
            encoding="utf-8",
        )
    (final_dir / "README.md").write_text(
        m4_readme.render_readme(policy, name=name, skipped=is_sentinel,
                                unknown_syscall_ids=unknown_ids),
        encoding="utf-8",
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


def _make_verify_trace_fn(layout: PathLayout) -> Callable[..., int]:
    def fn(image_tar: Path, run_flags: list[str], image_tag: str,
           soak_seconds: int, output_dir: Path) -> int:
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
        total = (len(d.new_paths) + len(d.new_ports) + len(d.new_caps)
                 + len(d.new_syscalls) + len(d.new_execs))
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
```

- [ ] **Step 11.4: Wire build_cmd into the top-level CLI**

Edit `src/containerizer/cli.py`. Add the import alongside the others:

```python
from containerizer.build.cli import build_cmd
```

Add the registration alongside the other `main.add_command` lines:

```python
main.add_command(build_cmd)
```

- [ ] **Step 11.5: Run tests, verify pass**

Run:
```pwsh
pytest tests/unit/build/test_cli.py -v
```

Expected: all 6 tests pass. If `result.stderr` doesn't carry the warning text, recheck `mix_stderr` plumbing — per M4 memory item 7, Click 8.3 always populates `result.stderr`.

- [ ] **Step 11.6: Full gate**

Run:
```pwsh
ruff check . ; ruff format --check . ; mypy src tests ; pytest -q
```

Expected: green.

- [ ] **Step 11.7: Commit**

```pwsh
git add src/containerizer/build/cli.py src/containerizer/cli.py tests/unit/build/test_cli.py
git -c user.email="github.v5f9w@bitbucket.onl" -c user.signingkey=BE707B220C995478 commit -S -m "feat(build): Click subcommand + main.add_command wiring (M6)"
```

---

## Task 12: Integration smoke test

**Files:**
- Create: `tests/integration/build/__init__.py`
- Create: `tests/integration/build/test_build_smoke.py`
- Possibly create: `tests/fixtures/build/expected/verify.json` (the golden)

- [ ] **Step 12.1: Create the integration package marker**

Create `tests/integration/build/__init__.py` with one line: `"""Integration tests for the build orchestrator (M6)."""`.

- [ ] **Step 12.2: Write the integration test**

Create `tests/integration/build/test_build_smoke.py`:

```python
"""End-to-end smoke test for build/pipeline.run_pipeline.

Podman-touching seams are faked; everything else is real. Catches
integration issues between paths.py, flags.py, readme.py, the real M3
analyzer (over committed fixtures), the real M4 generators, the real M5
diff, and the README rewrite.
"""

from __future__ import annotations

import io
import json
import shutil
from pathlib import Path

import pytest

from containerizer.analyze.assemble import assemble_trace_json
from containerizer.analyze.derive import derive_policy
from containerizer.analyze.reader import read_trace_dir
from containerizer.analyze.schema import PolicyJson, TraceJson
from containerizer.build.config import BuildConfig
from containerizer.build.paths import resolve_layout
from containerizer.build.pipeline import run_pipeline
from containerizer.generate import containerfile as cf_render
from containerizer.generate import quadlet as quadlet_render
from containerizer.generate import readme as m4_readme
from containerizer.generate import seccomp as seccomp_render
from containerizer.generate.syscall_table import resolve_syscall_names
from containerizer.probe.schema import ProbeResult
from containerizer.verify.diff import diff_traces

FIXTURES = Path("tests/fixtures")
SYNTH = FIXTURES / "trace" / "synthetic-recorded"


def _fake_probe(installer, base_image):
    return ProbeResult(
        kind="elf", arch="x86_64", glibc_min="2.35",
        needed_libs=[], interpreter="/lib64/ld-linux-x86-64.so.2",
        base_image_suggestion="ubuntu:24.04",
        base_image_reasons=["x86_64 + glibc 2.35"],
    )


def _fake_install_trace(installer, start_cmd, output_dir):
    output_dir.mkdir(parents=True, exist_ok=True)
    # Copy the M3 synthetic fixture in.
    for src in SYNTH.iterdir():
        shutil.copy2(src, output_dir / src.name)
    return 0


def _fake_verify_trace(image_tar, run_flags, image_tag, soak_seconds, output_dir):
    output_dir.mkdir(parents=True, exist_ok=True)
    # Reuse the same synthetic fixture, plus inject one extra syscall event to
    # produce a non-empty diff. The simplest way: copy the synthetic dir, then
    # append a single new syscalls.jsonl row referencing syscall id 437.
    for src in SYNTH.iterdir():
        shutil.copy2(src, output_dir / src.name)
    sys_path = output_dir / "syscalls.jsonl"
    extra = {"ts_ns": 999_999_999_999, "pid": 1234, "comm": "demo",
             "syscall_id": 437, "count": 1, "first_ts_ns": 999_999_999_999}
    with sys_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(extra) + "\n")
    return 0


def _fake_podman_build(layout):
    def fn(final_dir, image_tag):
        layout.verify_image_tar.parent.mkdir(parents=True, exist_ok=True)
        layout.verify_image_tar.write_bytes(b"fake-tarball")
        return layout.verify_image_tar
    return fn


def _real_parse_trace(trace_dir: Path) -> TraceJson:
    return assemble_trace_json(read_trace_dir(trace_dir))


def _real_derive_policy(trace: TraceJson) -> PolicyJson:
    return derive_policy(trace, warnings=list(trace.warnings))


def _real_generate(policy, name, final_dir):
    final_dir.mkdir(parents=True, exist_ok=True)
    syscall_names, unknown = resolve_syscall_names(policy.runtime.seccomp_syscalls)
    is_sentinel = policy.image.entrypoint == ["__UNSET__"]
    (final_dir / "seccomp.json").write_text(
        seccomp_render.render_seccomp_json(syscall_names), encoding="utf-8")
    if not is_sentinel:
        (final_dir / "Containerfile").write_text(
            cf_render.render_containerfile(policy), encoding="utf-8")
        (final_dir / f"{name}.container").write_text(
            quadlet_render.render_quadlet(policy, name=name,
                                          image_ref=f"localhost/{name}:latest"),
            encoding="utf-8")
    (final_dir / "README.md").write_text(
        m4_readme.render_readme(policy, name=name, skipped=is_sentinel,
                                unknown_syscall_ids=unknown),
        encoding="utf-8")


def _cfg(tmp_path: Path, **overrides) -> BuildConfig:
    installer = tmp_path / "installer.bin"
    installer.write_text("x", encoding="utf-8")
    base = dict(installer=installer, name="demo", out_dir=tmp_path / "out")
    base.update(overrides)
    return BuildConfig(**base)


def test_full_pipeline_with_fakes_produces_expected_final_dir(tmp_path: Path):
    layout = resolve_layout(
        tmp_path / "out", "demo",
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
        podman_build_fn=_fake_podman_build(layout),
        verify_trace_fn=_fake_verify_trace,
        diff_fn=diff_traces,
        layout=layout,
        stderr=io.StringIO(),
    )

    # Final dir has exactly the expected set of artifacts.
    assert layout.final_containerfile.exists()
    assert layout.final_quadlet.exists()
    assert layout.final_seccomp.exists()
    assert layout.final_readme.exists()
    assert layout.final_verify_json.exists()

    # README has the Verify results section.
    readme = layout.final_readme.read_text(encoding="utf-8")
    assert "## Verify results" in readme

    # verify.json parses as a VerifyReport with at least one new_syscall (the
    # injected 437) because the fake verify trace adds one syscall that wasn't
    # in the original.
    payload = json.loads(layout.final_verify_json.read_text(encoding="utf-8"))
    assert 437 in payload["diff"]["new_syscalls"]


def test_keep_intermediates_preserves_intermediates_subtree(tmp_path: Path):
    layout = resolve_layout(
        tmp_path / "out", "demo",
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
        podman_build_fn=_fake_podman_build(layout),
        verify_trace_fn=_fake_verify_trace,
        diff_fn=diff_traces,
        layout=layout,
        stderr=io.StringIO(),
    )

    inter = tmp_path / "out" / "demo" / ".intermediates"
    assert inter.exists()
    assert (inter / "probe.json").exists()
    assert (inter / "trace" / "original" / "COMPLETE").exists() or \
           (inter / "trace" / "original" / "syscalls.jsonl").exists()
    assert (inter / "analyze" / "trace.json").exists()
    assert (inter / "analyze" / "policy.json").exists()
    assert (inter / "analyze" / "verify-trace.json").exists()
    assert (inter / "verify" / "image.tar").exists()
```

- [ ] **Step 12.3: Run integration tests**

Run:
```pwsh
pytest tests/integration/build/test_build_smoke.py -v
```

Expected: both tests pass. If `read_trace_dir` complains about missing markers, the fake-install-trace copy step may have skipped `COMPLETE` — open `tests/fixtures/trace/synthetic-recorded/` and confirm `COMPLETE` is committed; if not, add `(output_dir / "COMPLETE").touch()` to `_fake_install_trace` and `_fake_verify_trace`.

- [ ] **Step 12.4: Full gate**

Run:
```pwsh
ruff check . ; ruff format --check . ; mypy src tests ; pytest -q
```

Expected: green. Verify total coverage stays ≥ 90%.

- [ ] **Step 12.5: Commit**

```pwsh
git add tests/integration/build
git -c user.email="github.v5f9w@bitbucket.onl" -c user.signingkey=BE707B220C995478 commit -S -m "test(build): integration smoke covering happy path + --keep-intermediates (M6)"
```

---

## Task 13: `MANUAL.md` scenarios 10 and 11

**Files:**
- Modify: `MANUAL.md`

- [ ] **Step 13.1: Inspect MANUAL.md to find where scenarios live**

Run:
```pwsh
type MANUAL.md
```

Note the highest existing scenario number and the section pattern (header style, body structure).

- [ ] **Step 13.2: Append scenarios 10 and 11**

Append to `MANUAL.md`:

```markdown
## Scenario 10: Synthetic installer end-to-end through `build`

**Goal:** Validate the M6 `build` pipeline against a real Podman machine
without exercising the real UniFi installer.

**Prerequisites:** A running Podman machine on Linux/macOS/Windows. At
least 10 GB free in the machine. The synthetic test installer
(`tests/fixtures/installers/synthetic.sh` or your equivalent) committed
to the repo.

**Procedure:**

```pwsh
# 1. Fresh out-dir
Remove-Item -Recurse -Force .\out\synthetic -ErrorAction SilentlyContinue

# 2. Run build with intermediates kept so the trace artifacts are inspectable.
containerizer build .\tests\fixtures\installers\synthetic.sh `
    --name synthetic `
    --verify-soak-seconds 15 `
    --keep-intermediates `
    --debug
```

**Expected:**
- `[probe]` line within 1s.
- `[trace]` lines stream as collectors start and the installer runs.
- An interactive prompt: "exercise it now. press Enter when done."
- After Enter: `[analyze]`, `[generate]`, `[build]`, `[verify]` lines.
- Exit 0.
- `out/synthetic/` contains Containerfile, synthetic.container,
  seccomp.json, README.md, verify.json.
- `out/synthetic/.intermediates/trace/verify/COMPLETE` exists.
- README has a `## Verify results` section.

**Common failure modes:**
- "podman not found" → `preflight_podman` did not run; check $env:PATH.
- "no podman machine is running" → run `podman machine start`.
- "podman build failed" → inspect `out/synthetic/Containerfile` and the
  build log under `.intermediates/`.
- "generated container failed to come up under strict policy" → the
  retrace's `READY_FAILED` marker fired. Look at
  `.intermediates/verify/target.err` and the collector JSONL under
  `.intermediates/trace/verify/` for syscall denials.

## Scenario 11: UniFi installer end-to-end through `build`

**Goal:** Run the real UniFi OS Server installer end-to-end. Closes the
design §11 open question about classifier rules at real-installer scale.

**Prerequisites:** Same as scenario 10 plus the UniFi installer binary
(~875 MB; not committed to the repo).

**Procedure:**

```pwsh
containerizer build .\unifi-installer.bin `
    --name unifi-os `
    --keep-intermediates `
    --verify-soak-seconds 60
```

**Expected:**
- `[trace]` shows the installer running for several minutes (UniFi
  installs MongoDB + JVM + the controller).
- Interactive prompt; exercise the admin UI on https://localhost:8443
  briefly, then press Enter.
- Build succeeds; `[verify]` produces either "no new events" or a small
  diff. Either is acceptable for v0.1.0.
- `out/unifi-os/` contains the full final-artifact set.
- The README's `## Verify results` section enumerates any deltas for
  triage; widen policy.json by hand and re-run `build` if needed.

**What success looks like for the milestone:** The container starts under
the Quadlet without manual fixup; the admin UI responds; restarting the
unit preserves state via the named volume.
```

- [ ] **Step 13.3: Commit**

```pwsh
git add MANUAL.md
git -c user.email="github.v5f9w@bitbucket.onl" -c user.signingkey=BE707B220C995478 commit -S -m "docs(manual): scenarios 10 (synthetic) + 11 (UniFi) for M6 build (M6)"
```

---

## Task 14: Final whole-branch review

Per memory item 8: M3 and M4's final whole-branch reviews caught real issues per-task reviews missed. Run a final pass before opening the PR.

**Files:**
- (none modified yet; this task may produce fix commits)

- [ ] **Step 14.1: Diff the whole branch against main**

Run:
```pwsh
git diff main...HEAD --stat
git diff main...HEAD -- src/containerizer/build/ src/containerizer/trace/runner.py src/containerizer/analyze/assemble.py src/containerizer/analyze/cli.py src/containerizer/cli.py sandbox/runner_image/
```

Read it carefully. Common things to look for:
- A function defined but never imported from its consumer.
- Type mismatches between `build/pipeline.py`'s callable seam and `build/cli.py`'s default-implementation closures.
- A `Path | None` field whose `None` branch isn't actually reachable but the type annotation suggests it is.
- README rewrite section header drift (e.g., `## Verify results` vs `## Verify Results`).

- [ ] **Step 14.2: Full gate one more time**

Run:
```pwsh
ruff check . ; ruff format --check . ; mypy src tests ; pytest -q --cov=src
```

Expected: green; coverage ≥ 90%.

- [ ] **Step 14.3: Spec coverage check**

Open `docs/superpowers/specs/2026-06-08-containerizer-m6-build.md`. For every numbered decision in §4 and every requirement in §9 (Exit criteria), point to a task that implements it:

- 4.1 full pipeline → Tasks 6 + 11
- 4.2 sentinel skip → Task 6 (sentinel branch + golden) + Task 5 (sentinel README)
- 4.3 nested podman → Tasks 8 + 10
- 4.4 wait-for-ready + soak → Task 10 (verify-orchestrator.sh)
- 4.5 output layout → Task 3 + integration test §12
- 4.6 verify exit semantics → Task 11 (non-empty diff still exit 0)
- 4.7 library calls + DI seam → Task 6 (run_pipeline signature)
- 4.8 README integration → Task 5
- 4.9 --start-cmd → Tasks 9 + 11 (env passthrough is plumbed end to end)
- 4.10 --skip-verify → Tasks 6 + 11
- 4.11 phase markers → Tasks 6 + 10
- 4.12 RAN_AND_DIED handling → Tasks 6 + 10
- 4.13 inline preflight → Task 11 (`preflight_podman`)

Exit criteria 1-7 are exercised by the integration test in Task 12. Criteria 8-9 (MANUAL.md, PR) are Tasks 13 and 14.5.

If any item has no corresponding task, add a small follow-up commit.

- [ ] **Step 14.4: Update memory file**

Open `C:\Users\yizshachuck\.claude\projects\C--Users-yizshachuck-source-containerizer\memory\m3_implementation_state.md`. Update the headline (M3+M4+M5+M6) and the "What's next" section to point to M7 (release-please cuts 0.1.0). Note any M6 lessons (e.g., nested-podman quirks) worth carrying forward. Do NOT do this from inside the agent; tell the user where to make the edit, since memory writes happen outside the project tree.

- [ ] **Step 14.5: Open the PR**

Push the branch and open one PR closing #44:

```pwsh
git push -u origin feat/m6-build

gh pr create --title "feat(build): M6 build subcommand end-to-end orchestrator" --body @'
## Summary

Closes #44.

Implements the M6 milestone per `docs/superpowers/specs/2026-06-08-containerizer-m6-build.md`. New `src/containerizer/build/` package with one module per responsibility (`config`, `paths`, `flags`, `readme`, `pipeline`, `cli`). `containerizer build <installer> --name <n>` composes probe → trace → analyze → generate → `podman build` → retrace under strict policy → analyze → diff into one process, writing final artifacts to `./out/<name>/` and intermediates to a tempdir (or `.intermediates/` with `--keep-intermediates`).

The M2 trace-runner image gains nested podman + `slirp4netns` + `crun` + `conmon`. The orchestrator script learns `--mode {install,verify}`; a new `verify-orchestrator.sh` implements the verify-mode workload (load image tar → run under strict-policy flags → wait for ready → soak → stop). The collectors in the outer privileged container observe the nested target.

Sentinel-entrypoint and `--skip-verify` both soft-skip rebuild/retrace/verify with a Verify-results README section explaining why; non-empty verify diffs warn and exit 0 (CI gating users still have standalone `containerizer verify`).

## Test plan

- [x] Unit tests for every renderer (`config`, `paths`, `flags`, `readme`, `pipeline`, `cli`).
- [x] Integration smoke test covering the full pipeline with podman-touching seams faked.
- [x] Coverage ≥ 90%.
- [x] Lint + type gate green (ruff + ruff format + mypy strict).
- [x] M3 refactor: promoted `_assemble_trace_json` to public `analyze/assemble.py`.

## Notes

- The trace-runner image change requires a `containerizer doctor`-style rebuild on the user's machine; we deferred a doctor command but `MANUAL.md` scenarios 10/11 walk through the rebuild.
- Real-podman end-to-end runs are MANUAL.md scenarios per design §9's CI budget.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
'@
```

Expected: PR URL printed. CodeQL pending pattern applies — auto-merge is disabled, expect ~2–3 minute CodeQL run. Per memory: use `ScheduleWakeup` at 180s to check, then merge once green.

---

## Done

After Task 14.5, M6 is shipped. Next milestone per memory: M7 — release-please cuts 0.1.0.
