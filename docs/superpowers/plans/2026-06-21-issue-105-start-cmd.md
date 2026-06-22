# Issue #105 `--start-cmd` Wiring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire `--start-cmd` end-to-end so daemon-bearing `.deb` installers (and install-then-exit ELF installers) start their daemons during the trace runtime phase, letting the analyzer derive a non-sentinel policy.

**Architecture:** A new env-var pair (`CONTAINERIZER_START_CMD`, `CONTAINERIZER_START_READY_SECONDS`) flows from `TraceRunner` argv into the orchestrator. After PHASE_MARKER, the orchestrator execs the start command (via `podman exec deb-install bash -c …` for deb; direct `bash -c …` for ELF), polls `ss -tlnp` for a LISTEN line with a timeout fallback, then sleeps a runtime-soak window before finalizing. `--verify-soak-seconds` auto-scales to `max(60, --start-ready-seconds)` when `--start-cmd` is set; one resolved value drives both install-mode runtime soak and verify-mode soak.

**Tech Stack:** Python 3 + Click (CLI), pydantic v2 (`BuildConfig`), Python `@dataclass(frozen=True)` (`TraceRunner`), bash (orchestrator script), pytest (tests), `tests/fixtures/probe/deb_helpers.py` (fixture deb builder).

**Spec:** [`docs/superpowers/specs/2026-06-21-containerizer-issue-105-start-cmd.md`](../specs/2026-06-21-containerizer-issue-105-start-cmd.md)

---

## File map

**Modify (source):**
- `src/containerizer/trace/runner.py` — install-mode-only fields `start_cmd: str | None`, `start_ready_seconds: int`; argv env vars
- `src/containerizer/build/config.py` — add `start_ready_seconds: int`, change `verify_soak_seconds` to `int | None`, add `effective_verify_soak_seconds` derived
- `src/containerizer/build/cli.py` — drop "no effect" warning; add `--start-ready-seconds`; sentinel-`None` default for `--verify-soak-seconds`; validation; thread to install_trace_fn
- `src/containerizer/trace/cli.py` — add `--start-cmd`, `--start-ready-seconds`, `--verify-soak-seconds`; thread to TraceRunner
- `src/containerizer/build/pipeline.py` — forward `start_ready_seconds` + `effective_verify_soak_seconds` to install_trace_fn and verify_trace_fn; pass start-cmd args to generate_fn
- `src/containerizer/generate/readme.py` — extend `_render_install_inputs` + `render_readme` with `start_cmd`, `start_ready_seconds`, `verify_soak_seconds` args
- `src/containerizer/generate/orchestrator.py` — thread the new args through `generate_all` → `render_readme`
- `sandbox/runner_image/trace-orchestrator.sh` — add post-PHASE_MARKER block to `run_deb_install` and `run_elf_install`

**Modify (tests):**
- `tests/unit/test_trace_runner.py` — argv env-var assertions
- `tests/unit/build/test_config.py` — `start_ready_seconds`, `effective_verify_soak_seconds`
- `tests/unit/build/test_cli.py` — warning gone, validation
- `tests/unit/test_trace_cli.py` — new CLI flags accepted + threaded
- `tests/unit/generate/test_render_install_inputs.py` — Start command subsection
- `tests/integration/trace/test_deb_pipeline.py` — daemon-bearing fixture + `--start-cmd`

**Create:**
- `tests/integration/trace/test_elf_start_cmd.py` — ELF `--start-cmd` integration test

**Modify (docs):**
- `MANUAL.md` — scenario 14 (UniFi + MongoDB)

---

## Task 1: TraceRunner — install-mode fields and validation

**Files:**
- Modify: `src/containerizer/trace/runner.py`
- Test: `tests/unit/test_trace_runner.py`

- [ ] **Step 1: Write failing test**

Append to `tests/unit/test_trace_runner.py`:

```python
def test_install_mode_accepts_start_cmd_and_ready_seconds(tmp_path: Path) -> None:
    installer = tmp_path / "install.sh"
    installer.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    output = tmp_path / "trace"
    output.mkdir()

    runner = TraceRunner(
        image_tag="runner:latest",
        installer=installer,
        output_dir=output,
        start_cmd="/etc/init.d/foo start",
        start_ready_seconds=90,
    )
    assert runner.start_cmd == "/etc/init.d/foo start"
    assert runner.start_ready_seconds == 90


def test_install_mode_defaults_start_cmd_to_none_and_ready_to_60(tmp_path: Path) -> None:
    installer = tmp_path / "install.sh"
    installer.write_text("", encoding="utf-8")
    output = tmp_path / "trace"
    output.mkdir()

    runner = TraceRunner(
        image_tag="runner:latest",
        installer=installer,
        output_dir=output,
    )
    assert runner.start_cmd is None
    assert runner.start_ready_seconds == 60


def test_verify_mode_rejects_start_cmd(tmp_path: Path) -> None:
    image_tar = tmp_path / "image.tar"
    image_tar.write_bytes(b"x")
    seccomp = tmp_path / "seccomp.json"
    seccomp.write_text("{}", encoding="utf-8")
    out = tmp_path / "verify-trace"

    with pytest.raises(ValueError, match="verify mode does not accept"):
        TraceRunner(
            image_tag="runner:latest",
            installer=None,
            output_dir=out,
            mode="verify",
            verify_image_tar=image_tar,
            verify_image_tag="generated:tag",
            verify_soak_seconds=30,
            verify_seccomp_path=seccomp,
            start_cmd="/etc/init.d/foo start",
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_trace_runner.py::test_install_mode_accepts_start_cmd_and_ready_seconds tests/unit/test_trace_runner.py::test_install_mode_defaults_start_cmd_to_none_and_ready_to_60 tests/unit/test_trace_runner.py::test_verify_mode_rejects_start_cmd -v`
Expected: FAIL — `TypeError: TraceRunner.__init__() got an unexpected keyword argument 'start_cmd'`.

- [ ] **Step 3: Add fields + validation**

In `src/containerizer/trace/runner.py`, in the `TraceRunner` dataclass body alongside the existing fields:

```python
# Issue #105: install-mode-only.
start_cmd: str | None = None
start_ready_seconds: int = 60
```

In `__post_init__`, extend the verify-mode rejection block (currently checks `extra_installers`, `apt_sources`, `apt_keys`) to also reject `start_cmd`:

```python
if self.extra_installers or self.apt_sources or self.apt_keys or self.start_cmd:
    raise ValueError(
        "verify mode does not accept extra installers, apt sources, apt keys, or start_cmd"
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_trace_runner.py -v`
Expected: PASS (all existing tests + 3 new).

- [ ] **Step 5: Commit**

```bash
git add src/containerizer/trace/runner.py tests/unit/test_trace_runner.py
git -c user.email="github.v5f9w@bitbucket.onl" -c user.signingkey=BE707B220C995478 commit -S -m "feat(trace): add start_cmd + start_ready_seconds fields to TraceRunner (#105)"
```

---

## Task 2: TraceRunner — install-mode argv env vars

**Files:**
- Modify: `src/containerizer/trace/runner.py:_install_argv`
- Test: `tests/unit/test_trace_runner.py`

- [ ] **Step 1: Write failing test**

Append to `tests/unit/test_trace_runner.py`:

