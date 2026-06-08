# M5 Verify Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the M5 milestone of the containerizer per [`docs/superpowers/specs/2026-06-08-containerizer-m5-verify.md`](../specs/2026-06-08-containerizer-m5-verify.md): a `containerizer verify --original <trace.json> --observed <trace.json> -o <out-dir>` subcommand that diffs two normalized trace.json documents and emits a `verify.json` listing observed runtime events not present in the original.

**Architecture:** A new `src/containerizer/verify/` package with one module per concern: `schema` (VerifyReport Pydantic models), `diff` (pure `diff_traces(original, observed) -> VerifyReport`), `writer` (deterministic JSON serialization), `cli` (Click subcommand + I/O). Reuses `TracePath`/`TracePort` from `analyze/schema.py`. Compares runtime phase only, one-directional (observed \ original). Exit 0 if subset, 1 if any new events, 2 on operational errors.

**Tech Stack:** Python 3.11+ + Click + Pydantic v2 (already in `pyproject.toml`), pytest. No new third-party dependencies.

---

## Conventions used throughout

- **Working directory:** all commands assume `C:\Users\yizshachuck\source\containerizer\` is the cwd. Use absolute paths in tools (Read/Edit/Write); use relative paths in shell commands.
- **Branch + PR strategy.** Single branch `feat/m5-verify` off latest `main`. One PR at the end closing #43. Per-task signed commits.
- **Commit signing.** Every commit MUST be signed per the user's global `CLAUDE.md`:
  ```
  git -c user.email="github.v5f9w@bitbucket.onl" \
      -c user.signingkey=BE707B220C995478 \
      commit -S -m "<message>"
  ```
  Never pass `--no-gpg-sign`. Never amend a published commit.
- **Conventional commit subject** per task. `feat(verify):` for new verify modules; `test(verify):` for fixtures and tests; `docs:` for the MANUAL update.
- **Coverage gate.** `pyproject.toml` enforces `--cov-fail-under=90`. New code in `src/containerizer/verify/` must keep total coverage ≥ 90%.
- **Lint + type gate.** `ruff check . && ruff format --check . && mypy src tests && pytest` must pass before committing every task.
- **Pydantic style.** v2, `BaseModel` subclasses, `ConfigDict(extra="forbid", frozen=True)` on every model. Match `analyze/schema.py`.
- **Line endings.** LF in the repo; Windows working copies see CRLF warnings. Benign.

---

## File map

Files created or modified by this plan:

| Path | Purpose | Task |
|---|---|---|
| `src/containerizer/verify/__init__.py` | Package marker | 1 |
| `tests/unit/verify/__init__.py` | Test package marker | 1 |
| `src/containerizer/verify/schema.py` | VerifyDiff + VerifyReport Pydantic models | 2 |
| `tests/unit/verify/test_schema.py` | Schema round-trip, frozen invariants | 2 |
| `src/containerizer/verify/diff.py` | `diff_traces(original, observed) -> VerifyReport` | 3 |
| `tests/unit/verify/test_diff.py` | Per-category diff tests, PARTIAL handling | 3 |
| `src/containerizer/verify/writer.py` | `write_verify_json(report, path)` | 4 |
| `tests/unit/verify/test_writer.py` | schema_version first, trailing newline | 4 |
| `src/containerizer/verify/cli.py` | `verify_cmd` Click subcommand | 5 |
| `src/containerizer/cli.py` | Register `verify_cmd` on main group | 5 |
| `tests/unit/verify/test_cli.py` | Happy/diff/error paths | 5 |
| `tests/fixtures/verify/original.json` | Baseline TraceJson fixture | 6 |
| `tests/fixtures/verify/observed-clean.json` | Identical to original | 6 |
| `tests/fixtures/verify/observed-with-new.json` | Adds one entry per category | 6 |
| `tests/fixtures/verify/expected/verify-with-new.json` | Golden verify.json | 6 |
| `tests/integration/verify/__init__.py` | Test package marker | 6 |
| `tests/integration/verify/test_verify_smoke.py` | E2E against fixtures + golden | 6 |
| `MANUAL.md` | Add scenario 9 (running verify) | 7 |

---

## Task 1: New `verify/` package + empty test directory

**Files:**
- Create: `src/containerizer/verify/__init__.py`
- Create: `tests/unit/verify/__init__.py`

This task lands first to give later tasks a stable target package.

- [ ] **Step 1: Create the package marker**

Write `src/containerizer/verify/__init__.py`:

```python
"""Containerizer trace verifier (M5)."""
```

- [ ] **Step 2: Create the unit-test package marker**

Write `tests/unit/verify/__init__.py` (empty file).

- [ ] **Step 3: Run the gate**

```
ruff check . && ruff format --check . && mypy src tests && pytest
```

Expected: PASS.

- [ ] **Step 4: Commit**

```
git add src/containerizer/verify/__init__.py tests/unit/verify/__init__.py
git -c user.email="github.v5f9w@bitbucket.onl" \
    -c user.signingkey=BE707B220C995478 \
    commit -S -m "feat(verify): bootstrap verify package + test directory"
