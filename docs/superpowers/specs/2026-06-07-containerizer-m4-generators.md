# M4 — Generators (Containerfile + Quadlet + seccomp + README) Spec

**Date:** 2026-06-07
**Status:** Approved (brainstorming)
**Parent spec:** [`2026-06-06-containerizer-design.md`](./2026-06-06-containerizer-design.md)
**Prior milestone spec:** [`2026-06-07-containerizer-m3-analyzer-policy.md`](./2026-06-07-containerizer-m3-analyzer-policy.md)
**Milestone issues:** #40, #41, #42

## 1. Overview

M4 stands up the generator stage. After M4, the user can run

```pwsh
PS> containerizer generate .\unifi-analyze\policy.json -n unifi-os -o .\unifi-build\
```

against a `policy.json` produced by M3's `analyze` and end up with four files in `unifi-build\`:

- `Containerfile` — the hardened image build recipe.
- `unifi-os.container` — the systemd Quadlet unit enforcing runtime policy.
- `seccomp.json` — OCI seccomp profile (`SCMP_ACT_ERRNO` default, allowlist from traced syscalls).
- `README.md` — audit trail: what was generated, what each allowance came from, what was skipped and why.

M4 is the first milestone whose output the user can actually feed to `podman build` and `systemctl --user`. M5 (`verify`) and M6 (`build`) consume what M4 produces.

## 2. Scope

### In M4

- `src/containerizer/generate/` — new package: `containerfile.py`, `quadlet.py`, `seccomp.py`, `readme.py`, `syscall_table.py`, `cli.py`, `__init__.py`.
- `containerizer generate <policy.json> -n <name> -o <out-dir>` CLI subcommand wired into the main group.
- One small schema bump in `analyze/schema.py`: `PolicyJson.schema_version: Literal[2]` and `PolicyJson.warnings: list[str]`. `analyze/derive.py` copies `trace.warnings` into the new field; `analyze/cli.py` adjusts accordingly.
- Regenerate the committed M3 golden `tests/fixtures/analyze/expected/synthetic-policy.json` for the v2 schema.
- `tests/unit/generate/` — per-module unit tests with in-Python hand-crafted policies and hand-written expected output strings.
- `tests/integration/generate/test_generate_smoke.py` — end-to-end test that chains `analyze` → `generate` against the M3 `synthetic-recorded/` fixture and diffs the four artifacts against committed goldens.
- `tests/fixtures/generate/expected/` — golden `Containerfile`, `unifi-os.container` (or whatever name the smoke test picks), `seccomp.json`, `README.md`.
- `sandbox/regen-syscall-table.sh` — one-shot helper (not in CI) to regenerate `src/containerizer/generate/syscall_table.py` from `arch/x86/entry/syscalls/syscall_64.tbl`.
- MANUAL.md — new scenario 8 showing the `generate` invocation.

### Out of M4 (deferred)

- `apt_packages` rendering — analyze still emits `[]`; M4 generator silently skips the apt install layer. Lands in M6.
- `verify` subcommand (diff observed-vs-captured against generated artifacts) — M5, issue #43.
- `build` subcommand (end-to-end `probe → trace → analyze → generate → verify`) — M6, issue #44.
- Egress allowlist on the Quadlet — design §2 non-goal.
- Multi-arch seccomp (only `SCMP_ARCH_X86_64` in M4; other arches are M6+).
- Reading `probe.json` — M4 takes only `policy.json` + `-n` flag.
- Pulling the daemon argv from anywhere other than `policy.image.entrypoint`. Sentinel handling per §5.5.

### Carried unchanged from the parent design spec

- Generator package lives at `src/containerizer/generate/` (parent §5.8).
- Deny-by-default hardening philosophy (parent §2, §7).
- Containerfile + `<name>.container` + `seccomp.json` + `README.md` are the four deliverables (parent §5.8, §3 ascii flow).
- The Quadlet renders `GlobalArgs=--security-opt seccomp=%h/.config/containers/seccomp/<name>.json` (parent §5.8).

## 3. Reading guide

This spec narrows the parent design spec's §5.8 (generators) for the M4 cut. Where this spec is silent, the parent is authoritative; where it contradicts, this spec wins for M4.

The parent's §5.8 reference to "Jinja-templates `Containerfile`" is superseded here: M4 uses stdlib-only string building (decision 4.4 below). Templates are pure Python functions returning strings.

## 4. Decisions captured from the M4 brainstorm

