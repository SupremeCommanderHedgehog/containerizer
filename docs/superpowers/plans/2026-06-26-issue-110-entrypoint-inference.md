# Issue #110 Entrypoint Inference Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire `--start-cmd` through to `derive_policy` so that when systemd is not required, the analyzer emits `entrypoint = ["bash", "-c", start_cmd]` instead of the `__UNSET__` sentinel; persist `start_cmd` in the trace artifact as a `START_CMD` sidecar file so standalone `containerizer analyze` benefits without a CLI re-spec.

**Architecture:** `start_cmd` becomes a first-class trace artifact (sidecar file at trace-dir root, peer of `COMPLETE`/`PHASE_MARKER`). Reader picks it up into `TraceBundle.start_cmd`, `assemble_trace_json` threads it into `TraceJson.start_cmd`, and `derive_policy` reads it to apply a 4-case entrypoint truth table (no schema-version bump — optional-with-default keeps v1 backwards-compat).

**Tech Stack:** Python 3.12, Pydantic v2, pytest, Click CLI, dataclasses.

**Execution environment:** All commands run on `cougar.home.arpa` as the `claude` user. SSH from Windows: `ssh -i $env:USERPROFILE\.ssh\claude_cougar claude@cougar.home.arpa`. CWD = `~/source/containerizer`. Branch: `fix/110-entrypoint-start-cmd` (already exists; holds the design spec at `docs/superpowers/specs/2026-06-26-containerizer-issue-110-entrypoint-inference.md`). Commits are GPG-signed automatically by git config.

**Spec:** [`docs/superpowers/specs/2026-06-26-containerizer-issue-110-entrypoint-inference.md`](../specs/2026-06-26-containerizer-issue-110-entrypoint-inference.md)

---

## File Structure

**Modify (production):**
- `src/containerizer/analyze/schema.py` — add `start_cmd` field to `TraceJson`
- `src/containerizer/analyze/reader.py` — add `start_cmd` field to `TraceBundle`; `read_trace_dir` reads `START_CMD` file
- `src/containerizer/analyze/assemble.py` — thread `bundle.start_cmd` into `TraceJson`
- `src/containerizer/analyze/derive.py` — entrypoint truth-table rewrite
- `src/containerizer/trace/runner.py` — `_materialize_start_cmd_file()` writes `START_CMD`
- `src/containerizer/trace/cli.py` — empty-string `--start-cmd ''` → `None` normalization
- `src/containerizer/build/cli.py` — empty-string `--start-cmd ''` → `None` normalization
- `docs/MANUAL.md` — one-line note that `--start-cmd` doubles as entrypoint

**Create (tests):**
- `tests/unit/trace/__init__.py` — empty; Python package marker (`tests/unit/trace/` does not exist on main)
- `tests/unit/trace/test_runner.py` — sidecar writing behavior
- `tests/unit/trace/test_cli.py` — empty-string normalization (create if missing)

**Modify (tests):**
- `tests/unit/analyze/test_schema.py` — round-trip + backwards-compat for `start_cmd`
- `tests/unit/analyze/test_reader.py` — pick up `START_CMD` file (present + absent)
- `tests/unit/analyze/test_assemble.py` — thread `bundle.start_cmd`
- `tests/unit/analyze/test_derive.py` — entrypoint truth-table cases
- `tests/unit/build/test_cli.py` — empty-string normalization
- `tests/integration/trace/test_deb_pipeline.py` — tighten the existing `test_deb_with_start_cmd_produces_non_sentinel_policy` to assert exact entrypoint

---

## Task 1: `TraceJson.start_cmd` schema field

**Goal:** Add the optional `start_cmd` field to `TraceJson` with a `None` default so old `trace.json` files still parse.

**Files:**
- Modify: `src/containerizer/analyze/schema.py` (TraceJson class)
- Modify: `tests/unit/analyze/test_schema.py` (add 2 tests)

- [ ] **Step 1: Add the round-trip + backwards-compat tests (will fail)**

Append to `tests/unit/analyze/test_schema.py`:

