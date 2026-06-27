# Issue #111 — Multi-deb / apt-source generator — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `containerizer build` produce a working `Containerfile` for `.deb` installer inputs (with optional `--apt-source` and `--apt-key` flags), closing the gap between the shipped trace-side support (#99, #103) and the analyze/generate sides.

**Architecture:** Trace runner writes new marker files (`INSTALLERS`, `APT_KEYS`) into the trace dir; a new reader helper surfaces them as `InstallInputs`; `derive_policy` builds a discriminated `InstallerSpec` (`DebInstaller | ExecutableInstaller`) on `PolicyImage`; `render_containerfile` dispatches on `kind` and emits an apt-install-layer Containerfile for the deb case; the build orchestrator stages installer files and apt-keys into `final_dir/` before `podman build`.

**Tech Stack:** Python 3.12, Pydantic v2, Click, pytest, ruff. All changes target `src/containerizer/**` and `tests/unit/**`. Integration tests are pre-existing and not modified.

**Companion spec:** `docs/superpowers/specs/2026-06-27-issue-111-multi-deb-generator-design.md`

**Pre-commit gate** (per repo convention): every commit must pass `ruff format --check .` + `ruff check .` + `pytest tests/`. Tasks include the explicit verification step.

---

## File Structure

**Created:**
- `tests/unit/analyze/test_reader_install_inputs.py` — Task 2 (new tests for the install-inputs reader helper)

**Modified — production code:**
- `src/containerizer/analyze/schema.py` — Task 1 (DebInstaller, ExecutableInstaller, InstallerSpec, PolicyImage field swap, schema_version bump)
- `src/containerizer/analyze/reader.py` — Task 2 (new `InstallInputs` dataclass + `read_install_inputs` helper)
- `src/containerizer/trace/runner.py` — Task 3 (`_materialize_installers_file`, `_materialize_apt_keys_file`; both called from `run()`)
- `src/containerizer/analyze/derive.py` — Task 4 (`derive_policy` accepts `install_inputs`; new `_build_installer_spec` + `_post_install_cleanup_for`)
- `src/containerizer/generate/containerfile.py` — Task 5 (dispatch on `kind`; new `_render_deb` and `_render_executable`)
- `src/containerizer/build/pipeline.py` — Task 6 (new `_stage_install_inputs`; calls `read_install_inputs` to build `InstallInputs` and passes to `derive_policy_fn`; new staging phase between generate and build)
- `src/containerizer/build/cli.py` — Task 6 (update `_default_derive_policy_fn` to pass `install_inputs`)
- `src/containerizer/analyze/cli.py` — Task 7 (standalone analyze calls `read_install_inputs` and passes to `derive_policy`)

**Modified — tests:**
- `tests/unit/analyze/test_schema.py` — Task 1 (new InstallerSpec roundtrip tests; schema_version assertion update)
- `tests/unit/analyze/test_derive.py` — Task 4 (replace `installer_path` assertions with InstallerSpec; new deb-case tests)
- `tests/unit/trace/test_runner.py` — Task 3 (INSTALLERS + APT_KEYS materializer tests)
- `tests/unit/generate/test_containerfile.py` — Task 5 (deb-rendering tests; update existing tests to construct policy with InstallerSpec)
- `tests/unit/build/test_pipeline.py` — Task 6 (`_stage_install_inputs` tests)
- `tests/integration/build/test_build_smoke.py` — Task 6 (smoke test must construct `BuildConfig` with the executable installer; fake derive must accept `install_inputs` kwarg)

**Not modified:** `src/containerizer/build/config.py` (BuildConfig already has the right fields), `src/containerizer/build/paths.py`, `src/containerizer/generate/cli.py`, `src/containerizer/generate/orchestrator.py`, `src/containerizer/generate/quadlet.py`, `src/containerizer/generate/readme.py`, `src/containerizer/generate/seccomp.py`.

---

## Task 1: Schema — discriminated `InstallerSpec` on `PolicyImage`

**Files:**
- Modify: `src/containerizer/analyze/schema.py`
- Test: `tests/unit/analyze/test_schema.py`

- [ ] **Step 1: Write failing tests for the new schema**

Append to `tests/unit/analyze/test_schema.py`:

```python
import json

import pytest
from pydantic import ValidationError

from containerizer.analyze.schema import (
    DebInstaller,
    ExecutableInstaller,
    PolicyImage,
    PolicyJson,
    PolicyRuntime,
)


def _runtime() -> PolicyRuntime:
    return PolicyRuntime(
        volumes=[],
        tmpfs=[],
        binds_ro=[],
        publish_ports=[],
        caps_add=[],
        seccomp_syscalls=[],
        read_only_rootfs=False,
    )


def test_policy_schema_version_is_three() -> None:
    policy = PolicyJson(
        image=PolicyImage(
            base="ubuntu:24.04",
            installer=ExecutableInstaller(path="/installer"),
            post_install_cleanup=[],
            systemd_required=False,
            entrypoint=["/x"],
        ),
        runtime=_runtime(),
    )
    assert policy.schema_version == 3


def test_executable_installer_roundtrips_via_json() -> None:
    policy = PolicyJson(
        image=PolicyImage(
            base="ubuntu:24.04",
            installer=ExecutableInstaller(path="/installer"),
            post_install_cleanup=[],
            systemd_required=False,
            entrypoint=["/x"],
        ),
        runtime=_runtime(),
    )
    blob = policy.model_dump_json()
    back = PolicyJson.model_validate_json(blob)
    assert isinstance(back.image.installer, ExecutableInstaller)
    assert back.image.installer.path == "/installer"


def test_deb_installer_roundtrips_via_json() -> None:
    policy = PolicyJson(
        image=PolicyImage(
            base="ubuntu:24.04",
            installer=DebInstaller(paths=["/tmp/foo.deb", "/tmp/bar.deb"]),
            apt_sources=["deb http://example/x noble main"],
            apt_keys=["example.gpg"],
            post_install_cleanup=["/tmp/*.deb"],
            systemd_required=False,
            entrypoint=["/x"],
        ),
        runtime=_runtime(),
    )
    blob = policy.model_dump_json()
    back = PolicyJson.model_validate_json(blob)
    assert isinstance(back.image.installer, DebInstaller)
    assert back.image.installer.paths == ["/tmp/foo.deb", "/tmp/bar.deb"]
    assert back.image.apt_sources == ["deb http://example/x noble main"]
    assert back.image.apt_keys == ["example.gpg"]


def test_installer_path_field_is_rejected() -> None:
    """The legacy installer_path field is gone; extra='forbid' rejects it."""
    raw = json.dumps(
        {
            "schema_version": 3,
            "image": {
                "base": "ubuntu:24.04",
                "installer_path": "/installer",
                "apt_packages": [],
                "post_install_cleanup": [],
                "systemd_required": False,
                "entrypoint": ["/x"],
            },
            "runtime": {
                "volumes": [],
                "tmpfs": [],
                "binds_ro": [],
                "publish_ports": [],
                "caps_add": [],
                "caps_drop": ["ALL"],
                "seccomp_syscalls": [],
                "read_only_rootfs": False,
                "no_new_privileges": True,
            },
            "warnings": [],
        }
    )
    with pytest.raises(ValidationError):
        PolicyJson.model_validate_json(raw)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/unit/analyze/test_schema.py -v
```