```

---

## Task 2: `schema.py` — VerifyDiff + VerifyReport

**Issue:** #43.

**Files:**
- Create: `src/containerizer/verify/schema.py`
- Create: `tests/unit/verify/test_schema.py`

Pydantic models. Reuses `TracePath`/`TracePort` from `analyze/schema.py`; no new path/port shape.

- [ ] **Step 1: Write the failing tests**

Write `tests/unit/verify/test_schema.py`:

```python
"""Tests for containerizer.verify.schema."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from containerizer.analyze.schema import TracePath, TracePort
from containerizer.verify.schema import VerifyDiff, VerifyReport


def _empty_diff() -> VerifyDiff:
    return VerifyDiff(
        new_paths=[],
        new_ports=[],
        new_caps=[],
        new_syscalls=[],
        new_execs=[],
    )


def test_verify_report_round_trip_minimal() -> None:
    r = VerifyReport(
        original_marker="COMPLETE",
        observed_marker="COMPLETE",
        diff=_empty_diff(),
    )
    raw = r.model_dump_json()
    r2 = VerifyReport.model_validate_json(raw)
    assert r == r2
    assert r2.schema_version == 1
    assert r2.warnings == []


def test_verify_report_carries_warnings_and_partial_markers() -> None:
    r = VerifyReport(
        original_marker="PARTIAL",
        observed_marker="COMPLETE",
        diff=_empty_diff(),
        warnings=["original trace marker is PARTIAL; comparison may be incomplete"],
    )
    assert r.original_marker == "PARTIAL"
    assert r.warnings == ["original trace marker is PARTIAL; comparison may be incomplete"]


def test_verify_diff_carries_typed_paths_and_ports() -> None:
    diff = VerifyDiff(
        new_paths=[
            TracePath(  # type: ignore[call-arg]
                path="/var/lib/x", ops=["read"], class_="persistent_rw", by=["a"]
            )
        ],
        new_ports=[TracePort(port=80, proto="tcp", by="a", ipv4=True, ipv6=False)],
        new_caps=["CAP_NET_BIND_SERVICE"],
        new_syscalls=[59],
        new_execs=["app"],
    )
    assert diff.new_paths[0].path == "/var/lib/x"
    assert diff.new_ports[0].port == 80


def test_verify_report_frozen() -> None:
    r = VerifyReport(
        original_marker="COMPLETE",
        observed_marker="COMPLETE",
        diff=_empty_diff(),
    )
    with pytest.raises(ValidationError):
        r.warnings = ["x"]  # type: ignore[misc]


def test_verify_report_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        VerifyReport.model_validate({
            "schema_version": 1,
            "original_marker": "COMPLETE",
            "observed_marker": "COMPLETE",
            "diff": _empty_diff().model_dump(),
            "warnings": [],
            "unexpected": True,
        })
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/verify/test_schema.py -v`
Expected: FAIL with ImportError on `containerizer.verify.schema`.

- [ ] **Step 3: Implement `schema.py`**

Write `src/containerizer/verify/schema.py`:

```python
"""Pydantic models for the verifier's verify.json output.

This module is the contract every other verify/ module depends on.
Reuses TracePath / TracePort from analyze.schema; no new path/port shape.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

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

- [ ] **Step 4: Run tests + gate + commit**

```
pytest tests/unit/verify/test_schema.py -v
ruff check . && ruff format --check . && mypy src tests && pytest
git add src/containerizer/verify/schema.py tests/unit/verify/test_schema.py
git -c user.email="github.v5f9w@bitbucket.onl" \
    -c user.signingkey=BE707B220C995478 \
    commit -S -m "feat(verify): schema.py — VerifyDiff + VerifyReport models"
```

---

## Task 3: `diff.py` — `diff_traces` pure function

**Issue:** #43.

**Files:**
- Create: `src/containerizer/verify/diff.py`
- Create: `tests/unit/verify/test_diff.py`

The comparison core. Takes two `TraceJson` models, returns a `VerifyReport`. Pure function.

- [ ] **Step 1: Write the failing tests**

Write `tests/unit/verify/test_diff.py`:

```python
"""Tests for containerizer.verify.diff."""

from __future__ import annotations

from containerizer.analyze.schema import (
    TraceJson,
    TracePath,
    TracePhase,
    TracePort,
)
from containerizer.verify.diff import diff_traces


def _phase(
    *,
    paths: list[TracePath] | None = None,
    ports: list[TracePort] | None = None,
    caps: list[str] | None = None,
    syscalls: list[int] | None = None,
    execs: list[str] | None = None,
) -> TracePhase:
    return TracePhase(
        duration_s=1.0,
        paths=paths or [],
        ports=ports or [],
        outbound=[],
        caps=caps or [],
        syscalls=syscalls or [],
        execs=execs or [],
    )


def _trace(
    *,
    runtime: TracePhase | None = None,
    marker: str = "COMPLETE",
) -> TraceJson:
    return TraceJson(
        phase_marker_ns=1000,
        marker=marker,  # type: ignore[arg-type]
        install=_phase(),
        runtime=runtime or _phase(),
        warnings=[],
    )


def test_identical_traces_produce_empty_diff() -> None:
    p = TracePath(  # type: ignore[call-arg]
        path="/var/lib/x", ops=["read"], class_="persistent_rw", by=["a"]
    )
    runtime = _phase(paths=[p], caps=["CAP_FOO"], syscalls=[1, 2], execs=["app"])
    t = _trace(runtime=runtime)
    report = diff_traces(t, t)
    assert report.diff.new_paths == []
    assert report.diff.new_ports == []
    assert report.diff.new_caps == []
    assert report.diff.new_syscalls == []
    assert report.diff.new_execs == []
    assert report.warnings == []


def test_new_path_surfaced() -> None:
    p1 = TracePath(  # type: ignore[call-arg]
        path="/a", ops=["read"], class_="persistent_rw", by=["x"]
    )
    p2 = TracePath(  # type: ignore[call-arg]
        path="/b", ops=["read"], class_="persistent_rw", by=["x"]
    )
    orig = _trace(runtime=_phase(paths=[p1]))
    obs = _trace(runtime=_phase(paths=[p1, p2]))
    report = diff_traces(orig, obs)
    assert len(report.diff.new_paths) == 1
    assert report.diff.new_paths[0].path == "/b"


def test_same_path_different_class_counts_as_new() -> None:
    p_orig = TracePath(  # type: ignore[call-arg]
        path="/a", ops=["read"], class_="unknown_rw", by=["x"]
    )
    p_obs = TracePath(  # type: ignore[call-arg]
        path="/a", ops=["read"], class_="persistent_rw", by=["x"]
    )
    orig = _trace(runtime=_phase(paths=[p_orig]))
    obs = _trace(runtime=_phase(paths=[p_obs]))
    report = diff_traces(orig, obs)
    assert len(report.diff.new_paths) == 1
    assert report.diff.new_paths[0].class_ == "persistent_rw"


def test_new_port_surfaced_by_port_proto_key() -> None:
    p_orig = TracePort(port=80, proto="tcp", by="x", ipv4=True, ipv6=False)
    p_obs_new = TracePort(port=443, proto="tcp", by="x", ipv4=True, ipv6=False)
    orig = _trace(runtime=_phase(ports=[p_orig]))
    obs = _trace(runtime=_phase(ports=[p_orig, p_obs_new]))
    report = diff_traces(orig, obs)
    assert [p.port for p in report.diff.new_ports] == [443]


def test_same_port_different_family_does_not_count_as_new() -> None:
    # ipv4 vs ipv6 flag changes don't gate the diff per spec 4.7
    p_orig = TracePort(port=80, proto="tcp", by="x", ipv4=True, ipv6=False)
    p_obs = TracePort(port=80, proto="tcp", by="x", ipv4=False, ipv6=True)
    orig = _trace(runtime=_phase(ports=[p_orig]))
    obs = _trace(runtime=_phase(ports=[p_obs]))
    report = diff_traces(orig, obs)
    assert report.diff.new_ports == []


def test_new_cap_surfaced() -> None:
    orig = _trace(runtime=_phase(caps=["CAP_FOO"]))
    obs = _trace(runtime=_phase(caps=["CAP_FOO", "CAP_BAR"]))
    report = diff_traces(orig, obs)
    assert report.diff.new_caps == ["CAP_BAR"]


def test_new_syscall_surfaced() -> None:
    orig = _trace(runtime=_phase(syscalls=[1, 2]))
    obs = _trace(runtime=_phase(syscalls=[1, 2, 59]))
    report = diff_traces(orig, obs)
    assert report.diff.new_syscalls == [59]


def test_new_exec_surfaced() -> None:
    orig = _trace(runtime=_phase(execs=["app"]))
    obs = _trace(runtime=_phase(execs=["app", "worker"]))
    report = diff_traces(orig, obs)
    assert report.diff.new_execs == ["worker"]


def test_multiple_categories_all_surface() -> None:
    p_new = TracePath(  # type: ignore[call-arg]
        path="/x", ops=["read"], class_="persistent_rw", by=["a"]
    )
    orig = _trace(runtime=_phase(caps=["CAP_A"], syscalls=[1]))
    obs = _trace(runtime=_phase(
        paths=[p_new],
        ports=[TracePort(port=80, proto="tcp", by="a", ipv4=True, ipv6=False)],
        caps=["CAP_A", "CAP_B"],
        syscalls=[1, 2],
        execs=["new"],
    ))
    report = diff_traces(orig, obs)
    d = report.diff
    assert len(d.new_paths) == 1
    assert len(d.new_ports) == 1
    assert d.new_caps == ["CAP_B"]
    assert d.new_syscalls == [2]
    assert d.new_execs == ["new"]
    # Summary warning lists each category count
    assert any("5 events not present" in w for w in report.warnings)


def test_install_phase_differences_ignored() -> None:
    p_install_only = TracePath(  # type: ignore[call-arg]
        path="/install-only", ops=["write"], class_="persistent_rw", by=["x"]
    )
    orig = TraceJson(
        phase_marker_ns=1000,
        marker="COMPLETE",
        install=_phase(paths=[p_install_only]),
        runtime=_phase(),
        warnings=[],
    )
    obs = TraceJson(
        phase_marker_ns=1000,
        marker="COMPLETE",
        install=_phase(),  # different install phase
        runtime=_phase(),
        warnings=[],
    )
    report = diff_traces(orig, obs)
    assert report.diff.new_paths == []


def test_partial_marker_on_either_input_warns() -> None:
    orig = _trace(marker="PARTIAL")
    obs = _trace()
    report = diff_traces(orig, obs)
    assert any("original trace marker is PARTIAL" in w for w in report.warnings)
    assert report.original_marker == "PARTIAL"
    assert report.observed_marker == "COMPLETE"


def test_partial_marker_on_observed_warns() -> None:
    orig = _trace()
    obs = _trace(marker="PARTIAL")
    report = diff_traces(orig, obs)
    assert any("observed trace marker is PARTIAL" in w for w in report.warnings)


def test_new_paths_sorted_for_determinism() -> None:
    pb = TracePath(  # type: ignore[call-arg]
        path="/b", ops=["read"], class_="persistent_rw", by=["x"]
    )
    pa = TracePath(  # type: ignore[call-arg]
        path="/a", ops=["read"], class_="persistent_rw", by=["x"]
    )
    orig = _trace()
    obs = _trace(runtime=_phase(paths=[pb, pa]))  # observed in non-sorted order
    report = diff_traces(orig, obs)
    assert [p.path for p in report.diff.new_paths] == ["/a", "/b"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/verify/test_diff.py -v`