```python
def test_tracejson_round_trips_start_cmd_when_set() -> None:
    tj = TraceJson(
        phase_marker_ns=123,
        marker="COMPLETE",
        install=_empty_phase(),
        runtime=_empty_phase(),
        warnings=[],
        start_cmd="/etc/init.d/mongod start && /etc/init.d/unifi start",
    )
    s = tj.model_dump_json(by_alias=True)
    tj2 = TraceJson.model_validate_json(s)
    assert tj2.start_cmd == "/etc/init.d/mongod start && /etc/init.d/unifi start"


def test_tracejson_start_cmd_defaults_to_none_for_backwards_compat() -> None:
    # Old v1 trace.json had no start_cmd field — parsing must still succeed
    # with start_cmd resolved to None via the Pydantic default.
    payload = {
        "schema_version": 1,
        "phase_marker_ns": 123,
        "marker": "COMPLETE",
        "install": _empty_phase().model_dump(),
        "runtime": _empty_phase().model_dump(),
        "warnings": [],
    }
    tj = TraceJson.model_validate(payload)
    assert tj.start_cmd is None
```

- [ ] **Step 2: Run the new tests and verify they fail**

```bash
pytest tests/unit/analyze/test_schema.py::test_tracejson_round_trips_start_cmd_when_set tests/unit/analyze/test_schema.py::test_tracejson_start_cmd_defaults_to_none_for_backwards_compat -v
```

Expected: FAIL. The first errors on unexpected kwarg `start_cmd`; the second's `tj.start_cmd` raises AttributeError.

- [ ] **Step 3: Add the `start_cmd` field to `TraceJson`**

In `src/containerizer/analyze/schema.py`, locate `class TraceJson(BaseModel):` and add `start_cmd: str | None = None` after the existing `warnings: list[str]` line. Final shape:

```python
class TraceJson(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    phase_marker_ns: int | None
    marker: Literal["COMPLETE", "PARTIAL"]
    install: TracePhase
    runtime: TracePhase
    warnings: list[str]
    start_cmd: str | None = None
```

- [ ] **Step 4: Run all schema tests and verify pass**

```bash
pytest tests/unit/analyze/test_schema.py -v
```

Expected: PASS (all schema tests including the two new ones).

- [ ] **Step 5: Commit**

```bash
git add src/containerizer/analyze/schema.py tests/unit/analyze/test_schema.py
git commit -m "feat(analyze): add TraceJson.start_cmd optional field (#110)" -m "Backwards-compatible: default None keeps schema_version=1; old trace.json files without start_cmd parse unchanged via Pydantic default fill."
```

---

## Task 2: `TraceBundle.start_cmd` + `START_CMD` file pickup

**Goal:** `read_trace_dir` picks up `<trace_dir>/START_CMD` and exposes it on `TraceBundle.start_cmd`.

**Files:**
- Modify: `src/containerizer/analyze/reader.py`
- Modify: `tests/unit/analyze/test_reader.py` (add 2 tests)

- [ ] **Step 1: Add the file-present + file-absent tests (will fail)**

Append to `tests/unit/analyze/test_reader.py`:

```python
def test_read_trace_dir_picks_up_start_cmd_file(tmp_path: Path) -> None:
    d = _make_complete_trace(tmp_path)
    (d / "START_CMD").write_text("/etc/init.d/mongod start", encoding="utf-8")
    bundle = read_trace_dir(d)
    assert bundle.start_cmd == "/etc/init.d/mongod start"


def test_read_trace_dir_start_cmd_none_when_file_absent(tmp_path: Path) -> None:
    d = _make_complete_trace(tmp_path)
    # No START_CMD file written.
    bundle = read_trace_dir(d)
    assert bundle.start_cmd is None
```

- [ ] **Step 2: Run new tests and verify they fail**

```bash
pytest tests/unit/analyze/test_reader.py::test_read_trace_dir_picks_up_start_cmd_file tests/unit/analyze/test_reader.py::test_read_trace_dir_start_cmd_none_when_file_absent -v
```

Expected: FAIL with `AttributeError: 'TraceBundle' object has no attribute 'start_cmd'`.

- [ ] **Step 3: Add the `start_cmd` field to `TraceBundle`**

In `src/containerizer/analyze/reader.py`, find the `@dataclass` `class TraceBundle:` and add `start_cmd: str | None = None` after `warnings`:

```python
@dataclass
class TraceBundle:
    marker: Literal["COMPLETE", "PARTIAL"]
    phase_marker_ns: int | None
    fallbacks: dict[str, dict[str, str]]
    # events[collector_name] = list of parsed JSON dicts (one per .jsonl line)
    events: dict[str, list[dict[str, object]]]
    warnings: list[str] = field(default_factory=list)
    start_cmd: str | None = None
```