```python
def test_install_argv_includes_start_cmd_env_when_set(tmp_path: Path) -> None:
    installer = tmp_path / "install.sh"
    installer.write_text("", encoding="utf-8")
    output = tmp_path / "trace"
    output.mkdir()

    runner = TraceRunner(
        image_tag="runner:latest",
        installer=installer,
        output_dir=output,
        start_cmd="/etc/init.d/foo start && sleep 1",
        start_ready_seconds=90,
    )
    argv = runner.argv()
    assert "CONTAINERIZER_START_CMD=/etc/init.d/foo start && sleep 1" in argv
    assert "CONTAINERIZER_START_READY_SECONDS=90" in argv


def test_install_argv_omits_start_cmd_env_when_unset(tmp_path: Path) -> None:
    installer = tmp_path / "install.sh"
    installer.write_text("", encoding="utf-8")
    output = tmp_path / "trace"
    output.mkdir()

    runner = TraceRunner(
        image_tag="runner:latest",
        installer=installer,
        output_dir=output,
    )
    argv = runner.argv()
    assert not any(a.startswith("CONTAINERIZER_START_CMD=") for a in argv)
    assert not any(a.startswith("CONTAINERIZER_START_READY_SECONDS=") for a in argv)


def test_install_argv_always_includes_verify_soak_env(tmp_path: Path) -> None:
    """Install-mode reads CONTAINERIZER_VERIFY_SOAK_SECONDS for runtime-soak
    when start_cmd is set; harmless when unset (orchestrator's sleep is gated
    on CONTAINERIZER_START_CMD being set)."""
    installer = tmp_path / "install.sh"
    installer.write_text("", encoding="utf-8")
    output = tmp_path / "trace"
    output.mkdir()

    runner = TraceRunner(
        image_tag="runner:latest",
        installer=installer,
        output_dir=output,
        verify_soak_seconds=45,
    )
    argv = runner.argv()
    assert "CONTAINERIZER_VERIFY_SOAK_SECONDS=45" in argv
```

- [ ] **Step 2: Allow `verify_soak_seconds` in install-mode TraceRunner**

The existing `__post_init__` does NOT reject `verify_soak_seconds` in install mode (it only validates verify-mode fields when `mode == "verify"`), so no change needed for installation. But the third test needs `verify_soak_seconds=45` accepted in install mode. Verify this works by reading the existing `__post_init__` — install-mode branch only validates `installer is not None`. No change required.

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/unit/test_trace_runner.py::test_install_argv_includes_start_cmd_env_when_set tests/unit/test_trace_runner.py::test_install_argv_omits_start_cmd_env_when_unset tests/unit/test_trace_runner.py::test_install_argv_always_includes_verify_soak_env -v`
Expected: FAIL — env strings not in argv.

- [ ] **Step 4: Add env vars to _install_argv**

In `src/containerizer/trace/runner.py::_install_argv`, find the existing `-e` block (around line 145–150) and add inside the returned list:

```python
"-e",
f"CONTAINERIZER_INTERACTIVE={1 if self.tty else 0}",
# Issue #105: start-cmd transport (env vars only present when start_cmd set).
*((
    "-e", f"CONTAINERIZER_START_CMD={self.start_cmd}",
    "-e", f"CONTAINERIZER_START_READY_SECONDS={self.start_ready_seconds}",
) if self.start_cmd else ()),
# Issue #105: runtime-soak window. Always set; orchestrator only sleeps when
# CONTAINERIZER_START_CMD is also set, so this is a no-op for non-start-cmd runs.
"-e",
f"CONTAINERIZER_VERIFY_SOAK_SECONDS={self.verify_soak_seconds if self.verify_soak_seconds is not None else 30}",
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/unit/test_trace_runner.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/containerizer/trace/runner.py tests/unit/test_trace_runner.py
git -c user.email="github.v5f9w@bitbucket.onl" -c user.signingkey=BE707B220C995478 commit -S -m "feat(trace): wire start_cmd env vars into install-mode argv (#105)"
```

---

## Task 3: BuildConfig — start_ready_seconds + effective_verify_soak_seconds

**Files:**
- Modify: `src/containerizer/build/config.py`
- Test: `tests/unit/build/test_config.py`

- [ ] **Step 1: Write failing test**

Append to `tests/unit/build/test_config.py`:

```python
def test_build_config_defaults_start_ready_seconds_to_60() -> None:
    cfg = BuildConfig(installer=Path("/tmp/x"), name="demo", out_dir=Path("out"))
    assert cfg.start_ready_seconds == 60


def test_build_config_verify_soak_defaults_to_none_sentinel() -> None:
    """Pipeline distinguishes 'user explicitly set 30' from 'user didn't set anything'
    so the auto-scale can fire only when no override was given."""
    cfg = BuildConfig(installer=Path("/tmp/x"), name="demo", out_dir=Path("out"))
    assert cfg.verify_soak_seconds is None


def test_effective_verify_soak_returns_30_when_no_start_cmd_and_no_override() -> None:
    cfg = BuildConfig(installer=Path("/tmp/x"), name="demo", out_dir=Path("out"))
    assert cfg.effective_verify_soak_seconds == 30


def test_effective_verify_soak_uses_explicit_override_when_set() -> None:
    cfg = BuildConfig(
        installer=Path("/tmp/x"),
        name="demo",
        out_dir=Path("out"),
        verify_soak_seconds=15,
    )
    assert cfg.effective_verify_soak_seconds == 15


def test_effective_verify_soak_uses_explicit_override_even_with_start_cmd() -> None:
    cfg = BuildConfig(
        installer=Path("/tmp/x"),
        name="demo",
        out_dir=Path("out"),
        start_cmd="/etc/init.d/foo start",
        start_ready_seconds=120,
        verify_soak_seconds=10,
    )
    assert cfg.effective_verify_soak_seconds == 10


def test_effective_verify_soak_autoscales_to_60_with_start_cmd_and_low_ready() -> None:
    cfg = BuildConfig(
        installer=Path("/tmp/x"),
        name="demo",
        out_dir=Path("out"),
        start_cmd="/etc/init.d/foo start",
        start_ready_seconds=30,
    )
    assert cfg.effective_verify_soak_seconds == 60


def test_effective_verify_soak_autoscales_to_start_ready_when_larger() -> None:
    cfg = BuildConfig(
        installer=Path("/tmp/x"),
        name="demo",
        out_dir=Path("out"),
        start_cmd="/etc/init.d/foo start",
        start_ready_seconds=120,
    )
    assert cfg.effective_verify_soak_seconds == 120
```

The existing `test_build_config_round_trip_defaults` asserts `verify_soak_seconds == 30`. Update that assertion to `verify_soak_seconds is None`:

```python
def test_build_config_round_trip_defaults() -> None:
    cfg = BuildConfig(installer=Path("/tmp/x"), name="demo", out_dir=Path("out"))

    assert cfg.schema_version == 1
    assert cfg.base_image is None
    assert cfg.start_cmd is None
    assert cfg.keep_intermediates is False
    assert cfg.verify_soak_seconds is None  # Issue #105: sentinel default
    assert cfg.skip_verify is False
    assert cfg.debug is False
    # ...rest unchanged
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/build/test_config.py -v`
Expected: FAIL — new tests fail (no `start_ready_seconds`, no `effective_verify_soak_seconds`); updated round-trip test fails (default is still 30).

- [ ] **Step 3: Update BuildConfig**

In `src/containerizer/build/config.py`, modify the `BuildConfig` class:

```python
class BuildConfig(BaseModel):
    """User-facing configuration for one `containerizer build` invocation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    installer: Path
    name: str
    out_dir: Path
    base_image: str | None = None
    start_cmd: str | None = None
    # Issue #105: --start-cmd companion. Only meaningful when start_cmd is set;
    # CLI validates that combination.
    start_ready_seconds: int = 60
    keep_intermediates: bool = False
    # Issue #105: sentinel-None default so the CLI can distinguish "user
    # explicitly set 30" from "user didn't set anything" and the auto-scale
    # in effective_verify_soak_seconds can fire only in the latter case.
    verify_soak_seconds: int | None = None
    skip_verify: bool = False
    debug: bool = False

    # Issue #102.
    extra_installers: tuple[Path, ...] = ()
    apt_sources: tuple[str, ...] = ()
    apt_keys: tuple[Path, ...] = ()

    @property
    def effective_verify_soak_seconds(self) -> int:
        """Resolved soak value. Explicit --verify-soak-seconds always wins.
        Otherwise: 30 by default, max(60, start_ready_seconds) when
        --start-cmd is set."""
        if self.verify_soak_seconds is not None:
            return self.verify_soak_seconds
        if self.start_cmd is not None:
            return max(60, self.start_ready_seconds)
        return 30
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/build/test_config.py -v`
Expected: PASS (all old + 7 new).

- [ ] **Step 5: Commit**

```bash
git add src/containerizer/build/config.py tests/unit/build/test_config.py
git -c user.email="github.v5f9w@bitbucket.onl" -c user.signingkey=BE707B220C995478 commit -S -m "feat(build): add start_ready_seconds + effective_verify_soak_seconds (#105)"
```

---

## Task 4: build CLI — drop warning, add --start-ready-seconds, sentinel verify-soak

**Files:**
- Modify: `src/containerizer/build/cli.py`
- Test: `tests/unit/build/test_cli.py`

- [ ] **Step 1: Inspect existing test file**

Run: `pytest tests/unit/build/test_cli.py -v --collect-only`

Read the existing tests to learn the CliRunner pattern used by this repo. The new tests below follow the same Click-CliRunner approach as the existing ones.

- [ ] **Step 2: Write failing tests**

Append to `tests/unit/build/test_cli.py`:

```python
def test_build_cli_no_longer_warns_about_start_cmd(tmp_path: Path, monkeypatch) -> None:
    """Issue #105: the 'has no effect' warning must be gone."""
    from click.testing import CliRunner

    from containerizer.build.cli import build_cmd

    installer = tmp_path / "foo.deb"
    installer.write_bytes(b"!<arch>\nfake")

    # Make preflight pass and bail before the actual pipeline runs.
    monkeypatch.setattr("containerizer.build.cli.preflight_podman", lambda: None)
    def _boom(*a, **kw):
        raise SystemExit(0)
    monkeypatch.setattr("containerizer.build.cli.run_pipeline", _boom)

    runner = CliRunner()
    result = runner.invoke(
        build_cmd,
        [str(installer), "--name", "foo", "--start-cmd", "/etc/init.d/foo start"],
        mix_stderr=False,
    )
    # Either exit 0 (we shimmed the pipeline) or a controlled failure;
    # whichever, the warning text must not appear.
    assert "has no effect" not in (result.output or "")
    assert "has no effect" not in (result.stderr or "")