Expected: FAIL with ImportError on `containerizer.verify.diff`.

- [ ] **Step 3: Implement `diff.py`**

Write `src/containerizer/verify/diff.py`:

```python
"""Pure diff of two TraceJson documents: observed.runtime \\ original.runtime."""

from __future__ import annotations

from containerizer.analyze.schema import TraceJson
from containerizer.verify.schema import VerifyDiff, VerifyReport


def diff_traces(original: TraceJson, observed: TraceJson) -> VerifyReport:
    """Compute observed.runtime \\ original.runtime per category.

    One-directional. Install phase ignored. Path comparison keyed on
    (path, class_); port comparison keyed on (port, proto); caps/syscalls/
    execs by simple set membership. Each `new_*` list sorted deterministically.
    """
    orig_path_keys = {(p.path, p.class_) for p in original.runtime.paths}
    new_paths = sorted(
        (p for p in observed.runtime.paths if (p.path, p.class_) not in orig_path_keys),
        key=lambda p: (p.path, p.class_),
    )

    orig_port_keys = {(p.port, p.proto) for p in original.runtime.ports}
    new_ports = sorted(
        (p for p in observed.runtime.ports if (p.port, p.proto) not in orig_port_keys),
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

- [ ] **Step 4: Run tests + gate + commit**

```
pytest tests/unit/verify/test_diff.py -v
ruff check . && ruff format --check . && mypy src tests && pytest
git add src/containerizer/verify/diff.py tests/unit/verify/test_diff.py
git -c user.email="github.v5f9w@bitbucket.onl" \
    -c user.signingkey=BE707B220C995478 \
    commit -S -m "feat(verify): diff.py — diff_traces pure function"
```

---

## Task 4: `writer.py` — deterministic JSON

**Issue:** #43.

**Files:**
- Create: `src/containerizer/verify/writer.py`
- Create: `tests/unit/verify/test_writer.py`

Mirrors `analyze/writer.py` exactly. `model_dump(by_alias=True, mode="json")` + `json.dumps(indent=2, sort_keys=False)` + trailing newline.

- [ ] **Step 1: Write the failing tests**

Write `tests/unit/verify/test_writer.py`:

```python
"""Tests for containerizer.verify.writer."""

from __future__ import annotations

import json
from pathlib import Path

from containerizer.verify.schema import VerifyDiff, VerifyReport
from containerizer.verify.writer import write_verify_json


def _report() -> VerifyReport:
    return VerifyReport(
        original_marker="COMPLETE",
        observed_marker="COMPLETE",
        diff=VerifyDiff(
            new_paths=[], new_ports=[], new_caps=[], new_syscalls=[], new_execs=[]
        ),
    )


def test_writer_emits_schema_version_first(tmp_path: Path) -> None:
    out = tmp_path / "verify.json"
    write_verify_json(_report(), out)
    text = out.read_text(encoding="utf-8")
    obj = json.loads(text)
    # Pydantic field order preserved; schema_version is first
    keys = list(obj.keys())
    assert keys[0] == "schema_version"
    assert obj["schema_version"] == 1


def test_writer_pretty_printed_with_trailing_newline(tmp_path: Path) -> None:
    out = tmp_path / "verify.json"
    write_verify_json(_report(), out)
    text = out.read_text(encoding="utf-8")
    assert text.endswith("\n")
    assert "  " in text  # indented JSON


def test_writer_round_trip(tmp_path: Path) -> None:
    out = tmp_path / "verify.json"
    write_verify_json(_report(), out)
    obj = json.loads(out.read_text(encoding="utf-8"))
    r2 = VerifyReport.model_validate(obj)
    assert r2 == _report()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/verify/test_writer.py -v`
Expected: FAIL with ImportError on `containerizer.verify.writer`.

- [ ] **Step 3: Implement `writer.py`**

Write `src/containerizer/verify/writer.py`:

```python
"""Serialize VerifyReport to disk with deterministic formatting."""