- [ ] **Step 4: Update `read_trace_dir` to read `START_CMD`**

In `src/containerizer/analyze/reader.py`, find the `return TraceBundle(...)` at the bottom of `read_trace_dir` and add the START_CMD read above it:

```python
start_cmd_path = trace_dir / "START_CMD"
start_cmd = (
    start_cmd_path.read_text(encoding="utf-8")
    if start_cmd_path.exists()
    else None
)
return TraceBundle(
    marker=marker,
    phase_marker_ns=phase_marker_ns,
    fallbacks=fallbacks,
    events=events,
    warnings=warnings,
    start_cmd=start_cmd,
)
```

(Find the existing return statement with `grep -n "return TraceBundle" src/containerizer/analyze/reader.py`.)

- [ ] **Step 5: Run all reader tests and verify pass**

```bash
pytest tests/unit/analyze/test_reader.py -v
```

Expected: PASS — including the 2 new tests plus all existing reader tests (since `start_cmd` defaults to None, no existing assertion changes).

- [ ] **Step 6: Commit**

```bash
git add src/containerizer/analyze/reader.py tests/unit/analyze/test_reader.py
git commit -m "feat(analyze): reader picks up <trace_dir>/START_CMD sidecar (#110)" -m "TraceBundle gains start_cmd field; read_trace_dir reads the START_CMD file at trace-dir root when present. Absent file means start_cmd=None (pre-fix default)."
```

---

## Task 3: `assemble_trace_json` threads `bundle.start_cmd` → `TraceJson`

**Goal:** Bundle's `start_cmd` lands on the assembled `TraceJson`.

**Files:**
- Modify: `src/containerizer/analyze/assemble.py` (the `provisional = TraceJson(...)` construction)
- Modify: `tests/unit/analyze/test_assemble.py` (add 1 test)

- [ ] **Step 1: Add the threading test (will fail)**

Append to `tests/unit/analyze/test_assemble.py` (add `TraceBundle` and `assemble_trace_json` imports at the top if not already present):

```python
def test_assemble_propagates_start_cmd_from_bundle() -> None:
    bundle = TraceBundle(
        marker="COMPLETE",
        phase_marker_ns=100,
        fallbacks={},
        events={
            name: []
            for name in ("open", "bind", "syscalls", "connect", "accept", "capable")
        },
        warnings=[],
        start_cmd="/etc/init.d/mongod start",
    )
    trace = assemble_trace_json(bundle)
    assert trace.start_cmd == "/etc/init.d/mongod start"
```

- [ ] **Step 2: Run test and verify it fails**

```bash
pytest tests/unit/analyze/test_assemble.py::test_assemble_propagates_start_cmd_from_bundle -v
```

