# Issue #105 — Wire `--start-cmd` to actually start daemons during the runtime phase

**Date:** 2026-06-21
**Status:** Draft (brainstorming)
**Parent spec:** [`2026-06-06-containerizer-design.md`](./2026-06-06-containerizer-design.md)
**Prior milestone specs:** [`2026-06-20-containerizer-issue-99-deb-support.md`](./2026-06-20-containerizer-issue-99-deb-support.md), [`2026-06-21-containerizer-issue-102-multi-deb.md`](./2026-06-21-containerizer-issue-102-multi-deb.md)
**Issue:** [#105](https://github.com/SupremeCommanderHedgehog/containerizer/issues/105)

## 1. Overview

`containerizer build` reserves `--start-cmd` today but only emits a warning that it has no effect. For ELF installers that auto-daemonize during their own install (UniFi OS Server M2 driving case), the missing wiring doesn't matter — the installer itself starts the daemon, the runtime phase observes it, the analyzer derives a policy. For `.deb` installers (#99) the install transaction completes inside a nested `ubuntu:24.04` container running `sleep infinity` without systemd, so postinst's `systemctl start <unit>` no-ops via `policy-rc.d=101`. No daemon runs, the analyzer emits the sentinel entrypoint, and M4 correctly refuses to generate `Containerfile` + Quadlet — the user gets only `seccomp.json` and a `README.md` documenting the SKIPPED state.

Reproduced 2026-06-21 against real-world UniFi 10.4.57 + MongoDB 8.0.26: apt installed all 239 packages cleanly post-#102, but no Containerfile shipped.

This spec wires `--start-cmd` through to fire a user-supplied daemon-start command inside the install container after PHASE_MARKER, polls for the daemon to bind a port, then soaks for a runtime observation window before finalizing the trace. The orchestrator then captures the daemon's steady-state syscalls/binds/caps and the analyzer derives a usable policy.

After this change, the UniFi flow becomes:

```pwsh
containerizer build .\unifi_sysvinit_all.deb `
    --installer .\mongodb-org-server_8.0.26_amd64.deb `
    --name unifi `
    --start-cmd '/etc/init.d/mongod start && sleep 10 && /etc/init.d/unifi start' `
    --start-ready-seconds 120
```

## 2. Scope

### In this change

- `src/containerizer/trace/runner.py` — `TraceRunner` gains `start_cmd: str | None = None` and `start_ready_seconds: int = 60`, install-mode-only (validated to be unset in verify mode like `extra_installers`/`apt_sources`/`apt_keys`). Install-mode argv conditionally adds `-e CONTAINERIZER_START_CMD=…` and `-e CONTAINERIZER_START_READY_SECONDS=…`, plus an unconditional `-e CONTAINERIZER_VERIFY_SOAK_SECONDS=…` (the install-mode runtime-soak window — see §3.2). Verify mode keeps its existing `VERIFY_SOAK_SECONDS` env.
- `sandbox/runner_image/trace-orchestrator.sh` — `run_deb_install` gains a new block between `PHASE_MARKER` write and the interactive/finalize branch: exec `bash -c "$CONTAINERIZER_START_CMD"` inside `deb-install`, poll `podman exec deb-install ss -tlnp` for any LISTEN line with a timeout fallback, then `sleep $CONTAINERIZER_VERIFY_SOAK_SECONDS` to let the daemon do steady-state work before finalize. `run_elf_install` gets the symmetric block — start-cmd execs directly inside the runner container (no nested container), ready-poll runs `ss -tlnp` without the `podman exec` prefix.
- `src/containerizer/build/cli.py` — drop the "has no effect" warning. Add `--start-ready-seconds INTEGER` (default 60). Validate: `--start-ready-seconds` without `--start-cmd` is a user error (clear message, non-zero exit). Refactor `--verify-soak-seconds` Click default to `None` so the pipeline can distinguish "user explicitly set 30" from "user didn't set anything"; resolve to `30` or `max(60, start_ready_seconds)` in `BuildConfig` based on whether `start_cmd` is set.
- `src/containerizer/trace/cli.py` — same three flag additions (`--start-cmd`, `--start-ready-seconds`, `--verify-soak-seconds`) for symmetry; `containerizer trace` is the lower-level entry point and should accept the same surface.
- `src/containerizer/build/config.py` — `BuildConfig` gains `start_ready_seconds: int = 60`. `start_cmd` already exists. Add a derived property or `__post_init__` resolver for `effective_verify_soak_seconds` (raw value if explicit, else `max(60, start_ready_seconds)` when `start_cmd` set, else `30`).
- `src/containerizer/build/pipeline.py` — `run_pipeline` forwards `start_ready_seconds` and the resolved verify-soak to `install_trace_fn`; `install_trace_fn` passes both to `TraceRunner`. Verify-mode runner already gets the resolved soak via the existing path.
- `src/containerizer/generate/readme.py` — `_render_install_inputs` learns optional `start_cmd: str | None`, `start_ready_seconds: int | None`, `verify_soak_seconds: int | None` arguments. When `start_cmd` is set, render a "Start command" subsection inside `## Install inputs` listing the verbatim command plus the resolved ready/soak windows. Pipeline + `generate_all` pass these through.
- Unit tests across `tests/unit/trace/test_runner.py`, `tests/unit/build/test_config.py`, `tests/unit/build/test_cli.py`, `tests/unit/generate/test_readme.py`.
- Integration tests in `tests/integration/trace/test_deb_pipeline.py` (daemon-bearing fixture deb) and a sibling ELF integration test in `tests/integration/trace/test_elf_pipeline.py` or extension of the existing ELF integration test.
- `MANUAL.md` scenario 14 documenting the real-world UniFi+MongoDB flow end-to-end.

### Carried unchanged

- `src/containerizer/probe/*` — probe is unaffected; the daemon-start hint is a runtime-phase concern, not a probe output.
- `src/containerizer/analyze/*` — the analyzer consumes whatever events the trace produced. The sentinel-entrypoint path already exists (#99) and remains the correct response when `--start-cmd` is omitted or the daemon never binds.
- `src/containerizer/verify/*` — verify-mode orchestrator is unchanged; the resolved `verify_soak_seconds` flows through the existing config field.
- `sandbox/runner_image/Containerfile` — no image-build-time changes. `ss` (from `iproute2`) is already present in `ubuntu:24.04` and in the runner image.
- Single-shot invocations without `--start-cmd` continue to work byte-identically. New fields default to "off"; new env vars are not set; the orchestrator's new block is gated on `${CONTAINERIZER_START_CMD:-}`.

### Out of scope (deferred)

- **Multi-daemon orchestration.** Users compose the full start command themselves (e.g., `'/etc/init.d/mongod start && sleep 10 && /etc/init.d/unifi start'`). Containerizer doesn't parse, sequence, or model individual daemons.
- **`Delegate=yes` on `containerizer-trace.service`.** Letting nested `--systemd=always` work natively (so `systemctl start unifi` runs without `--start-cmd`) is the cleaner long-term answer, but a bigger lift with real CI risk. `--start-cmd` is the pragmatic unblock. Tracked as a follow-up.
- **Auto-discovery of daemon-start.** No heuristic that reads the deb's systemd unit file and synthesizes a start command. Too many edge cases. A future "suggestion-only" warning (emit `/etc/init.d/<basename> start` as a hint when `DebProbe.systemd_units` is non-empty and the user didn't supply `--start-cmd`) is plausible follow-up but not in this PR.
- **Run-time config injection.** UniFi expects `UNIFI_MONGODB_SERVICE_ENABLED=false` etc. Users set these via `/etc/default/unifi` inside their `--start-cmd` if needed; no first-class flag.
- **`--start-ready-cmd` (custom readiness probe).** All driving real-world cases (UniFi, MongoDB) bind TCP. Adding a user-supplied readiness command is real CLI surface for a problem we don't have yet. The timeout fallback degrades gracefully for non-TCP daemons (queue workers, unix-socket services) — they always pay the full window. Revisit if a concrete non-TCP user appears.
- **Strict-fail on no LISTEN by timeout.** Existing sentinel-entrypoint handling already surfaces "your start-cmd didn't actually start a daemon" loudly: README ships SKIPPED with the sentinel warning in the audit trail. No second mechanism needed.
- **`--start-cmd` interpolation / templating.** Verbatim string. Users assemble shell themselves.

## 3. Architecture

### 3.1 Transport (`src/containerizer/trace/runner.py`)

`TraceRunner` gains two install-mode-only fields:

```python
start_cmd: str | None = None
start_ready_seconds: int = 60
```

`__post_init__` validates that both are absent in verify mode (`ValueError` like the existing install-only fields).

`_install_argv` adds three env vars:

```python
*(("-e", f"CONTAINERIZER_START_CMD={self.start_cmd}",
   "-e", f"CONTAINERIZER_START_READY_SECONDS={self.start_ready_seconds}")
  if self.start_cmd else ()),
"-e", f"CONTAINERIZER_VERIFY_SOAK_SECONDS={self.verify_soak_seconds}",
```

The existing `verify_soak_seconds: int | None` field is reused for both modes. Verify-mode validation already requires it non-None; install-mode reads it whenever set (pipeline always resolves to a concrete int — see §3.4). When neither `start_cmd` nor an explicit `--verify-soak-seconds` is supplied, the pipeline resolves to 30 and the env var still flows through (the install-mode orchestrator's runtime-soak `sleep` is gated on `${CONTAINERIZER_START_CMD:-}` so this is a no-op for non-start-cmd runs).

### 3.2 Orchestrator `run_deb_install` block

Inserted between the `PHASE_MARKER` write (line ~381) and the interactive/finalize branch (line ~383):

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

    # Runtime soak: let the daemon do real work before finalize.
    sleep "${CONTAINERIZER_VERIFY_SOAK_SECONDS:-30}"
fi
```

Design notes:

- `|| start_rc=$?` (not `|| true`) so we capture the exit code in `start.exitcode` for diagnostics. Matches the `installer.exitcode` pattern.
- We do **not** fail-fast on non-zero start. `init.d start` scripts can exit 0 while the daemon backgrounds; some return non-zero in benign cases (e.g., "already running" when a previous run leaked state — not applicable for our fresh container, but the principle holds). The sentinel-entrypoint path in M4 catches the "no daemon ran" case downstream.
- Ready-poll uses `ss -tlnp` (TCP listen, with process info). `grep -q LISTEN` matches any LISTEN line. We do not inspect specific ports — the user's `--start-cmd` may start a daemon on any port; the analyzer derives `publish_ports` from observed `bind` events independently.
- Timeout fallback is "proceed anyway" rather than fail. Non-TCP daemons (unix-socket, queue workers) always pay the full window. The analyzer downstream produces the sentinel + SKIPPED README if no useful daemon activity was observed.
- Runtime soak reads `CONTAINERIZER_VERIFY_SOAK_SECONDS` — the shared knob across install and verify phases (see §3.4). Defaults to 30s.
- The existing `podman stop -t 10 deb-install` at line ~398 sends SIGTERM to PID 1 (`sleep infinity`), wait 10s, SIGKILL. The daemon goes with it. Daemon shutdown syscalls land in the trace — useful for the analyzer.

### 3.3 Orchestrator `run_elf_install` symmetric block

Inserted between the `PHASE_MARKER` write (line ~234) and the interactive/finalize branch (line ~236):

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

Differences from the deb block:

- No `podman exec deb-install` prefix. start-cmd execs directly inside the trace runner container. The runner container's network namespace is `--network=host`-equivalent for these purposes; bpftrace and collectors don't bind ports, so `ss -tlnp` cleanly sees whatever the daemon started.
- The block fires only after the installer's foreground/backgrounded process has exited (the existing `wait "$installer_pid"` already gated this). ELF installers that themselves daemonize (UniFi OS Server M2 case) never let `wait` return, so `--start-cmd` is irrelevant for them — by construction.

### 3.4 Soak resolution (`src/containerizer/build/config.py`, `cli.py`, `pipeline.py`)

`BuildConfig` gains:

```python
start_ready_seconds: int = 60
# verify_soak_seconds becomes Optional with sentinel-None default.
verify_soak_seconds: int | None = None
```

A derived helper resolves the effective value:

```python
@property
def effective_verify_soak_seconds(self) -> int:
    if self.verify_soak_seconds is not None:
        return self.verify_soak_seconds
    if self.start_cmd is not None:
        return max(60, self.start_ready_seconds)
    return 30
```

`build/cli.py` defaults `--verify-soak-seconds` to `None` instead of `30`:

```python
@click.option("--verify-soak-seconds", type=int, default=None,
              help="Soak window (default 30s; 60s when --start-cmd is set, "
                   "or --start-ready-seconds if larger).")
```

`run_pipeline` reads `config.effective_verify_soak_seconds` and passes it to both:

- `install_trace_fn(..., verify_soak_seconds=...)` → `TraceRunner.verify_soak_seconds` (install mode) → install-mode argv `-e CONTAINERIZER_VERIFY_SOAK_SECONDS=…`.
- `verify_trace_fn(..., soak_seconds=...)` (existing) → `TraceRunner.verify_soak_seconds` (verify mode) → verify-mode argv `-e VERIFY_SOAK_SECONDS=…`.

One TraceRunner field serves both modes — install-mode argv reads it whenever non-None (pipeline always resolves to a concrete int). Two distinct env-var names (`CONTAINERIZER_VERIFY_SOAK_SECONDS` for install, `VERIFY_SOAK_SECONDS` for verify) so the verify-orchestrator's existing env-var contract stays unchanged. Renaming to a single shared name is a follow-up cleanup.

CLI validation: `--start-ready-seconds` without `--start-cmd` raises `click.UsageError` so the user catches the mistake at parse time instead of confusion when the value is ignored.

### 3.5 README rendering (`src/containerizer/generate/readme.py`)

`_render_install_inputs` signature extends with three optional arguments:

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
```

When `start_cmd` is set, append after the existing `apt sources:` block:

```markdown
Start command:
- `/etc/init.d/mongod start && sleep 10 && /etc/init.d/unifi start`
- Ready timeout: 120s
- Verify soak: 60s
```

`generate_all` and `render_readme` thread the three new arguments through. `pipeline.run_pipeline` passes `config.start_cmd`, `config.start_ready_seconds`, `config.effective_verify_soak_seconds` to `generate_fn`.

### 3.6 Trace artifacts

Two new files in `trace_dir/`:

- `start.log` — stdout+stderr of the start-cmd execution.
- `start.exitcode` — integer exit code of the start-cmd shell.

Existing artifacts (`COMPLETE`, `PARTIAL`, `PHASE_MARKER`, `install.log`, `installer.exitcode`, etc.) unchanged.

## 4. Testing

### Unit

- `tests/unit/trace/test_runner.py`:
  - Install-mode argv contains `-e CONTAINERIZER_START_CMD=...` and `-e CONTAINERIZER_START_READY_SECONDS=...` when `start_cmd` set; both absent when unset; `CONTAINERIZER_VERIFY_SOAK_SECONDS` always present (governs runtime soak).
  - Verify-mode rejects `start_cmd` and `start_ready_seconds` like it rejects `extra_installers`.
- `tests/unit/build/test_config.py`:
  - `effective_verify_soak_seconds` returns 30 when `start_cmd` is None.
  - Returns `max(60, start_ready_seconds)` when `start_cmd` set and `verify_soak_seconds` is None.
  - Returns the explicit `verify_soak_seconds` value when set, regardless of `start_cmd`.
- `tests/unit/build/test_cli.py`:
  - `--start-ready-seconds` without `--start-cmd` errors with non-zero exit and a clear message.
  - "no effect" warning is gone.
- `tests/unit/generate/test_readme.py`:
  - Install-inputs section renders the Start command subsection when `start_cmd` is set.
  - Section omitted entirely (existing behaviour) when `start_cmd` is None.

### Integration

A new daemon-bearing fixture deb shipped under `tests/fixtures/`. Minimal recipe: a postinst that drops `/etc/init.d/foo` with a single-line script invoking `nc -l -p 9999 &` plus a `pidof` check. The deb has no other payload and no systemd unit (deliberately — so the existing run_deb_install path is exercised without --systemd=always interactions).

- `tests/integration/trace/test_deb_pipeline.py` gains `test_start_cmd_daemon_observed`:
  - `containerizer build foo.deb --start-cmd '/etc/init.d/foo start' --start-ready-seconds 10 --name foo`.
  - Asserts: `COMPLETE` marker, `start.exitcode == 0`, trace JSONL contains a bind event on port 9999, generated `Containerfile` exists, policy entrypoint is non-sentinel, `runtime.publish_ports` contains 9999.
- `tests/integration/trace/test_elf_pipeline.py` (new or extension): a fixture shell-script installer that drops a tiny binary and exits, paired with `--start-cmd 'nc -l -p 9999 &'`. Same assertions shape.

### Manual

`MANUAL.md` scenario 14: real-world UniFi 10.4.57 + MongoDB 8.0.26 end-to-end. Documents the full invocation including `--installer mongodb-org-server_8.0.26_amd64.deb`, `--start-cmd '/etc/init.d/mongod start && sleep 10 && /etc/init.d/unifi start'`, `--start-ready-seconds 120`. Expected output: non-sentinel Containerfile, ports 8443/8080/8843/8880 + 27017 in policy, volumes for `/var/lib/mongodb` and `/usr/lib/unifi/data`.

## 5. Acceptance criteria

- [ ] `containerizer build foo.deb --start-cmd '/etc/init.d/foo start' --name foo` against the daemon-bearing fixture deb produces non-sentinel `Containerfile`, `foo.container` Quadlet, `seccomp.json`, and `README.md` listing port 9999.
- [ ] CLI no longer warns "has no effect" on `--start-cmd`.
- [ ] `--start-ready-seconds INTEGER` accepted on both `containerizer build` and `containerizer trace`, defaults to 60, validated to require `--start-cmd`.
- [ ] `--verify-soak-seconds` defaults to None at the CLI; `BuildConfig.effective_verify_soak_seconds` resolves correctly across all three cases (explicit, --start-cmd auto-scale, neither).
- [ ] Both unit and integration test suites green; ELF symmetric integration test passes.
- [ ] README renders the Start command subsection in `## Install inputs` when `--start-cmd` was supplied.
- [ ] `trace_dir/start.log` and `trace_dir/start.exitcode` written when `--start-cmd` runs.
- [ ] `MANUAL.md` scenario 14 documented for follow-up manual validation.

## 6. Risks and open questions

- **Analyzer entrypoint inference on Java daemons.** UniFi runs `java -jar /usr/lib/unifi/lib/ace.jar start`. The existing entrypoint-inference logic (systemd_required heuristic, etc.) was developed against native daemons. JVM daemons may need a long-running-java-process heuristic. Investigate during implementation; if the analyzer picks the wrong entrypoint, file a follow-up issue rather than expand this PR's scope.
- **SysV-init scripts in non-systemd nested container.** `/etc/init.d/<unit> start` may silently no-op via `policy-rc.d=101` in the same way postinst's `systemctl start` does. Test inside `podman run ubuntu:24.04` (no systemd) after apt-installing the fixture deb. If init.d scripts also no-op, the fallback in the user's `--start-cmd` is uglier (`sudo -u mongodb /usr/bin/mongod --fork --config /etc/mongod.conf && ...`). Document the limitation in MANUAL.md scenario 14 if this is the case; the design itself doesn't change.
- **Ready-poll false positives.** `ss -tlnp | grep -q LISTEN` matches any LISTEN line. If the install transaction itself left a process listening on a port (atypical — apt and dpkg don't bind), the readiness probe would trigger immediately before the daemon is actually up. Not a real concern for the driving cases but worth a note for future debugging.
- **Symmetric ELF wiring with a future runner-side listener.** Today the trace runner container binds no ports. If a future change adds a listener inside the runner (e.g., a debug control socket), the ELF ready-poll would see it pre-start-cmd and fire instantly. Mitigation deferred until concrete — current state is safe.

## 7. Follow-ups noted but not in this PR

- **`Delegate=yes` on `containerizer-trace.service`.** Would let nested `--systemd=always` work, making `--start-cmd` unnecessary for systemd-aware packages. File as a separate issue; size and CI risk are bigger.
- **Per-deb auto `--start-cmd` hint.** When `DebProbe.systemd_units` is non-empty and the user didn't supply `--start-cmd`, emit a build-time WARNING with a suggested command. Suggestion-only; never run unprompted.
- **`--start-cmd` with verify mode.** The verify orchestrator already runs the generated container under strict policy with the policy's own entrypoint. If `--start-cmd` produced a viable Containerfile, verify exercises the generated entrypoint naturally. No special wiring needed.
- **Non-TCP readiness probe.** When a real user surfaces with a queue worker or unix-socket daemon, revisit `--start-ready-cmd`.