from __future__ import annotations

import json
from pathlib import Path

from containerizer.verify.schema import VerifyReport


def write_verify_json(report: VerifyReport, path: Path) -> None:
    """Pretty-print the report with Pydantic field order; trailing newline."""
    obj: dict[str, object] = report.model_dump(by_alias=True, mode="json")
    text = json.dumps(obj, indent=2, sort_keys=False)
    path.write_text(text + "\n", encoding="utf-8")
```

- [ ] **Step 4: Run tests + gate + commit**

```
pytest tests/unit/verify/test_writer.py -v
ruff check . && ruff format --check . && mypy src tests && pytest
git add src/containerizer/verify/writer.py tests/unit/verify/test_writer.py
git -c user.email="github.v5f9w@bitbucket.onl" \
    -c user.signingkey=BE707B220C995478 \
    commit -S -m "feat(verify): writer.py — deterministic verify.json"
```

---

## Task 5: `cli.py` — verify subcommand + wiring

**Issue:** #43.

**Files:**
- Create: `src/containerizer/verify/cli.py`
- Modify: `src/containerizer/cli.py`
- Create: `tests/unit/verify/test_cli.py`

The pipeline glue: load two trace.json files → diff → write verify.json → emit summary → exit code.

- [ ] **Step 1: Write the failing tests**

Write `tests/unit/verify/test_cli.py`:

```python
"""Tests for the `containerizer verify` Click subcommand."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

from click.testing import CliRunner

from containerizer.analyze.schema import (
    TraceJson,
    TracePath,
    TracePhase,
    TracePort,
)
from containerizer.verify.cli import verify_cmd


def _empty_phase() -> TracePhase:
    return TracePhase(
        duration_s=1.0, paths=[], ports=[], outbound=[],
        caps=[], syscalls=[], execs=[],
    )


def _write_trace(
    path: Path,
    *,
    runtime: TracePhase,
    marker: str = "COMPLETE",
) -> None:
    t = TraceJson(
        phase_marker_ns=1000,
        marker=marker,  # type: ignore[arg-type]
        install=_empty_phase(),
        runtime=runtime,
        warnings=[],
    )
    path.write_text(t.model_dump_json(indent=2) + "\n", encoding="utf-8")


def _load_json(path: Path) -> dict[str, object]:
    return cast(dict[str, object], json.loads(path.read_text(encoding="utf-8")))


def test_verify_identical_traces_exits_zero(tmp_path: Path) -> None:
    orig = tmp_path / "orig.json"
    obs = tmp_path / "obs.json"
    runtime = TracePhase(
        duration_s=1.0, paths=[], ports=[],
        outbound=[], caps=["CAP_FOO"], syscalls=[1], execs=["app"],
    )
    _write_trace(orig, runtime=runtime)
    _write_trace(obs, runtime=runtime)
    out = tmp_path / "out"

    result = CliRunner().invoke(
        verify_cmd, ["--original", str(orig), "--observed", str(obs), "-o", str(out)]
    )
    assert result.exit_code == 0, result.output
    assert (out / "verify.json").exists()
    report = _load_json(out / "verify.json")
    diff = cast(dict[str, object], report["diff"])
    assert diff["new_paths"] == []
    assert diff["new_caps"] == []


def test_verify_new_event_exits_one_with_summary(tmp_path: Path) -> None:
    orig = tmp_path / "orig.json"
    obs = tmp_path / "obs.json"
    _write_trace(
        orig,
        runtime=TracePhase(
            duration_s=1.0, paths=[], ports=[], outbound=[],
            caps=[], syscalls=[], execs=[],
        ),
    )
    _write_trace(
        obs,
        runtime=TracePhase(
            duration_s=1.0,
            paths=[
                TracePath(  # type: ignore[call-arg]
                    path="/new", ops=["read"], class_="persistent_rw", by=["a"]
                )
            ],
            ports=[TracePort(port=80, proto="tcp", by="a", ipv4=True, ipv6=False)],
            outbound=[], caps=["CAP_X"], syscalls=[99], execs=["new"],
        ),
    )
    out = tmp_path / "out"

    result = CliRunner(mix_stderr=False).invoke(
        verify_cmd, ["--original", str(orig), "--observed", str(obs), "-o", str(out)]
    )
    assert result.exit_code == 1, result.output
    assert "1 new paths" in result.stderr
    assert "1 new ports" in result.stderr
    assert "1 new caps" in result.stderr
    assert "1 new syscalls" in result.stderr
    assert "1 new execs" in result.stderr

    report = _load_json(out / "verify.json")
    diff = cast(dict[str, object], report["diff"])
    assert len(cast(list[object], diff["new_paths"])) == 1


def test_verify_missing_input_errors(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        verify_cmd,
        ["--original", str(tmp_path / "nope.json"), "--observed", str(tmp_path / "also-nope.json"),
         "-o", str(tmp_path / "out")],
    )
    assert result.exit_code != 0
    assert result.exit_code != 1  # 2-or-other operational error, not "diff found"


def test_verify_partial_marker_warning_surfaces(tmp_path: Path) -> None:
    orig = tmp_path / "orig.json"
    obs = tmp_path / "obs.json"
    runtime = _empty_phase()
    _write_trace(orig, runtime=runtime, marker="PARTIAL")
    _write_trace(obs, runtime=runtime)
    out = tmp_path / "out"

    result = CliRunner().invoke(
        verify_cmd, ["--original", str(orig), "--observed", str(obs), "-o", str(out)]
    )
    assert result.exit_code == 0, result.output
    report = _load_json(out / "verify.json")
    warnings = cast(list[str], report["warnings"])
    assert any("PARTIAL" in w for w in warnings)


def test_main_cli_lists_verify() -> None:
    from containerizer.cli import main
    result = CliRunner().invoke(main, ["--help"])
    assert "verify" in result.output
```

Note on `CliRunner(mix_stderr=False)`: Click 8.3 removed this kwarg. If the gate fails with `TypeError: CliRunner.__init__() got an unexpected keyword argument 'mix_stderr'`, drop the kwarg — `result.stderr` is always populated in Click 8.3+ (verified for M4 Task 10).

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/verify/test_cli.py -v`
Expected: FAIL with ImportError on `containerizer.verify.cli`.

- [ ] **Step 3: Implement `verify/cli.py`**

Write `src/containerizer/verify/cli.py`:

```python
"""`containerizer verify --original <a> --observed <b> -o <out-dir>` Click subcommand."""

from __future__ import annotations

from pathlib import Path

import click

from containerizer.analyze.schema import TraceJson
from containerizer.verify.diff import diff_traces
from containerizer.verify.writer import write_verify_json


@click.command("verify")
@click.option(
    "--original",
    "original_path",
    required=True,
    type=click.Path(exists=True, dir_okay=False, readable=True, path_type=Path),
    help="Path to the original trace.json (baseline).",
)
@click.option(
    "--observed",
    "observed_path",
    required=True,
    type=click.Path(exists=True, dir_okay=False, readable=True, path_type=Path),
    help="Path to the observed trace.json (the new run to compare).",
)
@click.option(
    "-o",
    "--output-dir",
    required=True,
    type=click.Path(path_type=Path),
    help="Directory to write verify.json to.",
)
def verify_cmd(original_path: Path, observed_path: Path, output_dir: Path) -> None:
    """Diff OBSERVED trace.json against ORIGINAL trace.json. Emit verify.json.

    Exit 0 if observed runtime is a subset of original runtime; 1 if any new
    events are present; 2 on operational errors (missing/malformed inputs).
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    original = TraceJson.model_validate_json(original_path.read_text(encoding="utf-8"))
    observed = TraceJson.model_validate_json(observed_path.read_text(encoding="utf-8"))

    report = diff_traces(original, observed)
    write_verify_json(report, output_dir / "verify.json")

    d = report.diff
    total = (
        len(d.new_paths) + len(d.new_ports) + len(d.new_caps)
        + len(d.new_syscalls) + len(d.new_execs)
    )
    if total == 0:
        click.echo("verify: no new events", err=True)
        return

    click.echo(
        f"verify: {len(d.new_paths)} new paths, {len(d.new_ports)} new ports, "
        f"{len(d.new_caps)} new caps, {len(d.new_syscalls)} new syscalls, "
        f"{len(d.new_execs)} new execs",
        err=True,
    )
    raise click.exceptions.Exit(1)