Expected: FAIL with `assert None == "/etc/init.d/mongod start"` (because assemble doesn't pass `start_cmd` yet).

- [ ] **Step 3: Thread `bundle.start_cmd` in `assemble_trace_json`**

In `src/containerizer/analyze/assemble.py`, find the `provisional = TraceJson(...)` construction near the bottom of `assemble_trace_json` and add `start_cmd=bundle.start_cmd`:

```python
provisional = TraceJson(
    phase_marker_ns=bundle.phase_marker_ns,
    marker=bundle.marker,
    install=install,
    runtime=runtime,
    warnings=warnings,
    start_cmd=bundle.start_cmd,
)
```

The conditional `provisional.model_copy(update={"warnings": warnings})` further down preserves all unmodified fields, so `start_cmd` flows through unchanged.

- [ ] **Step 4: Run all assemble tests and verify pass**

```bash
pytest tests/unit/analyze/test_assemble.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/containerizer/analyze/assemble.py tests/unit/analyze/test_assemble.py
git commit -m "feat(analyze): assemble threads bundle.start_cmd into TraceJson (#110)"
```

---

## Task 4: `derive_policy` entrypoint truth table (main payoff)

**Goal:** Implement the 4-case entrypoint truth table from spec §3.3.

**Files:**
- Modify: `src/containerizer/analyze/derive.py` (`derive_policy` body)
- Modify: `tests/unit/analyze/test_derive.py` (extend `_make_trace` + 2 new tests)

- [ ] **Step 1: Extend the `_make_trace` test helper to accept `start_cmd`**

In `tests/unit/analyze/test_derive.py`, update the helper definition:

```python
def _make_trace(
    *,
    install: TracePhase = EMPTY_PHASE,
    runtime: TracePhase = EMPTY_PHASE,
    marker: str = "COMPLETE",
    warnings: list[str] | None = None,
    start_cmd: str | None = None,
) -> TraceJson:
    return TraceJson(
        phase_marker_ns=100 if marker == "COMPLETE" else None,
        marker=marker,  # type: ignore[arg-type]
        install=install,
        runtime=runtime,
        warnings=warnings or [],
        start_cmd=start_cmd,
    )
```

- [ ] **Step 2: Add the two new truth-table tests (will fail)**

Append to `tests/unit/analyze/test_derive.py`:

```python
def test_entrypoint_uses_start_cmd_when_no_systemd() -> None:
    runtime = TracePhase(
        duration_s=1.0,
        paths=[],
        ports=[],
        outbound=[],
        caps=[],
        syscalls=[],
        execs=["java"],  # no systemd in execs
    )
    policy = derive_policy(
        _make_trace(runtime=runtime, start_cmd="/etc/init.d/unifi start"),
    )
    assert policy.image.systemd_required is False
    assert policy.image.entrypoint == ["bash", "-c", "/etc/init.d/unifi start"]
    # No "start_cmd ignored" warning when systemd is not required.
    assert not any("start_cmd ignored" in w for w in policy.warnings)


def test_entrypoint_ignores_start_cmd_when_systemd_with_warning() -> None:
    runtime = TracePhase(
        duration_s=1.0,
        paths=[],
        ports=[],
        outbound=[],
        caps=[],
        syscalls=[],
        execs=["systemd", "java"],  # systemd in execs triggers systemd_required
    )
    policy = derive_policy(
        _make_trace(runtime=runtime, start_cmd="/etc/init.d/unifi start"),
    )
    assert policy.image.systemd_required is True
    assert policy.image.entrypoint == ["/sbin/init"]
    assert any(
        "start_cmd ignored: systemd detected as required" in w
        for w in policy.warnings
    )
```

- [ ] **Step 3: Run the new tests and verify they fail**

```bash
pytest tests/unit/analyze/test_derive.py::test_entrypoint_uses_start_cmd_when_no_systemd tests/unit/analyze/test_derive.py::test_entrypoint_ignores_start_cmd_when_systemd_with_warning -v
```

Expected: FAIL — first test asserts `["bash", "-c", "..."]` but gets `["__UNSET__"]`; second test asserts a warning that doesn't exist yet.

- [ ] **Step 4: Update `derive_policy` to implement the truth table**

In `src/containerizer/analyze/derive.py`, replace the existing logic:

```python
systemd_required = systemd_required_for(trace)
entrypoint = ["/sbin/init"] if systemd_required else [SENTINEL_ENTRYPOINT]
```

with the truth table:

```python
systemd_required = systemd_required_for(trace)
start_cmd = trace.start_cmd or None  # defensive: empty string -> None

final_warnings: list[str] = list(warnings or [])
if systemd_required:
    entrypoint = ["/sbin/init"]
    if start_cmd:
        final_warnings.append(
            "start_cmd ignored: systemd detected as required; "
            "using /sbin/init as entrypoint"
        )
elif start_cmd:
    entrypoint = ["bash", "-c", start_cmd]
else:
    entrypoint = [SENTINEL_ENTRYPOINT]
```

And change the `return PolicyJson(...)` at the end to use `final_warnings` instead of `warnings or []`:

```python
return PolicyJson(
    image=PolicyImage(
        base=probe_base,
        apt_packages=[],
        installer_path="/installer",
        post_install_cleanup=["/var/cache/apt/archives/*", "/installer"],
        systemd_required=systemd_required,
        entrypoint=entrypoint,
    ),
    runtime=PolicyRuntime(
        volumes=volumes,
        tmpfs=tmpfs,
        binds_ro=binds_ro,
        publish_ports=publish_ports,
        caps_add=runtime.caps,
        seccomp_syscalls=runtime.syscalls,
        read_only_rootfs=False,
    ),
    warnings=final_warnings,
)
```

- [ ] **Step 5: Run all derive tests and verify pass**

```bash
pytest tests/unit/analyze/test_derive.py -v
```

Expected: PASS — including the 2 new tests plus the existing sentinel + systemd tests (no behavior change for the start_cmd=None branch).

- [ ] **Step 6: Run the full analyze suite as a regression sanity check**

```bash
pytest tests/unit/analyze/ -v
```

Expected: PASS — no regressions in schema/reader/assemble/derive or any other analyze module.

- [ ] **Step 7: Commit**

```bash
git add src/containerizer/analyze/derive.py tests/unit/analyze/test_derive.py
git commit -m "feat(analyze): derive uses start_cmd as entrypoint when no systemd (#110)" -m "Implements the truth table from spec §3.3: start_cmd becomes the bash -c entrypoint when systemd is not required; ignored with a policy.warnings entry when systemd takes precedence. Existing sentinel behavior preserved for the None/no-start_cmd case."
```

---

## Task 5: `TraceRunner` writes `START_CMD` file

**Goal:** When `start_cmd` is set on an install-mode runner, materialize `<output_dir>/START_CMD` so the analyzer can pick it up.

**Files:**
- Modify: `src/containerizer/trace/runner.py` (new method + call site in `run()`)
- Create: `tests/unit/trace/__init__.py` — empty (package marker)
- Create: `tests/unit/trace/test_runner.py` — 2 new tests

- [ ] **Step 1: Create the trace unit-test package**

```bash
mkdir -p tests/unit/trace
touch tests/unit/trace/__init__.py
```

- [ ] **Step 2: Write the materialization tests**

Create `tests/unit/trace/test_runner.py`:

```python
"""Tests for trace.runner sidecar-file materialization."""

from __future__ import annotations

from pathlib import Path

from containerizer.trace.runner import TraceRunner


def _install_runner(output_dir: Path, installer: Path, **overrides: object) -> TraceRunner:
    return TraceRunner(
        image_tag="dummy:latest",
        installer=installer,
        output_dir=output_dir,
        **overrides,  # type: ignore[arg-type]
    )


def test_runner_writes_start_cmd_file_when_set(tmp_path: Path) -> None:
    installer = tmp_path / "i.bin"
    installer.write_text("x", encoding="utf-8")
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    runner = _install_runner(
        output_dir, installer, start_cmd="/etc/init.d/unifi start"
    )

    runner._materialize_start_cmd_file()

    sidecar = output_dir / "START_CMD"
    assert sidecar.exists()
    assert sidecar.read_text(encoding="utf-8") == "/etc/init.d/unifi start"


def test_runner_omits_start_cmd_file_when_unset(tmp_path: Path) -> None:
    installer = tmp_path / "i.bin"
    installer.write_text("x", encoding="utf-8")
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    runner = _install_runner(output_dir, installer)  # start_cmd default = None

    runner._materialize_start_cmd_file()

    assert not (output_dir / "START_CMD").exists()
```

- [ ] **Step 3: Run tests and verify they fail**

```bash
pytest tests/unit/trace/test_runner.py -v
```

Expected: FAIL with `AttributeError: 'TraceRunner' object has no attribute '_materialize_start_cmd_file'`.

- [ ] **Step 4: Add `_materialize_start_cmd_file()` and call it from `run()`**

In `src/containerizer/trace/runner.py`, find the existing `_materialize_apt_sources_file` method near the bottom of the `TraceRunner` class. Below it, add:

```python
def _materialize_start_cmd_file(self) -> None:
    """Write start_cmd to output_dir / 'START_CMD' so the analyzer can
    read it later and emit it as the image entrypoint. Issue #110.
    No-op when start_cmd is None."""
    if not self.start_cmd:
        return
    target = self.output_dir / "START_CMD"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(self.start_cmd, encoding="utf-8")
```

In the same file, find the `run()` method and add a call alongside the existing materialization step:

```python
def run(self) -> int:
    """Exec the podman command in the foreground."""
    self._materialize_apt_sources_file()
    self._materialize_start_cmd_file()
    result = subprocess.run(self.argv(), check=False)
    return result.returncode
```

- [ ] **Step 5: Run tests and verify pass**

```bash
pytest tests/unit/trace/test_runner.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/containerizer/trace/runner.py tests/unit/trace/__init__.py tests/unit/trace/test_runner.py
git commit -m "feat(trace): runner writes <output_dir>/START_CMD sidecar (#110)" -m "Whenever --start-cmd is set, the trace runner materializes a START_CMD file at trace-dir root alongside apt-sources.list. The analyzer reader picks it up to drive entrypoint inference."
```

---

## Task 6: Trace CLI empty-string normalization

**Goal:** `--start-cmd ''` reaches `TraceRunner` as `None`, not `""`. Keeps the derive truth table clean.

**Files:**
- Modify: `src/containerizer/trace/cli.py` (the `trace_cmd` callback body)
- Create: `tests/unit/trace/test_cli.py`

- [ ] **Step 1: Write the empty-string-normalization test**

Create `tests/unit/trace/test_cli.py`:

```python
"""CLI tests for `containerizer trace`."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from containerizer.trace import cli as trace_cli_module
from containerizer.trace.cli import trace_cmd


def test_empty_start_cmd_normalized_to_none(tmp_path: Path) -> None:
    """`--start-cmd ''` is treated as if --start-cmd wasn't passed at all."""
    installer = tmp_path / "i.bin"
    installer.write_text("x", encoding="utf-8")
    out_dir = tmp_path / "out"

    with patch.object(
        trace_cli_module, "_podman_machine_is_running", return_value=True
    ), patch.object(
        trace_cli_module, "RunnerImage"
    ) as mock_image, patch.object(
        trace_cli_module, "TraceRunner"
    ) as mock_runner_cls:
        mock_image.return_value.exists.return_value = True
        mock_image.return_value.tag = "test:latest"
        mock_runner_cls.return_value.run.return_value = 0

        runner = CliRunner()
        result = runner.invoke(
            trace_cmd,
            [str(installer), "-o", str(out_dir), "--start-cmd", ""],
        )

    assert result.exit_code == 0, result.output
    kwargs = mock_runner_cls.call_args.kwargs
    assert kwargs.get("start_cmd") is None
```

- [ ] **Step 2: Run test and verify it fails**

```bash
pytest tests/unit/trace/test_cli.py::test_empty_start_cmd_normalized_to_none -v
```

Expected: FAIL — the captured `start_cmd` kwarg is `""`, not `None`.

- [ ] **Step 3: Add the normalization to `trace_cmd`**

In `src/containerizer/trace/cli.py`, in the body of `trace_cmd` (the Click callback), insert this line as the first executable line of the function body (above `_validate_multi_deb_flags(...)`):

```python
if start_cmd == "":
    start_cmd = None
```

- [ ] **Step 4: Run test and verify pass**

```bash
pytest tests/unit/trace/test_cli.py::test_empty_start_cmd_normalized_to_none -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/containerizer/trace/cli.py tests/unit/trace/test_cli.py
git commit -m "feat(trace,cli): normalize --start-cmd '' to None (#110)"
```

---

## Task 7: Build CLI empty-string normalization

**Goal:** Same normalization for the build CLI surface — `BuildConfig.start_cmd` is `None`, not `""`, when the user explicitly passes `--start-cmd ''`.

**Files:**
- Modify: `src/containerizer/build/cli.py` (the `build_cmd` callback body)
- Modify: `tests/unit/build/test_cli.py` (add 1 test)

- [ ] **Step 1: Write the test**

Append to `tests/unit/build/test_cli.py` (use the existing `_ok_result` helper and existing patterns):

```python
def test_empty_start_cmd_normalized_to_none(tmp_path: Path) -> None:
    """`build --start-cmd ''` is treated as if --start-cmd wasn't passed at all."""
    installer = tmp_path / "i.bin"
    installer.write_text("x", encoding="utf-8")
    out_dir = tmp_path / "out"

    runner = CliRunner()
    with patch.object(
        build_cli_module, "preflight_podman"
    ), patch.object(
        build_cli_module, "run_pipeline",
        return_value=_ok_result(out_dir / "demo"),
    ) as mock_pipeline:
        result = runner.invoke(
            build_cmd,
            [
                str(installer),
                "--name", "demo",
                "-o", str(out_dir),
                "--start-cmd", "",
            ],
        )

    assert result.exit_code == 0, result.output
    # First positional arg to run_pipeline is the BuildConfig.
    config = mock_pipeline.call_args.args[0]
    assert config.start_cmd is None
```

(If `run_pipeline` is imported under a different name in `build/cli.py`, adjust the patch target to match — verify with `grep -n "run_pipeline\|pipeline" src/containerizer/build/cli.py`.)

- [ ] **Step 2: Run test and verify it fails**

```bash
pytest tests/unit/build/test_cli.py::test_empty_start_cmd_normalized_to_none -v
```

Expected: FAIL — `config.start_cmd` is `""`, not `None`.

- [ ] **Step 3: Add the normalization to `build_cmd`**

In `src/containerizer/build/cli.py`, in the body of `build_cmd`, insert this line as the first executable line of the function body (above `_validate_multi_deb_flags(...)`):

```python
if start_cmd == "":
    start_cmd = None
```

- [ ] **Step 4: Run test and verify pass**

```bash
pytest tests/unit/build/test_cli.py::test_empty_start_cmd_normalized_to_none -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/containerizer/build/cli.py tests/unit/build/test_cli.py
git commit -m "feat(build,cli): normalize --start-cmd '' to None (#110)"
```

---

## Task 8: Integration test tighten + MANUAL.md note

**Goal:** Tighten the existing #105 integration test to assert the exact entrypoint; document the new entrypoint behavior in MANUAL.

**Files:**
- Modify: `tests/integration/trace/test_deb_pipeline.py` (`test_deb_with_start_cmd_produces_non_sentinel_policy`)
- Modify: `docs/MANUAL.md`

- [ ] **Step 1: Read the existing integration test body**

```bash
sed -n '150,220p' tests/integration/trace/test_deb_pipeline.py
```

Identify (a) the variable that holds the `--start-cmd` string, and (b) the existing `assert policy.image.entrypoint != ["__UNSET__"]`-style line.

- [ ] **Step 2: Tighten the entrypoint assertion**

Replace the non-sentinel assertion in `test_deb_with_start_cmd_produces_non_sentinel_policy` with an exact-shape check. The replacement reads, where `start_cmd_string` is whatever local variable the test already uses for the `--start-cmd` argv value:

```python
# Issue #110: derive now lifts start_cmd into the image entrypoint when
# systemd is not required. Tighten from "anything non-sentinel" to the
# exact bash -c shape.
assert policy.image.entrypoint == ["bash", "-c", start_cmd_string]
```

If the existing test uses an inline string literal rather than a named variable, hoist the literal into a local first.

- [ ] **Step 3: Run the integration test (cougar only — needs full BPF)**

```bash
pytest tests/integration/trace/test_deb_pipeline.py::test_deb_with_start_cmd_produces_non_sentinel_policy -v
```

Expected: PASS on cougar (the trace pipeline produces a real policy.json whose entrypoint is now the exact `["bash", "-c", start_cmd_string]` shape).

If running locally on WSL: this integration test cannot run (per `wsl_tracepoints_limitation` memory). Defer to CI; do not skip with `pytest.skip`.

- [ ] **Step 4: Add a one-line note to docs/MANUAL.md**

Find the scenario in `docs/MANUAL.md` that introduces `--start-cmd` (most recently scenario 14). After the paragraph describing `--start-cmd`, append:

```markdown
When `--start-cmd` is provided and the workload is not systemd-managed, the same string also becomes the image entrypoint (`bash -c '<start_cmd>'`). For systemd workloads, the entrypoint stays `/sbin/init` and the supplied `--start-cmd` is recorded as a no-op in `policy.warnings`.
```

- [ ] **Step 5: Commit**

```bash
git add tests/integration/trace/test_deb_pipeline.py docs/MANUAL.md
git commit -m "docs(MANUAL),test(integration): --start-cmd doubles as entrypoint (#110)" -m "Tighten the #105 deb-pipeline integration test to assert the exact bash -c entrypoint shape; document the new derive behavior in MANUAL."
```

---

## Task 9: Cougar fixture sanity check (manual, not committed)

**Goal:** Validate end-to-end against the real 2026-06-24 cougar fixture without committing fixture data to the repo.

This is a smoke test, not code. Run only on cougar with sudo access to `/home/yizshachuck/source/containerizer/out/unifi-sudo/`.

- [ ] **Step 1: Make a writable copy of the fixture trace dir**

```bash
mkdir -p ~/sanity-check
sudo cp -r /home/yizshachuck/source/containerizer/out/unifi-sudo/.intermediates/trace/original ~/sanity-check/trace
sudo chown -R claude:claude ~/sanity-check/trace
```

- [ ] **Step 2: Synthesize the START_CMD file matching the workaround**

```bash
cat > ~/sanity-check/trace/START_CMD <<'EOF'
install -d -o mongodb -g mongodb /var/lib/mongodb /var/log/mongodb && runuser -u mongodb -- /usr/bin/mongod --fork --config /etc/mongod.conf && /usr/sbin/unifi-network-service-helper init && exec runuser -u unifi -- /usr/bin/java -jar /usr/lib/unifi/lib/ace.jar start
EOF
```

(Heredoc has no trailing newline trimming concerns — derive's `bash -c` swallows trailing whitespace harmlessly.)

- [ ] **Step 3: Run analyze against the fixture**

```bash
cd ~/source/containerizer
# Use whichever venv is wired up; create one if none.
test -d ~/venvs/containerizer && source ~/venvs/containerizer/bin/activate \
  || ( python3 -m venv ~/venvs/containerizer-110 \
       && source ~/venvs/containerizer-110/bin/activate \
       && pip install -e . )
containerizer analyze ~/sanity-check/trace -o ~/sanity-check/out
```

- [ ] **Step 4: Verify the entrypoint matches the 2026-06-24 workaround**

```bash
jq .image.entrypoint ~/sanity-check/out/policy.json
```

Expected:

```json
[
  "bash",
  "-c",
  "install -d -o mongodb -g mongodb /var/lib/mongodb /var/log/mongodb && runuser -u mongodb -- /usr/bin/mongod --fork --config /etc/mongod.conf && /usr/sbin/unifi-network-service-helper init && exec runuser -u unifi -- /usr/bin/java -jar /usr/lib/unifi/lib/ace.jar start"
]
```

This is byte-identical (mod whitespace) to the hand-patched policy the user shipped in 2026-06-24 — proving the fix subsumes the workaround.

- [ ] **Step 5: Clean up; do NOT commit anything from this step**

```bash
rm -rf ~/sanity-check
```

---

## Pre-PR sanity check

- [ ] **Run the full unit test suite**

```bash
pytest tests/unit/ -v
```

Expected: ALL PASS. Fix anything red before opening the PR.

- [ ] **Verify all task commits are signed**

```bash
git log --show-signature main..HEAD 2>&1 | grep -E "^(commit|gpg:)"
```

Expected: every commit shows `gpg: Good signature from "Patrick Connallon (claude-cougar) ..."`.

- [ ] **Push the feature branch + open the PR**

```bash
git push -u origin fix/110-entrypoint-start-cmd
gh pr create \
  --title "fix(analyze): wire --start-cmd as entrypoint when no systemd (#110)" \
  --body "$(cat <<'BODY'
## Summary

Closes #110.

When `--start-cmd` is provided and `systemd_required_for(trace)` is false, `derive_policy` now emits `entrypoint = ["bash", "-c", start_cmd]` instead of the `__UNSET__` sentinel. `start_cmd` persists in the trace artifact as a `START_CMD` sidecar file at the trace-dir root, so standalone `containerizer analyze <trace-dir>/` benefits without re-specifying the flag.

When systemd is detected as required, `--start-cmd` is ignored and a warning is added to `policy.warnings` ("start_cmd ignored: systemd detected as required; using /sbin/init as entrypoint").

Scope: `--start-cmd`-as-entrypoint only. `runtime.ports.by`-driven inference for trivial single-process daemons is intentionally deferred to a follow-up PR.

## Design spec

`docs/superpowers/specs/2026-06-26-containerizer-issue-110-entrypoint-inference.md`

## Test plan

- [x] Schema: `TraceJson.start_cmd` round-trips + missing-field backwards-compat
- [x] Reader: picks up `START_CMD` when present; `None` when absent
- [x] Assemble: threads `bundle.start_cmd` → `TraceJson`
- [x] Derive: 4-case entrypoint truth table (with systemd-override warning)
- [x] Runner: writes `START_CMD` file when `start_cmd` set; omits when unset
- [x] CLI: `--start-cmd ''` normalized to `None` on both `build` and `trace`
- [x] Integration: existing #105 deb-pipeline test tightened to exact entrypoint
- [x] Cougar fixture sanity check (local, not committed): real UniFi trace + synthesized `START_CMD` reproduces the hand-patched policy
BODY
)"
```
