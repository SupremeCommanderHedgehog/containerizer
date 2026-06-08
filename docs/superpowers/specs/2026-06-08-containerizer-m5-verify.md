# M5 — Verify (diff-only) Spec

**Date:** 2026-06-08
**Status:** Approved (brainstorming)
**Parent spec:** [`2026-06-06-containerizer-design.md`](./2026-06-06-containerizer-design.md)
**Prior milestone spec:** [`2026-06-07-containerizer-m4-generators.md`](./2026-06-07-containerizer-m4-generators.md)
**Milestone issues:** #43

## 1. Overview

M5 stands up the `verify` subcommand as a pure diff. After M5, the user can run

```pwsh
PS> containerizer verify --original .\original-trace.json --observed .\observed-trace.json -o .\verify-out\
verify: 3 new paths, 1 new syscall
```

against two normalized `trace.json` documents (M3's output) and end up with a `verify.json` document in `verify-out\` listing every runtime event present in the observed trace but missing from the original. Exit code communicates the headline result: 0 if observed is a subset of original, 1 if any new events were found, 2 on operational errors.

**M5 does not rebuild the image, start the container, or re-run the trace pipeline.** The design spec's §5.1 wording for `verify` ("rebuild and run the generated image briefly under strict policy, repeat the trace pipeline against it") is split across milestones: the rebuild + retrace orchestration lands in M6's `build` subcommand. M5 owns the comparison logic; M6 wires it into the end-to-end pipeline. This keeps M5 small, isolates the comparison's correctness from the considerable podman orchestration complexity, and gives M6 a clean dependency to consume.

## 2. Scope

### In M5

- `src/containerizer/verify/` — new package: `schema.py`, `diff.py`, `writer.py`, `cli.py`, `__init__.py`.
- `containerizer verify --original <trace.json> --observed <trace.json> -o <out-dir>` CLI subcommand wired into the main group.
- `tests/unit/verify/` — per-module unit tests with hand-crafted in-Python `TraceJson` inputs.
- `tests/integration/verify/test_verify_smoke.py` — end-to-end test against committed `trace.json` fixtures + golden `verify.json`.
- `tests/fixtures/verify/` — three committed `trace.json` fixtures: `original.json`, `observed-clean.json` (identical → empty diff), `observed-with-new.json` (synthesized to trip one entry per category).
- `tests/fixtures/verify/expected/verify-with-new.json` — golden `verify.json` for the with-new case.
- MANUAL.md — new scenario 9 showing the `verify` invocation.

### Out of M5 (deferred)

- Image rebuild orchestration (`podman build ./out/<name>/`) — M6's `build` subcommand.
- Container start/stop + retrace — M6.
- Reading `seccomp.json` directly to assert that observed syscalls are within the allowlist — covered by the trace.json comparison already (policy.json is derived from trace.json's runtime phase; an observed syscall outside the original trace would also be outside the seccomp allowlist).
- Auto-suggesting policy relaxations from `verify.json` — M6. The design §11 open question lands as: M5 reports, M6 acts.
- `doctor` subcommand mentioned in design §13's M5 line — no current issue; deferred to a separate milestone.
- "Recovery prompts" mentioned in design §13's M5 line — deferred.

### Carried unchanged from the parent design spec

- `verify` is a phase subcommand alongside `probe`, `trace`, `analyze`, `generate` (parent §5.1).
- Non-zero exit on any unknown events (parent §5.1 "surface anything not previously seen").
- The "captured trace" used for comparison is `trace.json` — the normalized analyze output, not the raw collector JSONL streams.

## 3. Reading guide

This spec narrows the parent design spec's §5.1 (verify CLI surface) and §11 (open question about auto-relaxation) for the M5 cut. Where this spec is silent, the parent is authoritative; where it contradicts, this spec wins for M5.

The parent's §5.1 wording for `verify` implies a full E2E rebuild + retrace + diff pipeline. M5 cleaves at the diff boundary — see decision 4.1 below for the rationale.

## 4. Decisions captured from the M5 brainstorm

| # | Decision | Choice | Rationale |
|---|----------|--------|-----------|
| 4.1 | Scope cut | Diff-only. M5 takes two pre-normalized `trace.json` files and emits `verify.json`. M6 owns rebuild + retrace orchestration. | The rebuild + run + retrace pipeline is substantial (podman orchestration, verify-runner image, M2 collector reuse). Splitting at the diff boundary keeps M5 testable in isolation, mirrors M3/M4's "pure-data" cut, and gives M6 a clean dependency. The user gets the "verify against the policy" UX in M6; M5 unblocks the comparison correctness. |
| 4.2 | Input contract | Two normalized `trace.json` files via `--original` and `--observed` flags. | Mirrors the M4 generator's input pattern (consumes already-normalized `policy.json`). User runs `analyze` on both trace dirs first. Self-documenting flag names beat positional args for a two-input command. No hidden coupling to the analyze pipeline; M5 stays a leaf consumer of the schema. |
| 4.3 | Output | Structured `verify.json` to `-o <out-dir>` + one-line stderr summary + exit code. | Matches M3/M4's `-o` pattern. Structured output enables M6 to consume verify.json without re-running. Stderr summary handles the interactive CLI case. |
| 4.4 | Diff direction | One-directional: observed \ original. Things in original but not observed are not flagged. | "Surface anything not previously seen" (parent §5.1) is one-directional. The brief verify run probably doesn't exercise everything the original did; flagging missing-from-observed would be noisy and unhelpful. |
| 4.5 | Phase scope | Compare `observed.runtime.*` against `original.runtime.*` only. Install phase ignored. | The generated container has no install phase. Policy.runtime is derived from original.runtime, so any observed runtime event missing from original.runtime is a policy gap by definition. |
| 4.6 | Path comparison key | `(path, class_)` tuple. Different class on the same path counts as new. | A path's classification (e.g., `unknown_rw` vs `persistent_rw`) determines its policy treatment. A class change is a meaningful new event. |
| 4.7 | Port comparison key | `(port, proto)` tuple. `ipv4`/`ipv6` flags don't gate the diff (carry through whichever variant was observed). | The exposure decision is "is this port allowed at all?" — family-specific binding nuances don't change the policy answer. |
| 4.8 | Schema reuse | Reuse `TracePath`/`TracePort` from `analyze/schema.py` for the diff entries. No new path/port models. | Same shape; duplicating would create drift risk. Verify imports from analyze; no schema bump in analyze. |
| 4.9 | PARTIAL trace handling | Warn but proceed. Both markers are surfaced in `verify.warnings`. | PARTIAL is informational; the user knows their trace is incomplete. Refusing to compare would be unhelpful when partial-vs-partial comparison is still useful. |
| 4.10 | Auto-suggest relaxation | Out of scope. M5 reports; M6 can read `verify.json` and decide whether to patch policy. | The design §11 open question becomes a separation-of-concerns answer: M5 = "what changed", M6 = "what to do about it". |
| 4.11 | Module layout | `src/containerizer/verify/` package with `schema`, `diff`, `writer`, `cli`. | Mirrors `analyze/` and `generate/`. Each module has one job; `cli` is the only one with I/O. |
| 4.12 | Diff function purity | `diff_traces(original, observed) -> VerifyReport` is pure; takes two `TraceJson` Pydantic models, returns a `VerifyReport`. No file I/O. | Same pure-function pattern as M4's renderers. Trivially unit-testable with hand-crafted in-Python inputs. |

## 5. Components

### 5.1 Package layout

```
src/containerizer/verify/
  __init__.py    # "Containerizer trace verifier (M5)."
  schema.py      # VerifyDiff, VerifyReport Pydantic models
  diff.py        # diff_traces(original: TraceJson, observed: TraceJson) -> VerifyReport
  writer.py      # write_verify_json(report: VerifyReport, path: Path) -> None
  cli.py         # `containerizer verify` Click subcommand + I/O orchestration
```

Each renderer/diff function is pure; only `cli.py` touches disk.

### 5.2 `schema.py`

Pydantic v2 models, `ConfigDict(extra="forbid", frozen=True)`, matching the precedent in `analyze/schema.py`:

```python
from containerizer.analyze.schema import TracePath, TracePort

class VerifyDiff(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    new_paths: list[TracePath]
    new_ports: list[TracePort]
    new_caps: list[str]
    new_syscalls: list[int]
    new_execs: list[str]


class VerifyReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    original_marker: Literal["COMPLETE", "PARTIAL"]
    observed_marker: Literal["COMPLETE", "PARTIAL"]
    diff: VerifyDiff
    warnings: list[str] = []
```

Matches the `PolicyJson.warnings: list[str] = []` precedent set in M4. `TracePath`/`TracePort` are re-imported from `analyze/schema.py`; no new path/port shape.

### 5.3 `diff.py`

`diff_traces(original: TraceJson, observed: TraceJson) -> VerifyReport`. Pure. Compares `original.runtime` against `observed.runtime` per the keys in decisions 4.6/4.7.

```python
def diff_traces(original: TraceJson, observed: TraceJson) -> VerifyReport:
    """Compute observed.runtime \\ original.runtime per category."""
    orig_paths = {(p.path, p.class_) for p in original.runtime.paths}
    new_paths = sorted(
        (p for p in observed.runtime.paths if (p.path, p.class_) not in orig_paths),
        key=lambda p: (p.path, p.class_),
    )

    orig_ports = {(p.port, p.proto) for p in original.runtime.ports}
    new_ports = sorted(
        (p for p in observed.runtime.ports if (p.port, p.proto) not in orig_ports),
        key=lambda p: (p.port, p.proto),
    )

    new_caps = sorted(set(observed.runtime.caps) - set(original.runtime.caps))
    new_syscalls = sorted(set(observed.runtime.syscalls) - set(original.runtime.syscalls))
    new_execs = sorted(set(observed.runtime.execs) - set(original.runtime.execs))

    warnings: list[str] = []
    if original.marker == "PARTIAL":
        warnings.append("original trace marker is PARTIAL; comparison may be incomplete")
    if observed.marker == "PARTIAL":
        warnings.append("observed trace marker is PARTIAL; comparison may be incomplete")

    diff = VerifyDiff(
        new_paths=new_paths,
        new_ports=new_ports,
        new_caps=new_caps,
        new_syscalls=new_syscalls,
        new_execs=new_execs,
    )
    total = len(new_paths) + len(new_ports) + len(new_caps) + len(new_syscalls) + len(new_execs)
    if total:
        warnings.append(
            f"observed runtime has {total} events not present in original "
            f"({len(new_paths)} paths, {len(new_ports)} ports, "
            f"{len(new_caps)} caps, {len(new_syscalls)} syscalls, "
            f"{len(new_execs)} execs)"
        )

    return VerifyReport(
        original_marker=original.marker,
        observed_marker=observed.marker,
        diff=diff,
        warnings=warnings,
    )
```

### 5.4 `writer.py`

`write_verify_json(report: VerifyReport, path: Path) -> None`. Mirrors `analyze/writer.py` exactly: `model_dump(by_alias=True, mode="json")` + `json.dumps(..., indent=2, sort_keys=False)` + trailing newline. Pydantic field order is the deterministic JSON key order.

### 5.5 `cli.py`

```python
@click.command("verify")
@click.option("--original", "original_path", required=True,
              type=click.Path(exists=True, dir_okay=False, readable=True, path_type=Path))
@click.option("--observed", "observed_path", required=True,
              type=click.Path(exists=True, dir_okay=False, readable=True, path_type=Path))
@click.option("-o", "--output-dir", required=True, type=click.Path(path_type=Path))
def verify_cmd(original_path: Path, observed_path: Path, output_dir: Path) -> None:
    """Diff observed trace.json against original trace.json. Emit verify.json."""
    output_dir.mkdir(parents=True, exist_ok=True)
    original = TraceJson.model_validate_json(original_path.read_text(encoding="utf-8"))
    observed = TraceJson.model_validate_json(observed_path.read_text(encoding="utf-8"))

    report = diff_traces(original, observed)
    write_verify_json(report, output_dir / "verify.json")

    total = sum(len(getattr(report.diff, name)) for name in
                ("new_paths", "new_ports", "new_caps", "new_syscalls", "new_execs"))
    if total == 0:
        click.echo("verify: no new events", err=True)
    else:
        d = report.diff
        click.echo(
            f"verify: {len(d.new_paths)} new paths, {len(d.new_ports)} new ports, "
            f"{len(d.new_caps)} new caps, {len(d.new_syscalls)} new syscalls, "
            f"{len(d.new_execs)} new execs",
            err=True,
        )
        raise click.exceptions.Exit(1)
```

Wires into `src/containerizer/cli.py`:

```python
from containerizer.verify.cli import verify_cmd
main.add_command(verify_cmd)
```

## 6. Data flow

```
original-trace.json --read--> TraceJson original
observed-trace.json --read--> TraceJson observed
                                 |
                                 v
                          diff_traces() --> VerifyReport
                                 |
                                 v
                       write_verify_json() --write--> <out-dir>/verify.json

                       stderr summary + exit code (0 if empty, 1 if any new)
```

## 7. Error and warning surfaces

| Situation | Behavior |
|-----------|----------|
| Either input file missing/unreadable | Click `Path(exists=True)` → exit 2 |
| Either input file fails `TraceJson.model_validate_json` | `ClickException` with validation summary → exit 2 |
| `<out-dir>` doesn't exist | `mkdir(parents=True, exist_ok=True)` — same pattern as analyze/generate |
| Either trace marker is PARTIAL | Append warning to `verify.warnings`, proceed normally, exit code unchanged |
| All `new_*` empty | Exit 0, write verify.json with empty arrays so M6/CI can read it unconditionally |
| Any `new_*` non-empty | Exit 1, write verify.json with populated arrays |
| Different schema_version on inputs | `TraceJson.model_validate_json` raises ValidationError → exit 2 (M3 traces are v1; future versions would need an explicit migration path) |

## 8. Testing strategy

### 8.1 Unit tests (`tests/unit/verify/`)

- `test_schema.py` — Pydantic round-trip; frozen invariants; reuses `TracePath`/`TracePort` correctly.
- `test_diff.py` — hand-crafted in-Python `TraceJson` pairs covering: identical traces (empty diff), new path only, new port only, new cap only, new syscall only, new exec only, multiple categories at once, PARTIAL marker handling on each input independently, `(path, class)` key (same path different class counts as new), `(port, proto)` key.
- `test_writer.py` — schema_version first, Pydantic field order preserved, trailing newline. Mirrors `analyze/test_writer.py`.
- `test_cli.py` — CliRunner happy-path (writes verify.json, exit 0, empty diff lists in JSON), diff-found path (exit 1, summary in stderr, populated lists in JSON), missing input (exit 2), malformed JSON input (exit 2), PARTIAL warning surfaces in verify.json.

### 8.2 Integration smoke (`tests/integration/verify/test_verify_smoke.py`)

Three committed fixtures under `tests/fixtures/verify/`:

- `original.json` — a hand-crafted `TraceJson` covering one entry in each runtime category.
- `observed-clean.json` — byte-identical to `original.json`.
- `observed-with-new.json` — same as original plus one synthesized new entry per category.

Two integration tests:

1. `test_clean_observed_exits_zero`: runs verify with `original.json` + `observed-clean.json`; asserts exit 0, verify.json has all empty arrays.
2. `test_new_observed_matches_golden`: runs verify with `original.json` + `observed-with-new.json`; asserts exit 1, verify.json equals `tests/fixtures/verify/expected/verify-with-new.json` (golden comparison).

The integration test does NOT exercise the `tests/fixtures/trace/synthetic-recorded/` fixture from M3 — that's the input to analyze, and M5 operates on analyze's output. Reusing it would require running the M3 analyze pipeline first, which is overhead the integration test doesn't need.

### 8.3 Coverage gate

`pyproject.toml` `--cov-fail-under=90` remains. M5 keeps total coverage ≥ 90%; per-module coverage on `verify/*` should be 100% (every branch is exercised by hand-crafted inputs).

## 9. Exit criteria

M5 is done when:

1. `containerizer verify --original a.json --observed b.json -o <tmp>` produces verify.json with the correct shape and exit code (0 for identical, 1 for any diff).
2. Identical-traces fixture produces empty diff arrays.
3. Synthesized observed-with-new fixture produces the correct deltas per category and matches the golden verify.json byte-for-byte.
4. PARTIAL traces produce a warning entry in `verify.warnings` without changing the exit code.
5. `pytest` (unit + integration, no `-m integration` exclusion) is green. Coverage ≥ 90%.
6. `ruff check . && ruff format --check . && mypy src tests && pytest` is green.
7. MANUAL.md scenario 9 (running verify) is added.
8. PR opened closing #43.

M5 is **not** required to:

- Rebuild the generated image or run the generated container (M6 problem).
- Re-run the M2 trace pipeline against the generated container (M6).
- Auto-suggest a relaxed policy.json from verify.json (M6 — closes the design §11 open question).
- Provide doctor/recovery functionality mentioned in design §13's M5 line (deferred).
- Compare against `seccomp.json` directly (the trace.json comparison subsumes it: observed syscalls outside original.runtime.syscalls would also be outside the derived seccomp allowlist).