def test_build_cli_start_ready_seconds_without_start_cmd_errors(tmp_path: Path, monkeypatch) -> None:
    from click.testing import CliRunner

    from containerizer.build.cli import build_cmd

    installer = tmp_path / "foo.deb"
    installer.write_bytes(b"!<arch>\nfake")
    monkeypatch.setattr("containerizer.build.cli.preflight_podman", lambda: None)

    runner = CliRunner()
    result = runner.invoke(
        build_cmd,
        [str(installer), "--name", "foo", "--start-ready-seconds", "90"],
        mix_stderr=False,
    )
    assert result.exit_code != 0
    err = (result.stderr or "") + (result.output or "")
    assert "--start-ready-seconds requires --start-cmd" in err


def test_build_cli_accepts_start_cmd_and_ready_seconds_together(tmp_path: Path, monkeypatch) -> None:
    from click.testing import CliRunner

    from containerizer.build.cli import build_cmd

    installer = tmp_path / "foo.deb"
    installer.write_bytes(b"!<arch>\nfake")
    monkeypatch.setattr("containerizer.build.cli.preflight_podman", lambda: None)
    captured = {}
    def _capture(config, **kw):
        captured["config"] = config
        raise SystemExit(0)
    monkeypatch.setattr("containerizer.build.cli.run_pipeline", _capture)

    runner = CliRunner()
    result = runner.invoke(
        build_cmd,
        [
            str(installer), "--name", "foo",
            "--start-cmd", "/etc/init.d/foo start",
            "--start-ready-seconds", "90",
        ],
        mix_stderr=False,
    )
    assert result.exit_code == 0
    cfg = captured["config"]
    assert cfg.start_cmd == "/etc/init.d/foo start"
    assert cfg.start_ready_seconds == 90
    # verify_soak_seconds left as sentinel; auto-scale picks max(60, 90) = 90.
    assert cfg.verify_soak_seconds is None
    assert cfg.effective_verify_soak_seconds == 90
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/unit/build/test_cli.py::test_build_cli_no_longer_warns_about_start_cmd tests/unit/build/test_cli.py::test_build_cli_start_ready_seconds_without_start_cmd_errors tests/unit/build/test_cli.py::test_build_cli_accepts_start_cmd_and_ready_seconds_together -v`
Expected: FAIL — warning still present; `--start-ready-seconds` not recognized; CLI doesn't validate the combination.

- [ ] **Step 4: Edit `src/containerizer/build/cli.py`**

Replace the existing `--verify-soak-seconds` Click option (around lines 64–69) with sentinel-None default:

```python
@click.option(
    "--verify-soak-seconds",
    type=int,
    default=None,
    help="Verify-phase idle observation window after daemon-ready. "
         "Defaults to 30s; when --start-cmd is set, auto-scales to "
         "max(60s, --start-ready-seconds).",
)
```

Add the new `--start-ready-seconds` option (immediately after `--start-cmd`):

```python
@click.option(
    "--start-ready-seconds",
    type=int,
    default=60,
    help="Seconds to wait for the daemon to bind a port after --start-cmd "
         "before proceeding. Only meaningful with --start-cmd.",
)
```

Update the `build_cmd` function signature: change `verify_soak_seconds: int` to `verify_soak_seconds: int | None`, add `start_ready_seconds: int`:

```python
def build_cmd(
    installer: Path,
    name: str,
    base_image: str | None,
    start_cmd: str | None,
    start_ready_seconds: int,
    out_dir: Path,
    keep_intermediates: bool,
    verify_soak_seconds: int | None,
    skip_verify: bool,
    debug: bool,
    extra_installers: tuple[Path, ...],
    apt_sources: tuple[str, ...],
    apt_keys: tuple[Path, ...],
) -> None:
```

Inside the body, ADD validation right after `_validate_multi_deb_flags(...)`:

```python
if start_cmd is None and start_ready_seconds != 60:
    raise click.UsageError("--start-ready-seconds requires --start-cmd")
```

Pass `start_ready_seconds=start_ready_seconds` into the `BuildConfig(...)` constructor:

```python
config = BuildConfig(
    installer=installer,
    name=name,
    out_dir=out_dir,
    base_image=base_image,
    start_cmd=start_cmd,
    start_ready_seconds=start_ready_seconds,
    keep_intermediates=keep_intermediates,
    verify_soak_seconds=verify_soak_seconds,
    skip_verify=skip_verify,
    debug=debug,
    extra_installers=tuple(p.resolve() for p in extra_installers),
    apt_sources=apt_sources,
    apt_keys=tuple(p.resolve() for p in apt_keys),
)
```

DELETE the "has no effect" warning block (the existing `if start_cmd is not None: click.echo("[warn] ... has no effect ...", err=True)`).

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/unit/build/test_cli.py -v`
Expected: PASS (all old + 3 new).

- [ ] **Step 6: Commit**

```bash
git add src/containerizer/build/cli.py tests/unit/build/test_cli.py
git -c user.email="github.v5f9w@bitbucket.onl" -c user.signingkey=BE707B220C995478 commit -S -m "feat(build): wire --start-ready-seconds and drop --start-cmd warning (#105)"
```

---

## Task 5: trace CLI — add --start-cmd, --start-ready-seconds, --verify-soak-seconds

**Files:**
- Modify: `src/containerizer/trace/cli.py`
- Test: `tests/unit/test_trace_cli.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/unit/test_trace_cli.py`:

