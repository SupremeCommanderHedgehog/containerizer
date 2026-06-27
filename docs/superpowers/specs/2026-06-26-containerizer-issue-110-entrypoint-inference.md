# Issue #110 — analyzer entrypoint inference fallback to `--start-cmd`

**Date:** 2026-06-26
**Status:** Draft (brainstorming)
**Parent spec:** [`2026-06-06-containerizer-design.md`](./2026-06-06-containerizer-design.md)
**Prior milestone specs:** [`2026-06-21-containerizer-issue-105-start-cmd.md`](./2026-06-21-containerizer-issue-105-start-cmd.md)
**Issue:** [#110](https://github.com/SupremeCommanderHedgehog/containerizer/issues/110)

## 1. Overview

After #105 wired `--start-cmd` to fire daemons during the runtime phase, the trace pipeline now captures rich runtime data (bind events, port owners, syscalls) for non-systemd workloads like UniFi controller + MongoDB. The analyzer correctly populates every policy field — paths, volumes, ports, caps, seccomp — **except `image.entrypoint`**, which goes straight to the `["__UNSET__"]` sentinel. The generator then refuses to emit a `Containerfile` and the user is forced to hand-patch `policy.json` (the workaround documented in the close-out memory of 2026-06-24).

The root cause is a binary fork in `src/containerizer/analyze/derive.py:42-43`:

```python
systemd_required = systemd_required_for(trace)
entrypoint = ["/sbin/init"] if systemd_required else [SENTINEL_ENTRYPOINT]
```

When `systemd_required` is false, no other signal is consulted — even though `runtime.ports.by` carries the binding process's `comm` and `--start-cmd` already encodes the user's explicit "this is what to run" intent (otherwise it would not have been needed during trace either).

This spec wires `--start-cmd` into the analyzer as the entrypoint when systemd is not required. The cougar fixture from 2026-06-24 — `out/unifi-sudo/.intermediates/trace/original/` — exercises this end-to-end: with the fix, `containerizer analyze` against that trace dir emits the same hand-patched entrypoint the workaround produced.

### Why not also a `runtime.ports.by`-driven heuristic?

For the renamed-comm Java case (`launcher` thread vs `java` binary in UniFi), inference from `ports.by` is insufficient — `runtime.execs` contains `java`, not `launcher`, so a port-binder lookup would still miss it. `--start-cmd` is the user-supplied ground truth and the only signal that fixes UniFi. A bonus port-binder heuristic for trivial single-process daemons is a separate, smaller PR and intentionally out of scope here.

## 2. Scope

### 2.1 In this change

- `src/containerizer/analyze/schema.py` — `TraceJson` gains an optional field:
  ```python
  start_cmd: str | None = None
  ```
  Default keeps `schema_version: Literal[1] = 1` — old `trace.json` files without `start_cmd` parse unchanged because Pydantic fills the default.
- `src/containerizer/trace/runner.py` — when `self.start_cmd` is set, write the raw string to `<trace_dir>/START_CMD` at trace finalization. File name matches the existing `COMPLETE` / `PARTIAL` / `PHASE_MARKER` convention (uppercase-name files at trace-dir root for single-fact metadata).
- `src/containerizer/analyze/reader.py` — `TraceBundle` gains `start_cmd: str | None = None`. `read_trace_dir` reads `<trace_dir>/START_CMD` if present, else `None`. Absent file is not an error or a warning — it's the pre-#105 default.
- `src/containerizer/analyze/assemble.py` — `assemble_trace_json` threads `bundle.start_cmd` into the produced `TraceJson`. No signature change to the public function; the field comes from the bundle.
- `src/containerizer/analyze/derive.py` — entrypoint-inference rewrite:
  ```python
  systemd_required = systemd_required_for(trace)
  start_cmd = trace.start_cmd or None
  if systemd_required:
      entrypoint = ["/sbin/init"]
      if start_cmd:
          warnings.append(
              "start_cmd ignored: systemd detected as required; "
              "using /sbin/init as entrypoint"
          )
  elif start_cmd:
      entrypoint = ["bash", "-c", start_cmd]
  else:
      entrypoint = [SENTINEL_ENTRYPOINT]
  ```
- `src/containerizer/trace/cli.py` and `src/containerizer/build/cli.py` — Click callback normalizes empty-string `--start-cmd ''` to `None` before passing into `BuildConfig` / `TraceRunner`. Keeps a single truth (`None` ⇔ no start command) inside `derive_policy`.
- `docs/MANUAL.md` — one line in scenario 14 (or wherever `--start-cmd` is introduced) noting that the value also becomes the image entrypoint when systemd is not required.

### 2.2 Tests

- **`tests/unit/analyze/test_derive.py`** — extend the existing entrypoint cases:
  - `test_entrypoint_unset_when_no_start_cmd_and_no_systemd` (keep)
  - `test_entrypoint_systemd_init_when_systemd_required` (keep)
  - `test_entrypoint_uses_start_cmd_when_no_systemd` (NEW)
  - `test_entrypoint_ignores_start_cmd_when_systemd_with_warning` (NEW)
- **`tests/unit/analyze/test_schema.py`** — backwards-compat:
  - `test_trace_json_accepts_missing_start_cmd_backwards_compat` (NEW)
  - `test_trace_json_round_trips_start_cmd` (NEW)
- **`tests/unit/analyze/test_reader.py`** — sidecar handling:
  - `test_read_trace_dir_picks_up_start_cmd_file` (NEW)
  - `test_read_trace_dir_start_cmd_none_when_file_absent` (NEW)
- **`tests/unit/trace/test_runner.py`** — sidecar writing:
  - `test_runner_writes_start_cmd_file_when_set` (NEW)
  - `test_runner_omits_start_cmd_file_when_unset` (NEW)
- **`tests/unit/build/test_cli.py` + `tests/unit/trace/test_cli.py`** — boundary normalization:
  - `test_empty_start_cmd_normalized_to_none` (NEW, on whichever CLI surface ends up doing the normalization)
- **`tests/integration/trace/test_deb_pipeline.py`** — tighten the existing `test_deb_with_start_cmd_produces_non_sentinel_policy` assertion to `policy.image.entrypoint == ["bash", "-c", "<the start_cmd>"]` (currently presumably only asserts non-sentinel).
- **Cougar fixture sanity check** — not committed; local validation step that synthesizes `START_CMD` in the 2026-06-24 fixture trace dir, re-runs `containerizer analyze`, and verifies the entrypoint matches the hand-patched workaround.

### 2.3 Carried unchanged

- `runtime.ports.by`-driven inference for trivial single-process daemons (would help when the user did NOT pass `--start-cmd`). Deferred to a follow-up PR.
- Candidate-list warnings when entrypoint ends up `__UNSET__` (suggesting `--start-cmd '<X>'` based on observed port owners). Deferred.
- Schema bump to `schema_version: Literal[2]`. The optional-with-default pattern preserves backwards-compat without a version bump; bumping for a single field is theoretical churn.
- Generator semantics. `containerizer generate` already accepts whatever `entrypoint` derive produces; once the sentinel goes away for the start_cmd path, generation Just Works.
- `--start-cmd`'s existing runtime-phase behavior (#105). The trace runner continues to fire the daemon during install for the runtime observation window, unchanged.

### 2.4 Out of scope (deferred)

- **Multi-daemon entrypoint synthesis.** When users compose `'/etc/init.d/mongod start && sleep 10 && /etc/init.d/unifi start'` (the actual UniFi case), the spec ships that verbatim into `bash -c`. The user has already proved the sequence works during trace; we trust them.
- **`exec` prefix injection.** The UniFi workaround in the close-out memory deliberately writes `exec runuser -u unifi -- /usr/bin/java ...` at the tail of its start-cmd. Auto-prepending `exec` would break that pattern (commands before the final daemon would not run). Users own PID-1 discipline inside their start-cmd.
- **`--start-cmd` as a multi-process model.** If a user wants `A & B & wait` under PID 1, they write that. The analyzer does not synthesize launch ordering.
- **Re-tracing with synthetic START_CMD on existing fixtures.** The cougar `out/unifi-sudo/` trace was taken before this fix shipped, so it has no `START_CMD` file. The local sanity-check step in §2.2 explicitly writes one — that's the test fixture pattern, not a migration commitment for users'' historical traces.

## 3. Architecture

### 3.1 Trace artifact (`<trace_dir>/START_CMD`)

A single text file at the trace-dir root containing the raw `--start-cmd` string, no quoting / no trailing newline trimming. Written by `trace/runner.py` at trace finalization (alongside `COMPLETE` / `PARTIAL` markers). Absent for traces taken without `--start-cmd` or before this change.

Why a sidecar file rather than embedding in another existing artifact:
- `PHASE_MARKER` is `int` nanoseconds — no structured container available for piggyback.
- `FALLBACKS.json` is keyed on collector name — semantically not the right home.
- Per-collector `.jsonl`s are event logs — not a place for one-off metadata.
- A dedicated file is the lowest-coupling, fewest-other-files-touched choice.

### 3.2 Schema (`TraceJson.start_cmd`)

Optional field with default `None`. `schema_version` stays at `1` because adding optional fields with defaults is backwards-compatible:
- v1 `trace.json` without `start_cmd` parses as `start_cmd=None` (Pydantic default fill).
- New writes include `start_cmd` (or omit it if `None` — depends on `model_config` / serialization mode; see §3.6).
- External tooling that pins `schema_version == 1` continues to read both old and new files without changes.

### 3.3 Derive (`derive_policy`)

The entrypoint truth table:

| `systemd_required` | `trace.start_cmd` | `image.entrypoint` | `policy.warnings` addition |
|---|---|---|---|
| False | `None` | `["__UNSET__"]` | (none — existing behavior) |
| False | `"X"` | `["bash", "-c", "X"]` | (none) |
| True | `None` | `["/sbin/init"]` | (none) |
| True | `"X"` | `["/sbin/init"]` | `"start_cmd ignored: systemd detected as required; using /sbin/init as entrypoint"` |

The warning is added inside `derive_policy` to the warnings list it already builds. No new error / no new warning type.

### 3.4 Data flow

```
build CLI --start-cmd X
  → BuildConfig.start_cmd = X
    → trace pipeline (existing #105)
       → trace/runner.py fires daemon during runtime phase (existing)
       → trace/runner.py writes <trace_dir>/START_CMD = X     [NEW]
    → trace dir on disk: COMPLETE, PHASE_MARKER, FALLBACKS.json, *.jsonl, START_CMD
       → containerizer analyze <trace-dir>/
          → read_trace_dir loads START_CMD into TraceBundle.start_cmd     [NEW]
             → assemble_trace_json threads into TraceJson.start_cmd       [NEW]
                → derive_policy reads trace.start_cmd → entrypoint table  [NEW]
```

Standalone `containerizer analyze trace-dir/` (no build pipeline) of a trace produced with `--start-cmd` Just Works.

### 3.5 Empty-string normalization

`--start-cmd ''` from Click reaches `BuildConfig.start_cmd = ""`. To keep derive's truth table clean (`None` ↔ "no start command" only), normalize at the CLI boundary:

```python
if start_cmd == "":
    start_cmd = None
```

Done in the `build` and `trace` CLI callbacks (one site each) before passing to `BuildConfig` / `TraceRunner`. Tested via the new `test_empty_start_cmd_normalized_to_none` cases.

### 3.6 Serialization shape

`TraceJson` is Pydantic with `model_config = ConfigDict(extra="forbid", frozen=True)`. Adding `start_cmd: str | None = None` does not conflict with `extra="forbid"` (which forbids EXTRA fields on input, not missing ones with defaults). Serialization of `None` → JSON `null`; downstream tooling unaffected.

If a future "elide nulls on output" preference emerges to match how other optional fields serialize elsewhere in the schema, that''s a one-line `Field(default=None, exclude=False)` toggle. Not bundled in this change.

## 4. Risks and mitigations

- **`bash -c` may not be on PATH in every base image.** Driving cases (`ubuntu:24.04` and all minimal Debian/Ubuntu derivatives) ship bash. If a user later targets a `bash`-less base (e.g., alpine without bash), the entrypoint will not run. Mitigation: the existing M4 generator already assumes bash for `--start-cmd` invocation during the trace runtime phase (#105 §3.1 / `trace-orchestrator.sh`). Consistency with that prior assumption — no new exposure.
- **Multi-line `--start-cmd` strings.** `bash -c` accepts the literal string as one arg. Newlines are fine. Already exercised by the UniFi workaround in the memory.
- **Schema-versioning regret.** If we later need a breaking schema change, having added `start_cmd` as v1-with-default rather than v2 does not constrain that future change. Backwards-compat stays the property of the v1 schema; v2 can be designed freely.
- **`policy.warnings` consumer regressions.** The new systemd-override warning is one more entry that may surface in user output. Existing warning consumers iterate the list; an extra entry is non-breaking. Verified by inspection: no consumer asserts a specific length.

## 5. Migration / rollout

- No user-visible CLI flag changes — `--start-cmd` is already in the surface.
- Old trace dirs without `START_CMD` continue to analyze unchanged (sentinel entrypoint, same as today).
- Users who hand-patched their `policy.json` post-#110 can drop the workaround on next trace.
- No release or version-bump implication beyond a normal feature PR.

## 6. References

- Issue: [#110](https://github.com/SupremeCommanderHedgehog/containerizer/issues/110)
- Prior #105 spec: [`2026-06-21-containerizer-issue-105-start-cmd.md`](./2026-06-21-containerizer-issue-105-start-cmd.md)
- Cougar fixture (2026-06-24 close-out): `/home/yizshachuck/source/containerizer/out/unifi-sudo/.intermediates/trace/original/` (sudo-read) — 175-line `bind.jsonl`, complete-but-for-entrypoint `policy.json`.
- Close-out memory: `memory/unifi_build_resume.md`.
