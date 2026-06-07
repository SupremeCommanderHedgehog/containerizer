# M3 — Analyzer + Policy Derivation Spec

**Date:** 2026-06-07
**Status:** Approved (brainstorming)
**Parent spec:** [`2026-06-06-containerizer-design.md`](./2026-06-06-containerizer-design.md)
**Prior milestone spec:** [`2026-06-06-containerizer-m2-sandbox-trace.md`](./2026-06-06-containerizer-m2-sandbox-trace.md)
**Milestone issues:** #38, #39

## 1. Overview

M3 stands up the analyzer half of the containerizer. After M3, the user can run

```pwsh
PS> containerizer analyze .\unifi-trace\ -o .\unifi-analyze\
```

against a trace directory produced by M2 and end up with two structured documents in `unifi-analyze\`:

- `trace.json` — schema-versioned, normalized view of the raw collector output (phase-split, aggregated, classified).
- `policy.json` — derived input to the M4 generator (volumes, tmpfs, binds_ro, publish_ports, caps_add, seccomp_syscalls, entrypoint, ...).

**Nothing in M3 renders a Containerfile, a Quadlet unit, or a seccomp policy file.** Those are M4. M3's job is "turn six per-collector JSONL streams plus a PHASE_MARKER into two well-typed JSON documents that the generator can consume unchanged."

The point of cutting M3 narrow this way is to lock the analyzer→generator contract (`policy.json` schema) before the generator starts producing artifacts. The classifier itself is the most rule-table-heavy module in the project; isolating it lets M4 land Jinja templates against a frozen policy.json and lets M6 iterate the rule table against a real installer without breaking the generator.

## 2. Scope

### In M3

- `src/containerizer/analyze/` — new package: `schema.py`, `reader.py`, `phases.py`, `paths.py`, `ports.py`, `caps.py`, `syscalls.py`, `execs.py`, `derive.py`, `writer.py`, `cli.py`.
- `containerizer analyze <trace-dir> -o <out-dir>` CLI subcommand — single command, runs the full reader → aggregators → derive → writer pipeline.
- `tests/unit/analyze/` — per-module unit tests, parametrized over fixture files.
- `tests/integration/analyze/test_analyze_smoke.py` — end-to-end test against a recorded synthetic trace, gated by golden files.
- `tests/fixtures/trace/paths-rules/` — hand-crafted JSONL snippets, one per path-class rule plus edge cases.
- `tests/fixtures/trace/phase-split/` — hand-crafted JSONL snippets covering COMPLETE-with-marker and PARTIAL-no-marker.
- `tests/fixtures/trace/synthetic-recorded/` — a real captured trace from the synthetic installer, time-scrubbed and committed.
- `tests/fixtures/analyze/expected/` — golden `trace.json` and `policy.json` files.
- `sandbox/record-fixture.sh` — helper script (not run in CI) to regenerate `synthetic-recorded/`.

### Out of M3 (deferred)

- Generators (Containerfile, Quadlet, seccomp.json) — M4, issues #40–#42.
- `verify` subcommand (diff-against-trace) — M5, issue #43.
- `build` subcommand (full pipeline orchestration) — M5, issue #44.
- Real installer acceptance + classifier rule iteration — M6.
- Parsing strace fallback logs into events. See §4.3.
- `apt_packages` derivation from `install.log`. See §4.4.
- `read_only_rootfs=true` derivation. See §4.5.
- `entrypoint` argv detection (the daemon's real command). See §4.6.
- Outbound IP rollup beyond the raw `connect.jsonl` dedup (no DNS resolution, no CIDR collapsing).

### Carried unchanged from the parent design spec

- The seven path-class rules and their ordering (parent §5.6).
- The `trace.json` and `policy.json` top-level shapes (parent §5.6, §5.7) — refined in §5 below.
- Phase model: install phase → PHASE_MARKER → runtime phase (parent §5.4).

## 3. Reading guide

This spec narrows the parent design spec's §5.6 (analyzer) and §5.7 (policy derivation) for the M3 cut, and re-spends the rules table from parent §5.6 with the small additions noted in §5.2. Where this spec is silent, the parent spec is authoritative. Where this spec contradicts the parent, this spec wins for M3 and the parent gets updated when M3 lands.

The parent spec also mentions an `analyzer.py` collapsing both responsibilities into one file (parent §5.7). M3 splits that into a `analyze/` package per §4.1.

## 4. Decisions captured from the M3 brainstorm

| # | Decision | Choice | Rationale |
|---|----------|--------|-----------|
| 4.1 | Module layout | `src/containerizer/analyze/` package, one module per responsibility (`reader`, `phases`, `paths`, `ports`, `caps`, `syscalls`, `execs`, `derive`, `writer`, `schema`, `cli`). | Mirrors `probe/`. Each module has one job, small interface, easy to unit-test. The classifier (`paths.py`) is the most likely to grow; isolating it makes that frictionless. |
| 4.2 | CLI surface | Single `containerizer analyze <trace-dir> -o <out-dir>` command writing both `trace.json` and `policy.json`. | One step from the user's POV; internal pipeline is two phases (event-normalize → policy-derive). |
| 4.3 | Strace fallback input | Skip; record a warning per fallback collector in `trace.json.warnings`. | Strace text parsing is fragile across versions, and bcc tcpconnect/tcpaccept work on most non-GHA hosts. Tracked by issue #77. |
| 4.4 | `apt_packages` | Emit `[]`; defer to M6 with real installer. | Parsing `install.log` for apt-get invocations is highly fragile and the synthetic fixture has nothing to test against. M4 still renders with no apt layer. |
| 4.5 | `read_only_rootfs` | Conservative default `false`. | The "every runtime write is mapped" invariant needs a real classifier-confidence baseline; M6 flips it on. |
| 4.6 | `entrypoint` | `["/sbin/init"]` when `systemd_required=true`, else sentinel `["__UNSET__"]` plus a warning. | M3 doesn't have a reliable "which exec is the daemon" heuristic. M4 generator can refuse the sentinel; real argv detection lands in M5/M6. |
| 4.7 | Path-class fixture strategy | Hand-crafted JSONL snippets under `tests/fixtures/trace/paths-rules/`, one per rule + edge cases, parametrized into the path classifier tests. Plus a single end-to-end smoke fixture against the recorded synthetic trace. | Fast tests, surgical coverage, easy to add a row when a rule grows. The recorded fixture catches end-to-end shape regressions. |
| 4.8 | Pydantic | Yes — `analyze/schema.py` defines all models for `TraceJson` and `PolicyJson`. | Matches the `probe/schema.py` precedent. Gives M4 a typed contract via `from containerizer.analyze.schema import PolicyJson`. |
| 4.9 | Spec layout | Standalone M3 spec (this document); do not edit parent design spec inline. | Matches M2's pattern. Keeps history of how each milestone was framed at decision time. |

## 5. Design

### 5.1 Module layout

```
src/containerizer/analyze/
  __init__.py
  schema.py        # Pydantic models: TraceJson, PolicyJson, sub-models.
  reader.py        # Reads <trace-dir>: per-collector .jsonl + FALLBACKS.json
                   # + PHASE_MARKER + COMPLETE|PARTIAL. Returns typed in-memory
                   # event lists; surfaces hard errors on missing-not-fallback.
  phases.py        # Splits events into install vs runtime by phase_marker_ns.
                   # Handles PARTIAL case (no marker, all events go to install).
  paths.py         # Rule table (§5.2) + aggregation (§5.3). Consumes
                   # open.jsonl events from the runtime phase only.
  ports.py         # bind.jsonl -> TracePort list (dedup on
                   # (port, proto, comm)); derives publish_ports.
  caps.py          # capable.jsonl -> deduped + superset-filtered capability
                   # list. Derives caps_add.
  syscalls.py      # syscalls.jsonl -> sorted unique syscall_id ints
                   # (runtime phase). Derives seccomp_syscalls.
  execs.py         # SYS_execve filter over syscalls.jsonl -> sorted unique
                   # comm list. Feeds both trace.json.runtime.execs and the
                   # systemd_required heuristic.
  derive.py        # TraceJson -> PolicyJson. All policy decisions live here
                   # (systemd heuristic, conservative defaults, sentinel
                   # handling). No event-level logic.
  writer.py        # Serializes TraceJson and PolicyJson to disk with
                   # schema_version stamped. Pretty-printed JSON.
  cli.py           # argparse subcommand wiring; registers `analyze` on
                   # containerizer.cli's subparser map.