| # | Decision | Choice | Rationale |
|---|----------|--------|-----------|
| 4.1 | Spec/PR scope | One spec, one branch, one PR covering all four generators + the schema bump. | Generators share the same input contract, philosophy, and test style. Splitting would multiply brainstorming and review overhead with no isolation benefit (no shared mutable state between generators). |
| 4.2 | Module layout | `src/containerizer/generate/` package, one module per generator (`containerfile`, `quadlet`, `seccomp`, `readme`) plus `syscall_table` (data) and `cli` (orchestration). | Mirrors `analyze/`. One module per issue (#40, #41, #42, plus the design-spec'd README). Easy to unit-test each in isolation; easy for M5/M6 to extend one without touching the others. |
| 4.3 | CLI input contract | `containerizer generate <policy.json> -n <name> -o <out-dir>`. Single positional + name flag + output flag. | `policy.json` is the only artifact the analyzer guarantees; pulling in `probe.json` couples generate to a separate pipeline stage with no current value (apt_packages is `[]` until M6). The `-n` flag is explicit and avoids dual-source name resolution footguns. |
| 4.4 | Templating | Stdlib Python only. Each generator is a function `(policy: PolicyJson) -> str` (or `bytes` for seccomp.json) built with `"\n".join([...])` over policy fields. No Jinja2 dep. | Outputs are small (~10-30 lines each); Jinja2's loop/conditional value doesn't pay for itself at this size. Pure Python is easier to unit-test, has zero runtime template-loading concerns, and keeps the dep footprint thin. |
| 4.5 | Sentinel handling | When `policy.image.entrypoint == ["__UNSET__"]`: skip `Containerfile` and `<name>.container`, still emit `seccomp.json` and `README.md`. README opens with a SKIPPED section explaining which artifacts weren't produced and why. CLI exits 0. | Seccomp and the audit trail are valuable independent of whether the daemon argv is known (e.g., M5 can still diff observed syscalls against the captured allowlist). Refusing everything would lose that. A loud README is enough — the missing files plus the SKIPPED section make the partial state visible. |
| 4.6 | Schema bump | `PolicyJson.schema_version: Literal[2]`, new `warnings: list[str]` field, default `[]`. `analyze/derive.derive_policy` accepts the trace warnings and passes them through; `analyze/cli` no longer needs to compute and inject the sentinel warning (still computes it for the `trace.json` side, but it flows into `policy.warnings` via the same list). | The generator's README "audit trail" section needs the unknown_rw/device/sentinel warnings, which currently only live in `trace.json`. Adding them to `policy.json` keeps the generator's input single-file and avoids a `--trace` flag. The bump is small and M4 is the only consumer. |
| 4.7 | Syscall lookup | Bundle a static `SYSCALL_NAMES: dict[int, str]` for `x86_64` generated from `arch/x86/entry/syscalls/syscall_64.tbl`. Commit the generated module + a `sandbox/regen-syscall-table.sh` script that regenerates it from a kernel checkout. CI does not regenerate. | The user runs the CLI on Windows; runtime libseccomp bindings aren't a Windows option. A static table is deterministic, has zero runtime deps, and the regenerate script makes refreshes a one-line manual operation. |
| 4.8 | Unknown syscall ID handling | If `policy.runtime.seccomp_syscalls` contains an ID not in `SYSCALL_NAMES`: drop it from the rendered allowlist, append a line to `policy.warnings`-style README audit ("syscall ID 437 not in bundled table — refresh syscall_table or upgrade") and a stderr warning. Don't crash. | An unknown ID usually means the table is stale relative to the kernel; better to ship a slightly-too-strict seccomp profile than to refuse to generate anything. The warning makes it visible. |
| 4.9 | Testing strategy | Per-module unit tests with hand-crafted in-Python `PolicyJson` inputs + hand-written expected output strings. One integration smoke test that chains `analyze` → `generate` against the M3 `synthetic-recorded/` fixture and diffs four golden files. | Mirrors M3's pattern (small parametrized unit tests + one end-to-end smoke). The integration smoke catches schema-bump regressions for free. |
| 4.10 | Templates packaged as code | No external template files in `src/containerizer/generate/templates/`. Each generator's template is a Python string built in the same `.py` file as the renderer. | Avoids the package-data-loading machinery (`importlib.resources`) and keeps test diffs in one place. The templates are short enough to inline. |

## 5. Components

### 5.1 Package layout

```
src/containerizer/generate/
  __init__.py          # "Containerizer policy generators (M4)."
  containerfile.py     # render_containerfile(policy) -> str
  quadlet.py           # render_quadlet(policy, name) -> str
  seccomp.py           # render_seccomp(policy) -> tuple[bytes, list[str]]
                       #   bytes = the JSON payload; list[str] = warnings (unknown IDs).
  readme.py            # render_readme(policy, name, *, skipped: bool) -> str
  syscall_table.py     # SYSCALL_NAMES: dict[int, str] (generated, do-not-hand-edit header)
  cli.py               # `containerizer generate` Click subcommand + write orchestration

sandbox/
  regen-syscall-table.sh   # bash helper, not run in CI
```

Each generator is pure (no I/O, no Click). The only module that touches the filesystem is `cli.py`. This keeps the renderers trivially unit-testable and lets M5's `verify` reuse them against in-memory policies.

### 5.2 `containerfile.py`

`render_containerfile(policy: PolicyJson) -> str` returns the full Containerfile text. Body (in order):

```
FROM {policy.image.base}

COPY ./installer {policy.image.installer_path}

RUN {policy.image.installer_path} \
 && rm -rf {policy.image.post_install_cleanup[0]} \
 && rm -rf {policy.image.post_install_cleanup[1]} \
 && ...
```

Then:

- If `policy.image.systemd_required`: `ENTRYPOINT ["/sbin/init"]`.
- Else (and not sentinel — sentinel is filtered upstream by `cli.py`): `ENTRYPOINT <json.dumps(policy.image.entrypoint)>`.

`policy.image.apt_packages` is unused in M4 (always `[]`); no apt install layer is emitted. When the field becomes non-empty in M6, a `RUN apt-get install -y …` layer goes between `FROM` and `COPY` — out of scope here, but the layout reserves the slot.

### 5.3 `quadlet.py`

`render_quadlet(policy: PolicyJson, name: str) -> str` returns the full `.container` text. Sections (in order):

```
[Unit]
Description=Containerized {name}
After=network-online.target
Wants=network-online.target

[Container]
Image={name}:latest
ContainerName={name}

# Volumes (named, persistent)
Volume={v.name}:{v.mount}        # one per policy.runtime.volumes

# Tmpfs (ephemeral)
Tmpfs={path}                     # one per policy.runtime.tmpfs

# Read-only bind mounts (host config)
Volume={path}:{path}:ro          # one per policy.runtime.binds_ro

# Network
PublishPort={p.host}:{p.container}/{p.proto}  # one per policy.runtime.publish_ports

# Capabilities — drops first (always includes ALL), then targeted adds
DropCapability={cap}             # one per policy.runtime.caps_drop (typically just "ALL")
AddCapability={cap}              # one per policy.runtime.caps_add (sorted alphabetically for deterministic goldens)

NoNewPrivileges={true/false}     # from policy.runtime.no_new_privileges
ReadOnly={true/false}            # from policy.runtime.read_only_rootfs

GlobalArgs=--security-opt seccomp=%h/.config/containers/seccomp/{name}.json

[Install]
WantedBy=default.target
```

Section ordering inside `[Container]` is fixed (volumes → tmpfs → binds → ports → caps → flags → seccomp) so golden diffs stay readable.

### 5.4 `seccomp.py`

`render_seccomp(policy: PolicyJson) -> tuple[bytes, list[str]]`. Resolves each `syscall_id` in `policy.runtime.seccomp_syscalls` to a name via `SYSCALL_NAMES`. Unknown IDs are dropped from the allowlist and reported in the returned warnings list (which `cli.py` surfaces to stderr and to the README).

Returned JSON shape (OCI format):

```json
{
  "defaultAction": "SCMP_ACT_ERRNO",
  "architectures": ["SCMP_ARCH_X86_64"],
  "syscalls": [
    {
      "names": ["read", "write", "execve", ...],
      "action": "SCMP_ACT_ALLOW"
    }
  ]
}
```

Serialized with `indent=2` and a trailing newline for deterministic goldens. `names` is sorted alphabetically.

### 5.5 `readme.py`

`render_readme(policy: PolicyJson, name: str, *, skipped: bool, unknown_syscall_ids: list[int]) -> str`. Sections (in order):

- **Title:** `# Containerizer output for {name}`.
- **SKIPPED (only when sentinel):** explains that `Containerfile` and `{name}.container` were not generated, quoting the sentinel warning text from `policy.warnings`, and pointing at the next step (M5 verify or a manual entrypoint override).
- **What was generated:** bullet list of files (Containerfile, Quadlet, seccomp.json, README.md) — adjusted when sentinel.
- **Audit trail:** the contents of `policy.warnings` as a bullet list. Each warning prefixed with its source (analyze emits them with stable prefixes like `unknown_rw aggregate:`, `device aggregate:`, `entrypoint is sentinel`).
- **Runtime allowlist:** one-line summaries — number of volumes, tmpfs, binds_ro, publish_ports, caps_add, seccomp syscalls. Each entry rendered with the field that justified it.
- **Unknown syscall IDs (only when non-empty):** lists the IDs that couldn't be resolved against the bundled table and suggests refreshing.
- **Next steps:** the canonical `podman build` + `systemctl --user daemon-reload && systemctl --user start {name}.service` invocation, including the seccomp profile install path.

### 5.6 `syscall_table.py`

Generated file. Header comment: "DO NOT HAND-EDIT. Regenerate via `sandbox/regen-syscall-table.sh`." Body:

```python
SYSCALL_NAMES: dict[int, str] = {
    0: "read",
    1: "write",
    ...
    # x86_64 Linux 6.x syscall table — ~450 entries
}
```

### 5.7 `cli.py`

`@click.command("analyze")`-style decorator, single function. Wiring (mirror of `analyze/cli.py`):

```python
@click.command("generate")
@click.argument("policy_path", type=click.Path(exists=True, dir_okay=False, ...))
@click.option("-n", "--name", required=True)
@click.option("-o", "--output-dir", required=True, type=click.Path(...))
def generate_cmd(policy_path: Path, name: str, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    policy = PolicyJson.model_validate_json(policy_path.read_text(encoding="utf-8"))
    sentinel = policy.image.entrypoint == [SENTINEL_ENTRYPOINT]

    seccomp_bytes, unknown_ids = render_seccomp(policy)
    (output_dir / "seccomp.json").write_bytes(seccomp_bytes)

    readme = render_readme(policy, name, skipped=sentinel, unknown_syscall_ids=unknown_ids)
    (output_dir / "README.md").write_text(readme, encoding="utf-8")

    if sentinel:
        click.echo(f"sentinel entrypoint detected — skipping Containerfile and {name}.container")
    else:
        (output_dir / "Containerfile").write_text(render_containerfile(policy), encoding="utf-8")
        (output_dir / f"{name}.container").write_text(render_quadlet(policy, name), encoding="utf-8")

    if unknown_ids:
        click.echo(f"warning: {len(unknown_ids)} syscall IDs not in bundled table: {unknown_ids}", err=True)
```

Also wires into `src/containerizer/cli.py`:

```python
from containerizer.generate.cli import generate_cmd
main.add_command(generate_cmd)
```

## 6. Schema bump details

### 6.1 `analyze/schema.py` changes

```python
class PolicyJson(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[2] = 2            # was: Literal[1] = 1
    image: PolicyImage
    runtime: PolicyRuntime
    warnings: list[str] = []                  # NEW
```

`TraceJson.schema_version` stays at 1 — only `PolicyJson` bumps. Both schema_versions are independent.

### 6.2 `analyze/derive.py` changes

`derive_policy` signature widens:

```python
def derive_policy(
    trace: TraceJson,
    *,
    probe_base: str = "ubuntu:24.04",
    warnings: list[str] | None = None,        # NEW
) -> PolicyJson:
    ...
    return PolicyJson(
        image=...,
        runtime=...,
        warnings=warnings or [],              # NEW
    )
```

### 6.3 `analyze/cli.py` changes

The existing post-derive `model_copy` that injects the sentinel warning into `trace.warnings` continues to work as-is. After computing the final `trace.warnings`, `cli.py` passes them to `derive_policy(trace, warnings=trace.warnings)`. Result: `policy.warnings == trace.warnings` (one direction; future warning types specific to policy could append more).

### 6.4 Golden refresh

The M3 `tests/fixtures/analyze/expected/synthetic-policy.json` golden was generated under schema v1 with no `warnings` field. After the bump, regenerate from the same synthetic-recorded fixture. The integration smoke test `test_analyze_smoke.py` then needs no code change — `model_validate_json` on the regenerated file is forward-compatible. Lands as part of the M4 PR.

### 6.5 Forward compatibility

A future M5/M6 schema bump that needs to drop or rename a field gets its own milestone bump. M4 does NOT define a v1→v2 migration shim; the analyzer always produces v2, the generator always consumes v2.

## 7. Error and warning surfaces

| Situation | Behavior |
|-----------|----------|
| `<policy.json>` missing or unreadable | Hard error via Click `Path(exists=True)`. |
| `<policy.json>` parses but fails `PolicyJson.model_validate_json` (e.g., v1 schema) | Hard error wrapped as `ClickException` with the Pydantic validation summary. Tell the user to re-run `containerizer analyze` to upgrade. |
| `<out-dir>` doesn't exist | `mkdir(parents=True, exist_ok=True)`, same as analyze. |
| Sentinel entrypoint | Skip Containerfile + Quadlet; emit seccomp + README with SKIPPED section. Exit 0. Echo to stderr "sentinel entrypoint detected — skipping Containerfile and {name}.container". |
| Unknown syscall ID in `policy.runtime.seccomp_syscalls` | Drop from allowlist; append to returned warnings; surface in README's "Unknown syscall IDs" section; echo to stderr. Exit 0. |
| Empty `policy.runtime.seccomp_syscalls` | Render `"syscalls": []` (an empty allowlist) and a README line noting that the seccomp profile blocks everything except the OCI defaults. Don't error — a probe with no runtime is possible. |
| Empty `policy.runtime.caps_add` | Render the `DropCapability=ALL` lines (always present per policy.runtime.caps_drop), omit `AddCapability=` lines, README notes "no capabilities added". |

## 8. Testing strategy

### 8.1 Unit tests

`tests/unit/generate/`:

- `test_containerfile.py` — feed hand-crafted `PolicyJson` (minimal, systemd_required, with cleanup), assert exact output string.
- `test_quadlet.py` — minimal policy, policy with volumes, policy with multiple ports, policy with caps. Assert exact `.container` text.
- `test_seccomp.py` — minimal policy (empty allowlist), policy with known IDs (resolves to names), policy with unknown IDs (drops + returns warning). Assert JSON shape via parsed `dict` comparison and the warnings list.
- `test_readme.py` — sentinel vs non-sentinel, with vs without unknown IDs, with vs without `policy.warnings`. Assert section presence (don't pin exact prose).
- `test_syscall_table.py` — assert a handful of well-known entries (0=read, 1=write, 2=open, 59=execve), assert table size is "approximately 450" (range check), assert no duplicate values.
- `test_cli.py` — CliRunner happy-path (3 or 4 files exist, are non-empty, parse correctly), sentinel path (Containerfile and `.container` absent), unknown-syscall path (stderr warning).

Each test sets up its `PolicyJson` in-Python (not from disk) so the test is self-documenting.

### 8.2 Integration smoke test

`tests/integration/generate/test_generate_smoke.py`:

1. Run `containerizer analyze tests/fixtures/trace/synthetic-recorded -o <tmp1>` to produce `policy.json`.
2. Run `containerizer generate <tmp1>/policy.json -n synthetic -o <tmp2>` to produce the four files.
3. Compare each of the four files to the golden in `tests/fixtures/generate/expected/`.

The goldens are committed and refreshed by hand (same workflow as M3's analyze goldens). The synthetic-recorded fixture's policy has `entrypoint == ["__UNSET__"]` (no systemd in runtime execs), so this smoke test exercises the sentinel path. A second test in the same file uses an in-Python `PolicyJson` with systemd_required=True and asserts the non-sentinel path emits all four.

### 8.3 Coverage gate

`pyproject.toml` `--cov-fail-under=90` remains. M4 keeps total coverage ≥ 90%; the smoke test doesn't contribute to coverage (no `integration` marker, but it's pure-Python so it does count — only the M2 trace integration test is excluded).

## 9. Exit criteria

M4 is done when:

1. `containerizer generate tests/fixtures/analyze/expected/synthetic-policy.json -n synthetic -o <tmp>` produces `seccomp.json` + `README.md` (sentinel path: `Containerfile` and `synthetic.container` are absent). `test_generate_smoke.py::test_sentinel_path` passes.
2. A separate non-sentinel `PolicyJson` produces all four files. `test_generate_smoke.py::test_full_emit` passes.
3. PolicyJson schema is v2 with `warnings: list[str]`; M3 synthetic golden `policy.json` is regenerated and committed; all prior M3 tests still pass.
4. All four generators have unit tests with hand-crafted policies + hand-written expected output assertions.
5. `pytest` (unit + integration, no `-m integration` exclusion) is green. Coverage ≥ 90%.
6. `ruff check . && ruff format --check . && mypy src tests && pytest` is green.
7. MANUAL.md scenario 8 (running generate) is added.
8. `gh pr create` opens a PR closing #40, #41, #42.

## 10. Out of scope (carried forward to M5/M6)

- `apt_packages` rendering (M6).
- Daemon argv detection beyond the sentinel (M5/M6).
- `read_only_rootfs=true` derivation (M6).
- Multi-arch seccomp (M6+).
- Egress allowlist (parent §2 non-goal).
- `verify` subcommand consuming the generated artifacts (M5, #43).
- `build` subcommand orchestrating the whole pipeline (M6, #44).