Expected: `ImportError: cannot import name 'DebInstaller'` (or similar) — the new types don't exist yet.

- [ ] **Step 3: Update the schema**

Replace the `PolicyImage` block and `PolicyJson.schema_version` in `src/containerizer/analyze/schema.py`. Add `Annotated` import.

Replace this:

```python
class PolicyImage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    base: str
    apt_packages: list[str]
    installer_path: str = "/installer"
    post_install_cleanup: list[str]
    systemd_required: bool
    entrypoint: list[str]
```

…with:

```python
class DebInstaller(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["deb"] = "deb"
    paths: list[str]


class ExecutableInstaller(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["executable"] = "executable"
    path: str = "/installer"


InstallerSpec = Annotated[
    DebInstaller | ExecutableInstaller,
    Field(discriminator="kind"),
]


class PolicyImage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    base: str
    installer: InstallerSpec
    apt_sources: list[str] = []
    apt_keys: list[str] = []
    apt_packages: list[str] = []
    post_install_cleanup: list[str]
    systemd_required: bool
    entrypoint: list[str]
```

Update the import line at the top of the file from:

```python
from typing import Literal
```

…to:

```python
from typing import Annotated, Literal
```

Update `PolicyJson.schema_version` literal from `Literal[2] = 2` to `Literal[3] = 3`.

- [ ] **Step 4: Run schema tests to verify they pass**

```bash
python -m pytest tests/unit/analyze/test_schema.py -v
```

Expected: All four new tests pass. Other tests in the file may now fail because they construct `PolicyImage(installer_path=...)` — that's fine, Tasks 4/5 will fix those callers.

- [ ] **Step 5: Commit**

```bash
git add src/containerizer/analyze/schema.py tests/unit/analyze/test_schema.py
git -c user.email="github.v5f9w@bitbucket.onl" -c user.signingkey=BE707B220C995478 commit -S -m "feat(schema): discriminated InstallerSpec on PolicyImage (#111)

Replace installer_path: str with installer: DebInstaller|ExecutableInstaller.
Add apt_sources, apt_keys fields. Bump policy schema_version 2 -> 3.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

Expected: signed commit lands. Pre-commit gate not run in this task (the rest of the codebase still references `installer_path`); end-of-feature task runs the full gate.

---

## Task 2: Reader — `InstallInputs` + `read_install_inputs`

**Files:**
- Modify: `src/containerizer/analyze/reader.py`
- Create: `tests/unit/analyze/test_reader_install_inputs.py`

- [ ] **Step 1: Write failing tests**

Create `tests/unit/analyze/test_reader_install_inputs.py`:

```python
"""Tests for analyze.reader.read_install_inputs."""

from __future__ import annotations

from pathlib import Path

from containerizer.analyze.reader import InstallInputs, read_install_inputs


def test_empty_trace_dir_returns_empty_install_inputs(tmp_path: Path) -> None:
    assert read_install_inputs(tmp_path) == InstallInputs()


def test_installers_file_read_as_basenames_in_order(tmp_path: Path) -> None:
    (tmp_path / "INSTALLERS").write_text(
        "unifi_sysvinit_all.deb\nmongodb-org-server_8.0.26_amd64.deb\n",
        encoding="utf-8",
    )
    out = read_install_inputs(tmp_path)
    assert out.installers == (
        "unifi_sysvinit_all.deb",
        "mongodb-org-server_8.0.26_amd64.deb",
    )


def test_apt_sources_file_read_verbatim(tmp_path: Path) -> None:
    (tmp_path / "apt-sources.list").write_text(
        "deb http://example/x noble main\ndeb http://example/y noble main\n",
        encoding="utf-8",
    )
    out = read_install_inputs(tmp_path)
    assert out.apt_sources == (
        "deb http://example/x noble main",
        "deb http://example/y noble main",
    )


def test_apt_keys_file_read_as_basenames(tmp_path: Path) -> None:
    (tmp_path / "APT_KEYS").write_text("mongodb.gpg\nexample.asc\n", encoding="utf-8")
    out = read_install_inputs(tmp_path)
    assert out.apt_keys == ("mongodb.gpg", "example.asc")


def test_blank_lines_are_skipped(tmp_path: Path) -> None:
    (tmp_path / "INSTALLERS").write_text("a.deb\n\nb.deb\n", encoding="utf-8")
    out = read_install_inputs(tmp_path)
    assert out.installers == ("a.deb", "b.deb")


def test_inputs_dataclass_is_immutable() -> None:
    import dataclasses

    inputs = InstallInputs(installers=("a.deb",))
    assert dataclasses.is_dataclass(inputs)
    # frozen=True means fields can't be reassigned.
    try:
        inputs.installers = ("b.deb",)  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        return
    raise AssertionError("InstallInputs should be frozen")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/unit/analyze/test_reader_install_inputs.py -v
```

Expected: `ImportError: cannot import name 'InstallInputs'` or `'read_install_inputs'`.

- [ ] **Step 3: Implement `InstallInputs` + `read_install_inputs`**

Append to `src/containerizer/analyze/reader.py` (after the existing `read_trace_dir` function):

```python
@dataclass(frozen=True)
class InstallInputs:
    """User-supplied install-time inputs surfaced from trace-dir marker files."""

    installers: tuple[str, ...] = ()
    apt_sources: tuple[str, ...] = ()
    apt_keys: tuple[str, ...] = ()


def read_install_inputs(trace_dir: Path) -> InstallInputs:
    """Read INSTALLERS / apt-sources.list / APT_KEYS marker files.

    All three files are optional; missing files yield empty tuples.
    Blank lines are skipped.
    """
    return InstallInputs(
        installers=_read_lines(trace_dir / "INSTALLERS"),
        apt_sources=_read_lines(trace_dir / "apt-sources.list"),
        apt_keys=_read_lines(trace_dir / "APT_KEYS"),
    )