```python
def test_trace_cli_threads_start_cmd_into_runner(tmp_path: Path, monkeypatch) -> None:
    from click.testing import CliRunner

    from containerizer.trace.cli import trace_cmd

    installer = tmp_path / "foo.deb"
    installer.write_bytes(b"!<arch>\nfake")

    monkeypatch.setattr("containerizer.trace.cli._podman_machine_is_running", lambda: True)
    monkeypatch.setattr(
        "containerizer.trace.cli.RunnerImage.exists", lambda self: True
    )

    captured = {}
    def _capture(self):
        captured["runner"] = self
        return 0
    monkeypatch.setattr("containerizer.trace.cli.TraceRunner.run", _capture)

    out = tmp_path / "trace"
    runner = CliRunner()
    result = runner.invoke(
        trace_cmd,
        [
            str(installer),
            "-o", str(out),
            "--start-cmd", "/etc/init.d/foo start",
            "--start-ready-seconds", "90",
            "--verify-soak-seconds", "45",
        ],
        mix_stderr=False,
    )
    assert result.exit_code == 0, result.output + (result.stderr or "")
    runner_inst = captured["runner"]
    assert runner_inst.start_cmd == "/etc/init.d/foo start"
    assert runner_inst.start_ready_seconds == 90
    assert runner_inst.verify_soak_seconds == 45


def test_trace_cli_start_ready_seconds_without_start_cmd_errors(tmp_path: Path, monkeypatch) -> None:
    from click.testing import CliRunner

    from containerizer.trace.cli import trace_cmd

    installer = tmp_path / "foo.deb"
    installer.write_bytes(b"!<arch>\nfake")
    monkeypatch.setattr("containerizer.trace.cli._podman_machine_is_running", lambda: True)

    out = tmp_path / "trace"
    runner = CliRunner()
    result = runner.invoke(
        trace_cmd,
        [str(installer), "-o", str(out), "--start-ready-seconds", "90"],
        mix_stderr=False,
    )
    assert result.exit_code != 0
    err = (result.stderr or "") + (result.output or "")
    assert "--start-ready-seconds requires --start-cmd" in err
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_trace_cli.py::test_trace_cli_threads_start_cmd_into_runner tests/unit/test_trace_cli.py::test_trace_cli_start_ready_seconds_without_start_cmd_errors -v`
Expected: FAIL — `--start-cmd` flag unknown.

- [ ] **Step 3: Edit `src/containerizer/trace/cli.py`**

Add three `@click.option` decorators to `trace_cmd` (between the existing `--apt-key` option and the function signature):

```python
@click.option(
    "--start-cmd",
    default=None,
    help="Daemon-start command exec'd inside the install container after PHASE_MARKER. "
         "Composed by the user; passed verbatim to bash -c.",
)
@click.option(
    "--start-ready-seconds",
    type=int,
    default=60,
    help="Seconds to wait for the daemon to bind a port after --start-cmd. "
         "Only meaningful with --start-cmd.",
)
@click.option(
    "--verify-soak-seconds",
    type=int,
    default=None,
    help="Runtime-soak window after the daemon is ready (defaults to 30s; "
         "auto-scales to max(60s, --start-ready-seconds) when --start-cmd is set).",
)
```

Extend the `trace_cmd` function signature:

```python
def trace_cmd(
    installer: Path,
    output_dir: Path,
    force: bool,
    extra_installers: tuple[Path, ...],
    apt_sources: tuple[str, ...],
    apt_keys: tuple[Path, ...],
    start_cmd: str | None,
    start_ready_seconds: int,
    verify_soak_seconds: int | None,
) -> None:
```

Add validation after the existing `_validate_multi_deb_flags(...)` call:

```python
if start_cmd is None and start_ready_seconds != 60:
    raise click.UsageError("--start-ready-seconds requires --start-cmd")
```

Resolve the verify-soak value with the same auto-scale rule used by `BuildConfig`:

```python
if verify_soak_seconds is None:
    resolved_soak = max(60, start_ready_seconds) if start_cmd is not None else 30
else:
    resolved_soak = verify_soak_seconds
```

Pass the new fields into `TraceRunner(...)`:

```python
runner = TraceRunner(
    image_tag=image.tag,
    installer=installer.resolve(),
    output_dir=output_dir.resolve(),
    tty=sys.stdin.isatty(),
    extra_installers=tuple(p.resolve() for p in extra_installers),
    apt_sources=apt_sources,
    apt_keys=tuple(p.resolve() for p in apt_keys),
    start_cmd=start_cmd,
    start_ready_seconds=start_ready_seconds,
    verify_soak_seconds=resolved_soak,
)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_trace_cli.py -v`
Expected: PASS (all old + 2 new).

- [ ] **Step 5: Commit**

```bash
git add src/containerizer/trace/cli.py tests/unit/test_trace_cli.py
git -c user.email="github.v5f9w@bitbucket.onl" -c user.signingkey=BE707B220C995478 commit -S -m "feat(trace): add --start-cmd, --start-ready-seconds, --verify-soak-seconds (#105)"
```

---

## Task 6: Pipeline + install_trace_fn — thread start_ready_seconds + effective soak

**Files:**
- Modify: `src/containerizer/build/pipeline.py`
- Modify: `src/containerizer/build/cli.py::_default_install_trace_fn`
- Test: `tests/unit/build/test_pipeline.py`

- [ ] **Step 1: Write failing test**

Append to `tests/unit/build/test_pipeline.py`:

```python
def test_pipeline_threads_start_cmd_and_effective_soak_to_install_trace_fn(tmp_path: Path) -> None:
    """Issue #105: pipeline must forward start_ready_seconds and the resolved
    effective_verify_soak_seconds to install_trace_fn."""
    from containerizer.analyze.derive import SENTINEL_ENTRYPOINT
    from containerizer.analyze.schema import PolicyImage, PolicyJson, PolicyRuntime, TraceJson
    from containerizer.build.config import BuildConfig
    from containerizer.build.paths import resolve_layout
    from containerizer.build.pipeline import run_pipeline
    from containerizer.probe.schema import ProbeResult

    cfg = BuildConfig(
        installer=tmp_path / "foo.deb",
        name="foo",
        out_dir=tmp_path / "out",
        start_cmd="/etc/init.d/foo start",
        start_ready_seconds=90,
    )
    (tmp_path / "foo.deb").write_bytes(b"!<arch>\n")
    layout = resolve_layout(cfg.out_dir, cfg.name, intermediates_root=tmp_path / "int", keep_intermediates=False)

    sentinel_policy = PolicyJson(
        image=PolicyImage(
            base="ubuntu:24.04", apt_packages=[], post_install_cleanup=[],
            systemd_required=False, entrypoint=[SENTINEL_ENTRYPOINT],
        ),
        runtime=PolicyRuntime(
            volumes=[], tmpfs=[], binds_ro=[], publish_ports=[],
            caps_add=[], seccomp_syscalls=[], read_only_rootfs=False,
        ),
        warnings=["sentinel reason"],
    )
    captured = {}

    def fake_install_trace_fn(installer, start_cmd, output_dir, **kw):
        captured["start_cmd"] = start_cmd
        captured["start_ready_seconds"] = kw.get("start_ready_seconds")
        captured["verify_soak_seconds"] = kw.get("verify_soak_seconds")
        (output_dir / "COMPLETE").write_text("", encoding="utf-8")
        return 0

    run_pipeline(
        cfg,
        probe_fn=lambda *a, **kw: ProbeResult(
            installer_kind="deb",
            installer_path=cfg.installer,
            installer_metadata={},
            base_image=None,
            warnings=[],
        ),
        install_trace_fn=fake_install_trace_fn,
        parse_trace_fn=lambda d: TraceJson(
            file_opens=[], socket_binds=[], capabilities=[],
            syscalls=[], execs=[], phase_marker_ns=None, warnings=[],
        ),
        derive_policy_fn=lambda t: sentinel_policy,
        generate_fn=lambda *a, **kw: None,
        podman_build_fn=lambda *a, **kw: Path("/x"),
        verify_trace_fn=lambda *a, **kw: 0,
        diff_fn=lambda a, b: None,
        layout=layout,
        stderr=sys.stderr,
    )

    assert captured["start_cmd"] == "/etc/init.d/foo start"
    assert captured["start_ready_seconds"] == 90
    assert captured["verify_soak_seconds"] == 90  # auto-scaled
```

NOTE: the existing test file may need `import sys` and `from pathlib import Path` — match the file's existing imports.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/build/test_pipeline.py::test_pipeline_threads_start_cmd_and_effective_soak_to_install_trace_fn -v`
Expected: FAIL — `install_trace_fn` not called with `start_ready_seconds` kwarg.

- [ ] **Step 3: Update pipeline**

In `src/containerizer/build/pipeline.py`, find the `install_trace_fn(...)` call (around line 57) and add the two new kwargs:

