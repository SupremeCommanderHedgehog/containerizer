# M2 — Sandbox + Trace Spec

**Date:** 2026-06-06
**Status:** Approved (brainstorming)
**Parent spec:** [`2026-06-06-containerizer-design.md`](./2026-06-06-containerizer-design.md)
**Milestone issues:** #23–#37 (M2), #38–#44 (M3+)

## 1. Overview

M2 stands up the trace half of the containerizer. After M2, the user can run

```pwsh
PS> containerizer trace .\unifi-installer.bin -o .\unifi-trace\
```

and end up with six per-collector JSONL streams plus an `install.log` and a `COMPLETE` / `PARTIAL` marker in `unifi-trace\`. **Nothing in M2 interprets that output** — no `trace.json`, no `policy.json`, no `Containerfile`. The analyzer and generators are M3+.

The point of cutting M2 narrow is to drive the privileged sandbox and the six collectors to "verifiably observes the right events" before paying any of the analyzer's cost. The integration test gates on the JSONL streams existing with expected events; the M3 analyzer can then iterate against frozen JSONL fixtures.

## 2. Scope

### In M2

- `sandbox/runner_image/` — Containerfile + orchestrator + collectors, lazy-built locally on first `containerizer trace`.
- `src/containerizer/trace/` — Python host wrapper (`image.py`, `runner.py`, `cli.py`).
- `tests/fixtures/trace/synthetic-installer.sh` — deterministic shell script exercising every collector.
- `tests/integration/trace/test_trace_pipeline.py` — `@pytest.mark.integration`-gated end-to-end test.
- New `trace-integration` CI job on ubuntu-latest, plus the branch-protection update to require it.

### Out of M2 (deferred to M3+)

- The analyzer (`src/containerizer/trace/analyzer.py`, `schema.py`, `paths.py`) — issue #38.
- Policy derivation (`policy.json`) — issue #39.
- Generators (Containerfile, Quadlet, seccomp) — issues #40, #41, #42.
- `verify` subcommand — issue #43.
- `build` subcommand (full pipeline orchestration) — issue #44.
- Caching of the runner image build in CI — eaten as a ~5 min cost per PR for now.
- Pushing the runner image to a registry — purely local build.

### Carried unchanged from the parent design spec

- Sandbox topology: a privileged container on the user's existing Podman machine (parent §2 non-goals).
- Collector set and JSONL schemas (parent §5.5).
- Phase model: install phase → user-driven smoke test → finalize (parent §5.4).
- `COMPLETE` vs `PARTIAL` marker semantics (parent §5.4).

## 3. Reading guide

This spec narrows the parent design spec's §5.3 (sandbox runner), §5.4 (orchestrator), and §5.5 (collectors) for the M2 cut. Where this spec is silent, the parent spec is authoritative. Where this spec contradicts the parent, this spec wins for M2 and the parent gets updated when M2 lands.

## 4. Decisions captured from the M2 brainstorm

| Decision | Choice | Rationale |
|---|---|---|
| M2 scope | Narrow: sandbox + raw JSONL only | Smallest cut that proves the trace half end to end; M3 analyzer iterates against frozen fixtures. |
| Image lifecycle | Lazy local `podman build` on first `containerizer trace` | No registry hosting, no CI publish workflow. Fits private personal repo. |
| Collectors shipped | All six per parent spec §5.5 | open + bind + syscalls (bpftrace) + tcpconnect + tcpaccept + capable (bcc). |
| Integration test fixture | Synthetic shell script | <1s, deterministic, total control over expected events; CI-friendly. |
| CI runner | GitHub Actions `ubuntu-latest` | Kernel ≥5.15 has BTF + eBPF; supports privileged containers. |
| Base distro | Fedora 41 | First-class `bcc-tools` + `bpftrace` packages, BTF in stock kernel, systemd-as-PID-1 supported. |
| CI image cache | None for M2 | Simpler; ~5 min build cost per PR is acceptable initially; optimise later. |
| Runner image tag | `localhost/containerizer-runner:sha-<hex8>` from `sha256(sandbox/runner_image/**)` | Change-driven rebuilds; reproducible. |

## 5. File layout

```
sandbox/runner_image/                       NEW top-level dir
  Containerfile                             Fedora 41 base + tooling + orchestrator + collectors
  trace-orchestrator.sh                     Bash orchestrator (parent §5.4)
  collectors/
    open.bt           bind.bt           syscalls.bt     bpftrace scripts
    tcpconnect.py     tcpaccept.py      capable.py      bcc-tools wrappers

src/containerizer/trace/                    NEW Python module
  __init__.py
  cli.py                                    Click `trace` subcommand
  image.py                                  Lazy build + hash-based tag
  runner.py                                 `podman run` construction + exec

tests/
  fixtures/trace/
    synthetic-installer.sh                  Deterministic fixture
  unit/
    test_trace_image.py                     Mock-subprocess: hash → tag, missing-image detect
    test_trace_runner.py                    Argv construction, output-dir validation
    test_trace_cli.py                       Click surface, pre-flight error messages
  integration/trace/
    __init__.py
    test_trace_pipeline.py                  @pytest.mark.integration, runs the real thing

.github/workflows/ci.yml                    + `trace-integration` job
```

## 6. Components

### 6.1 Runner image — `sandbox/runner_image/Containerfile`

Issue #23.

```dockerfile
FROM fedora:41

# Trace tooling. bcc + bpftrace need kernel headers / BTF on the host, which
# Fedora 41's stock kernel provides; nothing kernel-specific is needed inside
# the image itself.
RUN dnf install -y --setopt=install_weak_deps=False \
      systemd dbus \
      bcc-tools bpftrace strace audit-libs audit \
      jq python3 \
    && dnf clean all

# Orchestrator + collectors live under /opt/containerizer/ so /usr is not
# polluted with project-specific files.
COPY trace-orchestrator.sh /opt/containerizer/trace-orchestrator.sh
COPY collectors/           /opt/containerizer/collectors/
RUN chmod +x /opt/containerizer/trace-orchestrator.sh \
             /opt/containerizer/collectors/*.py

ENTRYPOINT ["/opt/containerizer/trace-orchestrator.sh"]
```

Image is ~600 MB. Built once via `podman build sandbox/runner_image/`, tagged from the host wrapper.

### 6.2 Orchestrator — `sandbox/runner_image/trace-orchestrator.sh`

Issues #24 (orchestrator), #25 (strace fallback).

Bash. Sequence (lifted from parent §5.4):

1. Receive the installer path as `$1` (mounted at `/installer:ro`).
2. For each collector in `/opt/containerizer/collectors/`, launch it backgrounded with stdout redirected to `/work/trace/<name>.jsonl` and stderr to `/work/trace/<name>.err`. Record the PID.
3. Wait 2 seconds for collectors to attach. For any collector whose process died, log the failure and start the strace fallback for that collector's coverage area (file or network).
4. Exec the installer; `tee` stdout+stderr to `/work/trace/install.log` so the user can scroll back.
5. On installer exit, write `/work/trace/PHASE_MARKER` containing `monotonic_ns: <ns>`.
6. Print to stderr: `software is running. exercise it now, then press <Enter> here to finalise.`
7. Read stdin one line. **Both Enter (`\n`) and EOF (stdin closed)** trigger the COMPLETE path: send SIGTERM to each collector PID; sleep 1s; SIGKILL anything still alive; write `/work/trace/COMPLETE`; exit 0. (EOF support is what lets the integration test finalise without typing — see §6.7.)
8. On SIGINT: same finalize path but write `/work/trace/PARTIAL` instead of `COMPLETE`.

The bash choice (over Python) is deliberate: the orchestrator is signal-driven process management, which is what bash is good at, and avoids pulling Python startup cost on every trace.

### 6.3 Collectors — `sandbox/runner_image/collectors/`

Issues #26–#31.

| File | Tool | Tracepoint / probe | Output | Schema |
|---|---|---|---|---|
| `open.bt` | bpftrace | `tracepoint:syscalls:sys_enter_openat` (and `sys_enter_open` if present) | `open.jsonl` | `{ts_ns, pid, comm, path, flags, mode, ret}` |
| `bind.bt` | bpftrace | `tracepoint:syscalls:sys_enter_bind` | `bind.jsonl` | `{ts_ns, pid, comm, family, addr, port, proto}` |
| `syscalls.bt` | bpftrace | `raw_syscalls:sys_enter` | `syscalls.jsonl` | `{pid, comm, syscall_id, count, first_ts_ns}` rolled up per (pid, syscall_id), flushed on `END` |
| `tcpconnect.py` | bcc-tools (`tcpconnect`) | kprobe on `tcp_v4_connect` / `tcp_v6_connect` | `connect.jsonl` | `{ts_ns, pid, comm, saddr, sport, daddr, dport, family}` |
| `tcpaccept.py` | bcc-tools (`tcpaccept`) | kretprobe on `inet_csk_accept` | `accept.jsonl` | `{ts_ns, pid, comm, laddr, lport, raddr, rport, family}` |
| `capable.py` | bcc-tools (`capable`) | kprobe on `cap_capable` | `capable.jsonl` | `{ts_ns, pid, comm, cap, audit, ret}` |

The bcc wrappers prefer using bcc as a Python library (importing `bcc.BPF` and emitting JSONL directly) over scraping the human-readable text output of the upstream tool. The bpftrace scripts use `printf` of a JSON-shaped string per event — bpftrace supports this directly.

### 6.4 Strace fallback — `sandbox/runner_image/trace-orchestrator.sh` (continued)

Issue #25.

If a collector exits before the installer is launched (failed kernel attach, missing BTF, missing kheaders), the orchestrator records the failure in `/work/trace/FALLBACKS.json`:

```json
{"open.bt": {"reason": "attach failed: no BTF", "fallback": "strace -e trace=file"}}
```

and starts `strace -f -e trace=file` or `strace -f -e trace=network` on the installer (and later the daemon) covering the failed collector's domain. Strace output goes to `/work/trace/<collector>.fallback.log` in strace's native format — the M3 analyzer can convert if needed.

The host wrapper surfaces the FALLBACKS file in its post-run summary so the user knows their trace was partially downgraded.

### 6.5 Host wrapper — `src/containerizer/trace/`

Issues #32 (`image.py`), #33 (`runner.py`), #34 (`cli.py`).

**`image.py` — `RunnerImage`**

```python
class RunnerImage:
    sandbox_dir: Path              # sandbox/runner_image/

    @cached_property
    def tag(self) -> str:
        """localhost/containerizer-runner:sha-<first 8 of sha256 of dir>"""

    def exists(self) -> bool:
        """podman image exists self.tag"""

    def build(self, *, stderr: IO[str]) -> None:
        """podman build -t self.tag self.sandbox_dir
        streams stderr to the caller's stream (typically click.get_text_stream('stderr'))"""
```

`tag` is computed by walking `sandbox_dir` recursively, sorting the resulting file list by relative path (lexicographic, normalised to forward slashes), and feeding each file's relative path bytes + `\x00` + file content bytes into a single SHA-256. The first 8 hex chars of the digest form the tag suffix: `localhost/containerizer-runner:sha-a3f1b2c4`. Reproducible across machines for the same `sandbox_dir` content; sensitive to renames as well as content changes.

`sandbox_dir` itself is resolved relative to the repo source tree (e.g., `Path(__file__).parents[3] / "sandbox" / "runner_image"`). M2 assumes an editable install (`pip install -e .`) so the directory is reachable from the package source location. Wheel-install support (bundling `sandbox/` as package data) is out of M2 scope.

**`runner.py` — `TraceRunner`**

```python
class TraceRunner:
    image_tag: str
    installer: Path                # absolute, host-side
    output_dir: Path               # absolute, host-side, must exist

    def argv(self) -> list[str]:
        """The podman run command, as a list. Pure; testable without exec."""

    def run(self) -> int:
        """subprocess.run(self.argv(), check=False); return exit code."""
```

`argv()` returns:

```
podman run --rm -it
  --privileged --pid=host
  -v <installer>:/installer:ro
  -v <output_dir>:/work/trace
  <image_tag>
  /installer
```

(Reasoning: `--privileged` and `--pid=host` are required for bcc/bpftrace to attach kprobes/tracepoints and to see the installer's process tree. The installer is mounted read-only because the trace shouldn't be able to mutate the input.)

**`cli.py` — Click command**

```python
@main.command("trace")
@click.argument("installer", type=click.Path(exists=True, dir_okay=False, readable=True, path_type=Path))
@click.option("-o", "--output-dir", required=True, type=click.Path(path_type=Path), help="Where to write the trace.")
@click.option("--force", is_flag=True, help="Overwrite output-dir if it already contains a COMPLETE marker.")
def trace_cmd(installer: Path, output_dir: Path, force: bool) -> None:
    ...
```

Sequence:

1. Pre-flight: verify podman machine is running (`podman machine ls --format json`); refuse with clear message + suggestion if not. (M2 doesn't probe `podman info` beyond this.)
2. Create `output_dir` if missing. If it exists and contains `COMPLETE` and `--force` is not set, refuse.
3. Build the `RunnerImage`. If missing, build with stderr streamed to the user; user sees `[image] building ...` from the wrapper plus podman's native output.
4. Construct the `TraceRunner` with absolute paths. Exec; wait for exit.
5. Post-run summary: read `output_dir/COMPLETE` or `PARTIAL`; line-count each JSONL; print:
   ```
   marker: COMPLETE
   open:      12,431 events
   connect:       18 events
   ...
   trace at <output_dir>  (next: containerizer analyze, not yet implemented)
   ```
6. If `FALLBACKS.json` exists, surface it as a warning paragraph.

### 6.6 Synthetic fixture — `tests/fixtures/trace/synthetic-installer.sh`

Issue #35.

A POSIX shell script that, when executed under the orchestrator:

- `cat /etc/passwd > /dev/null` — guarantees an `openat` event.
- `python3 -c "import socket; s=socket.socket(); s.bind(('127.0.0.1', 0)); s.listen(1); print(s.getsockname())"` — guarantees a `bind` event.
- `python3 -c "import socket; socket.socket().connect(('127.0.0.1', 1))" || true` — guarantees a `connect` event (and a failed-connect for variety; `|| true` keeps the script's exit code clean).
- Backgrounded `nc -l 12345 &` + foreground `echo hi | nc 127.0.0.1 12345 -w 1` — guarantees an `accept` event.
- `cat /proc/self/status` — guarantees several `syscalls.jsonl` rollups (open, read, close).
- `chown root:root /tmp/$$ 2>/dev/null; rm -f /tmp/$$` — guarantees a `capable.jsonl` CAP_CHOWN check.
- `echo "FIXTURE COMPLETE; finalising"`; the orchestrator's stdin is closed by the test driver, which triggers the `COMPLETE` path.

Runs in under 1 second in practice. No external dependencies beyond what's already in the runner image.

### 6.7 Integration test — `tests/integration/trace/test_trace_pipeline.py`

Issue #36.

```python
@pytest.mark.integration
def test_trace_pipeline_against_synthetic_fixture(tmp_path: Path) -> None:
    fixture = REPO_ROOT / "tests/fixtures/trace/synthetic-installer.sh"
    out = tmp_path / "trace"
    out.mkdir()

    # Spawn the real CLI as a subprocess so stdin to the podman-run container
    # is inherited from the test process. stdin=DEVNULL gives the orchestrator
    # an immediate EOF, which finalises COMPLETE without any user typing.
    result = subprocess.run(
        ["containerizer", "trace", str(fixture), "-o", str(out)],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=600,  # generous: 5 min image build + 1 min trace + slack
    )
    assert result.returncode == 0, (result.stdout, result.stderr)

    assert (out / "COMPLETE").exists()
    assert (out / "install.log").stat().st_size > 0
    for collector in ("open", "bind", "connect", "accept", "syscalls", "capable"):
        path = out / f"{collector}.jsonl"
        assert path.exists(), f"missing {path}"
        assert path.stat().st_size > 0, f"empty {path}"

    # Spot-check that the fixture's known events made it through.
    opens = [json.loads(line) for line in (out / "open.jsonl").read_text().splitlines()]
    assert any(rec.get("path") == "/etc/passwd" for rec in opens)
```

The `pytest.mark.integration` marker is registered in `pyproject.toml` so `--strict-markers` accepts it. Skipped by default; enabled by `pytest -m integration`.

Why not `click.testing.CliRunner`? `CliRunner.invoke(input="\n")` intercepts only the in-process `sys.stdin`; the subprocess we launch for `podman run` would inherit the parent process's *actual* stdin, not the CliRunner-managed buffer. The synthetic fixture's terminator (EOF, see §6.2) wouldn't fire. Running the CLI as a real subprocess with `stdin=DEVNULL` is the lowest-magic way to get the orchestrator to see EOF. The trade-off is that coverage from this run isn't collected automatically; that's acceptable since the unit tests defend the 90% gate and the integration test's value is end-to-end behaviour, not coverage.

### 6.8 CI job — `.github/workflows/ci.yml`

Issue #37.

A new job alongside the existing `lint` / `typecheck` / `test` / `trace-integration` matrix:

```yaml
trace-integration:
  name: Trace integration
  runs-on: ubuntu-latest
  steps:
    - uses: actions/checkout@<sha>  # SHA-pinned per issue #10
    - uses: actions/setup-python@<sha>
      with:
        python-version: "3.12"
    - name: Install runtime
      run: |
        sudo apt-get update
        sudo apt-get install -y podman bcc-tools bpftrace strace
    - name: Install package
      run: pip install -e ".[dev]"
    - name: Trace integration
      run: pytest -m integration -v
      timeout-minutes: 15  # allows runner-image build (~5 min) + trace (~1 min) + slack
```

After merge, branch protection on `main` adds `Trace integration` to the required checks list (alongside the existing 7).

Risks the trace-integration PR may need to handle: running privileged Podman under the GHA-provided unprivileged user may require `sudo podman` or a docker-rootless workaround; bcc tools on ubuntu-latest may need `kernel-headers-$(uname -r)` even with BTF. Both are tractable but not yet verified.

## 7. Data flow

```
host                                                                sandbox
─────                                                                ───────
containerizer trace ./install.sh -o ./trace/
    │
    ├── preflight: podman machine running?
    │
    ├── RunnerImage.exists() ─── no ──► podman build -t localhost/containerizer-runner:sha-X .
    │                                                  │
    │                                                  ▼
    │                                       image cached in podman store
    │
    ├── TraceRunner.run()
    │       │
    │       └── podman run --rm -it --privileged --pid=host \
    │             -v ./install.sh:/installer:ro \
    │             -v ./trace/:/work/trace \
    │             localhost/containerizer-runner:sha-X /installer
    │                                  │
    │                                  ▼
    │               trace-orchestrator.sh launches each collector
    │               (bcc tools and bpftrace scripts run as background
    │               processes, each writing JSONL to /work/trace/)
    │                                  │
    │                                  ▼
    │               exec /installer; tee to install.log
    │                                  │
    │                                  ▼
    │               PHASE_MARKER written
    │                                  │
    │               "press Enter to finalise" → reads stdin
    │                                  │
    │                                  ▼
    │               on Enter: SIGTERM collectors, flush, COMPLETE
    │
    └── post-run summary
        ├── read COMPLETE / PARTIAL
        ├── line-count each JSONL
        └── surface FALLBACKS.json if present
```

The host wrapper never reads the JSONL itself in M2 — that's the analyzer's job in M3. The wrapper only counts lines and reports markers.

## 8. Error handling

| Situation | Response |
|---|---|
| Podman machine not running | Pre-flight error: `Podman machine is not running. Start it with: podman machine start` |
| Installer file missing | Click's `click.Path(exists=True)` rejects before we run |
| Output dir contains `COMPLETE` already | Refuse unless `--force`: `Refusing to overwrite existing trace at <dir>. Use --force to replace, or pick a fresh directory.` |
| `podman build` fails | Exit non-zero, surface the last 20 lines of build stderr verbatim |
| `podman run` exits non-zero AND no marker present | `Trace did not finalise. Inspect <out>/install.log and <out>/*.err for collector errors.` Exit 1. |
| Marker is `PARTIAL` (user Ctrl-C) | Print summary as usual with a warning: `Trace was finalised from a partial run (Ctrl-C). M3 analyzer will treat any missing events as such.` Exit 0. |
| One or more collectors fell back to strace | Summary lists the affected collectors and the reasons from `FALLBACKS.json`. Exit 0 (degraded but usable). |

## 9. Security posture

The runner image runs with `--privileged --pid=host`. This is necessary for bcc/bpftrace to attach kprobes and see host process state, but the trade-off is real:

- The trace is intended to run on the developer's own Podman machine, not on shared infrastructure.
- The installer is bind-mounted **read-only** so the trace cannot mutate the source.
- The output dir is the only writable host path the container can touch.
- The container is `--rm`, so no state persists in the podman store after the trace.

The M2 spec does not attempt to constrain this further. A future hardening track may explore `unshare`-based isolation or rootless eBPF, but those are out of scope here.

## 10. Test plan

Unit tests (run on every PR, no podman dependency):

- `tests/unit/test_trace_image.py` — hash determinism, tag format, missing-image detection (mocked `podman image exists`), build invocation argv (mocked `subprocess.run`).
- `tests/unit/test_trace_runner.py` — `argv()` produces expected `podman run` command for various input combinations; output-dir validation (refuses pre-existing `COMPLETE`, accepts with `--force`).
- `tests/unit/test_trace_cli.py` — Click error messages for pre-flight failures (mocked `podman machine ls`); post-run summary formatting against fixture JSONL files.

Integration test (gated, runs in the new `trace-integration` CI job):

- `tests/integration/trace/test_trace_pipeline.py` as described in §6.7.

Existing coverage gate (`--cov-fail-under=90`) continues to apply to unit-test runs. The integration test contributes coverage too when its job runs, but isn't required to defend the gate.

## 11. Issues map

M2 (#23–#37):

| # | Title | Component |
|---|---|---|
| 23 | runner image Containerfile and sandbox/ scaffolding | §6.1 |
| 24 | bash trace-orchestrator with phase markers and stdin finalize | §6.2 |
| 25 | strace fallback when bcc/bpftrace collector fails to attach | §6.4 |
| 26 | `open.bt` bpftrace tracer for file accesses | §6.3 |
| 27 | `bind.bt` bpftrace tracer for `bind()` syscalls | §6.3 |
| 28 | `syscalls.bt` bpftrace tracer for syscall rollup | §6.3 |
| 29 | `tcpconnect` bcc-tools wrapper to JSONL | §6.3 |
| 30 | `tcpaccept` bcc-tools wrapper to JSONL | §6.3 |
| 31 | `capable` bcc-tools wrapper to JSONL | §6.3 |
| 32 | `image.py` — hash-based runner image tag and lazy podman build | §6.5 |
| 33 | `runner.py` — podman run construction | §6.5 |
| 34 | `cli.py` — `containerizer trace` command | §6.5 |
| 35 | synthetic shell-script fixture | §6.6 |
| 36 | integration test gated on `@pytest.mark.integration` | §6.7 |
| 37 | `trace-integration` CI job + branch protection rename | §6.8 |

M3+ (#38–#44) is out of M2 scope; see the M3+ milestone for the post-trace phase issues.
