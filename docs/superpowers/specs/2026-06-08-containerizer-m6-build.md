# M6 — `build` Subcommand Spec

**Date:** 2026-06-08
**Status:** Approved (brainstorming)
**Parent spec:** [`2026-06-06-containerizer-design.md`](./2026-06-06-containerizer-design.md)
**Prior milestone specs:** [`2026-06-07-containerizer-m4-generators.md`](./2026-06-07-containerizer-m4-generators.md), [`2026-06-08-containerizer-m5-verify.md`](./2026-06-08-containerizer-m5-verify.md)
**Milestone issues:** #44

## 1. Overview

M6 stands up the `build` subcommand as the default end-to-end UX:

```pwsh
PS> containerizer build .\unifi-installer.bin --name unifi-os
[probe]    elf x86_64, glibc 2.35+, base image suggestion: ubuntu:24.04
[trace]    starting trace-runner; running installer (this can take a while)...
[trace]    installer complete. starting daemon.
[trace]    daemon ready on tcp:8443. exercise it now. press Enter when done.
[trace]    finalising trace... 14 paths, 6 ports, 38 syscalls
[analyze]  trace.json + policy.json written
[generate] artifacts written to ./out/unifi-os/
[build]    podman build ./out/unifi-os/ -> unifi-os:m6-verify
[verify]   running generated image under strict policy (soak 30s)...
[verify]   no new events
[done]     ./out/unifi-os/
```

`build` orchestrates probe -> trace -> analyze -> generate -> `podman build` -> retrace under strict policy -> analyze -> diff into one Python process. Final artifacts land in `./out/<name>/`; intermediates default to a system tempdir cleaned on success.

M6 also delivers the M5 spec's promise that "the user gets the 'verify against the policy' UX in M6": the rebuild + retrace + diff loop the M5 standalone command deliberately omitted. The standalone `verify` subcommand keeps its diff-only contract unchanged.

## 2. Scope

### In M6

- `src/containerizer/build/` package: `cli.py`, `pipeline.py`, `config.py`, `paths.py`, `flags.py`, `readme.py`, `__init__.py`.
- `containerizer build <installer> --name <name>` CLI subcommand wired into the main group.
- `src/containerizer/sandbox/runner_image/Containerfile`: add podman + nested-podman dependencies.
- `src/containerizer/sandbox/runner_image/trace-orchestrator.sh`: gain a `--mode {install,verify}` flag.
- `src/containerizer/sandbox/runner_image/verify-orchestrator.sh`: NEW, runs the generated image under strict policy with a soak window.
- `src/containerizer/trace/runner.py`: `TraceRunner` gains a `mode: Literal["install", "verify"]` parameter. Install mode preserves all M2 behavior.
- `tests/unit/build/` and `tests/integration/build/`.
- `tests/fixtures/build/` with golden README variants and a golden verify.json.
- MANUAL.md scenarios 10 (synthetic end-to-end) and 11 (UniFi end-to-end).

### Out of M6 (deferred)

- `doctor` subcommand. No issue currently tracks it; M6 ships a single inline preflight (`podman --version`, machine running on Win/Mac).
- `--smoke-cmd` for scripted exercise during the install trace. Parent design §11.
- Auto-relaxation of `policy.json` from verify diffs. Parent design §11 open question. M6 reports; future milestone could propose patches.
- A standalone "rebuild and retrace" mode of the `verify` subcommand. The rebuild loop lives only inside `build`. The standalone `verify` command keeps its M5 diff-only contract.
- `--strict` / `--fail-on-diff` flag to make `build` exit non-zero on a non-empty verify diff. Standalone `verify` already exits 1 on diff for users who want CI gating.
- CI integration test that touches real podman. End-to-end-with-real-podman runs stay in MANUAL.md per design §9's CI budget.
- Cross-architecture / arm64 / image signing — design §12, same as every prior milestone.

### Carried unchanged from parent and prior specs

- Per-phase subcommands (`probe`, `trace`, `analyze`, `generate`, `verify`) continue to exist for iteration and debugging (parent §5.1).
- Standalone `verify` is diff-only (M5 §2).
- M4's sentinel-entrypoint behavior (`policy.image.entrypoint == ["__UNSET__"]` skips Containerfile + Quadlet but still emits seccomp.json + README.md).
- Pure-function pattern: only `cli.py`-style modules touch disk and subprocess; everything else is `(input: PydanticModel, ...) -> ...` (parent §5.6 / §5.7, M4 / M5 precedent).

## 3. Reading guide

This spec narrows parent design §4.1 (the `build` CLI sketch) and §5.1 (the `verify` description that the M5 spec deferred). Where this spec is silent, the parent is authoritative. Where it contradicts, this spec wins for M6.

