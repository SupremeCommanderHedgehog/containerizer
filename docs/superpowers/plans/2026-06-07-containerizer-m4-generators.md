# M4 Generators Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the M4 milestone of the containerizer per [`docs/superpowers/specs/2026-06-07-containerizer-m4-generators.md`](../specs/2026-06-07-containerizer-m4-generators.md): a `containerizer generate <policy.json> -n <name> -o <out-dir>` subcommand that consumes `policy.json` (M3's output) and emits `Containerfile`, `<name>.container`, `seccomp.json`, and `README.md`. Sentinel entrypoint policies emit only `seccomp.json` + `README.md`.

**Architecture:** A new `src/containerizer/generate/` package with one module per artifact (`containerfile`, `quadlet`, `seccomp`, `readme`), a bundled `syscall_table.py` for syscall_id→name resolution, and a `cli.py` orchestrator. Each renderer is a pure function `(policy: PolicyJson) -> str | bytes`; `cli.py` is the only module that touches disk. Templating is stdlib-only string building (no Jinja2 dep). The plan also includes a small schema bump (`PolicyJson` v1→v2 with a new `warnings: list[str]` field) so the generator's README "audit trail" stays single-input.

**Tech Stack:** Python 3.11+ + Click + Pydantic v2 (already in `pyproject.toml`), pytest. No new third-party dependencies.

---

## Conventions used throughout

- **Working directory:** all commands assume `C:\Users\yizshachuck\source\containerizer\` is the cwd. Use absolute paths in tools (Read/Edit/Write); use relative paths in shell commands.
- **Branch + PR strategy.** Single branch `feat/m4-generators` off latest `main`. One PR at the end closing #40, #41, #42. Per-task signed commits. Mirrors how M3 was actually executed (the plan's literal "PR per task" wording from M3 was overhead; M4 commits straight to the integration branch).
- **Commit signing.** Every commit MUST be signed per the user's global `CLAUDE.md`:
  ```
  git -c user.email="github.v5f9w@bitbucket.onl" \
      -c user.signingkey=BE707B220C995478 \
      commit -S -m "<message>"
  ```
  Never pass `--no-gpg-sign`. Never amend a published commit.
- **Conventional commit subject** per task. `feat(generate):` for new generate modules; `feat(analyze):` or `refactor(analyze):` for the schema bump pieces; `test(generate):` for fixtures and tests; `docs:` for the MANUAL update.
- **Close the matching issues.** This plan covers issues #40 (Containerfile), #41 (Quadlet), #42 (seccomp). Final task references all three with `Closes #40, #41, #42`.
- **Coverage gate.** `pyproject.toml` enforces `--cov-fail-under=90`. New code in `src/containerizer/generate/` must keep total coverage ≥ 90%.
- **Lint + type gate.** `ruff check . && ruff format --check . && mypy src tests && pytest` must pass before pushing every task.
- **Pydantic style.** v2, `BaseModel` subclasses, `ConfigDict(extra="forbid", frozen=True)` on every model. Match the precedent in `analyze/schema.py`.
- **No magic numbers.** Constants live at module top with a one-line comment if non-obvious.
- **Line endings.** Repo is set up for LF; Windows working copies see CRLF warnings. Benign.
- **Cross-platform code.** The user runs the CLI on Windows; any helper scripts that need to run cross-platform should be Python, not bash.

---

## File map

Files created or modified by this plan:

| Path | Purpose | Task |
|---|---|---|
| `src/containerizer/generate/__init__.py` | Package marker | 1 |
| `src/containerizer/analyze/schema.py` | Bump PolicyJson to v2; add `warnings` field | 2 |
| `src/containerizer/analyze/derive.py` | Accept `warnings` kwarg, pass through to PolicyJson | 3 |
| `src/containerizer/analyze/cli.py` | Pass `trace.warnings` to `derive_policy` | 4 |
| `tests/fixtures/analyze/expected/synthetic-policy.json` | Regenerate for v2 schema | 4 |
| `sandbox/regen_syscall_table.py` | One-shot Python helper to regenerate the table | 5 |
| `src/containerizer/generate/syscall_table.py` | Bundled `SYSCALL_NAMES: dict[int, str]` (generated) | 5 |
| `src/containerizer/generate/seccomp.py` | `render_seccomp(policy) -> (bytes, list[int])` | 6 |
| `src/containerizer/generate/containerfile.py` | `render_containerfile(policy) -> str` | 7 |
| `src/containerizer/generate/quadlet.py` | `render_quadlet(policy, name) -> str` | 8 |
| `src/containerizer/generate/readme.py` | `render_readme(policy, name, *, skipped, unknown_syscall_ids) -> str` | 9 |
| `src/containerizer/generate/cli.py` | `generate_cmd` Click subcommand | 10 |
| `src/containerizer/cli.py` | Register `generate_cmd` on the main group | 10 |
| `tests/unit/generate/__init__.py` | Test package marker | 1 |
| `tests/unit/generate/test_syscall_table.py` | Table size + key entries pinned | 5 |
| `tests/unit/generate/test_seccomp.py` | Empty / known / unknown ID paths | 6 |
| `tests/unit/generate/test_containerfile.py` | Minimal / systemd / cleanup paths | 7 |
| `tests/unit/generate/test_quadlet.py` | Volumes, ports, caps, binds_ro paths | 8 |
| `tests/unit/generate/test_readme.py` | Sentinel vs non-sentinel sections | 9 |
| `tests/unit/generate/test_cli.py` | Happy path, sentinel path, unknown ID path | 10 |
| `tests/integration/generate/__init__.py` | Test package marker | 11 |
| `tests/integration/generate/test_generate_smoke.py` | analyze → generate against goldens | 11 |
| `tests/fixtures/generate/expected/Containerfile` | Golden (non-sentinel smoke) | 11 |
| `tests/fixtures/generate/expected/synthetic-os.container` | Golden Quadlet | 11 |
| `tests/fixtures/generate/expected/seccomp.json` | Golden seccomp (sentinel-path smoke) | 11 |
| `tests/fixtures/generate/expected/README.md` | Golden README (sentinel-path smoke) | 11 |
| `MANUAL.md` | Add scenario 8 (running generate) | 12 |

---

## Task 1: New `generate/` package + empty test directory

**Issue:** prep (no individual issue).

**Files:**
- Create: `src/containerizer/generate/__init__.py`
- Create: `tests/unit/generate/__init__.py`

This task lands first to give every later task a stable target package.

- [ ] **Step 1: Create the package marker**

Write `src/containerizer/generate/__init__.py`:

```python
"""Containerizer policy generators (M4)."""
```

- [ ] **Step 2: Create the unit-test package marker**

Write `tests/unit/generate/__init__.py` (empty file).

- [ ] **Step 3: Run the gate**

```
ruff check . && ruff format --check . && mypy src tests && pytest
```

Expected: PASS.

- [ ] **Step 4: Commit**

```
git -c user.email="github.v5f9w@bitbucket.onl" \
    -c user.signingkey=BE707B220C995478 \
    commit -S -m "feat(generate): bootstrap generate package + test directory"
```

---

## Task 2: Schema bump — `PolicyJson` v2 + `warnings` field

**Issue:** #40, #41, #42 (prep).

**Files:**
- Modify: `src/containerizer/analyze/schema.py` (PolicyJson model only)
- Modify: `tests/unit/analyze/test_schema.py` (any tests pinning PolicyJson.schema_version=1)

The generator's README needs the audit trail (sentinel, unknown_rw, device warnings). Those live in `trace.json.warnings` today; we copy them into `policy.warnings` so the generator stays single-input.

- [ ] **Step 1: Find existing tests that pin `schema_version`**

Run: `grep -nE "schema_version.*1|policy.*schema_version" tests/unit/analyze/test_schema.py`

Expected: one or two test assertions of the form `assert policy.schema_version == 1` or similar. Note their locations — Step 4 updates them.

- [ ] **Step 2: Modify `PolicyJson` in `src/containerizer/analyze/schema.py`**

Find the existing block:

```python
class PolicyJson(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    image: PolicyImage
    runtime: PolicyRuntime
```

Replace with:

```python
class PolicyJson(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[2] = 2
    image: PolicyImage
    runtime: PolicyRuntime
    warnings: list[str] = []
```

(`TraceJson.schema_version` stays at 1. The two schema_versions are independent.)

- [ ] **Step 3: Add a unit test for the new field**

Append to `tests/unit/analyze/test_schema.py`:

```python
def test_policy_json_v2_has_warnings_field() -> None:
    policy = PolicyJson(
        image=PolicyImage(
            base="ubuntu:24.04",
            apt_packages=[],
            post_install_cleanup=[],
            systemd_required=False,
            entrypoint=["__UNSET__"],
        ),
        runtime=PolicyRuntime(
            volumes=[], tmpfs=[], binds_ro=[], publish_ports=[],
            caps_add=[], seccomp_syscalls=[], read_only_rootfs=False,
        ),
        warnings=["unknown_rw aggregate: /var/lib/foo"],
    )
    assert policy.schema_version == 2
    assert policy.warnings == ["unknown_rw aggregate: /var/lib/foo"]


def test_policy_json_warnings_defaults_to_empty_list() -> None:
    policy = PolicyJson(
        image=PolicyImage(
            base="ubuntu:24.04",
            apt_packages=[],
            post_install_cleanup=[],
            systemd_required=False,
            entrypoint=["__UNSET__"],
        ),
        runtime=PolicyRuntime(
            volumes=[], tmpfs=[], binds_ro=[], publish_ports=[],
            caps_add=[], seccomp_syscalls=[], read_only_rootfs=False,
        ),
    )
    assert policy.warnings == []
```

- [ ] **Step 4: Update any existing tests in `test_schema.py` that pin v1**

If Step 1 found `assert ... schema_version == 1` for PolicyJson, change to `== 2`. Leave TraceJson schema_version=1 assertions alone.

- [ ] **Step 5: Run the gate**

```
pytest tests/unit/analyze/test_schema.py -v
ruff check . && ruff format --check . && mypy src tests && pytest
```

Expected: PASS for the schema test; the analyze unit tests + integration smoke test may FAIL until Tasks 3-4 update derive.py + golden. That's expected — proceed.

If the gate fails purely due to those known-broken tests, note which ones in your commit message so the next task knows what to fix. If it fails for unrelated reasons, stop and report.

- [ ] **Step 6: Commit**

```
git add src/containerizer/analyze/schema.py tests/unit/analyze/test_schema.py
git -c user.email="github.v5f9w@bitbucket.onl" \
    -c user.signingkey=BE707B220C995478 \
    commit -S -m "feat(analyze): bump PolicyJson to v2 with warnings field"
```

---

## Task 3: `derive.py` — accept `warnings` kwarg

**Issue:** #40, #41, #42 (prep).

**Files:**
- Modify: `src/containerizer/analyze/derive.py` (`derive_policy` signature)
- Modify: `tests/unit/analyze/test_derive.py` (one new test)

`derive_policy` widens to accept an optional `warnings` list and forwards it into `PolicyJson.warnings`. No other behavior changes.

- [ ] **Step 1: Read the current `derive.py` signature**

Run: `head -40 src/containerizer/analyze/derive.py`

Confirm the signature is:
```python
def derive_policy(trace: TraceJson, *, probe_base: str = "ubuntu:24.04") -> PolicyJson:
```

- [ ] **Step 2: Add the failing test**

Append to `tests/unit/analyze/test_derive.py`:

```python
def test_derive_policy_forwards_warnings_to_policy() -> None:
    trace = _make_trace()
    policy = derive_policy(trace, warnings=["unknown_rw aggregate: /var/lib/x", "device aggregate: /dev/foo"])
    assert policy.warnings == ["unknown_rw aggregate: /var/lib/x", "device aggregate: /dev/foo"]


def test_derive_policy_warnings_defaults_to_empty() -> None:
    trace = _make_trace()
    policy = derive_policy(trace)
    assert policy.warnings == []
```

- [ ] **Step 3: Run test to verify failure**

Run: `pytest tests/unit/analyze/test_derive.py::test_derive_policy_forwards_warnings_to_policy -v`
Expected: FAIL (TypeError: unexpected keyword argument 'warnings' OR AssertionError on `policy.warnings`).

- [ ] **Step 4: Update `derive_policy`**

In `src/containerizer/analyze/derive.py`, change the signature:

```python
def derive_policy(
    trace: TraceJson,
    *,
    probe_base: str = "ubuntu:24.04",
    warnings: list[str] | None = None,
) -> PolicyJson:
```

In the `return PolicyJson(...)` block at the bottom of the function, add `warnings=warnings or []` to the kwargs:

```python
    return PolicyJson(
        image=PolicyImage(...),
        runtime=PolicyRuntime(...),
        warnings=warnings or [],
    )
```

- [ ] **Step 5: Run the gate**

```
pytest tests/unit/analyze/test_derive.py -v
ruff check . && ruff format --check . && mypy src tests && pytest
```

Expected: derive tests PASS. The analyze CLI tests and integration smoke may still be broken (Task 4 fixes those).

- [ ] **Step 6: Commit**

```
git add src/containerizer/analyze/derive.py tests/unit/analyze/test_derive.py
git -c user.email="github.v5f9w@bitbucket.onl" \
    -c user.signingkey=BE707B220C995478 \
    commit -S -m "feat(analyze): derive_policy forwards warnings into PolicyJson.warnings"
```

---

## Task 4: `analyze/cli.py` passes warnings through + regenerate M3 golden

**Issue:** #40, #41, #42 (prep).

**Files:**
- Modify: `src/containerizer/analyze/cli.py`
- Regenerate: `tests/fixtures/analyze/expected/synthetic-policy.json`

`_assemble_trace_json` already produces a `trace` whose `warnings` list is final (after the sentinel `model_copy`). Now `derive_policy` needs to receive those warnings.

- [ ] **Step 1: Find the call to `derive_policy` in `analyze/cli.py`**

Run: `grep -n "derive_policy" src/containerizer/analyze/cli.py`