```

- [ ] **Step 4: Wire the subcommand into the main CLI**

Edit `src/containerizer/cli.py`. Near the other imports at the top, add:

```python
from containerizer.verify.cli import verify_cmd
```

Near the bottom, after `main.add_command(generate_cmd)`, add:

```python
main.add_command(verify_cmd)
```

- [ ] **Step 5: Run tests + gate + commit**

```
pytest tests/unit/verify/test_cli.py -v
ruff check . && ruff format --check . && mypy src tests && pytest
git add src/containerizer/verify/cli.py src/containerizer/cli.py tests/unit/verify/test_cli.py
git -c user.email="github.v5f9w@bitbucket.onl" \
    -c user.signingkey=BE707B220C995478 \
    commit -S -m "feat(verify): cli.py — wire verify subcommand into main group"
```

---

## Task 6: Integration smoke + fixtures + golden

**Issue:** #43.

**Files:**
- Create: `tests/integration/verify/__init__.py`
- Create: `tests/fixtures/verify/original.json`
- Create: `tests/fixtures/verify/observed-clean.json`
- Create: `tests/fixtures/verify/observed-with-new.json`
- Create: `tests/fixtures/verify/expected/verify-with-new.json`
- Create: `tests/integration/verify/test_verify_smoke.py`

End-to-end test against committed trace.json fixtures + golden verify.json.

- [ ] **Step 1: Create the package marker**

Write `tests/integration/verify/__init__.py` (empty file).

- [ ] **Step 2: Hand-craft the `original.json` fixture**

Write `tests/fixtures/verify/original.json`:

```json
{
  "schema_version": 1,
  "phase_marker_ns": 1000,
  "marker": "COMPLETE",
  "install": {
    "duration_s": 0.0,
    "exit": null,
    "paths": [],
    "ports": [],
    "outbound": [],
    "caps": [],
    "syscalls": [],
    "execs": []
  },
  "runtime": {
    "duration_s": 1.0,
    "exit": null,
    "paths": [
      {
        "path": "/var/lib/app",
        "ops": ["read", "write"],
        "class": "persistent_rw",
        "by": ["app"]
      },
      {
        "path": "/etc/resolv.conf",
        "ops": ["read"],
        "class": "host_config_ro",
        "by": ["app"]
      }
    ],
    "ports": [
      {"port": 8443, "proto": "tcp", "by": "app", "ipv4": true, "ipv6": false}
    ],
    "outbound": [],
    "caps": ["CAP_NET_BIND_SERVICE"],
    "syscalls": [1, 59],
    "execs": ["app"]
  },
  "warnings": []
}
```

- [ ] **Step 3: Create `observed-clean.json` (byte-identical to `original.json`)**

Copy the same content:

```
Copy-Item tests/fixtures/verify/original.json tests/fixtures/verify/observed-clean.json -Force
```

(Or write the same JSON content via Write. The point is byte-identical content.)

- [ ] **Step 4: Hand-craft the `observed-with-new.json` fixture**

Write `tests/fixtures/verify/observed-with-new.json` — same as `original.json` but with one synthesized entry added per category:

```json
{
  "schema_version": 1,
  "phase_marker_ns": 1000,
  "marker": "COMPLETE",
  "install": {
    "duration_s": 0.0,
    "exit": null,
    "paths": [],
    "ports": [],
    "outbound": [],
    "caps": [],
    "syscalls": [],
    "execs": []
  },
  "runtime": {
    "duration_s": 1.0,
    "exit": null,
    "paths": [
      {
        "path": "/var/lib/app",
        "ops": ["read", "write"],
        "class": "persistent_rw",
        "by": ["app"]
      },
      {
        "path": "/etc/resolv.conf",
        "ops": ["read"],
        "class": "host_config_ro",
        "by": ["app"]
      },
      {
        "path": "/var/log/app",
        "ops": ["write"],
        "class": "persistent_rw",
        "by": ["app"]
      }
    ],
    "ports": [
      {"port": 8443, "proto": "tcp", "by": "app", "ipv4": true, "ipv6": false},
      {"port": 9000, "proto": "tcp", "by": "app", "ipv4": true, "ipv6": false}
    ],
    "outbound": [],
    "caps": ["CAP_NET_BIND_SERVICE", "CAP_CHOWN"],
    "syscalls": [1, 2, 59],
    "execs": ["app", "worker"]
  },
  "warnings": []
}
```

- [ ] **Step 5: Generate the golden `verify-with-new.json`**

Run (PowerShell), creating a temp dir to capture verify's output and copying just the golden file:

```powershell
New-Item -ItemType Directory -Path tests/fixtures/verify/expected -Force | Out-Null
$tmp = New-Item -ItemType Directory -Path ([System.IO.Path]::GetTempPath() + [System.Guid]::NewGuid())
.venv\Scripts\containerizer.exe verify `
    --original tests/fixtures/verify/original.json `
    --observed tests/fixtures/verify/observed-with-new.json `
    -o $tmp
Copy-Item $tmp/verify.json tests/fixtures/verify/expected/verify-with-new.json
Remove-Item -Recurse $tmp
```