```python
install_trace_fn(
    config.installer,
    config.start_cmd,
    layout.trace_original_dir,
    extra_installers=config.extra_installers,
    apt_sources=config.apt_sources,
    apt_keys=config.apt_keys,
    start_ready_seconds=config.start_ready_seconds,
    verify_soak_seconds=config.effective_verify_soak_seconds,
)
```

Find the `verify_trace_fn(...)` call (around line 130) and change `config.verify_soak_seconds` to `config.effective_verify_soak_seconds`:

```python
verify_trace_fn(
    image_tar,
    run_flags,
    image_tag,
    config.effective_verify_soak_seconds,
    layout.trace_verify_dir,
)
```

- [ ] **Step 4: Update `_default_install_trace_fn` in `src/containerizer/build/cli.py`**

```python
def _default_install_trace_fn(
    installer: Path,
    start_cmd: str | None,
    output_dir: Path,
    *,
    extra_installers: tuple[Path, ...] = (),
    apt_sources: tuple[str, ...] = (),
    apt_keys: tuple[Path, ...] = (),
    start_ready_seconds: int = 60,
    verify_soak_seconds: int = 30,
) -> int:
    image = RunnerImage(sandbox_dir=_sandbox_dir())
    if not image.exists():
        click.echo(f"[image] building {image.tag} (first run, ~5 min)...", err=True)
        image.build(stderr=sys.stderr)

    runner = TraceRunner(
        image_tag=image.tag,
        installer=installer.resolve(),
        output_dir=output_dir.resolve(),
        tty=sys.stdin.isatty(),
        extra_installers=extra_installers,
        apt_sources=apt_sources,
        apt_keys=apt_keys,
        start_cmd=start_cmd,
        start_ready_seconds=start_ready_seconds,
        verify_soak_seconds=verify_soak_seconds,
    )
    return runner.run()
```

The stale "reserved for future orchestrator env wiring" comment on `start_cmd` should be removed.

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/unit/build/test_pipeline.py tests/unit/build/test_cli.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/containerizer/build/pipeline.py src/containerizer/build/cli.py tests/unit/build/test_pipeline.py
git -c user.email="github.v5f9w@bitbucket.onl" -c user.signingkey=BE707B220C995478 commit -S -m "feat(build): thread start_ready_seconds and effective_verify_soak through pipeline (#105)"
```

---

## Task 7: README — Start command subsection in Install inputs

**Files:**
- Modify: `src/containerizer/generate/readme.py`
- Modify: `src/containerizer/generate/orchestrator.py`
- Modify: `src/containerizer/build/pipeline.py` (pass start-cmd args into generate_fn)
- Modify: `src/containerizer/build/cli.py::_default_generate_fn`
- Test: `tests/unit/generate/test_render_install_inputs.py`

- [ ] **Step 1: Write failing test**

Append to `tests/unit/generate/test_render_install_inputs.py`:

```python
def test_install_inputs_section_renders_start_command_when_set() -> None:
    section = _render_install_inputs(
        primary=Path("/x/unifi.deb"),
        extras=(),
        apt_sources=(),
        start_cmd="/etc/init.d/mongod start && sleep 10 && /etc/init.d/unifi start",
        start_ready_seconds=120,
        verify_soak_seconds=60,
    )
    assert "Start command:" in section
    assert "/etc/init.d/mongod start && sleep 10 && /etc/init.d/unifi start" in section
    assert "Ready timeout: 120s" in section
    assert "Verify soak: 60s" in section


def test_install_inputs_section_omits_start_command_when_unset() -> None:
    section = _render_install_inputs(
        primary=Path("/x/unifi.deb"),
        extras=(),
        apt_sources=(),
    )
    assert "Start command:" not in section
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/generate/test_render_install_inputs.py::test_install_inputs_section_renders_start_command_when_set tests/unit/generate/test_render_install_inputs.py::test_install_inputs_section_omits_start_command_when_unset -v`
Expected: FAIL — function rejects unknown kwargs `start_cmd`.

- [ ] **Step 3: Update `_render_install_inputs` and `render_readme`**

In `src/containerizer/generate/readme.py`:

```python
def _render_install_inputs(
    primary: Path | None,
    extras: tuple[Path, ...],
    apt_sources: tuple[str, ...],
    *,
    start_cmd: str | None = None,
    start_ready_seconds: int | None = None,
    verify_soak_seconds: int | None = None,
) -> str:
    """Render the 'Install inputs' section. Returns '' when nothing to render."""
    if primary is None and not extras and not apt_sources and start_cmd is None:
        return ""
    lines = ["## Install inputs\n"]
    if primary is not None:
        lines.append("Primary installer:")
        lines.append(f"- `{primary.name}`")
        lines.append("")
    if extras:
        lines.append("Additional installers:")
        for p in extras:
            lines.append(f"- `{p.name}`")
        lines.append("")
    if apt_sources:
        lines.append("apt sources:")
        for src in apt_sources:
            cleaned = _APT_BRACKET_OPTS.sub("", src).strip()
            lines.append(f"- `{cleaned}`")
        lines.append("")
    if start_cmd is not None:
        lines.append("Start command:")
        lines.append(f"- `{start_cmd}`")
        if start_ready_seconds is not None:
            lines.append(f"- Ready timeout: {start_ready_seconds}s")
        if verify_soak_seconds is not None:
            lines.append(f"- Verify soak: {verify_soak_seconds}s")
        lines.append("")
    return "\n".join(lines)
```

Update `render_readme` to accept and pass through the new args:

```python
def render_readme(
    policy: PolicyJson,
    name: str,
    *,
    skipped: bool,
    unknown_syscall_ids: list[int],
    install_primary: Path | None = None,
    install_extras: tuple[Path, ...] = (),
    install_apt_sources: tuple[str, ...] = (),
    install_start_cmd: str | None = None,
    install_start_ready_seconds: int | None = None,
    install_verify_soak_seconds: int | None = None,
) -> str:
    # ...existing body, but pass the new kwargs to _render_install_inputs:
    install_inputs = _render_install_inputs(
        install_primary,
        install_extras,
        install_apt_sources,
        start_cmd=install_start_cmd,
        start_ready_seconds=install_start_ready_seconds,
        verify_soak_seconds=install_verify_soak_seconds,
    )
    # ...rest unchanged
```

- [ ] **Step 4: Update `generate_all` in `src/containerizer/generate/orchestrator.py`**

```python
def generate_all(
    policy: PolicyJson,
    name: str,
    out_dir: Path,
    *,
    install_primary: Path | None = None,
    install_extras: tuple[Path, ...] = (),
    install_apt_sources: tuple[str, ...] = (),
    install_start_cmd: str | None = None,
    install_start_ready_seconds: int | None = None,
    install_verify_soak_seconds: int | None = None,
) -> list[int]:
    # ...existing body
    (out_dir / "README.md").write_text(
        render_readme(
            policy,
            name,
            skipped=is_sentinel,
            unknown_syscall_ids=unknown_ids,
            install_primary=install_primary,
            install_extras=install_extras,
            install_apt_sources=install_apt_sources,
            install_start_cmd=install_start_cmd,
            install_start_ready_seconds=install_start_ready_seconds,
            install_verify_soak_seconds=install_verify_soak_seconds,
        ),
        encoding="utf-8",
    )
    return unknown_ids
```

- [ ] **Step 5: Update `_default_generate_fn` in `src/containerizer/build/cli.py`**

```python
def _default_generate_fn(
    policy: PolicyJson,
    name: str,
    final_dir: Path,
    *,
    install_primary: Path | None = None,
    install_extras: tuple[Path, ...] = (),
    install_apt_sources: tuple[str, ...] = (),
    install_start_cmd: str | None = None,
    install_start_ready_seconds: int | None = None,
    install_verify_soak_seconds: int | None = None,
) -> None:
    unknown_ids = generate_all(
        policy,
        name,
        final_dir,
        install_primary=install_primary,
        install_extras=install_extras,
        install_apt_sources=install_apt_sources,
        install_start_cmd=install_start_cmd,
        install_start_ready_seconds=install_start_ready_seconds,
        install_verify_soak_seconds=install_verify_soak_seconds,
    )
    if unknown_ids:
        click.echo(
            f"warning: syscall IDs not in bundled table "
            f"(dropped from seccomp allowlist): {unknown_ids}",
            err=True,
        )