Note the line (it's a single call inside `generate_cmd`).

- [ ] **Step 2: Update the call**

Change:
```python
    policy = derive_policy(trace)
```
to:
```python
    policy = derive_policy(trace, warnings=list(trace.warnings))
```

(`list(...)` defensive-copies the frozen list to a mutable one for the kwarg pattern; minor but matches the project's caution around frozen models.)

- [ ] **Step 3: Run the CLI tests**

Run: `pytest tests/unit/analyze/test_cli.py -v`
Expected: PASS. Existing tests check trace.warnings semantics; they're unaffected.

- [ ] **Step 4: Regenerate the M3 synthetic golden**

Run (PowerShell):
```powershell
.venv\Scripts\containerizer.exe analyze tests/fixtures/trace/synthetic-recorded -o tests/fixtures/analyze/expected
Move-Item -Force tests/fixtures/analyze/expected/policy.json tests/fixtures/analyze/expected/synthetic-policy.json
Remove-Item tests/fixtures/analyze/expected/trace.json
```

(The trace.json output is unchanged from M3 — overwriting and then removing leaves the existing synthetic-trace.json intact. If a `Move-Item` step replaces synthetic-trace.json instead of the unmoved trace.json, run analyze separately to a temp dir and copy only policy.json over.)

A safer one-liner:
```powershell
$tmp = New-Item -ItemType Directory -Path ([System.IO.Path]::GetTempPath() + [System.Guid]::NewGuid())
.venv\Scripts\containerizer.exe analyze tests/fixtures/trace/synthetic-recorded -o $tmp
Move-Item -Force $tmp/policy.json tests/fixtures/analyze/expected/synthetic-policy.json
Remove-Item -Recurse $tmp
```

- [ ] **Step 5: Verify the regenerated golden has `schema_version: 2` and a `warnings` field**

Open `tests/fixtures/analyze/expected/synthetic-policy.json`. Confirm:
- First two keys: `"schema_version": 2`, `"image": {...}`.
- Bottom of file has a `"warnings": [...]` array containing the sentinel warning string `"entrypoint is sentinel ['__UNSET__']; M4 must refuse this policy"` plus any other warnings the synthetic trace produces.

If `schema_version` is 1 or `warnings` is missing, Steps 2-3 didn't take effect. Re-check the cli.py change.

- [ ] **Step 6: Run the integration smoke test**

Run: `pytest tests/integration/analyze/test_analyze_smoke.py -v`
Expected: PASS. Regenerated golden matches the analyzer's new output.

- [ ] **Step 7: Run the full gate**

```
ruff check . && ruff format --check . && mypy src tests && pytest
```

Expected: PASS.

- [ ] **Step 8: Commit**

```
git add src/containerizer/analyze/cli.py tests/fixtures/analyze/expected/synthetic-policy.json
git -c user.email="github.v5f9w@bitbucket.onl" \
    -c user.signingkey=BE707B220C995478 \
    commit -S -m "feat(analyze): cli forwards trace.warnings into PolicyJson + regen golden"
```

---

## Task 5: `syscall_table.py` + regen script

**Issue:** #42.

**Files:**
- Create: `sandbox/regen_syscall_table.py`
- Create: `src/containerizer/generate/syscall_table.py` (generated)
- Create: `tests/unit/generate/test_syscall_table.py`

Bundled lookup of `syscall_id → name` for `x86_64`, generated from the Linux kernel's `arch/x86/entry/syscalls/syscall_64.tbl`. The regen script runs by hand when the table goes stale.

- [ ] **Step 1: Write the regen script**

Write `sandbox/regen_syscall_table.py`:

```python
#!/usr/bin/env python3
"""Regenerate src/containerizer/generate/syscall_table.py from the upstream
Linux kernel's arch/x86/entry/syscalls/syscall_64.tbl.

Not run in CI. Invoke by hand whenever the kernel adds new syscalls and you
want the bundled table to cover them. The currently-pinned kernel tag is the
constant TBL_URL at the top.

Usage:
    python sandbox/regen_syscall_table.py
"""

from __future__ import annotations

import re
import sys
import urllib.request
from pathlib import Path

# Pin to a specific kernel tag so regeneration is reproducible. Bump as needed.
KERNEL_TAG = "v6.6"
TBL_URL = (
    f"https://raw.githubusercontent.com/torvalds/linux/{KERNEL_TAG}/"
    f"arch/x86/entry/syscalls/syscall_64.tbl"
)

OUTPUT_PATH = (
    Path(__file__).resolve().parent.parent
    / "src" / "containerizer" / "generate" / "syscall_table.py"
)

# syscall_64.tbl lines look like:
#   0       common  read                    sys_read
#   1       common  write                   sys_write
# We want columns 1 (number), 2 (abi), 3 (name).
# Skip lines starting with '#', empty lines, and abi=='x32' (32-bit compat).
LINE_RE = re.compile(r"^\s*(\d+)\s+(\S+)\s+(\S+)\s+\S+\s*(?:#.*)?$")


def fetch_table(url: str) -> str:
    with urllib.request.urlopen(url, timeout=30) as resp:
        return resp.read().decode("utf-8")


def parse(text: str) -> dict[int, str]:
    table: dict[int, str] = {}
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = LINE_RE.match(line)
        if not match:
            continue
        sysno, abi, name = match.group(1), match.group(2), match.group(3)
        if abi == "x32":
            continue
        table[int(sysno)] = name
    return table


def render(table: dict[int, str], source_tag: str) -> str:
    lines = [
        '"""Bundled x86_64 syscall_id -> name lookup table.',
        "",
        "DO NOT HAND-EDIT. Regenerate via:",
        "    python sandbox/regen_syscall_table.py",
        "",
        f"Source: torvalds/linux@{source_tag} arch/x86/entry/syscalls/syscall_64.tbl",
        '"""',
        "",
        "from __future__ import annotations",
        "",
        "SYSCALL_NAMES: dict[int, str] = {",
    ]
    for sysno in sorted(table):
        lines.append(f"    {sysno}: {table[sysno]!r},")
    lines.append("}")
    return "\n".join(lines) + "\n"


def main() -> int:
    print(f"fetching {TBL_URL}", file=sys.stderr)
    text = fetch_table(TBL_URL)
    table = parse(text)
    print(f"parsed {len(table)} entries", file=sys.stderr)
    OUTPUT_PATH.write_text(render(table, KERNEL_TAG), encoding="utf-8")
    print(f"wrote {OUTPUT_PATH}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Run the regen script**

```
python sandbox/regen_syscall_table.py
```

Expected output:
```
fetching https://raw.githubusercontent.com/torvalds/linux/v6.6/arch/x86/entry/syscalls/syscall_64.tbl
parsed N entries
wrote C:\Users\yizshachuck\source\containerizer\src\containerizer\generate\syscall_table.py
```

Where N is around 350-450. If N is dramatically off (e.g., 0 or 1000+), inspect the parser regex.

- [ ] **Step 3: Verify the generated file**

Open `src/containerizer/generate/syscall_table.py`. Confirm it starts with the docstring, has `SYSCALL_NAMES: dict[int, str] = {`, and contains lines like `0: 'read',`, `1: 'write',`, `2: 'open',`, `59: 'execve',`. The file should be roughly 450 lines.

- [ ] **Step 4: Write the table unit test**

Write `tests/unit/generate/test_syscall_table.py`:

```python
"""Tests for the bundled syscall table."""

from __future__ import annotations

from containerizer.generate.syscall_table import SYSCALL_NAMES


def test_table_pins_well_known_x86_64_syscalls() -> None:
    # If any of these change, x86_64 ABI is broken or our parser is wrong.
    assert SYSCALL_NAMES[0] == "read"
    assert SYSCALL_NAMES[1] == "write"
    assert SYSCALL_NAMES[2] == "open"
    assert SYSCALL_NAMES[3] == "close"
    assert SYSCALL_NAMES[59] == "execve"
    assert SYSCALL_NAMES[60] == "exit"


def test_table_size_is_reasonable() -> None:
    # Kernel v6.6 has roughly 380 x86_64 syscalls. A wide range catches both
    # accidental truncation and accidental inclusion of x32 entries.
    assert 300 <= len(SYSCALL_NAMES) <= 500


def test_table_values_are_unique() -> None:
    # Two syscall IDs mapping to the same name would be a parser bug.
    assert len(set(SYSCALL_NAMES.values())) == len(SYSCALL_NAMES)
```

- [ ] **Step 5: Run the test + gate**

```
pytest tests/unit/generate/test_syscall_table.py -v
ruff check . && ruff format --check . && mypy src tests && pytest
```

Expected: PASS. The generated file is large; ruff/mypy should handle it cleanly (it's just a dict literal).

- [ ] **Step 6: Commit**

```
git add sandbox/regen_syscall_table.py src/containerizer/generate/syscall_table.py tests/unit/generate/test_syscall_table.py
git -c user.email="github.v5f9w@bitbucket.onl" \
    -c user.signingkey=BE707B220C995478 \
    commit -S -m "feat(generate): bundled syscall_table.py + regen script (Linux v6.6 x86_64)"
```

---

## Task 6: `seccomp.py`

**Issue:** #42.

**Files:**
- Create: `src/containerizer/generate/seccomp.py`
- Create: `tests/unit/generate/test_seccomp.py`

Render the OCI-format `seccomp.json` payload as bytes; return alongside a warnings list for unknown IDs.

- [ ] **Step 1: Write the failing tests**

Write `tests/unit/generate/test_seccomp.py`:

```python
"""Tests for analyze.generate.seccomp."""

from __future__ import annotations

import json

from containerizer.analyze.schema import (
    PolicyImage,
    PolicyJson,
    PolicyRuntime,
)
from containerizer.generate.seccomp import render_seccomp


def _policy(syscalls: list[int]) -> PolicyJson:
    return PolicyJson(
        image=PolicyImage(
            base="ubuntu:24.04",
            apt_packages=[],
            post_install_cleanup=[],
            systemd_required=False,
            entrypoint=["__UNSET__"],
        ),
        runtime=PolicyRuntime(
            volumes=[], tmpfs=[], binds_ro=[], publish_ports=[],
            caps_add=[], seccomp_syscalls=syscalls, read_only_rootfs=False,
        ),
    )


def test_empty_allowlist_renders_oci_shape() -> None:
    payload, unknown = render_seccomp(_policy([]))
    obj = json.loads(payload)
    assert obj["defaultAction"] == "SCMP_ACT_ERRNO"
    assert obj["architectures"] == ["SCMP_ARCH_X86_64"]
    assert obj["syscalls"] == [{"names": [], "action": "SCMP_ACT_ALLOW"}]
    assert unknown == []


def test_known_ids_resolve_to_sorted_names() -> None:
    payload, unknown = render_seccomp(_policy([59, 1, 0]))  # execve, write, read
    obj = json.loads(payload)
    assert obj["syscalls"][0]["names"] == ["execve", "read", "write"]
    assert unknown == []


def test_unknown_ids_dropped_and_returned() -> None:
    payload, unknown = render_seccomp(_policy([0, 99999]))
    obj = json.loads(payload)
    assert obj["syscalls"][0]["names"] == ["read"]
    assert unknown == [99999]


def test_payload_is_pretty_printed_with_trailing_newline() -> None:
    payload, _ = render_seccomp(_policy([0]))
    text = payload.decode("utf-8")
    assert text.endswith("\n")
    assert "  " in text  # indented JSON
```

(The cli layer is responsible for formatting the unknown-IDs warning string for stderr; seccomp.py just returns the raw int list.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/generate/test_seccomp.py -v`
Expected: FAIL with ImportError on `render_seccomp`.

- [ ] **Step 3: Implement `seccomp.py`**

Write `src/containerizer/generate/seccomp.py`:

```python
"""Render PolicyJson into an OCI seccomp.json payload."""

from __future__ import annotations

import json

from containerizer.analyze.schema import PolicyJson
from containerizer.generate.syscall_table import SYSCALL_NAMES

DEFAULT_ACTION = "SCMP_ACT_ERRNO"
ALLOW_ACTION = "SCMP_ACT_ALLOW"
ARCHITECTURES = ["SCMP_ARCH_X86_64"]


def render_seccomp(policy: PolicyJson) -> tuple[bytes, list[int]]:
    """Render policy.runtime.seccomp_syscalls as an OCI seccomp profile.

    Returns (payload_bytes, unknown_ids). Unknown syscall IDs are dropped
    from the allowlist; the caller is responsible for surfacing them to
    the user (cli.py emits both a stderr warning and a README section).
    """
    names: list[str] = []
    unknown: list[int] = []
    for sysno in policy.runtime.seccomp_syscalls:
        name = SYSCALL_NAMES.get(sysno)
        if name is None:
            unknown.append(sysno)
        else:
            names.append(name)

    payload = {
        "defaultAction": DEFAULT_ACTION,
        "architectures": ARCHITECTURES,
        "syscalls": [{"names": sorted(names), "action": ALLOW_ACTION}],
    }
    text = json.dumps(payload, indent=2) + "\n"
    return text.encode("utf-8"), unknown
```

- [ ] **Step 4: Run tests + gate + commit**

```
pytest tests/unit/generate/test_seccomp.py -v
ruff check . && ruff format --check . && mypy src tests && pytest
git add src/containerizer/generate/seccomp.py tests/unit/generate/test_seccomp.py
git -c user.email="github.v5f9w@bitbucket.onl" \
    -c user.signingkey=BE707B220C995478 \
    commit -S -m "feat(generate): seccomp.py — OCI seccomp profile from PolicyJson"
```

---

## Task 7: `containerfile.py`

**Issue:** #40.

**Files:**
- Create: `src/containerizer/generate/containerfile.py`
- Create: `tests/unit/generate/test_containerfile.py`

Render the Containerfile body. apt_packages is always `[]` in M4, so no apt layer.

- [ ] **Step 1: Write the failing tests**

Write `tests/unit/generate/test_containerfile.py`:

```python
"""Tests for analyze.generate.containerfile."""

from __future__ import annotations

from containerizer.analyze.schema import (
    PolicyImage,
    PolicyJson,
    PolicyRuntime,
)
from containerizer.generate.containerfile import render_containerfile


def _policy(
    *,
    systemd_required: bool,
    entrypoint: list[str],
    cleanup: list[str] | None = None,
) -> PolicyJson:
    return PolicyJson(
        image=PolicyImage(
            base="ubuntu:24.04",
            apt_packages=[],
            post_install_cleanup=cleanup or [],
            systemd_required=systemd_required,
            entrypoint=entrypoint,
        ),
        runtime=PolicyRuntime(
            volumes=[], tmpfs=[], binds_ro=[], publish_ports=[],
            caps_add=[], seccomp_syscalls=[], read_only_rootfs=False,
        ),
    )


def test_containerfile_minimal_argv_entrypoint() -> None:
    text = render_containerfile(
        _policy(systemd_required=False, entrypoint=["/opt/app/bin/app", "--config", "/etc/app.conf"])
    )
    assert text.startswith("FROM ubuntu:24.04\n")
    assert "COPY ./installer /installer\n" in text
    assert "RUN /installer" in text
    assert 'ENTRYPOINT ["/opt/app/bin/app", "--config", "/etc/app.conf"]\n' in text


def test_containerfile_systemd_entrypoint_overrides_argv() -> None:
    text = render_containerfile(
        _policy(systemd_required=True, entrypoint=["/opt/app/bin/app"])
    )
    assert 'ENTRYPOINT ["/sbin/init"]\n' in text
    assert "/opt/app/bin/app" not in text


def test_containerfile_cleanup_lines_appended_to_run() -> None:
    text = render_containerfile(
        _policy(
            systemd_required=False,
            entrypoint=["/x"],
            cleanup=["/var/cache/apt/archives/*", "/installer"],
        )
    )
    assert "RUN /installer \\\n && rm -rf /var/cache/apt/archives/* \\\n && rm -rf /installer\n" in text


def test_containerfile_ends_with_trailing_newline() -> None:
    text = render_containerfile(_policy(systemd_required=False, entrypoint=["/x"]))
    assert text.endswith("\n")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/generate/test_containerfile.py -v`
Expected: FAIL with ImportError.

- [ ] **Step 3: Implement `containerfile.py`**

Write `src/containerizer/generate/containerfile.py`:

```python
"""Render PolicyJson into a Containerfile."""

from __future__ import annotations

import json

from containerizer.analyze.schema import PolicyJson


def render_containerfile(policy: PolicyJson) -> str:
    """Render the policy as a Containerfile string with trailing newline.

    apt_packages is always `[]` in M4; no apt install layer is emitted.
    Sentinel-entrypoint policies are filtered upstream by cli.py — this
    function assumes a real entrypoint.
    """
    lines: list[str] = [
        f"FROM {policy.image.base}",
        "",
        f"COPY ./installer {policy.image.installer_path}",
        "",
    ]
    run_parts = [f"RUN {policy.image.installer_path}"]
    for path in policy.image.post_install_cleanup:
        run_parts.append(f" && rm -rf {path}")
    lines.append(" \\\n".join(run_parts))
    lines.append("")

    if policy.image.systemd_required:
        entrypoint = ["/sbin/init"]
    else:
        entrypoint = list(policy.image.entrypoint)
    lines.append(f"ENTRYPOINT {json.dumps(entrypoint)}")
    return "\n".join(lines) + "\n"
```

- [ ] **Step 4: Run tests + gate + commit**

```
pytest tests/unit/generate/test_containerfile.py -v
ruff check . && ruff format --check . && mypy src tests && pytest
git add src/containerizer/generate/containerfile.py tests/unit/generate/test_containerfile.py
git -c user.email="github.v5f9w@bitbucket.onl" \
    -c user.signingkey=BE707B220C995478 \
    commit -S -m "feat(generate): containerfile.py — Containerfile from PolicyJson"
```

---

## Task 8: `quadlet.py`

**Issue:** #41.

**Files:**
- Create: `src/containerizer/generate/quadlet.py`
- Create: `tests/unit/generate/test_quadlet.py`

Render the `.container` Quadlet unit. Sections in fixed order for deterministic goldens.

- [ ] **Step 1: Write the failing tests**

Write `tests/unit/generate/test_quadlet.py`:

```python
"""Tests for analyze.generate.quadlet."""

from __future__ import annotations

from containerizer.analyze.schema import (
    PolicyImage,
    PolicyJson,
    PolicyPort,
    PolicyRuntime,
    PolicyVolume,
)
from containerizer.generate.quadlet import render_quadlet

_IMAGE = PolicyImage(
    base="ubuntu:24.04",
    apt_packages=[],
    post_install_cleanup=[],
    systemd_required=False,
    entrypoint=["/opt/app/bin/app"],
)


def _runtime(
    *,
    volumes: list[PolicyVolume] | None = None,
    tmpfs: list[str] | None = None,
    binds_ro: list[str] | None = None,
    ports: list[PolicyPort] | None = None,
    caps_add: list[str] | None = None,
) -> PolicyRuntime:
    return PolicyRuntime(
        volumes=volumes or [],
        tmpfs=tmpfs or [],
        binds_ro=binds_ro or [],
        publish_ports=ports or [],
        caps_add=caps_add or [],
        seccomp_syscalls=[],
        read_only_rootfs=False,
    )


def _policy(runtime: PolicyRuntime) -> PolicyJson:
    return PolicyJson(image=_IMAGE, runtime=runtime)


def test_quadlet_has_required_sections() -> None:
    text = render_quadlet(_policy(_runtime()), "myapp")
    assert "[Unit]" in text
    assert "[Container]" in text
    assert "[Install]" in text
    assert "Image=myapp:latest" in text
    assert "ContainerName=myapp" in text
    assert "WantedBy=default.target" in text


def test_quadlet_volumes_render_one_line_each() -> None:
    text = render_quadlet(
        _policy(_runtime(volumes=[
            PolicyVolume(name="app-data", mount="/var/lib/app"),
            PolicyVolume(name="app-logs", mount="/var/log/app"),
        ])),
        "myapp",
    )
    assert "Volume=app-data:/var/lib/app" in text
    assert "Volume=app-logs:/var/log/app" in text


def test_quadlet_tmpfs_renders_one_line_each() -> None:
    text = render_quadlet(_policy(_runtime(tmpfs=["/tmp", "/run"])), "myapp")
    assert "Tmpfs=/tmp" in text
    assert "Tmpfs=/run" in text


def test_quadlet_binds_ro_use_volume_ro_syntax() -> None:
    text = render_quadlet(
        _policy(_runtime(binds_ro=["/etc/resolv.conf"])),
        "myapp",
    )
    assert "Volume=/etc/resolv.conf:/etc/resolv.conf:ro" in text


def test_quadlet_publish_ports() -> None:
    text = render_quadlet(
        _policy(_runtime(ports=[PolicyPort(host=8443, container=8443, proto="tcp")])),
        "myapp",
    )
    assert "PublishPort=8443:8443/tcp" in text


def test_quadlet_drops_all_then_adds_sorted() -> None:
    text = render_quadlet(
        _policy(_runtime(caps_add=["CAP_NET_BIND_SERVICE", "CAP_CHOWN"])),
        "myapp",
    )
    drop_line = text.index("DropCapability=ALL")
    chown_line = text.index("AddCapability=CAP_CHOWN")
    bind_line = text.index("AddCapability=CAP_NET_BIND_SERVICE")
    assert drop_line < chown_line < bind_line  # drops before adds, adds sorted


def test_quadlet_security_flags() -> None:
    text = render_quadlet(_policy(_runtime()), "myapp")
    assert "NoNewPrivileges=true" in text
    assert "ReadOnly=false" in text


def test_quadlet_seccomp_global_args() -> None:
    text = render_quadlet(_policy(_runtime()), "myapp")
    assert "GlobalArgs=--security-opt seccomp=%h/.config/containers/seccomp/myapp.json" in text


def test_quadlet_ends_with_trailing_newline() -> None:
    text = render_quadlet(_policy(_runtime()), "myapp")
    assert text.endswith("\n")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/generate/test_quadlet.py -v`
Expected: FAIL with ImportError.

- [ ] **Step 3: Implement `quadlet.py`**

Write `src/containerizer/generate/quadlet.py`:

```python
"""Render PolicyJson into a systemd Quadlet `.container` unit."""

from __future__ import annotations

from containerizer.analyze.schema import PolicyJson


def render_quadlet(policy: PolicyJson, name: str) -> str:
    """Render policy.runtime as a Quadlet container unit string.

    Sections in fixed order (volumes -> tmpfs -> binds_ro -> ports -> caps ->
    flags -> seccomp) so golden diffs stay readable.
    """
    runtime = policy.runtime
    lines: list[str] = [
        "[Unit]",
        f"Description=Containerized {name}",
        "After=network-online.target",
        "Wants=network-online.target",
        "",
        "[Container]",
        f"Image={name}:latest",
        f"ContainerName={name}",
    ]

    for vol in runtime.volumes:
        lines.append(f"Volume={vol.name}:{vol.mount}")
    for path in runtime.tmpfs:
        lines.append(f"Tmpfs={path}")
    for path in runtime.binds_ro:
        lines.append(f"Volume={path}:{path}:ro")
    for port in runtime.publish_ports:
        lines.append(f"PublishPort={port.host}:{port.container}/{port.proto}")

    # Drops first (always includes ALL), then sorted adds.
    for cap in runtime.caps_drop:
        lines.append(f"DropCapability={cap}")
    for cap in sorted(runtime.caps_add):
        lines.append(f"AddCapability={cap}")

    lines.append(f"NoNewPrivileges={str(runtime.no_new_privileges).lower()}")
    lines.append(f"ReadOnly={str(runtime.read_only_rootfs).lower()}")
    lines.append(
        f"GlobalArgs=--security-opt seccomp=%h/.config/containers/seccomp/{name}.json"
    )
    lines.append("")
    lines.append("[Install]")
    lines.append("WantedBy=default.target")
    return "\n".join(lines) + "\n"
```

- [ ] **Step 4: Run tests + gate + commit**

```
pytest tests/unit/generate/test_quadlet.py -v
ruff check . && ruff format --check . && mypy src tests && pytest
git add src/containerizer/generate/quadlet.py tests/unit/generate/test_quadlet.py
git -c user.email="github.v5f9w@bitbucket.onl" \
    -c user.signingkey=BE707B220C995478 \
    commit -S -m "feat(generate): quadlet.py — .container Quadlet unit from PolicyJson"
```

---

## Task 9: `readme.py`

**Issue:** #40, #41, #42.

**Files:**
- Create: `src/containerizer/generate/readme.py`
- Create: `tests/unit/generate/test_readme.py`

Render the human-readable audit trail. Sections vary based on whether sentinel was triggered.

- [ ] **Step 1: Write the failing tests**

Write `tests/unit/generate/test_readme.py`:

```python
"""Tests for analyze.generate.readme."""

from __future__ import annotations

from containerizer.analyze.schema import (
    PolicyImage,
    PolicyJson,
    PolicyPort,
    PolicyRuntime,
    PolicyVolume,
)
from containerizer.generate.readme import render_readme


def _policy(
    *,
    warnings: list[str] | None = None,
    entrypoint: list[str] | None = None,
) -> PolicyJson:
    return PolicyJson(
        image=PolicyImage(
            base="ubuntu:24.04",
            apt_packages=[],
            post_install_cleanup=[],
            systemd_required=False,
            entrypoint=entrypoint or ["__UNSET__"],
        ),
        runtime=PolicyRuntime(
            volumes=[PolicyVolume(name="app-data", mount="/var/lib/app")],
            tmpfs=["/tmp"],
            binds_ro=["/etc/resolv.conf"],
            publish_ports=[PolicyPort(host=80, container=80, proto="tcp")],
            caps_add=["CAP_NET_BIND_SERVICE"],
            seccomp_syscalls=[0, 1],
            read_only_rootfs=False,
        ),
        warnings=warnings or [],
    )


def test_readme_has_title_with_name() -> None:
    text = render_readme(_policy(), "myapp", skipped=False, unknown_syscall_ids=[])
    assert text.startswith("# Containerizer output for myapp\n")


def test_readme_non_sentinel_lists_four_files() -> None:
    text = render_readme(_policy(), "myapp", skipped=False, unknown_syscall_ids=[])
    assert "Containerfile" in text
    assert "myapp.container" in text
    assert "seccomp.json" in text
    assert "README.md" in text
    assert "SKIPPED" not in text


def test_readme_sentinel_has_skipped_section() -> None:
    text = render_readme(
        _policy(warnings=["entrypoint is sentinel ['__UNSET__']; M4 must refuse this policy"]),
        "myapp",
        skipped=True,
        unknown_syscall_ids=[],
    )
    assert "## SKIPPED" in text
    assert "Containerfile" in text
    assert "myapp.container" in text
    assert "entrypoint is sentinel" in text


def test_readme_audit_trail_lists_policy_warnings() -> None:
    text = render_readme(
        _policy(warnings=["unknown_rw aggregate: /var/foo", "device aggregate: /dev/bar"]),
        "myapp",
        skipped=False,
        unknown_syscall_ids=[],
    )
    assert "unknown_rw aggregate: /var/foo" in text
    assert "device aggregate: /dev/bar" in text


def test_readme_unknown_syscalls_section_only_when_nonempty() -> None:
    text_with = render_readme(_policy(), "myapp", skipped=False, unknown_syscall_ids=[437, 999])
    assert "Unknown syscall IDs" in text_with
    assert "437" in text_with
    assert "999" in text_with

    text_without = render_readme(_policy(), "myapp", skipped=False, unknown_syscall_ids=[])
    assert "Unknown syscall IDs" not in text_without


def test_readme_runtime_allowlist_summary() -> None:
    text = render_readme(_policy(), "myapp", skipped=False, unknown_syscall_ids=[])
    assert "1 volume" in text or "volumes: 1" in text or "Volumes: 1" in text
    assert "/var/lib/app" in text
    assert "/etc/resolv.conf" in text
    assert "CAP_NET_BIND_SERVICE" in text


def test_readme_next_steps_mentions_podman_build_and_systemctl() -> None:
    text = render_readme(_policy(), "myapp", skipped=False, unknown_syscall_ids=[])
    assert "podman build" in text
    assert "systemctl --user" in text


def test_readme_ends_with_trailing_newline() -> None:
    text = render_readme(_policy(), "myapp", skipped=False, unknown_syscall_ids=[])
    assert text.endswith("\n")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/generate/test_readme.py -v`
Expected: FAIL with ImportError.

- [ ] **Step 3: Implement `readme.py`**

Write `src/containerizer/generate/readme.py`:

```python
"""Render the human-readable README audit trail for a generated policy."""

from __future__ import annotations

from containerizer.analyze.schema import PolicyJson


def render_readme(
    policy: PolicyJson,
    name: str,
    *,
    skipped: bool,
    unknown_syscall_ids: list[int],
) -> str:
    """Render the README.md describing the generated artifacts.

    Sections (in order):
      - Title
      - SKIPPED (only if sentinel)
      - What was generated
      - Audit trail (policy.warnings)
      - Runtime allowlist (volumes, tmpfs, binds_ro, ports, caps, syscalls)
      - Unknown syscall IDs (only when non-empty)
      - Next steps
    """
    runtime = policy.runtime
    sections: list[str] = [f"# Containerizer output for {name}\n"]

    if skipped:
        sections.append(
            "## SKIPPED\n\n"
            f"`Containerfile` and `{name}.container` were NOT generated because the "
            f"policy's entrypoint is the sentinel `['__UNSET__']`. The seccomp profile "
            f"and this README still ship so you can diff future runs.\n\n"
            "Relevant warning:\n\n"
            + _render_sentinel_warning(policy.warnings)
            + "\n"
        )

    sections.append(_render_what_was_generated(name, skipped))
    sections.append(_render_audit_trail(policy.warnings))
    sections.append(_render_runtime_allowlist(runtime))
    if unknown_syscall_ids:
        sections.append(_render_unknown_syscalls(unknown_syscall_ids))
    sections.append(_render_next_steps(name))

    return "\n".join(sections).rstrip() + "\n"


def _render_what_was_generated(name: str, skipped: bool) -> str:
    if skipped:
        files = [f"- `seccomp.json`", f"- `README.md` (this file)"]
    else:
        files = [
            f"- `Containerfile`",
            f"- `{name}.container`",
            f"- `seccomp.json`",
            f"- `README.md` (this file)",
        ]
    return "## What was generated\n\n" + "\n".join(files) + "\n"


def _render_audit_trail(warnings: list[str]) -> str:
    body = "## Audit trail\n\n"
    if not warnings:
        return body + "(no warnings from the analyzer)\n"
    return body + "\n".join(f"- {w}" for w in warnings) + "\n"


def _render_runtime_allowlist(runtime) -> str:  # type: ignore[no-untyped-def]
    lines = [
        "## Runtime allowlist",
        "",
        f"- Volumes: {len(runtime.volumes)}",
    ]
    for vol in runtime.volumes:
        lines.append(f"  - `{vol.name}` -> `{vol.mount}`")
    lines.append(f"- Tmpfs: {len(runtime.tmpfs)}")
    for path in runtime.tmpfs:
        lines.append(f"  - `{path}`")
    lines.append(f"- Read-only binds: {len(runtime.binds_ro)}")
    for path in runtime.binds_ro:
        lines.append(f"  - `{path}`")
    lines.append(f"- Published ports: {len(runtime.publish_ports)}")
    for port in runtime.publish_ports:
        lines.append(f"  - `{port.host}:{port.container}/{port.proto}`")
    lines.append(f"- Added capabilities: {len(runtime.caps_add)}")
    for cap in sorted(runtime.caps_add):
        lines.append(f"  - `{cap}`")
    lines.append(f"- Seccomp syscalls allowed: {len(runtime.seccomp_syscalls)}")
    return "\n".join(lines) + "\n"


def _render_unknown_syscalls(unknown: list[int]) -> str:
    return (
        "## Unknown syscall IDs\n\n"
        f"The following syscall IDs were in the policy but not in the bundled lookup "
        f"table; they were dropped from the seccomp allowlist. Consider running "
        f"`python sandbox/regen_syscall_table.py` to refresh:\n\n"
        + "\n".join(f"- `{sysno}`" for sysno in unknown)
        + "\n"
    )


def _render_next_steps(name: str) -> str:
    return (
        "## Next steps\n\n"
        "```sh\n"
        f"# Build the image:\n"
        f"podman build -t {name}:latest .\n"
        "\n"
        f"# Install seccomp profile + Quadlet unit:\n"
        f"mkdir -p ~/.config/containers/seccomp ~/.config/containers/systemd\n"
        f"cp seccomp.json ~/.config/containers/seccomp/{name}.json\n"
        f"cp {name}.container ~/.config/containers/systemd/\n"
        "\n"
        f"# Start under systemd --user:\n"
        f"systemctl --user daemon-reload\n"
        f"systemctl --user start {name}.service\n"
        "```\n"
    )


def _render_sentinel_warning(warnings: list[str]) -> str:
    for w in warnings:
        if "sentinel" in w:
            return f"> {w}"
    return "> (sentinel warning text not found in policy.warnings)"
```

- [ ] **Step 4: Run tests + gate + commit**

```
pytest tests/unit/generate/test_readme.py -v
ruff check . && ruff format --check . && mypy src tests && pytest
git add src/containerizer/generate/readme.py tests/unit/generate/test_readme.py
git -c user.email="github.v5f9w@bitbucket.onl" \
    -c user.signingkey=BE707B220C995478 \
    commit -S -m "feat(generate): readme.py — audit-trail README from PolicyJson"
```

(If ruff or mypy flags the `_render_runtime_allowlist(runtime)` `# type: ignore[no-untyped-def]` as unused, replace with the explicit type: `runtime: "PolicyRuntime"` and import `PolicyRuntime`.)

---

## Task 10: `cli.py` — generate subcommand + wiring

**Issue:** #40, #41, #42.

**Files:**
- Create: `src/containerizer/generate/cli.py`
- Modify: `src/containerizer/cli.py`
- Create: `tests/unit/generate/test_cli.py`

- [ ] **Step 1: Write the failing test**

Write `tests/unit/generate/test_cli.py`:

```python
"""Tests for the `containerizer generate` Click subcommand."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from containerizer.analyze.schema import (
    PolicyImage,
    PolicyJson,
    PolicyPort,
    PolicyRuntime,
    PolicyVolume,
)
from containerizer.generate.cli import generate_cmd


def _write_policy(
    path: Path,
    *,
    entrypoint: list[str],
    caps_add: list[str] | None = None,
    syscalls: list[int] | None = None,
) -> None:
    policy = PolicyJson(
        image=PolicyImage(
            base="ubuntu:24.04",
            apt_packages=[],
            post_install_cleanup=["/installer"],
            systemd_required=False,
            entrypoint=entrypoint,
        ),
        runtime=PolicyRuntime(
            volumes=[PolicyVolume(name="app-data", mount="/var/lib/app")],
            tmpfs=["/tmp"],
            binds_ro=["/etc/resolv.conf"],
            publish_ports=[PolicyPort(host=80, container=80, proto="tcp")],
            caps_add=caps_add or [],
            seccomp_syscalls=syscalls or [],
            read_only_rootfs=False,
        ),
        warnings=[],
    )
    path.write_text(policy.model_dump_json(indent=2) + "\n", encoding="utf-8")


def test_generate_happy_path_emits_four_files(tmp_path: Path) -> None:
    policy_path = tmp_path / "policy.json"
    _write_policy(policy_path, entrypoint=["/opt/app/bin/app"], syscalls=[0, 1, 59])
    out = tmp_path / "out"

    result = CliRunner().invoke(generate_cmd, [str(policy_path), "-n", "myapp", "-o", str(out)])
    assert result.exit_code == 0, result.output

    assert (out / "Containerfile").exists()
    assert (out / "myapp.container").exists()
    assert (out / "seccomp.json").exists()
    assert (out / "README.md").exists()

    assert (out / "Containerfile").read_text(encoding="utf-8").startswith("FROM ubuntu:24.04")
    seccomp = json.loads((out / "seccomp.json").read_text(encoding="utf-8"))
    assert seccomp["defaultAction"] == "SCMP_ACT_ERRNO"


def test_generate_sentinel_skips_containerfile_and_quadlet(tmp_path: Path) -> None:
    policy_path = tmp_path / "policy.json"
    _write_policy(policy_path, entrypoint=["__UNSET__"])
    out = tmp_path / "out"

    result = CliRunner().invoke(generate_cmd, [str(policy_path), "-n", "myapp", "-o", str(out)])
    assert result.exit_code == 0, result.output

    assert not (out / "Containerfile").exists()
    assert not (out / "myapp.container").exists()
    assert (out / "seccomp.json").exists()
    assert (out / "README.md").exists()

    readme = (out / "README.md").read_text(encoding="utf-8")
    assert "SKIPPED" in readme
    assert "sentinel" in result.output.lower()


def test_generate_unknown_syscall_warns_on_stderr(tmp_path: Path) -> None:
    policy_path = tmp_path / "policy.json"
    _write_policy(policy_path, entrypoint=["/x"], syscalls=[0, 99999])
    out = tmp_path / "out"

    result = CliRunner(mix_stderr=False).invoke(
        generate_cmd, [str(policy_path), "-n", "myapp", "-o", str(out)]
    )
    assert result.exit_code == 0, result.output
    assert "99999" in result.stderr


def test_generate_missing_policy_file_errors(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        generate_cmd, [str(tmp_path / "nope.json"), "-n", "x", "-o", str(tmp_path / "out")]
    )
    assert result.exit_code != 0


def test_main_cli_lists_generate() -> None:
    from containerizer.cli import main
    result = CliRunner().invoke(main, ["--help"])
    assert "generate" in result.output
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/generate/test_cli.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `generate/cli.py`**

Write `src/containerizer/generate/cli.py`:

```python
"""`containerizer generate <policy.json> -n <name> -o <out-dir>` Click subcommand."""

from __future__ import annotations

from pathlib import Path

import click

from containerizer.analyze.schema import PolicyJson
from containerizer.generate.containerfile import render_containerfile
from containerizer.generate.quadlet import render_quadlet
from containerizer.generate.readme import render_readme
from containerizer.generate.seccomp import render_seccomp

SENTINEL_ENTRYPOINT = "__UNSET__"


@click.command("generate")
@click.argument(
    "policy_path",
    type=click.Path(exists=True, dir_okay=False, readable=True, path_type=Path),
)
@click.option(
    "-n",
    "--name",
    required=True,
    help="Short name for the generated unit (used in filenames and Quadlet identifiers).",
)
@click.option(
    "-o",
    "--output-dir",
    required=True,
    type=click.Path(path_type=Path),
    help="Directory to write the generated artifacts to.",
)
def generate_cmd(policy_path: Path, name: str, output_dir: Path) -> None:
    """Render Containerfile + Quadlet + seccomp + README from POLICY_PATH."""
    output_dir.mkdir(parents=True, exist_ok=True)
    policy = PolicyJson.model_validate_json(policy_path.read_text(encoding="utf-8"))
    sentinel = policy.image.entrypoint == [SENTINEL_ENTRYPOINT]

    seccomp_bytes, unknown_ids = render_seccomp(policy)
    (output_dir / "seccomp.json").write_bytes(seccomp_bytes)

    readme = render_readme(policy, name, skipped=sentinel, unknown_syscall_ids=unknown_ids)
    (output_dir / "README.md").write_text(readme, encoding="utf-8")

    if sentinel:
        click.echo(
            f"sentinel entrypoint detected — skipping Containerfile and {name}.container"
        )
    else:
        (output_dir / "Containerfile").write_text(
            render_containerfile(policy), encoding="utf-8"
        )
        (output_dir / f"{name}.container").write_text(
            render_quadlet(policy, name), encoding="utf-8"
        )

    if unknown_ids:
        click.echo(
            f"warning: syscall IDs not in bundled table "
            f"(dropped from seccomp allowlist): {unknown_ids}",
            err=True,
        )
```

- [ ] **Step 4: Wire the subcommand into the main CLI**

Edit `src/containerizer/cli.py`. Near the other imports at the top, add:

```python
from containerizer.generate.cli import generate_cmd
```

Near the bottom, after `main.add_command(analyze_cmd)` (or whichever line registers the previous subcommand), add:

```python
main.add_command(generate_cmd)
```

- [ ] **Step 5: Run tests + gate + commit**

```
pytest tests/unit/generate/test_cli.py -v
ruff check . && ruff format --check . && mypy src tests && pytest
git add src/containerizer/generate/cli.py src/containerizer/cli.py tests/unit/generate/test_cli.py
git -c user.email="github.v5f9w@bitbucket.onl" \
    -c user.signingkey=BE707B220C995478 \
    commit -S -m "feat(generate): cli.py — wire generate subcommand into main group"
```

---

## Task 11: Integration smoke test + goldens

**Issue:** #40, #41, #42.

**Files:**
- Create: `tests/integration/generate/__init__.py`
- Create: `tests/integration/generate/test_generate_smoke.py`
- Create: `tests/fixtures/generate/expected/seccomp.json` (sentinel-path golden)
- Create: `tests/fixtures/generate/expected/README.md` (sentinel-path golden)
- Create: `tests/fixtures/generate/expected/Containerfile` (non-sentinel-path golden)
- Create: `tests/fixtures/generate/expected/synthetic-os.container` (non-sentinel-path golden)

End-to-end test that chains `analyze` → `generate` against the M3 synthetic fixture. The synthetic fixture's policy has `entrypoint == ["__UNSET__"]` (sentinel), so the smoke test exercises BOTH paths: one against the synthetic fixture directly (sentinel — emits only seccomp + README), and one against a hand-crafted non-sentinel policy (full emit).

- [ ] **Step 1: Create the package marker**

Write `tests/integration/generate/__init__.py` (empty file).

- [ ] **Step 2: Write the smoke test**

Write `tests/integration/generate/test_generate_smoke.py`:

```python
"""End-to-end smoke tests for `containerizer generate`."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest
from click.testing import CliRunner

from containerizer.analyze.cli import analyze_cmd
from containerizer.analyze.schema import (
    PolicyImage,
    PolicyJson,
    PolicyPort,
    PolicyRuntime,
    PolicyVolume,
)
from containerizer.generate.cli import generate_cmd

REPO_ROOT = Path(__file__).resolve().parents[3]
RECORDED = REPO_ROOT / "tests" / "fixtures" / "trace" / "synthetic-recorded"
EXPECTED = REPO_ROOT / "tests" / "fixtures" / "generate" / "expected"


def _load_json(path: Path) -> dict[str, object]:
    return cast(dict[str, object], json.loads(path.read_text(encoding="utf-8")))


@pytest.fixture
def golden_seccomp() -> dict[str, object]:
    return _load_json(EXPECTED / "seccomp.json")


@pytest.fixture
def golden_readme() -> str:
    return (EXPECTED / "README.md").read_text(encoding="utf-8")


@pytest.fixture
def golden_containerfile() -> str:
    return (EXPECTED / "Containerfile").read_text(encoding="utf-8")


@pytest.fixture
def golden_quadlet() -> str:
    return (EXPECTED / "synthetic-os.container").read_text(encoding="utf-8")


def test_sentinel_smoke_from_synthetic_fixture(
    tmp_path: Path,
    golden_seccomp: dict[str, object],
    golden_readme: str,
) -> None:
    """Chain analyze -> generate on the M3 synthetic fixture.

    The synthetic fixture's runtime execs don't include any systemd comm, so
    the policy's entrypoint is the sentinel. Only seccomp + README should land.
    """
    analyze_out = tmp_path / "analyze-out"
    generate_out = tmp_path / "generate-out"
    runner = CliRunner()

    r1 = runner.invoke(analyze_cmd, [str(RECORDED), "-o", str(analyze_out)])
    assert r1.exit_code == 0, r1.output

    r2 = runner.invoke(
        generate_cmd,
        [str(analyze_out / "policy.json"), "-n", "synthetic-os", "-o", str(generate_out)],
    )
    assert r2.exit_code == 0, r2.output

    assert not (generate_out / "Containerfile").exists()
    assert not (generate_out / "synthetic-os.container").exists()

    actual_seccomp = _load_json(generate_out / "seccomp.json")
    assert actual_seccomp == golden_seccomp

    actual_readme = (generate_out / "README.md").read_text(encoding="utf-8")
    assert actual_readme == golden_readme


def test_full_emit_from_handcrafted_non_sentinel_policy(
    tmp_path: Path,
    golden_containerfile: str,
    golden_quadlet: str,
) -> None:
    """Construct a non-sentinel policy in-Python; assert all four files emit
    and that Containerfile + Quadlet match committed goldens.
    """
    policy = PolicyJson(
        image=PolicyImage(
            base="ubuntu:24.04",
            apt_packages=[],
            post_install_cleanup=["/var/cache/apt/archives/*", "/installer"],
            systemd_required=True,
            entrypoint=["/sbin/init"],
        ),
        runtime=PolicyRuntime(
            volumes=[PolicyVolume(name="app-data", mount="/var/lib/app")],
            tmpfs=["/tmp"],
            binds_ro=["/etc/resolv.conf"],
            publish_ports=[PolicyPort(host=8443, container=8443, proto="tcp")],
            caps_add=["CAP_NET_BIND_SERVICE"],
            seccomp_syscalls=[0, 1, 59],
            read_only_rootfs=False,
        ),
        warnings=[],
    )
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(policy.model_dump_json(indent=2) + "\n", encoding="utf-8")
    out = tmp_path / "out"

    result = CliRunner().invoke(
        generate_cmd, [str(policy_path), "-n", "synthetic-os", "-o", str(out)]
    )
    assert result.exit_code == 0, result.output

    assert (out / "Containerfile").exists()
    assert (out / "synthetic-os.container").exists()
    assert (out / "seccomp.json").exists()
    assert (out / "README.md").exists()

    assert (out / "Containerfile").read_text(encoding="utf-8") == golden_containerfile
    assert (out / "synthetic-os.container").read_text(encoding="utf-8") == golden_quadlet
```

- [ ] **Step 3: Generate the goldens for the sentinel path**

Run (PowerShell):
```powershell
$tmp = New-Item -ItemType Directory -Path ([System.IO.Path]::GetTempPath() + [System.Guid]::NewGuid())
.venv\Scripts\containerizer.exe analyze tests/fixtures/trace/synthetic-recorded -o $tmp
.venv\Scripts\containerizer.exe generate $tmp/policy.json -n synthetic-os -o tests/fixtures/generate/expected
Remove-Item -Recurse $tmp
```

After this runs, `tests/fixtures/generate/expected/` should contain only `seccomp.json` and `README.md` (sentinel path skipped Containerfile + Quadlet).

- [ ] **Step 4: Generate the goldens for the non-sentinel path**

Run the second smoke test once with capture so we can hand-build the goldens. Easier path: use `containerizer generate` against a hand-crafted policy.

```powershell
$tmp = New-Item -ItemType Directory -Path ([System.IO.Path]::GetTempPath() + [System.Guid]::NewGuid())
$policy = @'
{
  "schema_version": 2,
  "image": {
    "base": "ubuntu:24.04",
    "apt_packages": [],
    "installer_path": "/installer",
    "post_install_cleanup": ["/var/cache/apt/archives/*", "/installer"],
    "systemd_required": true,
    "entrypoint": ["/sbin/init"]
  },
  "runtime": {
    "volumes": [{"name": "app-data", "mount": "/var/lib/app"}],
    "tmpfs": ["/tmp"],
    "binds_ro": ["/etc/resolv.conf"],
    "publish_ports": [{"host": 8443, "container": 8443, "proto": "tcp"}],
    "caps_add": ["CAP_NET_BIND_SERVICE"],
    "caps_drop": ["ALL"],
    "seccomp_syscalls": [0, 1, 59],
    "read_only_rootfs": false,
    "no_new_privileges": true
  },
  "warnings": []
}
'@
$policy | Set-Content $tmp/policy.json -Encoding utf8
.venv\Scripts\containerizer.exe generate $tmp/policy.json -n synthetic-os -o $tmp/out
Copy-Item $tmp/out/Containerfile tests/fixtures/generate/expected/Containerfile
Copy-Item $tmp/out/synthetic-os.container tests/fixtures/generate/expected/synthetic-os.container
Remove-Item -Recurse $tmp
```

(The README.md from this run is NOT the golden — the sentinel-path README from Step 3 is the golden.)

- [ ] **Step 5: Manually inspect all four goldens**

Open each:
- `tests/fixtures/generate/expected/seccomp.json` — should be valid JSON with `defaultAction: SCMP_ACT_ERRNO`, `architectures: ["SCMP_ARCH_X86_64"]`, `syscalls: [{"names": [...], "action": "SCMP_ACT_ALLOW"}]`. The names list will be small because the synthetic fixture's runtime syscall IDs are `[1, 59]` (write, execve).
- `tests/fixtures/generate/expected/README.md` — should have `## SKIPPED` and `sentinel` (since the synthetic-os smoke is the sentinel path).
- `tests/fixtures/generate/expected/Containerfile` — should start with `FROM ubuntu:24.04`, contain `ENTRYPOINT ["/sbin/init"]`.
- `tests/fixtures/generate/expected/synthetic-os.container` — should have `[Container]`, `Volume=app-data:/var/lib/app`, `PublishPort=8443:8443/tcp`, `DropCapability=ALL`, `AddCapability=CAP_NET_BIND_SERVICE`.

If any are obviously wrong, that's an upstream renderer bug — stop and report.

- [ ] **Step 6: Run the gate**

```
pytest tests/integration/generate/test_generate_smoke.py -v
ruff check . && ruff format --check . && mypy src tests && pytest
```

Expected: PASS.

- [ ] **Step 7: Commit**

```
git add tests/integration/generate/__init__.py tests/integration/generate/test_generate_smoke.py tests/fixtures/generate/expected/
git -c user.email="github.v5f9w@bitbucket.onl" \
    -c user.signingkey=BE707B220C995478 \
    commit -S -m "test(generate): integration smoke test + sentinel/non-sentinel goldens"
```

---

## Task 12: MANUAL.md scenario 8 + final PR

**Issue:** #40, #41, #42.

**Files:**
- Modify: `MANUAL.md`

- [ ] **Step 1: Read the current MANUAL.md to match style**

Locate scenario 7 (the `analyze` walkthrough added in M3). The M4 scenario goes immediately after it. Match heading level (`##`), code-fence language (`pwsh`), prompt prefix (`PS>`).

- [ ] **Step 2: Add scenario 8**

After scenario 7, before any "Output to a file" or similar section, append:

```markdown
## Scenario 8 — Generate hardened container artifacts

After `containerizer analyze` produces a `policy.json`, run the generator to emit the container build context and runtime policy:

```pwsh
PS> containerizer generate .\unifi-analyze\policy.json -n unifi-os -o .\unifi-build\
sentinel entrypoint detected — skipping Containerfile and unifi-os.container
```

The generator writes `Containerfile`, `<name>.container` (a systemd Quadlet unit), `seccomp.json` (OCI-format syscall allowlist), and `README.md` (audit trail) into `<out-dir>`. When the policy's entrypoint is the sentinel `["__UNSET__"]` (no recognizable daemon was traced), the Containerfile and Quadlet are skipped; the seccomp profile and README still ship so you can diff against future runs. See `docs/superpowers/specs/2026-06-07-containerizer-m4-generators.md` for the full contract.
```

- [ ] **Step 3: Run the gate**

```
ruff check . && ruff format --check . && mypy src tests && pytest
```

Expected: PASS.

- [ ] **Step 4: Commit**

```
git add MANUAL.md
git -c user.email="github.v5f9w@bitbucket.onl" \
    -c user.signingkey=BE707B220C995478 \
    commit -S -m "docs: MANUAL.md scenario 8 — containerizer generate"
```

- [ ] **Step 5: Open the final PR**

```
git push origin feat/m4-generators
gh pr create --title "feat(generate): M4 generators (Containerfile + Quadlet + seccomp + README)" --body "$(cat <<'EOF'
## Summary

Closes #40, #41, #42.

Implements the M4 milestone per `docs/superpowers/specs/2026-06-07-containerizer-m4-generators.md`. New `src/containerizer/generate/` package with one module per artifact (`containerfile`, `quadlet`, `seccomp`, `readme`), a bundled `syscall_table.py` for syscall_id->name resolution (x86_64 Linux v6.6), and a `cli.py` orchestrator. Single `containerizer generate <policy.json> -n <name> -o <out-dir>` CLI subcommand.

Sentinel-entrypoint policies (`entrypoint == ["__UNSET__"]`) skip Containerfile + Quadlet but still emit `seccomp.json` + `README.md` with a SKIPPED section explaining what wasn't produced and why.

Includes a small schema bump: `PolicyJson` is now v2 with a new `warnings: list[str]` field copied from `trace.warnings`. The M3 synthetic golden `policy.json` was regenerated to match.

Templating is stdlib-only string building (no Jinja2 dep).

## Test plan

- [x] Unit tests for every renderer (containerfile, quadlet, seccomp, readme, syscall_table, cli).
- [x] Integration smoke test exercising both sentinel and non-sentinel paths against committed goldens.
- [x] Coverage stays >= 90%.
- [x] Lint + type gate green.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Wait for CI to go green on all branch-protection required checks, then squash-merge.

---

## Exit criteria

M4 is done when:

1. `containerizer generate tests/fixtures/analyze/expected/synthetic-policy.json -n synthetic-os -o <tmp>` produces `seccomp.json` + `README.md` only (sentinel path). The Containerfile + Quadlet are absent.
2. `containerizer generate <non-sentinel-policy> -n <name> -o <tmp>` produces all four files matching committed goldens.
3. PolicyJson schema is v2 with `warnings: list[str]`; the M3 synthetic `policy.json` golden is regenerated and committed; all prior M3 tests still pass.
4. All four renderers have unit tests with hand-crafted policies + hand-written expected output assertions.
5. `pytest` (unit + integration, no `-m integration` exclusion) is green. Coverage ≥ 90%.
6. `ruff check . && ruff format --check . && mypy src tests && pytest` is green.
7. MANUAL.md scenario 8 (running generate) is added.
8. PR opened closing #40, #41, #42; CI green on all required checks.

M4 is **not** required to:

- Produce a working `podman build` (M5 verifies that against a real installer).
- Detect a daemon entrypoint correctly when systemd isn't involved (M5/M6).
- Render apt_packages (still always `[]` from M3; M6).
- Flip `read_only_rootfs` on (M6).
- Support arches other than x86_64 (M6+).