```

`schema.py` is imported by every other module; nothing imports back into the aggregators. The dependency graph is a DAG with `cli.py` at the root.

### 5.2 Path classification rules

Applied to runtime-phase events from `open.jsonl` only. First match wins.

| # | Match | Class | Policy effect |
|---|-------|-------|---------------|
| 1 | path under `/opt/*`, `/usr/lib/*`, or `/usr/share/*` AND ops ⊆ {read, stat, exec} | `image_static` | none — baked into image |
| 2 | path under `/var/lib`, `/var/log`, or `/var/spool` AND `write` ∈ ops | `persistent_rw` | `runtime.volumes[]` |
| 3 | path under `/tmp`, `/run`, `/var/run`, `/var/tmp`, or `/dev/shm` AND `write` ∈ ops | `ephemeral_rw` | `runtime.tmpfs[]` |
| 4 | path ∈ `/etc/resolv.conf`, `/etc/hosts`, `/etc/localtime`, `/etc/timezone` | `host_config_ro` | `runtime.binds_ro[]` |
| 5 | path under `/dev/` | `device` | none in M3; warning surfaced |
| 6 | path under `/proc` or `/sys` | filtered out | n/a — default container mounts |
| 7a | else AND `write` ∈ ops | `unknown_rw` | warning; forces `read_only_rootfs=false` (M3 already does this by default) |
| 7b | else, read-only | `unknown_ro` | warning only |

The rule table lives in `paths.py` as a module-level Python list of typed records — one per rule — that the classifier iterates in order. Adding a rule = add a row; no other code change.

### 5.3 Path aggregation

Raw events are per-file. The classifier collapses them to one entry per **mount-relevant root**:

| Class | Aggregation key |
|-------|-----------------|
| `image_static` | prefix root + the next single path component: `/opt/unifi/lib/x` → `/opt/unifi`; `/usr/lib/unifi/foo` → `/usr/lib/unifi` |
| `persistent_rw` | persistent root + the next single path component: `/var/lib/unifi/db/wt.db` → `/var/lib/unifi`; `/var/log/unifi/access.log` → `/var/log/unifi` |
| `ephemeral_rw` | tmpfs root itself: `/tmp/xyz/foo` → `/tmp` |
| `host_config_ro` | exact path (each file is its own bind) |
| `device` | exact `/dev/<leaf>` |
| `unknown_rw`, `unknown_ro` | exact path (user must see what the analyzer didn't recognize) |

Within one aggregated entry:
- `ops` = union of collapsed events' ops
- `by` = deduped, sorted set of `comm` values

Mixed-class collisions: if events under the same aggregation key would split across rule 1 (read-only) and rule 7a (write) — e.g., a write somewhere inside `/opt/unifi` — the whole aggregate gets bumped to `unknown_rw` and a warning is recorded. The install-prefix-is-read-only invariant has been violated and the user needs to know.

### 5.4 Phase splitting

`PHASE_MARKER` is one line written by the orchestrator after the installer exits: `monotonic_ns: <int>`. bpftrace's `nsecs` builtin and `/proc/uptime` are the same `CLOCK_MONOTONIC` source, so the comparison is apples-to-apples — `phases.py` carries a comment noting that to prevent silent breakage if a future collector switches clocks.

Two cases:

- **COMPLETE marker present, PHASE_MARKER present:** events with `ts_ns < phase_marker_ns` → install; events with `ts_ns ≥ phase_marker_ns` → runtime. `TraceJson.marker = "COMPLETE"`.
- **PARTIAL marker present, no PHASE_MARKER:** installer never finished. All events go to install; runtime phase is empty. `TraceJson.marker = "PARTIAL"`. `TraceJson.phase_marker_ns = None`. The derive step still runs and produces a `policy.json` shaped correctly but mostly empty, with a warning that there is no runtime data to base policy on.

### 5.5 Other aggregators

- **Ports** (`ports.py`): one `TracePort` per `(port, proto, comm)` tuple from `bind.jsonl`. `ipv4`/`ipv6` set from family (AF_INET=2, AF_INET6=10). `unix` and `?` proto entries are kept in `trace.json` but skipped from `policy.runtime.publish_ports`.
- **Outbound** (rolled into reader/derive): one `TraceOutbound` per `(daddr, dport, comm)` from `connect.jsonl`. Goes into `trace.json` only — `policy.json` has no outbound concept.
- **Caps** (`caps.py`): dedupe `capable.jsonl` capability names. Filter the cap-set-superset table (e.g., drop `CAP_DAC_READ_SEARCH` when `CAP_DAC_OVERRIDE` is present). Output → `policy.runtime.caps_add[]`.
- **Syscalls** (`syscalls.py`): sorted unique `syscall_id` ints from runtime-phase `syscalls.jsonl` events. Output → `policy.runtime.seccomp_syscalls[]`. M4 turns ints into names via libseccomp.
- **Execs** (`execs.py`): comm values from `syscalls.jsonl` events where `syscall_id == SYS_execve` (59 on x86_64). Deduped, sorted. Feeds `trace.json.runtime.execs` and the `systemd_required` heuristic.

### 5.6 Policy derivation

Everything in `derive.py`. Consumes a `TraceJson`, returns a `PolicyJson`.

- **`base`**: read from `probe.json` if `probe.json` exists in `<trace-dir>`; else default `ubuntu:24.04` and add a warning. (M2's `containerizer trace` does not currently write `probe.json` into the trace dir — leave this hook in place; the M3 reader looks for it but tolerates absence.)
- **`apt_packages`**: `[]` always in M3.
- **`installer_path`**: `"/installer"` (matches M2's mount path).
- **`post_install_cleanup`**: static list `["/var/cache/apt/archives/*", "/installer"]`.
- **`systemd_required`**: `True` if `execs` contains any of `systemd`, `systemctl`, `init`, `systemd-tmpfiles`, **or** any `persistent_rw` path under `/etc/systemd/system/` was written during install. Else `False`.
- **`entrypoint`**: `["/sbin/init"]` when `systemd_required`. Else `["__UNSET__"]` with a warning.
- **`volumes`**: one per `persistent_rw` aggregate. Name derived from the leaf component of the aggregate path + `-data`: `/var/lib/unifi` → `unifi-data`. If two aggregates would produce the same name (e.g., `/var/lib/unifi` and `/var/log/unifi` both → `unifi-data`), disambiguate by prepending the parent's leaf: `unifi-data`, `log-unifi-data`. Mount is the aggregate's path.
- **`tmpfs`**: list of unique `ephemeral_rw` aggregate paths.
- **`binds_ro`**: list of unique `host_config_ro` paths.
- **`publish_ports`**: from ports aggregator, filtered to tcp/udp only.
- **`caps_add`**: from caps aggregator.
- **`caps_drop`**: always `["ALL"]`.
- **`seccomp_syscalls`**: from syscalls aggregator.
- **`read_only_rootfs`**: always `False` in M3.
- **`no_new_privileges`**: always `True`.

### 5.7 Error and warning surfaces

| Situation | Behavior |
|-----------|----------|
| `<trace-dir>` missing or unreadable | Hard error, non-zero exit. |
| Neither COMPLETE nor PARTIAL marker present | Hard error: trace is corrupt or in-flight. |
| A collector file is missing AND in `FALLBACKS.json` | Warning in `trace.json.warnings`, skip. |
| A collector file is missing AND not in `FALLBACKS.json` | Hard error (orchestrator should always produce these). |
| A collector file is present but empty AND not in `FALLBACKS.json` | Warning only. Some installers genuinely don't do that thing. |
| `unknown_rw` aggregate exists | Warning per aggregate listing the path. |
| `device` aggregate exists | Warning per aggregate (M3 has no policy field for devices). |
| `systemd_required=false` AND no recognizable daemon exec | Warning that `entrypoint` is sentinel. |
| Non-JSON line in a `.jsonl` (e.g., bpftrace map-dump exit text) | Silently skipped in reader. The trace-integration test for M2 already documented this behavior. |

## 6. Implementation notes

### 6.1 Schemas

`schema.py` Pydantic v2 models:

```python
class TracePath(BaseModel):
    path: str
    ops: list[Literal["read", "write", "mkdir", "stat", "exec"]]
    class_: Literal[
        "image_static", "persistent_rw", "ephemeral_rw",
        "host_config_ro", "device", "unknown_rw", "unknown_ro"
    ] = Field(alias="class", serialization_alias="class")
    by: list[str]

class TracePort(BaseModel):
    port: int
    proto: Literal["tcp", "udp", "unix", "?"]
    by: str
    ipv4: bool
    ipv6: bool

class TraceOutbound(BaseModel):
    daddr: str
    dport: int
    comm: str

class TracePhase(BaseModel):
    duration_s: float
    exit: int | None = None  # install only
    paths: list[TracePath]
    ports: list[TracePort]
    outbound: list[TraceOutbound]
    caps: list[str]
    syscalls: list[int]
    execs: list[str]

class TraceJson(BaseModel):
    schema_version: Literal[1] = 1
    phase_marker_ns: int | None
    marker: Literal["COMPLETE", "PARTIAL"]
    install: TracePhase
    runtime: TracePhase
    warnings: list[str]

class PolicyImage(BaseModel):
    base: str
    apt_packages: list[str]
    installer_path: str = "/installer"
    post_install_cleanup: list[str]
    systemd_required: bool
    entrypoint: list[str]

class PolicyVolume(BaseModel):
    name: str
    mount: str

class PolicyPort(BaseModel):
    host: int
    container: int
    proto: Literal["tcp", "udp"]

class PolicyRuntime(BaseModel):
    volumes: list[PolicyVolume]
    tmpfs: list[str]
    binds_ro: list[str]
    publish_ports: list[PolicyPort]
    caps_add: list[str]
    caps_drop: list[str] = ["ALL"]
    seccomp_syscalls: list[int]
    read_only_rootfs: bool
    no_new_privileges: bool = True

class PolicyJson(BaseModel):
    schema_version: Literal[1] = 1
    image: PolicyImage
    runtime: PolicyRuntime
```

### 6.2 Writer

JSON output is pretty-printed (`indent=2`), sorted by key at each level for deterministic golden-file diffs. `schema_version` is the first key. `class_` field serializes as `"class"` via Pydantic's `serialization_alias`.

### 6.3 Reader robustness

`reader.py` ignores lines that don't start with `{` (handles bpftrace's exit-time map dumps that survive `-q`). It is otherwise strict: malformed JSON inside a `{...}` line is a hard error, not a warning.

## 7. Test plan

### 7.1 Layout

```
tests/
  unit/analyze/
    test_reader.py        # missing files, empty files, fallback handling,
                          # malformed JSON behavior, non-JSON line filter
    test_phases.py        # COMPLETE+marker split, PARTIAL no-marker case,
                          # boundary inclusion (>=)
    test_paths.py         # parametrized over tests/fixtures/trace/paths-rules/
                          # — one case per rule + collision case
    test_ports.py         # tcp/udp/unix/? handling; dedup; family flags
    test_caps.py          # dedup; superset filter table
    test_syscalls.py      # phase filter; sort; dedup
    test_execs.py         # execve filter; sort; dedup
    test_derive.py        # systemd_required heuristic; conservative defaults;
                          # sentinel entrypoint; warnings populated
    test_writer.py        # schema_version stamping; key sort;
                          # `class` alias serialization
  integration/analyze/
    test_analyze_smoke.py # full CLI against synthetic-recorded/;
                          # golden-file diff
  fixtures/
    trace/
      paths-rules/
        rule1-image-static.jsonl
        rule2-persistent-rw.jsonl
        rule3-ephemeral-rw.jsonl
        rule4-host-config.jsonl
        rule5-device.jsonl
        rule6-proc-sys-filtered.jsonl
        rule7a-unknown-rw.jsonl
        rule7b-unknown-ro.jsonl
        collision-mixed-class.jsonl
      phase-split/
        complete-with-marker.jsonl
        partial-no-marker.jsonl
      synthetic-recorded/
        open.jsonl
        bind.jsonl
        capable.jsonl
        syscalls.jsonl
        connect.jsonl
        accept.jsonl
        FALLBACKS.json
        PHASE_MARKER
        COMPLETE
    analyze/
      expected/
        synthetic-trace.json
        synthetic-policy.json
```

### 7.2 Unit-test patterns

Each rule-fixture is a `.jsonl` snippet of fake open/bind/etc. events. The test loads it, runs the relevant module function on the in-memory event list, and asserts on the produced Pydantic model. No subprocess. No `tmp_path`. No real filesystem outside the fixture directory.

Path-rule tests are parametrized over the directory:

```python
@pytest.mark.parametrize("fixture", sorted((FIXTURES / "paths-rules").glob("*.jsonl")))
def test_rule_classification(fixture):
    expected = json.loads(fixture.read_text().splitlines()[0][2:])  # first line: // expected
    events = [json.loads(l) for l in fixture.read_text().splitlines() if l.startswith("{")]
    aggregated = paths.classify_runtime(events)
    assert aggregated == expected
```

(Pseudocode — the exact mechanism is the implementer's call; the contract is "one fixture per rule + edge case, parametrized".)

### 7.3 Smoke test

`test_analyze_smoke.py` runs `containerizer analyze tests/fixtures/trace/synthetic-recorded/ -o <tmp>`, then `json.loads()` both outputs and `==`-compares against `tests/fixtures/analyze/expected/synthetic-trace.json` and `…/synthetic-policy.json`. Golden-file maintenance: when a schema field or default changes, the same commit updates the golden file. Diffs are stable because `ts_ns` was scrubbed at fixture-capture time (see §7.4).

### 7.4 Capturing `synthetic-recorded/`

A helper script committed at `sandbox/record-fixture.sh` (not run in CI):

1. Runs `containerizer trace tests/fixtures/trace/synthetic-installer.sh -o <tmp>` against the M2 pipeline.
2. Rewrites every `ts_ns` and `PHASE_MARKER` value to a monotonic-relative integer starting from 0, so the fixture is bit-stable across runs.
3. Copies the rewritten directory to `tests/fixtures/trace/synthetic-recorded/`.

The script exists so the fixture can be regenerated deterministically when collectors change schema (e.g., a new field). It is not part of the test suite; it is run by hand, the diff is committed, and CI consumes the committed bytes.

## 8. Open questions

None at spec time. Decisions captured in §4.

## 9. Exit criteria

M3 is done when:

1. `containerizer analyze tests/fixtures/trace/synthetic-recorded/ -o <tmp>` produces a `trace.json` and `policy.json` matching the committed golden files.
2. All path-class rule fixtures classify per §5.2 and aggregate per §5.3.
3. PARTIAL trace handling produces a shaped-correctly `policy.json` with warnings populated.
4. `PolicyJson.model_validate_json(<golden policy.json>)` and `TraceJson.model_validate_json(<golden trace.json>)` both succeed — i.e., the schemas accept their own output. (Verified by a dedicated unit test in `test_writer.py`, not by a hypothetical M4 generator.)
5. `pytest` (unit + integration, no `-m integration` exclusion) is green.

M3 is **not** required to:

- produce a useful policy for a real installer (M6 problem).
- detect a daemon entrypoint correctly (M5/M6 problem).
- flip `read_only_rootfs` on (M6).
- parse `apt_packages` out of `install.log` (M6).