```

- [ ] **Step 6: Update pipeline `generate_fn` call in `src/containerizer/build/pipeline.py`**

```python
generate_fn(
    policy,
    config.name,
    layout.final_dir,
    install_primary=config.installer,
    install_extras=config.extra_installers,
    install_apt_sources=config.apt_sources,
    install_start_cmd=config.start_cmd,
    install_start_ready_seconds=config.start_ready_seconds if config.start_cmd else None,
    install_verify_soak_seconds=config.effective_verify_soak_seconds if config.start_cmd else None,
)
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `pytest tests/unit/generate/ tests/unit/build/ -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/containerizer/generate/readme.py src/containerizer/generate/orchestrator.py src/containerizer/build/pipeline.py src/containerizer/build/cli.py tests/unit/generate/test_render_install_inputs.py
git -c user.email="github.v5f9w@bitbucket.onl" -c user.signingkey=BE707B220C995478 commit -S -m "feat(generate): render Start command subsection in README install inputs (#105)"
```

---

## Task 8: Orchestrator — run_deb_install start-cmd block

**Files:**
- Modify: `sandbox/runner_image/trace-orchestrator.sh::run_deb_install`
- Test: `tests/unit/test_orchestrator_dispatch.py`

- [ ] **Step 1: Inspect existing dispatch tests**

Read `tests/unit/test_orchestrator_dispatch.py` to understand the test pattern (likely bash-script grep assertions). The new tests will mirror that pattern.

- [ ] **Step 2: Write failing test**

Append to `tests/unit/test_orchestrator_dispatch.py`:

```python
def test_run_deb_install_executes_start_cmd_post_phase_marker() -> None:
    """Issue #105: the run_deb_install function must contain a block that
    execs CONTAINERIZER_START_CMD inside deb-install after PHASE_MARKER."""
    from pathlib import Path

    script = Path("sandbox/runner_image/trace-orchestrator.sh").read_text(encoding="utf-8")
    # The block must be inside run_deb_install (between its function header
    # and the closing brace) — coarse-grain check that it sits AFTER the
    # PHASE_MARKER write.
    pm_idx = script.index('PHASE_MARKER')
    start_idx = script.index('CONTAINERIZER_START_CMD')
    assert start_idx > pm_idx, "start-cmd block must follow PHASE_MARKER write"
    assert 'podman exec deb-install bash -c "$CONTAINERIZER_START_CMD"' in script
    assert 'podman exec deb-install ss -tlnp' in script
    assert 'CONTAINERIZER_START_READY_SECONDS' in script
    assert 'CONTAINERIZER_VERIFY_SOAK_SECONDS' in script
    assert 'TRACE_DIR/start.log' in script
    assert 'TRACE_DIR/start.exitcode' in script
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/unit/test_orchestrator_dispatch.py::test_run_deb_install_executes_start_cmd_post_phase_marker -v`
Expected: FAIL — strings absent from script.

- [ ] **Step 4: Edit `sandbox/runner_image/trace-orchestrator.sh::run_deb_install`**

Locate the existing `awk … > "$TRACE_DIR/PHASE_MARKER"` line (around line 381). Insert this block IMMEDIATELY AFTER that line and BEFORE the `if [[ -n "${CONTAINERIZER_INTERACTIVE:-}" ]]; then interactive="${CONTAINERIZER_INTERACTIVE}"` lines (around line 383):

```bash
    if [[ -n "${CONTAINERIZER_START_CMD:-}" ]]; then
        echo "trace-orchestrator: starting daemon(s) via --start-cmd" >&2
        start_rc=0
        podman exec deb-install bash -c "$CONTAINERIZER_START_CMD" \
            > "$TRACE_DIR/start.log" 2>&1 || start_rc=$?
        echo "$start_rc" > "$TRACE_DIR/start.exitcode"

        # Ready-poll: any LISTEN line in the nested container, timeout fallback.
        deadline=$(( $(date +%s) + ${CONTAINERIZER_START_READY_SECONDS:-60} ))
        ready=0
        while (( $(date +%s) < deadline )); do
            if podman exec deb-install ss -tlnp 2>/dev/null | grep -q LISTEN; then
                echo "trace-orchestrator: daemon ready (LISTEN observed)" >&2
                ready=1
                break
            fi
            sleep 2
        done
        if (( ready == 0 )); then
            echo "trace-orchestrator: ready-poll timed out after ${CONTAINERIZER_START_READY_SECONDS:-60}s; proceeding" >&2
        fi

        # Runtime soak: let the daemon do real work before finalize. Reuses
        # CONTAINERIZER_VERIFY_SOAK_SECONDS (governs both install and verify
        # observation windows) -- pipeline resolves to max(60, start_ready_seconds)
        # when --start-cmd is set.
        sleep "${CONTAINERIZER_VERIFY_SOAK_SECONDS:-30}"
    fi
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/unit/test_orchestrator_dispatch.py -v`
Expected: PASS.

- [ ] **Step 6: Quick syntax check on the bash script**

Run: `bash -n sandbox/runner_image/trace-orchestrator.sh`
Expected: exit 0 (no output). If `bash` is unavailable on Windows PowerShell, run via WSL or skip — the integration test in Task 10 will catch syntax errors.

- [ ] **Step 7: Commit**

```bash
git add sandbox/runner_image/trace-orchestrator.sh tests/unit/test_orchestrator_dispatch.py
git -c user.email="github.v5f9w@bitbucket.onl" -c user.signingkey=BE707B220C995478 commit -S -m "feat(orchestrator): exec --start-cmd in deb-install after PHASE_MARKER (#105)"
```

---

## Task 9: Orchestrator — run_elf_install symmetric block

**Files:**
- Modify: `sandbox/runner_image/trace-orchestrator.sh::run_elf_install`
- Test: `tests/unit/test_orchestrator_dispatch.py`

- [ ] **Step 1: Write failing test**

Append to `tests/unit/test_orchestrator_dispatch.py`:

```python
def test_run_elf_install_executes_start_cmd_post_phase_marker() -> None:
    """Issue #105: symmetric block inside run_elf_install — start-cmd execs
    directly in the runner container (no podman exec prefix)."""
    from pathlib import Path

    script = Path("sandbox/runner_image/trace-orchestrator.sh").read_text(encoding="utf-8")
    elf_start = script.index('run_elf_install()')
    elf_end = script.index('run_deb_install()')
    elf_body = script[elf_start:elf_end]
    assert 'CONTAINERIZER_START_CMD' in elf_body
    assert 'bash -c "$CONTAINERIZER_START_CMD"' in elf_body
    # No podman exec inside the ELF block (it runs in the runner container directly).
    # Find the start-cmd exec line and confirm it isn't 'podman exec ... bash -c'.
    assert 'podman exec deb-install bash -c "$CONTAINERIZER_START_CMD"' not in elf_body
    # ss -tlnp polled directly (no podman exec prefix).
    assert 'ss -tlnp' in elf_body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_orchestrator_dispatch.py::test_run_elf_install_executes_start_cmd_post_phase_marker -v`
Expected: FAIL — strings absent from `run_elf_install` body.

- [ ] **Step 3: Edit `sandbox/runner_image/trace-orchestrator.sh::run_elf_install`**

Locate the existing `awk … > "$TRACE_DIR/PHASE_MARKER"` line inside `run_elf_install` (around line 234). Insert IMMEDIATELY AFTER it, BEFORE the `if [[ "$interactive" == 1 ]]; then` block (around line 236):