If `.venv\Scripts\containerizer.exe` doesn't exist, ask which Python entry point to use.

- [ ] **Step 6: Manually inspect the golden**

Open `tests/fixtures/verify/expected/verify-with-new.json`. Verify the diff contains exactly:

- `new_paths`: one entry — `/var/log/app` with class `persistent_rw`.
- `new_ports`: one entry — port 9000, proto tcp.
- `new_caps`: `["CAP_CHOWN"]`.
- `new_syscalls`: `[2]`.
- `new_execs`: `["worker"]`.
- `warnings`: one summary line indicating 5 events.
- `original_marker` and `observed_marker` both `"COMPLETE"`.

If anything differs, stop and report — that's an upstream diff/CLI bug, not a Task 6 issue.

- [ ] **Step 7: Write the smoke test**

Write `tests/integration/verify/test_verify_smoke.py`:

```python
"""End-to-end smoke tests for `containerizer verify`."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest
from click.testing import CliRunner

from containerizer.verify.cli import verify_cmd

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "verify"
EXPECTED = FIXTURES / "expected"


def _load_json(path: Path) -> dict[str, object]:
    return cast(dict[str, object], json.loads(path.read_text(encoding="utf-8")))


@pytest.fixture
def golden_with_new() -> dict[str, object]:
    return _load_json(EXPECTED / "verify-with-new.json")


def test_clean_observed_exits_zero_with_empty_diff(tmp_path: Path) -> None:
    out = tmp_path / "out"
    result = CliRunner().invoke(
        verify_cmd,
        [
            "--original", str(FIXTURES / "original.json"),
            "--observed", str(FIXTURES / "observed-clean.json"),
            "-o", str(out),
        ],
    )
    assert result.exit_code == 0, result.output
    report = _load_json(out / "verify.json")
    diff = cast(dict[str, object], report["diff"])
    assert diff["new_paths"] == []
    assert diff["new_ports"] == []
    assert diff["new_caps"] == []
    assert diff["new_syscalls"] == []
    assert diff["new_execs"] == []


def test_observed_with_new_matches_golden(
    tmp_path: Path,
    golden_with_new: dict[str, object],
) -> None:
    out = tmp_path / "out"
    result = CliRunner().invoke(
        verify_cmd,
        [
            "--original", str(FIXTURES / "original.json"),
            "--observed", str(FIXTURES / "observed-with-new.json"),
            "-o", str(out),
        ],
    )
    assert result.exit_code == 1, result.output
    actual = _load_json(out / "verify.json")
    assert actual == golden_with_new
```