def _read_lines(path: Path) -> tuple[str, ...]:
    if not path.exists():
        return ()
    return tuple(
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/unit/analyze/test_reader_install_inputs.py -v
```

Expected: All six tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/containerizer/analyze/reader.py tests/unit/analyze/test_reader_install_inputs.py
git -c user.email="github.v5f9w@bitbucket.onl" -c user.signingkey=BE707B220C995478 commit -S -m "feat(analyze): read_install_inputs surfaces trace-dir markers (#111)

New InstallInputs dataclass + reader for INSTALLERS / apt-sources.list /
APT_KEYS. Threaded into derive_policy in a later commit.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 3: Trace runner — write `INSTALLERS` + `APT_KEYS` markers

**Files:**
- Modify: `src/containerizer/trace/runner.py`
- Test: `tests/unit/trace/test_runner.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/unit/trace/test_runner.py`:

```python
def test_run_materializes_installers_file(tmp_path: Path, monkeypatch) -> None:
    """INSTALLERS lists primary basename first, then extras."""
    primary = tmp_path / "primary.deb"
    primary.write_text("x", encoding="utf-8")
    extra = tmp_path / "extra.deb"
    extra.write_text("x", encoding="utf-8")
    out = tmp_path / "trace"
    out.mkdir()

    runner = TraceRunner(
        image_tag="test:tag",
        installer=primary,
        output_dir=out,
        extra_installers=(extra,),
    )

    def _no_op(argv, check=False):  # noqa: ARG001
        class _R:
            returncode = 0

        return _R()

    monkeypatch.setattr("containerizer.trace.runner.subprocess.run", _no_op)
    runner.run()

    text = (out / "INSTALLERS").read_text(encoding="utf-8")
    assert text == "primary.deb\nextra.deb\n"


def test_run_materializes_apt_keys_file(tmp_path: Path, monkeypatch) -> None:
    primary = tmp_path / "primary.deb"
    primary.write_text("x", encoding="utf-8")
    key = tmp_path / "mongodb.gpg"
    key.write_text("x", encoding="utf-8")
    out = tmp_path / "trace"
    out.mkdir()

    runner = TraceRunner(
        image_tag="test:tag",
        installer=primary,
        output_dir=out,
        apt_keys=(key,),
    )

    def _no_op(argv, check=False):  # noqa: ARG001
        class _R:
            returncode = 0

        return _R()

    monkeypatch.setattr("containerizer.trace.runner.subprocess.run", _no_op)
    runner.run()

    assert (out / "APT_KEYS").read_text(encoding="utf-8") == "mongodb.gpg\n"


def test_run_does_not_write_apt_keys_file_when_none(tmp_path: Path, monkeypatch) -> None:
    primary = tmp_path / "primary.deb"
    primary.write_text("x", encoding="utf-8")
    out = tmp_path / "trace"
    out.mkdir()

    runner = TraceRunner(
        image_tag="test:tag",
        installer=primary,
        output_dir=out,
    )

    def _no_op(argv, check=False):  # noqa: ARG001
        class _R:
            returncode = 0

        return _R()

    monkeypatch.setattr("containerizer.trace.runner.subprocess.run", _no_op)
    runner.run()

    assert not (out / "APT_KEYS").exists()
    # INSTALLERS still written (primary only).
    assert (out / "INSTALLERS").read_text(encoding="utf-8") == "primary.deb\n"
```

If the test file doesn't already import `TraceRunner` and `Path`, add the imports at the top:

```python
from pathlib import Path

from containerizer.trace.runner import TraceRunner
```

(Skip if already present.)

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/unit/trace/test_runner.py::test_run_materializes_installers_file tests/unit/trace/test_runner.py::test_run_materializes_apt_keys_file tests/unit/trace/test_runner.py::test_run_does_not_write_apt_keys_file_when_none -v
```

Expected: `INSTALLERS` / `APT_KEYS` files not written.

- [ ] **Step 3: Add materializers and wire into `run()`**

In `src/containerizer/trace/runner.py`, add two methods alongside the existing `_materialize_apt_sources_file` and `_materialize_start_cmd_file`:

```python
def _materialize_installers_file(self) -> None:
    """Write INSTALLERS marker (one basename per line, primary first).
    Install mode only; verify mode has installer=None."""
    if self.installer is None:
        return
    target = self.output_dir / "INSTALLERS"
    target.parent.mkdir(parents=True, exist_ok=True)
    lines = [self.installer.name] + [p.name for p in self.extra_installers]
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")

def _materialize_apt_keys_file(self) -> None:
    """Write APT_KEYS marker (one basename per line). No-op when empty."""
    if not self.apt_keys:
        return
    target = self.output_dir / "APT_KEYS"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "\n".join(k.name for k in self.apt_keys) + "\n",
        encoding="utf-8",
    )
```

Update `run()` to call them. Replace this block:

```python
def run(self) -> int:
    """Exec the podman command in the foreground."""
    self._materialize_apt_sources_file()
    self._materialize_start_cmd_file()
    result = subprocess.run(self.argv(), check=False)
    return result.returncode
```

…with:

```python
def run(self) -> int:
    """Exec the podman command in the foreground."""
    self._materialize_apt_sources_file()
    self._materialize_start_cmd_file()
    self._materialize_installers_file()
    self._materialize_apt_keys_file()
    result = subprocess.run(self.argv(), check=False)
    return result.returncode
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/unit/trace/test_runner.py -v
```

Expected: all three new tests pass; existing tests in the file also pass (no behavior change to existing methods).

- [ ] **Step 5: Commit**

```bash
git add src/containerizer/trace/runner.py tests/unit/trace/test_runner.py
git -c user.email="github.v5f9w@bitbucket.onl" -c user.signingkey=BE707B220C995478 commit -S -m "feat(trace): write INSTALLERS and APT_KEYS marker files (#111)

Trace runner now persists installer-basenames and apt-key-basenames into
the trace dir alongside the existing apt-sources.list / START_CMD files.
analyze reads them via read_install_inputs.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 4: Derive — accept `install_inputs`, build `InstallerSpec`

**Files:**
- Modify: `src/containerizer/analyze/derive.py`
- Modify: `tests/unit/analyze/test_derive.py`

- [ ] **Step 1: Update existing test for new shape, add deb-case tests**

In `tests/unit/analyze/test_derive.py`, replace `test_conservative_defaults_in_minimal_trace`:

```python
def test_conservative_defaults_in_minimal_trace() -> None:
    policy = derive_policy(_make_trace())
    assert policy.image.apt_packages == []
    assert isinstance(policy.image.installer, ExecutableInstaller)
    assert policy.image.installer.path == "/installer"
    assert policy.image.post_install_cleanup == ["/var/cache/apt/archives/*", "/installer"]
    assert policy.image.apt_sources == []
    assert policy.image.apt_keys == []
    assert policy.runtime.read_only_rootfs is False
    assert policy.runtime.no_new_privileges is True
    assert policy.runtime.caps_drop == ["ALL"]
```

Add the import at the top of the file:

```python
from containerizer.analyze.reader import InstallInputs
from containerizer.analyze.schema import (
    DebInstaller,
    ExecutableInstaller,
    TraceJson,
    TracePath,
    TracePhase,
    TracePort,
)
```

(Replace the existing `from containerizer.analyze.schema import (...)` block with the expanded one above.)

Append these new tests at the end of the file:

```python
def test_derive_installer_deb_single() -> None:
    inputs = InstallInputs(installers=("foo.deb",))
    policy = derive_policy(_make_trace(), install_inputs=inputs)
    assert isinstance(policy.image.installer, DebInstaller)
    assert policy.image.installer.paths == ["/tmp/foo.deb"]


def test_derive_installer_deb_multi() -> None:
    inputs = InstallInputs(
        installers=("primary.deb", "extra1.deb", "extra2.deb"),
    )
    policy = derive_policy(_make_trace(), install_inputs=inputs)
    assert isinstance(policy.image.installer, DebInstaller)
    assert policy.image.installer.paths == [
        "/tmp/primary.deb",
        "/tmp/extra1.deb",
        "/tmp/extra2.deb",
    ]


def test_derive_installer_executable_when_primary_not_deb() -> None:
    inputs = InstallInputs(installers=("unifi-installer.bin",))
    policy = derive_policy(_make_trace(), install_inputs=inputs)
    assert isinstance(policy.image.installer, ExecutableInstaller)
    assert policy.image.installer.path == "/installer"


def test_derive_apt_sources_propagated() -> None:
    inputs = InstallInputs(
        installers=("foo.deb",),
        apt_sources=("deb http://example/x noble main",),
    )
    policy = derive_policy(_make_trace(), install_inputs=inputs)
    assert policy.image.apt_sources == ["deb http://example/x noble main"]


def test_derive_apt_keys_propagated_as_basenames() -> None:
    inputs = InstallInputs(
        installers=("foo.deb",),
        apt_keys=("mongodb.gpg", "extra.asc"),
    )
    policy = derive_policy(_make_trace(), install_inputs=inputs)
    assert policy.image.apt_keys == ["mongodb.gpg", "extra.asc"]


def test_derive_post_install_cleanup_for_deb() -> None:
    inputs = InstallInputs(installers=("foo.deb",))
    policy = derive_policy(_make_trace(), install_inputs=inputs)
    assert policy.image.post_install_cleanup == [
        "/tmp/*.deb",
        "/var/lib/apt/lists/*",
        "/var/cache/apt/archives/*",
    ]


def test_derive_no_install_inputs_falls_back_to_executable() -> None:
    """Backwards-compatible: derive_policy() with no install_inputs
    behaves as today (sentinel single-executable shape)."""
    policy = derive_policy(_make_trace())
    assert isinstance(policy.image.installer, ExecutableInstaller)
    assert policy.image.installer.path == "/installer"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/unit/analyze/test_derive.py -v
```

Expected: all the new tests fail with `TypeError: derive_policy() got an unexpected keyword argument 'install_inputs'`, and the updated `test_conservative_defaults_in_minimal_trace` fails because `installer_path` is gone.

- [ ] **Step 3: Update `derive_policy` to accept `install_inputs`**

In `src/containerizer/analyze/derive.py`, update the imports:

```python
from containerizer.analyze.reader import InstallInputs
from containerizer.analyze.schema import (
    DebInstaller,
    ExecutableInstaller,
    InstallerSpec,
    PolicyImage,
    PolicyJson,
    PolicyPort,
    PolicyRuntime,
    PolicyVolume,
    TraceJson,
    TracePath,
)
```

Replace the `derive_policy` signature + the `PolicyImage(...)` construction:

```python
def derive_policy(
    trace: TraceJson,
    *,
    install_inputs: InstallInputs | None = None,
    probe_base: str = "ubuntu:24.04",
    warnings: list[str] | None = None,
) -> PolicyJson:
    """Turn a normalized TraceJson into a PolicyJson the M4 generator can consume."""
    runtime = trace.runtime

    # Volumes from persistent_rw paths. Disambiguate name collisions by
    # prepending the parent's leaf component.
    persistent = [p for p in runtime.paths if p.class_ == "persistent_rw"]
    volumes = _derive_volumes(persistent)

    tmpfs = sorted({p.path for p in runtime.paths if p.class_ == "ephemeral_rw"})
    binds_ro = sorted({p.path for p in runtime.paths if p.class_ == "host_config_ro"})

    publish_ports = [
        PolicyPort(host=p.port, container=p.port, proto=p.proto)
        for p in runtime.ports
        if p.proto in ("tcp", "udp")
    ]

    systemd_required = systemd_required_for(trace)
    start_cmd = trace.start_cmd or None

    final_warnings: list[str] = list(warnings or [])
    if systemd_required:
        entrypoint = ["/sbin/init"]
        if start_cmd:
            final_warnings.append(
                "start_cmd ignored: systemd detected as required; using /sbin/init as entrypoint"
            )
    elif start_cmd:
        entrypoint = ["bash", "-c", start_cmd]
    else:
        entrypoint = [SENTINEL_ENTRYPOINT]

    installer = _build_installer_spec(install_inputs)
    apt_sources = list(install_inputs.apt_sources) if install_inputs else []
    apt_keys = list(install_inputs.apt_keys) if install_inputs else []

    return PolicyJson(
        image=PolicyImage(
            base=probe_base,
            installer=installer,
            apt_sources=apt_sources,
            apt_keys=apt_keys,
            apt_packages=[],
            post_install_cleanup=_post_install_cleanup_for(installer),
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


def _build_installer_spec(install_inputs: InstallInputs | None) -> InstallerSpec:
    """Decide DebInstaller vs ExecutableInstaller from the markers.

    Rule: if installers is empty (no markers), legacy single-executable
    shape. If the primary basename ends in '.deb', treat all as .deb
    (CLI's _validate_multi_deb_flags already ensures extras are .deb).
    Otherwise, single executable at /installer.
    """
    if install_inputs is None or not install_inputs.installers:
        return ExecutableInstaller(path="/installer")
    primary = install_inputs.installers[0]
    if primary.endswith(".deb"):
        paths = [f"/tmp/{name}" for name in install_inputs.installers]
        return DebInstaller(paths=paths)
    return ExecutableInstaller(path="/installer")


def _post_install_cleanup_for(installer: InstallerSpec) -> list[str]:
    if isinstance(installer, DebInstaller):
        return ["/tmp/*.deb", "/var/lib/apt/lists/*", "/var/cache/apt/archives/*"]
    return ["/var/cache/apt/archives/*", "/installer"]
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/unit/analyze/test_derive.py -v
```

Expected: all derive tests pass (existing + new).

- [ ] **Step 5: Commit**

```bash
git add src/containerizer/analyze/derive.py tests/unit/analyze/test_derive.py
git -c user.email="github.v5f9w@bitbucket.onl" -c user.signingkey=BE707B220C995478 commit -S -m "feat(analyze): derive InstallerSpec + apt fields from install_inputs (#111)

derive_policy now takes an optional InstallInputs kwarg and builds either
a DebInstaller (when primary basename ends in .deb) or an
ExecutableInstaller (legacy default). apt_sources and apt_keys propagate
into PolicyImage; post_install_cleanup branches on installer kind.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 5: Renderer — dispatch on `kind`, emit deb-flavored Containerfile

**Files:**
- Modify: `src/containerizer/generate/containerfile.py`
- Modify: `tests/unit/generate/test_containerfile.py`

- [ ] **Step 1: Update existing tests + add deb-case tests**

In `tests/unit/generate/test_containerfile.py`, replace the entire file with:

```python
"""Tests for containerizer.generate.containerfile."""

from __future__ import annotations

from containerizer.analyze.schema import (
    DebInstaller,
    ExecutableInstaller,
    InstallerSpec,
    PolicyImage,
    PolicyJson,
    PolicyRuntime,
)
from containerizer.generate.containerfile import render_containerfile


def _policy(
    *,
    systemd_required: bool,
    entrypoint: list[str],
    installer: InstallerSpec | None = None,
    apt_sources: list[str] | None = None,
    apt_keys: list[str] | None = None,
    cleanup: list[str] | None = None,
) -> PolicyJson:
    return PolicyJson(
        image=PolicyImage(
            base="ubuntu:24.04",
            installer=installer or ExecutableInstaller(path="/installer"),
            apt_sources=apt_sources or [],
            apt_keys=apt_keys or [],
            post_install_cleanup=cleanup or [],
            systemd_required=systemd_required,
            entrypoint=entrypoint,
        ),
        runtime=PolicyRuntime(
            volumes=[],
            tmpfs=[],
            binds_ro=[],
            publish_ports=[],
            caps_add=[],
            seccomp_syscalls=[],
            read_only_rootfs=False,
        ),
    )


# --- Executable installer (legacy path) ---


def test_containerfile_executable_minimal() -> None:
    text = render_containerfile(
        _policy(
            systemd_required=False,
            entrypoint=["/opt/app/bin/app", "--config", "/etc/app.conf"],
        )
    )
    assert text.startswith("FROM ubuntu:24.04\n")
    assert "COPY ./installer /installer\n" in text
    assert "RUN /installer" in text
    assert 'ENTRYPOINT ["/opt/app/bin/app", "--config", "/etc/app.conf"]\n' in text


def test_containerfile_executable_systemd_entrypoint_overrides_argv() -> None:
    text = render_containerfile(_policy(systemd_required=True, entrypoint=["/opt/app/bin/app"]))
    assert 'ENTRYPOINT ["/sbin/init"]\n' in text
    assert "/opt/app/bin/app" not in text


def test_containerfile_executable_cleanup_lines_appended_to_run() -> None:
    text = render_containerfile(
        _policy(
            systemd_required=False,
            entrypoint=["/x"],
            cleanup=["/var/cache/apt/archives/*", "/installer"],
        )
    )
    assert (
        "RUN /installer \\\n && rm -rf /var/cache/apt/archives/* \\\n && rm -rf /installer\n"
        in text
    )


def test_containerfile_ends_with_trailing_newline() -> None:
    text = render_containerfile(_policy(systemd_required=False, entrypoint=["/x"]))
    assert text.endswith("\n")


# --- Deb installer (new path) ---


def test_containerfile_deb_single() -> None:
    text = render_containerfile(
        _policy(
            systemd_required=False,
            entrypoint=["/usr/sbin/foo"],
            installer=DebInstaller(paths=["/tmp/foo.deb"]),
            cleanup=["/tmp/*.deb", "/var/lib/apt/lists/*", "/var/cache/apt/archives/*"],
        )
    )
    assert text.startswith("FROM ubuntu:24.04\n")
    assert "ENV DEBIAN_FRONTEND=noninteractive\n" in text
    assert "COPY ./installers/foo.deb /tmp/foo.deb\n" in text
    assert "apt-get install -y --no-install-recommends" in text
    assert "/tmp/foo.deb" in text
    assert "rm -rf /tmp/*.deb /var/lib/apt/lists/* /var/cache/apt/archives/*" in text
    assert 'ENTRYPOINT ["/usr/sbin/foo"]\n' in text
    # No COPY ./installer for the deb path.
    assert "COPY ./installer /installer" not in text


def test_containerfile_deb_multi_with_apt_source_and_key() -> None:
    text = render_containerfile(
        _policy(
            systemd_required=False,
            entrypoint=["/usr/bin/unifi-start"],
            installer=DebInstaller(
                paths=[
                    "/tmp/unifi_sysvinit_all.deb",
                    "/tmp/mongodb-org-server_8.0.26_amd64.deb",
                ],
            ),
            apt_sources=[
                "deb [signed-by=/etc/apt/keyrings/mongodb.gpg] "
                "https://repo.mongodb.org/apt/ubuntu noble/mongodb-org/8.0 multiverse"
            ],
            apt_keys=["mongodb.gpg"],
            cleanup=["/tmp/*.deb", "/var/lib/apt/lists/*", "/var/cache/apt/archives/*"],
        )
    )
    assert "COPY ./apt-keys/mongodb.gpg /etc/apt/keyrings/mongodb.gpg\n" in text
    assert (
        "deb [signed-by=/etc/apt/keyrings/mongodb.gpg] "
        "https://repo.mongodb.org/apt/ubuntu noble/mongodb-org/8.0 multiverse"
    ) in text
    assert "COPY ./installers/unifi_sysvinit_all.deb /tmp/unifi_sysvinit_all.deb\n" in text
    assert (
        "COPY ./installers/mongodb-org-server_8.0.26_amd64.deb "
        "/tmp/mongodb-org-server_8.0.26_amd64.deb\n"
    ) in text
    # Both .debs in the apt-get install line.
    assert "/tmp/unifi_sysvinit_all.deb" in text
    assert "/tmp/mongodb-org-server_8.0.26_amd64.deb" in text


def test_containerfile_deb_apt_source_without_key() -> None:
    text = render_containerfile(
        _policy(
            systemd_required=False,
            entrypoint=["/x"],
            installer=DebInstaller(paths=["/tmp/foo.deb"]),
            apt_sources=["deb http://example/x noble main"],
            cleanup=["/tmp/*.deb"],
        )
    )
    # Sources are present.
    assert "deb http://example/x noble main" in text
    # No apt-keys COPY block.
    assert "COPY ./apt-keys/" not in text


def test_containerfile_deb_no_sources_no_keys() -> None:
    text = render_containerfile(
        _policy(
            systemd_required=False,
            entrypoint=["/x"],
            installer=DebInstaller(paths=["/tmp/foo.deb"]),
            cleanup=["/tmp/*.deb"],
        )
    )
    # No sources block, no keys block.
    assert "/etc/apt/sources.list.d/containerizer.list" not in text
    assert "COPY ./apt-keys/" not in text
    # apt-get install still runs.
    assert "apt-get install -y --no-install-recommends \\\n      /tmp/foo.deb" in text


def test_containerfile_deb_systemd_uses_sbin_init_entrypoint() -> None:
    text = render_containerfile(
        _policy(
            systemd_required=True,
            entrypoint=["/usr/sbin/whatever"],
            installer=DebInstaller(paths=["/tmp/foo.deb"]),
            cleanup=["/tmp/*.deb"],
        )
    )
    assert 'ENTRYPOINT ["/sbin/init"]\n' in text
    assert "/usr/sbin/whatever" not in text
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/unit/generate/test_containerfile.py -v
```

Expected: deb-case tests fail (`COPY ./apt-keys/...` not in text), and existing executable tests now pass because the `_policy` helper constructs the new shape.

- [ ] **Step 3: Implement renderer dispatch**

Replace the entire body of `src/containerizer/generate/containerfile.py`:

```python
"""Render PolicyJson into a Containerfile."""

from __future__ import annotations

import json

from containerizer.analyze.schema import DebInstaller, PolicyJson


def render_containerfile(policy: PolicyJson) -> str:
    """Render the policy as a Containerfile string with trailing newline.

    Dispatches on installer.kind: DebInstaller emits an apt-install layer
    that copies the .debs and any apt-keys/apt-sources; ExecutableInstaller
    emits the legacy single-executable RUN line.

    Sentinel-entrypoint policies are filtered upstream by cli.py — this
    function assumes a real entrypoint.
    """
    if isinstance(policy.image.installer, DebInstaller):
        return _render_deb(policy)
    return _render_executable(policy)


def _render_executable(policy: PolicyJson) -> str:
    lines: list[str] = [
        f"FROM {policy.image.base}",
        "",
        "COPY ./installer /installer",
        "",
    ]
    run_parts = ["RUN /installer"]
    for path in policy.image.post_install_cleanup:
        run_parts.append(f" && rm -rf {path}")
    lines.append(" \\\n".join(run_parts))
    lines.append("")
    lines.append(_entrypoint_line(policy))
    return "\n".join(lines) + "\n"


def _render_deb(policy: PolicyJson) -> str:
    assert isinstance(policy.image.installer, DebInstaller)  # for type narrowing
    image = policy.image
    deb_paths = image.installer.paths

    lines: list[str] = [
        f"FROM {image.base}",
        "ENV DEBIAN_FRONTEND=noninteractive",
        "",
    ]

    # apt-keys block (only when keys are present).
    if image.apt_keys:
        for key in image.apt_keys:
            lines.append(f"COPY ./apt-keys/{key} /etc/apt/keyrings/{key}")
        lines.append("")

    # sources block (only when sources are present).
    if image.apt_sources:
        sources_body = "\n".join(image.apt_sources)
        lines.append(
            "RUN install -d /etc/apt/sources.list.d \\\n"
            " && cat > /etc/apt/sources.list.d/containerizer.list <<'EOF'\n"
            f"{sources_body}\n"
            "EOF"
        )
        lines.append("")

    # Each .deb gets its own COPY line.
    for deb_path in deb_paths:
        basename = deb_path.rsplit("/", 1)[-1]
        lines.append(f"COPY ./installers/{basename} {deb_path}")
    lines.append("")

    # apt-get update && install + cleanup.
    install_target_lines = " \\\n      ".join(deb_paths)
    cleanup = " ".join(policy.image.post_install_cleanup)
    lines.append(
        "RUN set -eux \\\n"
        " && apt-get update \\\n"
        " && apt-get install -y --no-install-recommends \\\n"
        f"      {install_target_lines} \\\n"
        f" && rm -rf {cleanup}"
    )
    lines.append("")

    lines.append(_entrypoint_line(policy))
    return "\n".join(lines) + "\n"


def _entrypoint_line(policy: PolicyJson) -> str:
    entrypoint = (
        ["/sbin/init"] if policy.image.systemd_required else list(policy.image.entrypoint)
    )
    return f"ENTRYPOINT {json.dumps(entrypoint)}"
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/unit/generate/test_containerfile.py -v
```

Expected: all tests (legacy + new deb) pass.

- [ ] **Step 5: Commit**

```bash
git add src/containerizer/generate/containerfile.py tests/unit/generate/test_containerfile.py
git -c user.email="github.v5f9w@bitbucket.onl" -c user.signingkey=BE707B220C995478 commit -S -m "feat(generate): render deb-install layer when policy.installer.kind=deb (#111)

render_containerfile now dispatches on the discriminated InstallerSpec.
DebInstaller emits COPY apt-keys -> write sources.list.d -> COPY .debs
-> apt-get update && install --no-install-recommends -> cleanup.
ExecutableInstaller path is byte-identical to the prior renderer.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 6: Build pipeline — stage files into `final_dir/`, thread `install_inputs`

**Files:**
- Modify: `src/containerizer/build/pipeline.py`
- Modify: `src/containerizer/build/cli.py`
- Modify: `tests/unit/build/test_pipeline.py`
- Modify: `tests/integration/build/test_build_smoke.py`

- [ ] **Step 1: Write failing tests for `_stage_install_inputs`**

Append to `tests/unit/build/test_pipeline.py`:

```python
from pathlib import Path

from containerizer.build.pipeline import _stage_install_inputs


def test_stage_install_inputs_executable_copies_to_installer(tmp_path: Path) -> None:
    primary = tmp_path / "src" / "primary.bin"
    primary.parent.mkdir()
    primary.write_text("X", encoding="utf-8")
    final = tmp_path / "final"
    final.mkdir()

    _stage_install_inputs(
        final_dir=final,
        installer=primary,
        extra_installers=(),
        apt_keys=(),
    )

    assert (final / "installer").read_text(encoding="utf-8") == "X"
    assert not (final / "installers").exists()
    assert not (final / "apt-keys").exists()


def test_stage_install_inputs_deb_copies_to_installers_subdir(tmp_path: Path) -> None:
    primary = tmp_path / "src" / "foo.deb"
    primary.parent.mkdir()
    primary.write_text("DEB", encoding="utf-8")
    extra = tmp_path / "src" / "bar.deb"
    extra.write_text("EXTRA", encoding="utf-8")
    final = tmp_path / "final"
    final.mkdir()

    _stage_install_inputs(
        final_dir=final,
        installer=primary,
        extra_installers=(extra,),
        apt_keys=(),
    )

    assert (final / "installers" / "foo.deb").read_text(encoding="utf-8") == "DEB"
    assert (final / "installers" / "bar.deb").read_text(encoding="utf-8") == "EXTRA"
    assert not (final / "installer").exists()


def test_stage_install_inputs_apt_keys_copied_to_subdir(tmp_path: Path) -> None:
    primary = tmp_path / "src" / "foo.deb"
    primary.parent.mkdir()
    primary.write_text("DEB", encoding="utf-8")
    key = tmp_path / "src" / "mongodb.gpg"
    key.write_text("KEY", encoding="utf-8")
    final = tmp_path / "final"
    final.mkdir()

    _stage_install_inputs(
        final_dir=final,
        installer=primary,
        extra_installers=(),
        apt_keys=(key,),
    )

    assert (final / "apt-keys" / "mongodb.gpg").read_text(encoding="utf-8") == "KEY"


def test_stage_install_inputs_no_apt_keys_skips_keys_subdir(tmp_path: Path) -> None:
    primary = tmp_path / "src" / "foo.bin"
    primary.parent.mkdir()
    primary.write_text("X", encoding="utf-8")
    final = tmp_path / "final"
    final.mkdir()

    _stage_install_inputs(
        final_dir=final,
        installer=primary,
        extra_installers=(),
        apt_keys=(),
    )

    assert not (final / "apt-keys").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/unit/build/test_pipeline.py -v
```

Expected: `ImportError: cannot import name '_stage_install_inputs'`.

- [ ] **Step 3: Implement `_stage_install_inputs` and wire into `run_pipeline`**

In `src/containerizer/build/pipeline.py`, add `shutil` to the imports:

```python
import shutil
```

Add the helper near the existing private helpers at the bottom of the file:

```python
def _stage_install_inputs(
    *,
    final_dir: Path,
    installer: Path,
    extra_installers: tuple[Path, ...],
    apt_keys: tuple[Path, ...],
) -> None:
    """Copy installer files and apt-keys into final_dir so the Containerfile's
    COPY lines resolve during podman build.

    Deb / multi-deb path: installers/<name>.deb + apt-keys/<name>.
    Executable path: installer (bare file, matches COPY ./installer).
    """
    final_dir.mkdir(parents=True, exist_ok=True)
    if installer.suffix == ".deb" or extra_installers:
        installers_dir = final_dir / "installers"
        installers_dir.mkdir(exist_ok=True)
        shutil.copy2(installer, installers_dir / installer.name)
        for extra in extra_installers:
            shutil.copy2(extra, installers_dir / extra.name)
    else:
        shutil.copy2(installer, final_dir / "installer")

    if apt_keys:
        keys_dir = final_dir / "apt-keys"
        keys_dir.mkdir(exist_ok=True)
        for key in apt_keys:
            shutil.copy2(key, keys_dir / key.name)
```

Wire it into `run_pipeline` immediately after the `generate_fn(...)` call and before the sentinel check (phase 4a). Insert this block:

```python
    # 4. generate
    ...
    generate_fn(
        policy,
        config.name,
        layout.final_dir,
        install_primary=config.installer,
        ...
    )

    # NEW — stage install inputs into final_dir so podman build can resolve COPY lines.
    _stage_install_inputs(
        final_dir=layout.final_dir,
        installer=config.installer,
        extra_installers=config.extra_installers,
        apt_keys=config.apt_keys,
    )

    # 4a. sentinel
    if policy.image.entrypoint == [SENTINEL_ENTRYPOINT]:
        ...
```

Exact edit: place the new block between line 96 (end of the `generate_fn(...)` call) and the `# 4a. sentinel` comment.

- [ ] **Step 4: Thread `install_inputs` into `derive_policy_fn`**

Update `derive_policy_fn`'s call site in `run_pipeline`. Find:

```python
    policy = derive_policy_fn(original_trace)
```

Replace with:

```python
    install_inputs = read_install_inputs(layout.trace_original_dir)
    policy = derive_policy_fn(original_trace, install_inputs)
```

Update the `derive_policy_fn` type signature near the top of `run_pipeline`:

```python
    derive_policy_fn: Callable[[TraceJson, InstallInputs], PolicyJson],
```

Add the imports at the top of `pipeline.py`:

```python
from containerizer.analyze.reader import InstallInputs, read_install_inputs
```

In `src/containerizer/build/cli.py`, update `_default_derive_policy_fn`:

```python
def _default_derive_policy_fn(trace: TraceJson, install_inputs: InstallInputs) -> PolicyJson:
    return derive_policy(
        trace,
        install_inputs=install_inputs,
        warnings=list(trace.warnings),
    )
```

Add the import in `cli.py`:

```python
from containerizer.analyze.reader import InstallInputs
```

- [ ] **Step 5: Update the build smoke test to accept the new signature**

In `tests/integration/build/test_build_smoke.py`, replace `_real_derive_policy`:

```python
def _real_derive_policy(trace: TraceJson, install_inputs) -> PolicyJson:
    return derive_policy(trace, install_inputs=install_inputs, warnings=list(trace.warnings))
```

Add the import:

```python
from containerizer.analyze.reader import InstallInputs  # noqa: F401  (used implicitly via signature)
```

(The unused import warning is fine; ruff's `F401` won't trigger because the name is referenced in the type hint. If ruff complains, drop the comment and add it to a real type annotation: `def _real_derive_policy(trace: TraceJson, install_inputs: InstallInputs) -> PolicyJson:`.)

- [ ] **Step 6: Run unit + integration tests**

```bash
python -m pytest tests/unit/build/test_pipeline.py tests/integration/build/test_build_smoke.py -v
```

Expected: all `_stage_install_inputs` tests pass; `test_build_smoke.py` passes (it uses the fake `_fake_podman_build`, so the staging side effect doesn't break anything).

- [ ] **Step 7: Commit**

```bash
git add src/containerizer/build/pipeline.py src/containerizer/build/cli.py tests/unit/build/test_pipeline.py tests/integration/build/test_build_smoke.py
git -c user.email="github.v5f9w@bitbucket.onl" -c user.signingkey=BE707B220C995478 commit -S -m "feat(build): stage installers + apt-keys into final_dir before podman build (#111)

run_pipeline now calls read_install_inputs to build the InstallInputs
that feeds derive_policy, and stages installer files / apt-keys into
final_dir/{installer,installers/,apt-keys/} so the Containerfile's COPY
lines resolve. Closes the latent staging gap for the executable case
too — previously only happened to work in tests that faked podman build.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 7: Standalone analyze CLI — pass `install_inputs` to `derive_policy`

**Files:**
- Modify: `src/containerizer/analyze/cli.py`

- [ ] **Step 1: Read the existing CLI and patch the derive call**

In `src/containerizer/analyze/cli.py`, update the imports:

```python
from containerizer.analyze.reader import read_install_inputs, read_trace_dir
```

(Add `read_install_inputs` to the existing import.)

Replace the body of `analyze_cmd`:

```python
def analyze_cmd(trace_dir: Path, output_dir: Path) -> None:
    """Analyze TRACE_DIR (produced by `containerizer trace`) and emit
    trace.json + policy.json."""
    output_dir.mkdir(parents=True, exist_ok=True)
    bundle = read_trace_dir(trace_dir)
    trace = assemble_trace_json(bundle)
    install_inputs = read_install_inputs(trace_dir)
    policy = derive_policy(
        trace,
        install_inputs=install_inputs,
        warnings=list(trace.warnings),
    )
    write_trace_json(trace, output_dir / "trace.json")
    write_policy_json(policy, output_dir / "policy.json")
    click.echo(f"wrote {output_dir / 'trace.json'} and {output_dir / 'policy.json'}")
```

- [ ] **Step 2: Run the analyze CLI test**

```bash
python -m pytest tests/unit/analyze/test_cli.py -v
```

Expected: passes. (If it fails on a missing trace-dir marker file, the fix is in the test fixture — the test should construct an analyzable trace dir; the new code path is a no-op when INSTALLERS / apt-sources.list / APT_KEYS are absent.)

- [ ] **Step 3: Commit**

```bash
git add src/containerizer/analyze/cli.py
git -c user.email="github.v5f9w@bitbucket.onl" -c user.signingkey=BE707B220C995478 commit -S -m "feat(analyze): standalone CLI threads install_inputs into derive_policy (#111)

containerizer analyze now reads INSTALLERS / apt-sources.list / APT_KEYS
markers from the trace dir and passes them to derive_policy, so the
standalone flow produces the same .deb policy as the build pipeline.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 8: Full pre-commit gate + cleanup

**Files:** none modified; just verifies the whole feature.

- [ ] **Step 1: Run ruff format check**

```bash
ruff format --check .
```

Expected: zero diffs. If anything fails, run `ruff format .` and amend the last commit (or stage + commit the formatting fix as `style: ruff format (#111)`).

- [ ] **Step 2: Run ruff lint**

```bash
ruff check .
```

Expected: zero issues. Fix any reported by editing the source and re-running.

- [ ] **Step 3: Run the full unit test suite**

```bash
python -m pytest tests/unit -v
```

Expected: all unit tests pass.

- [ ] **Step 4: Run integration tests that don't require BPF/podman**

```bash
python -m pytest tests/integration/build/test_build_smoke.py tests/integration/generate -v
```

Expected: passes. (Other integration tests require BPF and will be exercised by CI on the Linux runner.)

- [ ] **Step 5: Final verification — check the README rendering is unaffected**

```bash
python -m pytest tests/unit/generate/test_readme.py -v
```

Expected: passes. The README renderer reads only the install-input parameters via `generate_all`'s kwargs; the schema change shouldn't reach it.

- [ ] **Step 6: If anything in steps 1-5 required a fix, commit it**

```bash
git add -A
git -c user.email="github.v5f9w@bitbucket.onl" -c user.signingkey=BE707B220C995478 commit -S -m "chore: ruff format / lint fixes for #111

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

(Skip if nothing to commit.)

- [ ] **Step 7: Push and open the PR**

```bash
git push -u origin <branch-name>
gh pr create --title "feat(generate): multi-deb + apt-source Containerfile (#111)" --body "$(cat <<'EOF'
## Summary
- Closes #111
- `PolicyImage.installer` is now a discriminated `DebInstaller | ExecutableInstaller`; policy schema_version bumps 2 → 3 (intermediate artifact, no external consumers)
- Trace runner persists `INSTALLERS` + `APT_KEYS` marker files; reader's new `read_install_inputs` surfaces them; `derive_policy` accepts an `install_inputs` kwarg; `containerfile.py` dispatches on `kind`
- Build orchestrator stages installer files + apt-keys into `final_dir/{installers,apt-keys}/`; also fixes a latent staging gap for the executable case

## Test plan
- [x] Full unit suite green on Windows: `python -m pytest tests/unit -v`
- [x] Build smoke integration test green: `python -m pytest tests/integration/build/test_build_smoke.py -v`
- [x] `ruff format --check .` clean
- [x] `ruff check .` clean
- [ ] CI's Linux runner exercises the .deb integration tests under real BPF/podman
- [ ] (Manual, on cougar) end-to-end UniFi + MongoDB build produces an image that boots far enough for mongod and the bound ports to come up

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Expected: PR URL is printed.

---

## Self-Review Notes

Ran the checklist:

- **Spec coverage:** every section of the spec maps to a task. Schema → Task 1. Trace markers → Task 3. Reader → Task 2. Derive → Task 4. Renderer → Task 5. Build orchestrator + staging → Task 6. Standalone analyze CLI → Task 7. Test pyramid → spread across Tasks 1, 2, 3, 4, 5, 6 (unit tests added per-component). CI gate → Task 8.
- **Placeholder scan:** none found.
- **Type consistency:** `InstallInputs` defined in Task 2, referenced in Tasks 4/6/7. `DebInstaller`, `ExecutableInstaller`, `InstallerSpec` defined in Task 1, used in Tasks 4/5. `_stage_install_inputs` defined in Task 6, used only there (called from `run_pipeline`).
- **Names match across tasks:** `read_install_inputs` (Task 2 = Task 6/7), `_build_installer_spec` / `_post_install_cleanup_for` (Task 4 only), `_render_deb` / `_render_executable` / `_entrypoint_line` (Task 5 only).