```bash
    if [[ -n "${CONTAINERIZER_START_CMD:-}" ]]; then
        echo "trace-orchestrator: starting daemon(s) via --start-cmd" >&2
        start_rc=0
        bash -c "$CONTAINERIZER_START_CMD" \
            > "$TRACE_DIR/start.log" 2>&1 || start_rc=$?
        echo "$start_rc" > "$TRACE_DIR/start.exitcode"

        deadline=$(( $(date +%s) + ${CONTAINERIZER_START_READY_SECONDS:-60} ))
        ready=0
        while (( $(date +%s) < deadline )); do
            if ss -tlnp 2>/dev/null | grep -q LISTEN; then
                echo "trace-orchestrator: daemon ready (LISTEN observed)" >&2
                ready=1
                break
            fi
            sleep 2
        done
        if (( ready == 0 )); then
            echo "trace-orchestrator: ready-poll timed out after ${CONTAINERIZER_START_READY_SECONDS:-60}s; proceeding" >&2
        fi

        sleep "${CONTAINERIZER_VERIFY_SOAK_SECONDS:-30}"
    fi
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_orchestrator_dispatch.py -v`
Expected: PASS.

- [ ] **Step 5: Bash syntax check**

Run: `bash -n sandbox/runner_image/trace-orchestrator.sh`
Expected: exit 0.

- [ ] **Step 6: Commit**

```bash
git add sandbox/runner_image/trace-orchestrator.sh tests/unit/test_orchestrator_dispatch.py
git -c user.email="github.v5f9w@bitbucket.onl" -c user.signingkey=BE707B220C995478 commit -S -m "feat(orchestrator): symmetric --start-cmd block in run_elf_install (#105)"
```

---

## Task 10: Integration test — daemon-bearing deb fixture with --start-cmd

**Files:**
- Modify: `tests/fixtures/probe/deb_helpers.py` (add a `postinst_payload` parameter)
- Modify: `tests/integration/trace/test_deb_pipeline.py`

- [ ] **Step 1: Extend the deb-builder fixture to accept a postinst script**

In `tests/fixtures/probe/deb_helpers.py`, extend `build_minimal_deb`:

```python
def build_minimal_deb(
    path: Path,
    *,
    package: str = "hello",
    version: str = "2.10-3",
    architecture: str = "amd64",
    depends: str = "libc6 (>= 2.34)",
    maintainer: str = "Test <test@example.com>",
    description: str = "test package\n A test package for containerizer.",
    systemd_unit: str | None = "hello.service",
    extra_unit_paths: list[str] | None = None,
    init_script_body: str | None = None,
    postinst_body: str | None = None,
) -> None:
    """Write a minimal but valid .deb to *path*.

    Issue #105: optional init_script_body installs an executable
    /etc/init.d/<package> with the supplied body. postinst_body adds a
    DEBIAN/postinst script (rendered into control.tar.gz, executable).
    """
    control_fields = [
        f"Package: {package}",
        f"Version: {version}",
        f"Architecture: {architecture}",
        f"Maintainer: {maintainer}",
        f"Depends: {depends}",
        f"Description: {description}",
        "",
    ]
    control_entries: dict[str, bytes] = {"control": "\n".join(control_fields).encode()}
    if postinst_body is not None:
        control_entries["postinst"] = postinst_body.encode()
    control_tar = _make_tar_gz_with_modes(
        {p: (b, 0o755 if p == "postinst" else 0o644) for p, b in control_entries.items()}
    )

    data_entries: dict[str, tuple[bytes, int]] = {
        f"./usr/bin/{package}": (b"#!/bin/sh\necho hello\n", 0o755),
    }
    if systemd_unit is not None:
        unit_body = (
            "[Unit]\nDescription=Hello service\n"
            "[Service]\nExecStart=/usr/bin/hello\n"
            "[Install]\nWantedBy=multi-user.target\n"
        )
        data_entries[f"./lib/systemd/system/{systemd_unit}"] = (unit_body.encode(), 0o644)
    if extra_unit_paths:
        extra_body = (
            "[Unit]\nDescription=Extra service\n"
            "[Service]\nExecStart=/usr/bin/true\n"
            "[Install]\nWantedBy=multi-user.target\n"
        )
        for ep in extra_unit_paths:
            data_entries[ep] = (extra_body.encode(), 0o644)
    if init_script_body is not None:
        data_entries[f"./etc/init.d/{package}"] = (init_script_body.encode(), 0o755)
    data_tar = _make_tar_gz_with_modes(data_entries)

    buf = io.BytesIO()
    buf.write(b"!<arch>\n")
    _ar_append(buf, "debian-binary", b"2.0\n")
    _ar_append(buf, "control.tar.gz", control_tar)
    _ar_append(buf, "data.tar.gz", data_tar)
    path.write_bytes(buf.getvalue())


def _make_tar_gz_with_modes(entries: dict[str, tuple[bytes, int]]) -> bytes:
    """Build a tar.gz where each entry is (content, mode)."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for path, (content, mode) in entries.items():
            info = tarfile.TarInfo(name=path)
            info.size = len(content)
            info.mode = mode
            tf.addfile(info, io.BytesIO(content))
    return buf.getvalue()
```

Keep the existing `_make_tar_gz` function untouched (still used by the existing path of `build_minimal_deb` if you prefer minimal-diff; otherwise route everything through the new helper as shown above).

- [ ] **Step 2: Write failing integration test**

Append to `tests/integration/trace/test_deb_pipeline.py`:

```python
@pytest.mark.integration
def test_deb_with_start_cmd_produces_non_sentinel_policy(tmp_path: Path) -> None:
    """Issue #105: --start-cmd fires a daemon, ready-poll observes LISTEN, soak
    captures runtime activity, analyzer derives a non-sentinel policy."""
    deb = tmp_path / "foo_1.0_amd64.deb"
    build_minimal_deb(
        deb,
        package="foo",
        version="1.0",
        depends="netcat-openbsd",  # nc is needed for the init script.
        systemd_unit=None,
        init_script_body=(
            "#!/bin/sh\n"
            "case \"$1\" in\n"
            "  start) (nc -l -p 9999 &) ; sleep 0.5 ;;\n"
            "  *) echo unsupported ;;\n"
            "esac\n"
        ),
    )

    out = tmp_path / "trace"
    out.mkdir()

    try:
        result = subprocess.run(
            [
                "containerizer", "trace", str(deb),
                "-o", str(out),
                "--start-cmd", "/etc/init.d/foo start",
                "--start-ready-seconds", "30",
                "--verify-soak-seconds", "5",
            ],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=900,
        )
    except subprocess.TimeoutExpired as exc:
        _dump_trace_dir(out, reason=f"TimeoutExpired after {exc.timeout}s")
        raise

    if result.returncode != 0:
        _dump_trace_dir(out, reason=f"returncode={result.returncode}")
        raise AssertionError(
            f"containerizer trace exited {result.returncode}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )

    try:
        assert (out / "COMPLETE").exists(), f"no COMPLETE marker; stderr:\n{result.stderr}"
        # New artifacts.
        assert (out / "start.log").exists()
        assert (out / "start.exitcode").exists()
        assert (out / "start.exitcode").read_text().strip() == "0"
        # bind.jsonl should mention port 9999 (the nc listener).
        bind = (out / "bind.jsonl").read_text(errors="replace")
        assert "9999" in bind, f"port 9999 not seen in bind.jsonl; head:\n{bind[:500]}"
    except AssertionError:
        _dump_trace_dir(out, reason="start-cmd integration assertion failure")
        raise
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/integration/trace/test_deb_pipeline.py::test_deb_with_start_cmd_produces_non_sentinel_policy -v -s`
Expected: FAIL — until all prior tasks land, either the orchestrator block isn't there or the env vars aren't propagated. (If you ran this AFTER all prior tasks merged, it should PASS now.)

- [ ] **Step 4: Verify the test passes after rebuilding the runner image**

The orchestrator change requires rebuilding the runner image. Force a rebuild:

```bash
podman image rm localhost/containerizer-runner --force 2>/dev/null || true
```

Then re-run the test:

Run: `pytest tests/integration/trace/test_deb_pipeline.py::test_deb_with_start_cmd_produces_non_sentinel_policy -v -s`
Expected: PASS. First run rebuilds the runner image (slow, ~5 min); subsequent runs reuse it.

- [ ] **Step 5: Commit**

```bash
git add tests/fixtures/probe/deb_helpers.py tests/integration/trace/test_deb_pipeline.py
git -c user.email="github.v5f9w@bitbucket.onl" -c user.signingkey=BE707B220C995478 commit -S -m "test(integration): daemon-bearing deb + --start-cmd end-to-end (#105)"
```