- [ ] **Step 8: Run the gate**

```
pytest tests/integration/verify/test_verify_smoke.py -v
ruff check . && ruff format --check . && mypy src tests && pytest
```

Expected: PASS.

- [ ] **Step 9: Commit**

```
git add tests/integration/verify/__init__.py tests/integration/verify/test_verify_smoke.py tests/fixtures/verify/
git -c user.email="github.v5f9w@bitbucket.onl" \
    -c user.signingkey=BE707B220C995478 \
    commit -S -m "test(verify): integration smoke test + clean/with-new fixtures + golden"
```

---

## Task 7: MANUAL.md scenario 9 + final PR

**Issue:** #43.

**Files:**
- Modify: `MANUAL.md`

- [ ] **Step 1: Read the current MANUAL.md to match style**

Locate scenario 8 (the M4 `generate` walkthrough). Note its heading level (`##`), code-fence language (`pwsh`), prompt prefix (`PS>`), inline output.

- [ ] **Step 2: Add scenario 9**

After scenario 8, append:

```markdown
## Scenario 9 — Verify the generated policy

After running `containerizer generate` to produce artifacts, rebuild the image, run it briefly, capture a fresh trace, run `containerizer analyze` on that trace, and then diff the new `trace.json` against the original with `verify`:

```pwsh
PS> containerizer verify --original .\unifi-analyze\trace.json --observed .\unifi-rerun-analyze\trace.json -o .\unifi-verify\
verify: 1 new paths, 0 new ports, 0 new caps, 2 new syscalls, 0 new execs
```

The exit code is 0 if the observed trace's runtime events are a subset of the original's, or 1 if any new events appear. `verify.json` lists exactly what was new in each category so you can decide whether to re-run with a longer interaction or to relax the policy. See `docs/superpowers/specs/2026-06-08-containerizer-m5-verify.md` for the full contract. (Rebuilding + re-tracing the generated container will land in M6's `build` subcommand; for now those steps are manual.)
```

Match scenario 8's exact style. If MANUAL.md uses a slightly different convention, adapt.

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
    commit -S -m "docs: MANUAL.md scenario 9 — containerizer verify"
```

- [ ] **Step 5: Open the final PR**

(The controller handles push + PR; the implementer subagent stops at Step 4 above. If running this plan inline without a controller:)

```
git push origin feat/m5-verify
gh pr create --title "feat(verify): M5 verify (diff-only)" --body "$(cat <<'EOF'
## Summary

Closes #43.

Implements the M5 milestone per `docs/superpowers/specs/2026-06-08-containerizer-m5-verify.md`. New `src/containerizer/verify/` package with `schema`, `diff`, `writer`, `cli` modules. Single `containerizer verify --original <trace.json> --observed <trace.json> -o <out-dir>` CLI subcommand that emits a `verify.json` describing observed runtime events not present in the original trace.

Scope: diff-only. The rebuild + retrace orchestration deferred to M6's `build` subcommand. Reuses `TracePath` / `TracePort` from `analyze/schema.py`; no new path/port shape. Compares runtime phase only, one-directional (observed \ original). Exit 0 if subset, 1 if any new events, 2 on operational errors.

## Test plan

- [x] Unit tests for every module (schema, diff, writer, cli).
- [x] Integration smoke test against committed `original.json` + `observed-clean.json` (exit 0) and `original.json` + `observed-with-new.json` (exit 1, matches golden `verify-with-new.json`).
- [x] Coverage stays >= 90%.
- [x] Lint + type gate green.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Wait for CI to go green on all branch-protection required checks, then squash-merge.

---

## Exit criteria

M5 is done when:

1. `containerizer verify --original a.json --observed b.json -o <tmp>` produces verify.json with the correct shape and exit code (0 for subset, 1 for any diff).
2. Identical-traces fixture (`observed-clean.json`) produces empty diff arrays.
3. Synthesized-deltas fixture (`observed-with-new.json`) produces the right entries per category and matches the golden byte-for-byte.
4. PARTIAL traces warn (entry in `verify.warnings`) without changing the exit code.
5. `pytest` (unit + integration, no `-m integration` exclusion) is green. Coverage ≥ 90%.
6. `ruff check . && ruff format --check . && mypy src tests && pytest` is green.
7. MANUAL.md scenario 9 (running verify) is added.
8. PR opened closing #43; CI green on all required checks.

M5 is **not** required to:

- Rebuild the generated image (M6).
- Run the generated container or capture a fresh trace (M6).
- Auto-suggest a relaxed policy.json (M6).
- Provide doctor/recovery functionality (deferred — no current issue).
- Compare `seccomp.json` allowlist directly (the trace.json comparison subsumes it).