The parent's §5.1 wording for `verify` ("rebuild and run the generated image briefly under strict policy") was split across M5 and M6 in the M5 spec's §1: M5 owns the diff; M6 owns the rebuild + retrace. This spec finishes that split by specifying the M6 half.

## 4. Decisions captured from the M6 brainstorm

| # | Decision | Choice | Rationale |
|---|----------|--------|-----------|
| 4.1 | M6 scope | Full pipeline: orchestrate + rebuild + retrace + verify. | Closes M6 as originally framed in design §5.1 and matches the M5 spec's "M6 wires it into the end-to-end pipeline" promise. The retrace work is genuinely new but reuses M2/M3/M5 components without duplication. |
| 4.2 | Sentinel handling | On `policy.image.entrypoint == ["__UNSET__"]`, soft-skip phases 5/6/7 and exit 0. README is rewritten with a "verify skipped: no entrypoint" section. | Mirrors M4's existing sentinel branch (M4 also soft-skips Containerfile + Quadlet on sentinel). The artifact dir is honest about what's missing without losing the parts that did work. |
| 4.3 | Retrace mechanism | Nested podman inside the existing M2 trace-runner. Extend the fedora:40 runner image with `podman`, `slirp4netns`, `crun`, `conmon`. The trace orchestrator gains a verify mode; collectors live in the outer (privileged) container and observe the nested process tree. | Reuses every M2 component (collectors, JSONL layout, PHASE_MARKER). Sibling-container topology was rejected as a brand-new sandbox plumbing path; dedicated-verify-image was rejected as redundant infrastructure. |
| 4.4 | Verify smoke pattern | Wait-for-ready (reusing M2's daemon-ready detection: port-bound or "ready" log line, configurable timeout) followed by a fixed idle soak (default 30s, `--verify-soak-seconds` to override). No user interaction in verify mode. | Validates the generated container starts under strict policy and survives idle without doubling the human time investment. The policy-too-tight failure mode shows up as a daemon-not-ready timeout (`READY_FAILED` marker). |
| 4.5 | Output layout | Final artifacts in `./out/<name>/`: `Containerfile`, `<name>.container`, `seccomp.json`, `README.md`, `verify.json`. Intermediates default to a system tempdir cleaned on success. `--keep-intermediates` moves them under `./out/<name>/.intermediates/` and preserves them. | Matches design §6 intent: artifacts are what the user deploys; intermediates are debug-only. verify.json belongs with the deployed artifacts because it's the audit trail. |
| 4.6 | Verify exit semantics | Non-empty verify diff is a warning, not a failure. `build` exits 0 with a stderr warning, README "Verify results" section listing the deltas, and a populated verify.json. CI gating users invoke standalone `containerizer verify` (M5) which still exits 1 on diff. | `build`'s success criterion is "I produced deployable artifacts." A diff is advisory; the artifacts themselves are valid. |
| 4.7 | Orchestrator pattern | Library calls. `build/cli.py` is the thin Click layer; `build/pipeline.py` composes the 7 phases through a dependency-injection seam (each phase passed in as a callable). Defaults wire to real implementations; tests inject fakes. | Type-checked boundaries, single Python process, fast iteration, clean error propagation. Mirrors the M4/M5 cli.py orchestrator pattern one layer up. Subprocess-per-phase was rejected as slow and harder to test. Refactoring earlier milestones' cli.py into thin shims was rejected as a too-large blast radius for one milestone. |
| 4.8 | README integration | M6 rewrites M4's README in-place by string patching, appending a "Verify results" section (or one-line "no new events" / "skipped" variant) before any trailing "Warnings" section. Idempotent. | Re-rendering from scratch would duplicate M4's renderer logic in M6; string patching keeps the M4 renderer unchanged and the M6 layer focused on its delta. |
| 4.9 | `--start-cmd` flag | Expose `--start-cmd <cmd>` on `build`, pass through to the trace orchestrator as a hint when daemon auto-detect would otherwise fall back to the sentinel. | Lets users avoid sentinel proactively when they know the daemon command; doesn't change behavior when the orchestrator successfully auto-detects. |
| 4.10 | `--skip-verify` flag | Stop after generate. Same UX as M4 standalone. README gets a "verify skipped (--skip-verify)" section. | For tight iteration on generate output; matches the standalone behavior the user already knows. |
| 4.11 | Phase markers in verify mode | `verify-orchestrator.sh` writes `PHASE_MARKER` at start (no install phase exists). M3's analyzer interprets the whole trace as runtime when marker timestamp equals trace start. Additional markers `READY_FAILED`, `RAN_AND_DIED`, `LOAD_FAILED` capture verify-specific failure modes. | Keeps the JSONL contract identical between install and verify modes so M3's analyzer needs no mode awareness. |
| 4.12 | `RAN_AND_DIED` handling | If the generated container exits non-zero mid-soak, finalize collectors normally, run analyze + diff against the partial trace, surface the marker in `verify.warnings` and README, exit 0. | The verify trace is still informative — likely captures the syscall denial that killed the daemon. Refusing to compare would waste the captured data. |
| 4.13 | Preflight scope | One inline check (`podman --version`, machine running on Win/Mac) at CLI entry. No `doctor` subcommand in M6. | The `doctor` work has no current issue and is out of scope. Inline preflight is enough to fail fast before any runner-image build. |

## 5. Components

### 5.1 Package layout

```
src/containerizer/build/
  __init__.py        # "Containerizer build orchestrator (M6)."
  cli.py             # `containerizer build` Click subcommand; the only module
                     # that does subprocess + disk orchestration directly.
  pipeline.py        # run_pipeline(config: BuildConfig, *, probe_fn,
                     #              install_trace_fn, parse_trace_fn,
                     #              derive_policy_fn, generate_fn,
                     #              podman_build_fn, verify_trace_fn, diff_fn)
                     #     -> BuildResult
                     # Composes the 7 phases. Pure given its injected callables.
  config.py          # BuildConfig + BuildResult Pydantic models (frozen,
                     # extra="forbid", schema_version=1).
  paths.py           # resolve_layout(out, name, keep_intermediates) -> PathLayout
                     # Pure. Per-phase subdirs, tempdir vs .intermediates/.
  flags.py           # podman_run_flags(policy: PolicyJson) -> list[str]
                     # Pure. Strict-policy `podman run` args from policy.runtime.
                     # Same flags the M4 quadlet renderer encodes declaratively,
                     # in argv form for the verify pass.
  readme.py          # rewrite_readme_with_verify(readme_text: str,
                     #                            verify: VerifyReport | None,
                     #                            skip_reason: str | None) -> str
                     # Pure. Appends a "Verify results" section to the M4 README.
                     # Idempotent.

src/containerizer/sandbox/runner_image/
  Containerfile           # MODIFIED: dnf install podman slirp4netns crun conmon
                          # fuse-overlayfs shadow-utils; pre-create rootless
                          # storage roots.
  trace-orchestrator.sh   # MODIFIED: --mode {install,verify} flag. Install mode
                          # unchanged. Verify mode runs verify-orchestrator.sh
                          # for the workload, shares collector start/stop.
  verify-orchestrator.sh  # NEW (~80 LOC bash):
                          #   podman load < /work/verify/image.tar
                          #   podman run --name target $VERIFY_RUN_FLAGS $TAG &
                          #   wait_for_ready (port-bound OR log "ready")
                          #   sleep $VERIFY_SOAK_SECONDS
                          #   podman stop target

src/containerizer/trace/
  runner.py          # MODIFIED: TraceRunner gains
                     #   mode: Literal["install", "verify"] = "install"
                     # and the corresponding env vars + mounts in verify mode.

src/containerizer/cli.py
                     # MODIFIED: add build_cmd to the main group.
```

Approximate LOC: cli ~120, pipeline ~200, config ~40, paths ~80, flags ~100, readme ~80 = ~620 LOC for new Python; ~150 LOC for bash; ~10 LOC Containerfile delta; plus tests.

### 5.2 `config.py`

```python
class BuildConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    installer: Path
    name: str
    out_dir: Path                 # default ./out resolved by caller
    base_image: str | None = None
    start_cmd: str | None = None
    keep_intermediates: bool = False
    verify_soak_seconds: int = 30
    skip_verify: bool = False
    debug: bool = False


class BuildResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    final_dir: Path                   # ./out/<name>/
    intermediates_dir: Path | None    # None if cleaned, Path if preserved
    verify: VerifyReport | None       # None if skipped
    skip_reason: Literal["sentinel", "flag"] | None = None
    warnings: list[str] = []
```

### 5.3 `paths.py`

`resolve_layout(out: Path, name: str, *, keep_intermediates: bool) -> PathLayout`. Pure. Returns a `PathLayout` dataclass exposing:

- `final_dir: Path` — `out / name`
- `intermediates_dir: Path` — tempdir path (created by caller) or `final_dir / ".intermediates"` if `keep_intermediates`
- `probe_json: Path`
- `trace_original_dir: Path`, `trace_verify_dir: Path`
- `analyze_trace_json: Path`, `analyze_policy_json: Path`, `analyze_verify_trace_json: Path`
- `verify_image_tar: Path`, `verify_seccomp_copy: Path`
- `final_containerfile: Path`, `final_quadlet: Path`, `final_seccomp: Path`, `final_readme: Path`, `final_verify_json: Path`

The tempdir itself is created by `cli.py` (which owns disk I/O); `paths.py` just computes the layout assuming whatever root path is passed in.

### 5.4 `flags.py`

`podman_run_flags(policy: PolicyJson) -> list[str]`. Pure. Returns the argv tail of a strict-policy `podman run` invocation derived from `policy.runtime`:

- `--cap-drop=ALL` (always)
- one `--cap-add=<CAP>` per `policy.runtime.caps_add` entry
- `--read-only` iff `policy.runtime.read_only_rootfs`
- `--security-opt no-new-privileges` iff `policy.runtime.no_new_privileges`
- `--security-opt seccomp=/work/verify/seccomp.json` (the path the bind-mount makes available)
- `--tmpfs <path>` per `policy.runtime.tmpfs` entry
- `-v <path>:<path>:ro` per `policy.runtime.binds_ro` entry
- `-v <volume_name>:<mount>` per `policy.runtime.volumes` entry (anonymous in verify mode — we don't persist data across verify runs)
- `-p <host>:<container>/<proto>` per `policy.runtime.publish_ports`

Returns `[]` for the sentinel entrypoint case (caller never invokes `flags.py` on the sentinel branch; this is defense-in-depth).

### 5.5 `readme.py`

`rewrite_readme_with_verify(readme_text: str, *, verify: VerifyReport | None, skip_reason: Literal["sentinel", "flag"] | None) -> str`. Pure.

Logic:
- If `verify is None and skip_reason is None`: return `readme_text` unchanged (shouldn't happen; defensive).
- If `skip_reason == "sentinel"`: insert/replace a "Verify results" section: "Verify skipped: no entrypoint detected; re-run with `--start-cmd '<cmd>'` to enable the verify pass."
- If `skip_reason == "flag"`: "Verify skipped: `--skip-verify` was set."
- If `verify is not None` and all `verify.diff.*` arrays are empty: "Verify results: no new events observed."
- If `verify is not None` and any array non-empty: full table section listing counts and first ~5 details per category (truncated with "..." if more).

Section is inserted before the trailing "## Warnings" section if present, else appended. Re-running on already-rewritten text replaces the existing "Verify results" section (idempotent).

### 5.6 `pipeline.py`

```python
def run_pipeline(
    config: BuildConfig,
    *,
    probe_fn: Callable[[Path, str | None], ProbeResult],
    install_trace_fn: Callable[[Path, str | None, Path], int],
    # (installer, start_cmd, output_dir) -> podman exit code;
    # the pipeline reads COMPLETE/PARTIAL markers from output_dir to
    # interpret the run.
    parse_trace_fn: Callable[[Path], TraceJson],
    # (trace_dir) -> TraceJson. JSONL + markers -> normalized trace.
    derive_policy_fn: Callable[[TraceJson], PolicyJson],
    # Install mode only. Verify mode reuses parse_trace_fn alone.
    generate_fn: Callable[[PolicyJson, str, Path], None],
    podman_build_fn: Callable[[Path, str], Path],
    # (final_dir, image_tag) -> image_tar path
    verify_trace_fn: Callable[[Path, list[str], str, int, Path], int],
    # (image_tar, run_flags, image_tag, soak_seconds, output_dir)
    #   -> podman exit code. Pipeline reads COMPLETE/READY_FAILED/
    #   RAN_AND_DIED/LOAD_FAILED markers from output_dir.
    diff_fn: Callable[[TraceJson, TraceJson], VerifyReport],
    layout: PathLayout,
    stderr: TextIO,
) -> BuildResult:
    ...
```

The pipeline does not create the tempdir, parse Click flags, or emit the stderr summary lines — `cli.py` owns those. The pipeline does write every intermediate JSON (probe.json, trace.json, policy.json, verify-trace.json) and every final artifact under `layout.final_dir` (verify.json, the rewritten README.md). Logically:

1. Call `probe_fn`, persist `probe.json`.
2. Call `install_trace_fn`. Inspect `layout.trace_original_dir` for `COMPLETE` / `PARTIAL` / neither; raise if neither, surface PARTIAL as a warning.
3. Call `parse_trace_fn(layout.trace_original_dir)` → `TraceJson`. Call `derive_policy_fn(trace_json)` → `PolicyJson`. Persist both.
4. Call `generate_fn(policy, name, layout.final_dir)` writing M4 artifacts.
5. Check sentinel (`policy.image.entrypoint == ["__UNSET__"]`); if sentinel, rewrite README with `skip_reason="sentinel"` and short-circuit.
6. Check `config.skip_verify`; if set, rewrite README with `skip_reason="flag"` and short-circuit.
7. Call `podman_build_fn(layout.final_dir, image_tag)`. Copy `layout.final_seccomp` to `layout.verify_seccomp_copy` so the bind-mount path in `flags.podman_run_flags` resolves.
8. Call `verify_trace_fn` with the tar, the result of `flags.podman_run_flags(policy)`, the image tag, soak seconds, and `layout.trace_verify_dir`. Inspect that dir for markers: `LOAD_FAILED` / `READY_FAILED` → raise; `RAN_AND_DIED` → continue with a warning; `COMPLETE` → continue clean.
9. Call `parse_trace_fn(layout.trace_verify_dir)` → verify `TraceJson`. (No `derive_policy_fn` call — verify mode has no install phase; policy derivation isn't meaningful.)
10. Call `diff_fn(original_trace_json, verify_trace_json)` → `VerifyReport`.
11. Write `verify.json` to `layout.final_verify_json`.
12. Rewrite README via `readme.rewrite_readme_with_verify(text, verify=report, skip_reason=None)`.
13. Return `BuildResult` with the populated `VerifyReport` and any warnings (e.g., the `RAN_AND_DIED` note).

**M3 refactor needed.** `analyze/cli.py` currently has a private `_assemble_trace_json(bundle: TraceBundle) -> TraceJson`. M6 promotes it to `analyze/derive.py` (or a new `analyze/assemble.py`) as a module-level public function, then `parse_trace_fn` defaults to `read_trace_dir + assemble_trace_json`. The existing `analyze_cmd` keeps the same behavior; this is a non-breaking factor-out.

### 5.7 `cli.py`

```python
@click.command("build")
@click.argument("installer", type=click.Path(exists=True, dir_okay=False,
                                             readable=True, path_type=Path))
@click.option("--name", required=True)
@click.option("--base-image", default=None)
@click.option("--start-cmd", default=None)
@click.option("-o", "--out", type=click.Path(path_type=Path), default=Path("out"))
@click.option("--keep-intermediates", is_flag=True)
@click.option("--verify-soak-seconds", type=int, default=30)
@click.option("--skip-verify", is_flag=True)
@click.option("--debug", is_flag=True)
def build_cmd(installer, name, base_image, start_cmd, out,
              keep_intermediates, verify_soak_seconds, skip_verify, debug):
    ...
```

`build_cmd` resolves the layout, ensures podman is reachable (preflight), creates the tempdir if `--keep-intermediates` is off, then invokes `run_pipeline` with the default phase-callables. On exception, prints the intermediates path and re-raises as `ClickException`.

### 5.8 Runner-image changes (sandbox/runner_image)

#### `Containerfile` additions

Appended after the existing bcc-tools layer:

```Dockerfile
RUN dnf install -y \
        podman \
        slirp4netns \
        fuse-overlayfs \
        crun \
        conmon \
        shadow-utils && \
    dnf clean all && \
    rm -rf /var/cache/dnf

RUN mkdir -p /var/lib/containers /var/lib/shared/overlay-images \
             /var/lib/shared/overlay-layers /var/lib/shared/vfs-images \
             /var/lib/shared/vfs-layers && \
    chmod 755 /var/lib/containers
```

The outer runner stays `--privileged` (M2 §5.3). Nested podman runs as root inside that privileged container; we explicitly do not stack rootless-in-rootless.

#### `trace-orchestrator.sh` changes

- Add `--mode install|verify` flag parsing. Default `install` preserves all M2 behavior.
- Collector start/stop framing is shared.
- In install mode, the workload portion is unchanged: run `/installer`, wait for daemon, wait for Enter, write `COMPLETE`/`PARTIAL`.
- In verify mode, the workload portion delegates to `verify-orchestrator.sh`.

#### `verify-orchestrator.sh` (new)

```bash
#!/bin/bash
set -euo pipefail

: "${VERIFY_IMAGE_TAG:?required}"
: "${VERIFY_SOAK_SECONDS:?required}"
: "${VERIFY_RUN_FLAGS:?required}"

WORK=/work/trace

# 1. Load the generated image.
if ! podman load < /work/verify/image.tar 2>/work/verify/load.log; then
    touch "$WORK/LOAD_FAILED"
    exit 1
fi

# 2. Write the phase marker immediately (verify mode has no install phase).
date +%s%N > "$WORK/PHASE_MARKER"

# 3. Run the generated container under strict policy.
podman run --name target -d $VERIFY_RUN_FLAGS "$VERIFY_IMAGE_TAG" \
    > /work/verify/target.cid 2>/work/verify/target.err

# 4. Wait for ready: any port bound OR "ready" in logs OR 30s timeout.
ready_deadline=$(( $(date +%s) + 30 ))
while [ "$(date +%s)" -lt "$ready_deadline" ]; do
    if podman exec target ss -tlnp 2>/dev/null | grep -q LISTEN; then
        break
    fi
    if podman logs target 2>/dev/null | grep -qi "ready"; then
        break
    fi
    sleep 1
done
if [ "$(date +%s)" -ge "$ready_deadline" ]; then
    touch "$WORK/READY_FAILED"
    podman stop -t 2 target || true
    exit 1
fi

# 5. Soak.
sleep "$VERIFY_SOAK_SECONDS"

# 6. Stop the generated container. If it already died, mark RAN_AND_DIED.
if ! podman container exists target; then
    touch "$WORK/RAN_AND_DIED"
else
    podman stop -t 5 target || true
    if [ "$(podman inspect target --format '{{.State.ExitCode}}' 2>/dev/null \
            || echo 0)" -ne 0 ]; then
        touch "$WORK/RAN_AND_DIED"
    fi
fi

touch "$WORK/COMPLETE"
```

The collectors in the outer container are started by `trace-orchestrator.sh` before this script runs and stopped after it returns. The collectors observe the nested process tree of `target` because the outer container is privileged.

### 5.9 `trace/runner.py` changes

`TraceRunner.__init__` gains `mode: Literal["install", "verify"] = "install"` and, in verify mode, the additional inputs: `image_tar: Path`, `image_tag: str`, `verify_run_flags: list[str]`, `verify_soak_seconds: int`, `seccomp_path: Path`.

In install mode the existing `podman run` invocation is unchanged.

In verify mode `podman run` is built with:
- `-v <image_tar>:/work/verify/image.tar:ro`
- `-v <seccomp_path>:/work/verify/seccomp.json:ro`
- `-e VERIFY_IMAGE_TAG=<image_tag>`
- `-e VERIFY_SOAK_SECONDS=<n>`
- `-e VERIFY_RUN_FLAGS=<shell-quoted list>`
- the orchestrator command `trace-orchestrator.sh --mode verify`
- no `-it` (non-interactive)

`VERIFY_RUN_FLAGS` is shell-quoted as a single env var because passing argv arrays through `-e` doesn't survive the shell; the verify-orchestrator unquotes it with `$VERIFY_RUN_FLAGS` (word-split intentional).

## 6. Data flow

```
                                installer
                                    │
                                    ▼
                            +-- probe_fn ----+
                            │  ProbeResult   │ ── write ──►  <tmp>/probe.json
                            +-------+--------+
                                    │
                                    ▼
                       +-- install_trace_fn ---+
                       │  TraceRunner install  │
                       │  <tmp>/trace/original/│
                       +-----------+-----------+
                                   │
                                   ▼
                       +-- parse_trace_fn -----+
                       │  TraceJson            │ ── write ──► <tmp>/analyze/trace.json
                       +-----------+-----------+
                                   │
                                   ▼
                       +-- derive_policy_fn ---+
                       │  PolicyJson           │ ── write ──► <tmp>/analyze/policy.json
                       +-----------+-----------+
                                   │
                                   ▼
                       +-- generate_fn --------+
                       │  M4 renderers         │ ── write ──► ./out/<name>/{Containerfile,
                       +-----------+-----------+                <name>.container,seccomp.json,
                                   │                              README.md}
                                   ▼
                         sentinel? --yes--> rewrite_readme_with_verify(skip="sentinel")
                                                                          │
                                                                          ▼
                                                                       return BuildResult
                                   │ no
                                   ▼
                         --skip-verify? --yes--> rewrite_readme_with_verify(skip="flag")
                                                                          │
                                                                          ▼
                                                                       return BuildResult
                                   │ no
                                   ▼
                       +-- podman_build_fn ----+
                       │  podman build         │
                       │  podman save -> tar   │ ── write ──► <tmp>/verify/image.tar
                       +-----------+-----------+
                                   │
                                   ▼
                       +-- verify_trace_fn ----+
                       │  TraceRunner verify   │ ── write ──► <tmp>/trace/verify/*.jsonl + markers
                       +-----------+-----------+
                                   │
                                   ▼
                       +-- parse_trace_fn -----+
                       │  TraceJson (verify)   │ ── write ──► <tmp>/analyze/verify-trace.json
                       │  (no derive_policy)   │
                       +-----------+-----------+
                                   │
                                   ▼
                       +-- diff_fn (M5) -------+
                       │  diff_traces(orig,obs)│ ── write ──► ./out/<name>/verify.json
                       │  -> VerifyReport      │
                       +-----------+-----------+
                                   │
                                   ▼
                       rewrite_readme_with_verify(verify=report) ──► ./out/<name>/README.md
                                   │
                                   ▼
                            BuildResult(verify=report, ...)
```

The `<tmp>/...` paths become `./out/<name>/.intermediates/...` when `--keep-intermediates` is set. On phase failure, `<tmp>` is preserved regardless of the flag.

## 7. Error and warning surfaces

| Phase | Failure | Behavior | Recovery prompt |
|---|---|---|---|
| preflight | `podman` not on PATH | exit 2 before any phase | "install podman, retry" |
| preflight | Podman machine not running (Win/Mac) | exit 2 | "podman machine start, retry" |
| 1. probe | `UnsupportedInstallerKind` | exit 1, preserve tempdir | "supply a supported installer; this kind isn't in M1's probe table" |
| 1. probe | Any other exception | exit 1, preserve tempdir | "tempdir at <path>" |
| 2. trace install | Runner-image build fails | stream build log, exit 1, preserve tempdir | "inspect <tmp>/runner-build.log; rerun with --debug" |
| 2. trace install | Sandbox container won't start | stream container logs, exit 1 | "rerun with --debug" |
| 2. trace install | Installer exits non-zero | preserve `install.log` + tempdir, exit 1 | "inspect <tmp>/trace/original/install.log" |
| 2. trace install | PARTIAL marker (user Ctrl-C'd) | continue, surface in README warnings | informational |
| 2. trace install | Neither COMPLETE nor PARTIAL written | exit 1, preserve tempdir | "trace did not finalise; inspect collector stderr" |
| 3. analyze original | Any analyzer exception | exit 1, preserve tempdir | "inspect raw JSONL at <tmp>/trace/original/" |
| 4. generate | Any renderer exception | exit 1, preserve tempdir; partial ./out/<name>/ left in place | "inspect <tmp>/analyze/policy.json" |
| 4a. sentinel | `entrypoint == ["__UNSET__"]` | soft-skip 5/6/7, rewrite README, exit 0 | "re-run with --start-cmd '<cmd>'" |
| 5. podman build | `podman build` non-zero | stream build log, exit 1, preserve tempdir | "inspect ./out/<name>/Containerfile; rerun with --debug" |
| 5. podman save | save fails | exit 1, preserve tempdir | "check disk space at TMPDIR" |
| 6. retrace | Runner won't start in verify mode | exit 1, preserve tempdir | "rerun with --debug" |
| 6. retrace | `READY_FAILED` marker | exit 1, preserve verify trace | "generated container failed to come up under strict policy; inspect <tmp>/trace/verify/" |
| 6. retrace | `RAN_AND_DIED` marker | continue to analyze + diff, surface in README, exit 0 with warning | "daemon exited during soak; check verify.json for syscall denials" |
| 6. retrace | `LOAD_FAILED` marker | exit 1, preserve tempdir | "podman save/load round-trip failed" |
| 7. analyze verify | Analyzer exception | exit 1, preserve tempdir | "verify retrace captured but analyzer failed" |
| 7. diff | `diff_traces` raises | exit 1, preserve tempdir; verify.json not written | "trace.json + verify-trace.json at <tmp>/analyze/" |
| 7. readme rewrite | README missing or unparseable | exit 1; verify.json preserved; original README intact | "verify.json was written but README rewrite failed; rerun build or hand-edit README" |
| any | `--debug` and any phase failed | drop a `podman exec -it <runner> /bin/bash` in the runner if one is still alive; else just preserve tempdir | "exit shell to fall through to normal cleanup" |

Invariants:
- Every non-zero exit preserves intermediates and prints the absolute path.
- `./out/<name>/` is never deleted by `build`. If generate succeeded, its output survives any later failure.
- The sentinel branch is exit 0. Same for `--skip-verify` and `RAN_AND_DIED`.

## 8. Testing strategy

### 8.1 Unit tests (`tests/unit/build/`)

- `test_config.py` — `BuildConfig` / `BuildResult` Pydantic round-trip, frozen invariants, `schema_version` pinning.
- `test_paths.py` — `resolve_layout` table-driven: `--keep-intermediates` on/off, per-phase subdirs computed correctly, idempotent against pre-existing dirs.
- `test_flags.py` — `podman_run_flags` per knob: caps_add → `--cap-add`, tmpfs → `--tmpfs`, binds_ro → `-v ...:ro`, publish_ports → `-p`, read_only_rootfs → `--read-only`, no_new_privileges → `--security-opt no-new-privileges`, seccomp path included. Empty inputs → minimum-viable flag list. Sentinel-entrypoint policy returns `[]` (defense-in-depth).
- `test_readme.py` — `rewrite_readme_with_verify` against golden files: `empty-diff.md`, `with-diff.md`, `skipped-sentinel.md`, `skipped-flag.md`. Idempotency (rewrite twice == rewrite once). Section placement before any trailing Warnings section, else appended.
- `test_pipeline.py` — `run_pipeline` composition tested with fake callables injected via the §5.6 seam (`probe_fn`, `install_trace_fn`, `parse_trace_fn`, `derive_policy_fn`, `generate_fn`, `podman_build_fn`, `verify_trace_fn`, `diff_fn`):
  - Happy path: every phase returns success, `BuildResult.verify` populated, README rewrite called once.
  - Sentinel branch: `derive_policy_fn` returns `PolicyJson` with sentinel entrypoint; phases 5/6/7 not called; `skip_reason == "sentinel"`.
  - `--skip-verify` branch: phases 5/6/7 not called; `skip_reason == "flag"`.
  - Per-phase failure: each phase raises in turn; assert exit, assert later phases not called.
  - Trace marker handling: install-mode `COMPLETE` / `PARTIAL` / neither; verify-mode `COMPLETE` / `READY_FAILED` / `RAN_AND_DIED` / `LOAD_FAILED`. Each marker drives the expected pipeline behavior (proceed, fail, proceed-with-warning).
  - `RAN_AND_DIED` path: `verify_trace_fn` writes the marker but the verify trace is otherwise usable; phase 7 still runs; `BuildResult.warnings` contains the marker note; exit 0.
- `test_cli.py` — Click `CliRunner` tests against `build_cmd`, with the pipeline faked via a module-level seam:
  - Happy path: exit 0, stderr summary lines in expected order, final dir listing printed.
  - Diff non-empty: exit 0, warning in stderr, "verify.json" path printed.
  - Sentinel: exit 0, skip notice in stderr.
  - `--skip-verify`: exit 0, skip notice mentions the flag.
  - `--keep-intermediates`: layout resolution called with the flag.
  - Missing installer file: Click `Path(exists=True)` → exit 2.
  - Preflight failure (podman missing): exit 2, no phases run.
  - `--verify-soak-seconds` propagates into `BuildConfig`.

### 8.2 Integration smoke (`tests/integration/build/test_build_smoke.py`)

One end-to-end test with podman-touching seams faked, everything else real.

Faked: `probe_fn` (returns hand-crafted `ProbeResult`), `install_trace_fn` (writes committed JSONL fixtures + `COMPLETE` marker into the target dir, returns exit 0), `podman_build_fn` (writes a sentinel `image.tar`, returns its path), `verify_trace_fn` (writes a committed JSONL fixture set + `COMPLETE` marker into the verify trace dir, with slight differences from the install-mode fixture so the diff has content, returns exit 0).

Real: `parse_trace_fn` runs the M3 reader + assembler over the fixture JSONL, `derive_policy_fn` runs M3 derive, M4 renderers, M5 `diff_traces`, README rewrite, final dir writes.

Assertions:
- `./out/<name>/` contains exactly: `Containerfile`, `<name>.container`, `seccomp.json`, `verify.json`, `README.md`.
- README contains the "Verify results" section with expected counts.
- `verify.json` matches `tests/fixtures/build/expected/verify.json` byte-for-byte.
- Tempdir cleaned (default behavior).

A second test with `--keep-intermediates` asserts `./out/<name>/.intermediates/` is preserved with the expected structure.

A third test with sentinel-producing fixture asserts the soft-skip branch: phases 5/6/7 fakes not called, README has the sentinel section, exit 0.

### 8.3 Manual acceptance (out of CI)

- `MANUAL.md` scenario 10: synthetic installer end-to-end through `build`. Validates the nested-podman runner-image changes against a real podman machine.
- `MANUAL.md` scenario 11: UniFi installer end-to-end through `build`. Closes the design §11 open question about classifier rules at real-installer scale.

These are documented in MANUAL.md, not enforced in CI. CI stays under design §9's 3-minute budget.

### 8.4 Coverage gate

`pyproject.toml --cov-fail-under=90` holds. M6's new Python modules target 100% per-module coverage (every branch exercised by hand-crafted inputs). The runner-image bash scripts are exempt.

## 9. Exit criteria

M6 is done when:

1. `containerizer build <installer> --name <name>` produces `./out/<name>/` with the expected final-artifact set (`Containerfile`, `<name>.container`, `seccomp.json`, `verify.json`, `README.md`) when given a synthetic installer fixture.
2. `--skip-verify` produces the same final artifacts minus `verify.json`, and the README has the skipped section.
3. Sentinel-producing fixture exits 0 with the sentinel skip section in the README and no `verify.json`.
4. `--keep-intermediates` preserves the full intermediates tree at `./out/<name>/.intermediates/`.
5. Phase-level fakes confirm each phase's failure mode produces the exit code in §7's table.
6. Unit tests + integration tests green. Coverage ≥ 90% total; M6's new modules at 100%.
7. `ruff check . && ruff format --check . && mypy src tests && pytest` green.
8. MANUAL.md scenarios 10 and 11 written.
9. PR opened closing #44.

M6 is **not** required to:

- Pass a real-podman end-to-end run in CI (manual scenarios cover it).
- Implement `doctor`, `--smoke-cmd`, or auto-relaxation (out of scope per §2).
- Validate arm64 / cross-architecture (parent §12 out-of-scope).
- Provide a standalone "rebuild + retrace" mode of the `verify` subcommand (the rebuild loop lives only inside `build`).