---

## Task 11: ELF integration test — --start-cmd inside runner container

**Files:**
- Create: `tests/integration/trace/test_elf_start_cmd.py`

- [ ] **Step 1: Write failing test**

Create `tests/integration/trace/test_elf_start_cmd.py`:

```python
"""Issue #105: ELF installer + --start-cmd symmetric wiring."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

_DUMP_DIR = Path("/tmp/trace-debug-dump")


def _dump_trace_dir(out: Path, *, reason: str) -> None:
    if _DUMP_DIR.exists():
        shutil.rmtree(_DUMP_DIR, ignore_errors=True)
    _DUMP_DIR.mkdir(parents=True, exist_ok=True)
    if out.exists():
        for child in out.iterdir():
            target = _DUMP_DIR / child.name
            try:
                shutil.copy2(child, target)
            except Exception as exc:  # pragma: no cover - best-effort
                print(f"[dump] copy {child} failed: {exc}", file=sys.stderr)
    print(f"\n=== trace dir dump (reason: {reason}) ===", file=sys.stderr)
    print(f"=== source: {out} ===", file=sys.stderr)
    print(f"=== saved to: {_DUMP_DIR} ===", file=sys.stderr)


@pytest.mark.integration
def test_elf_with_start_cmd_produces_runtime_observation(tmp_path: Path) -> None:
    """ELF installer is a no-op shell script that exits immediately; --start-cmd
    launches a nc listener; ready-poll observes LISTEN; soak captures activity."""
    installer = tmp_path / "install.sh"
    installer.write_text("#!/bin/sh\necho 'installed nothing'\nexit 0\n", encoding="utf-8")
    installer.chmod(0o755)

    out = tmp_path / "trace"
    out.mkdir()

    try:
        result = subprocess.run(
            [
                "containerizer", "trace", str(installer),
                "-o", str(out),
                "--start-cmd", "nc -l -p 9999 &",
                "--start-ready-seconds", "30",
                "--verify-soak-seconds", "5",
            ],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=900,
        )
    except subprocess.TimeoutExpired as exc:
        _dump_trace_dir(out, reason=f"TimeoutExpired after {exc.timeout}s")
        raise

    if result.returncode != 0:
        _dump_trace_dir(out, reason=f"returncode={result.returncode}")
        raise AssertionError(
            f"containerizer trace exited {result.returncode}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )

    try:
        assert (out / "COMPLETE").exists(), f"no COMPLETE marker; stderr:\n{result.stderr}"
        assert (out / "start.log").exists()
        assert (out / "start.exitcode").exists()
        bind = (out / "bind.jsonl").read_text(errors="replace")
        assert "9999" in bind, f"port 9999 not seen in bind.jsonl; head:\n{bind[:500]}"
    except AssertionError:
        _dump_trace_dir(out, reason="elf start-cmd assertion failure")
        raise
```

- [ ] **Step 2: Run test to verify it passes**

Run: `pytest tests/integration/trace/test_elf_start_cmd.py -v -s`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/trace/test_elf_start_cmd.py
git -c user.email="github.v5f9w@bitbucket.onl" -c user.signingkey=BE707B220C995478 commit -S -m "test(integration): ELF --start-cmd symmetric wiring (#105)"
```

---

## Task 12: MANUAL.md scenario 14 — UniFi + MongoDB

**Files:**
- Modify: `MANUAL.md`

- [ ] **Step 1: Read existing MANUAL.md scenarios to learn the format**

Run: Read `MANUAL.md` and pick the most recent scenario (likely 12 or 13 from issue #102) as the template.

- [ ] **Step 2: Append scenario 14**

At the end of `MANUAL.md`, append (adjust heading level to match prior scenarios):

```markdown
## Scenario 14 — UniFi 10.4.57 + MongoDB 8.0.26 with `--start-cmd` (#105)

Validates that a daemon-bearing multi-deb install yields a non-sentinel
Containerfile via `--start-cmd`. Requires:
- `unifi_sysvinit_all.deb` (10.4.x or compatible)
- `mongodb-org-server_8.0.x_amd64.deb`

Invocation:

```pwsh
containerizer build .\unifi_sysvinit_all.deb `
    --installer .\mongodb-org-server_8.0.26_amd64.deb `
    --name unifi `
    --start-cmd '/etc/init.d/mongod start && sleep 10 && /etc/init.d/unifi start' `
    --start-ready-seconds 120 `
    --keep-intermediates `
    --skip-verify
```

Expected `out/unifi/`:
- `Containerfile` exists and entrypoint references `java -jar /usr/lib/unifi/lib/ace.jar start` (or a comparable long-running JVM process)
- `unifi.container` Quadlet unit present
- `seccomp.json` non-empty
- `README.md` contains a `Start command:` subsection under `## Install inputs` listing the literal command, ready timeout 120s, verify soak 120s
- Runtime allowlist lists ports `8443`, `8080`, `8843`, `8880` for UniFi and `27017` for MongoDB
- Volumes include `/var/lib/mongodb` and `/usr/lib/unifi/data`

Known gotchas:
- JVM warmup + schema migration takes 30–90s; the 120s `--start-ready-seconds` and auto-scaled 120s verify-soak are the floor.
- If `/etc/init.d/unifi start` no-ops via `policy-rc.d=101` inside the non-systemd nested container, the user can fall back to:
  ```
  --start-cmd 'sudo -u mongodb /usr/bin/mongod --fork --config /etc/mongod.conf && sleep 5 && /usr/sbin/unifi-network-service-helper init && sudo -u unifi /usr/bin/java -jar /usr/lib/unifi/lib/ace.jar start &'
  ```
- UniFi requires `UNIFI_MONGODB_SERVICE_ENABLED=false` (default) — verify in `/etc/default/unifi` if MongoDB isn't reached.
```

- [ ] **Step 3: Commit**

```bash
git add MANUAL.md
git -c user.email="github.v5f9w@bitbucket.onl" -c user.signingkey=BE707B220C995478 commit -S -m "docs(MANUAL): scenario 14 UniFi+MongoDB --start-cmd flow (#105)"
```

---

## Final verification

- [ ] **Run the full unit suite**

Run: `pytest tests/unit -v`
Expected: PASS across all files touched (test_trace_runner, test_config, test_cli build/trace, test_render_install_inputs, test_orchestrator_dispatch, test_pipeline).

- [ ] **Run the affected integration tests**

Run: `pytest tests/integration/trace/test_deb_pipeline.py tests/integration/trace/test_elf_start_cmd.py -v -s`
Expected: PASS. These rebuild the runner image once; subsequent runs are fast.

- [ ] **Manually run scenario 14**

Follow `MANUAL.md` scenario 14. Verify the bullet list in that scenario.

- [ ] **Open PR**

Once all of the above pass and you've validated manually:

```bash
gh pr create --title "feat(trace,build): wire --start-cmd to start daemons during the runtime phase (#105)" --body "$(cat <<'EOF'
## Summary
- Wires `--start-cmd` end-to-end so daemon-bearing `.deb` installers (and install-then-exit ELF installers) start their daemons during the trace runtime phase
- After PHASE_MARKER: orchestrator execs the start command (`podman exec deb-install bash -c …` for deb; direct `bash -c …` for ELF), polls `ss -tlnp` for LISTEN with timeout fallback, sleeps a runtime-soak window before finalize
- `--verify-soak-seconds` auto-scales to `max(60s, --start-ready-seconds)` when `--start-cmd` is set; one resolved value drives both install-mode runtime soak and verify-mode soak
- Drops the "has no effect" warning on `--start-cmd`
- README's `## Install inputs` section gains a `Start command:` subsection

Closes #105.

## Test plan
- [ ] `pytest tests/unit -v` passes
- [ ] `pytest tests/integration/trace/test_deb_pipeline.py tests/integration/trace/test_elf_start_cmd.py -v -s` passes
- [ ] `MANUAL.md` scenario 14 (UniFi + MongoDB) yields a non-sentinel Containerfile referencing port 8443 / 27017 and `java -jar ace.jar`

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Do NOT push or merge without user confirmation.
