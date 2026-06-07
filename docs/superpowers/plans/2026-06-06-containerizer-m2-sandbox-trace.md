# M2 Sandbox + Trace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the M2 milestone of the containerizer per `docs/superpowers/specs/2026-06-06-containerizer-m2-sandbox-trace.md`: a `containerizer trace <installer> -o trace/` subcommand that runs the installer inside a privileged Podman sandbox with six bcc/bpftrace collectors attached, producing six per-collector JSONL streams plus an `install.log` and a `COMPLETE` / `PARTIAL` marker.

**Architecture:** A new top-level `sandbox/runner_image/` directory holds a Fedora 41 Containerfile, the bash trace-orchestrator, and the six collector scripts. A new `src/containerizer/trace/` Python module owns the host wrapper: hash-based lazy image build, `podman run` construction, and the Click subcommand. The host wrapper never reads collector JSONL itself — that's M3's job. A synthetic shell-script fixture and a `@pytest.mark.integration`-gated end-to-end test exercise the full pipeline; a new `trace-integration` CI job on ubuntu-latest runs it on every PR.

**Tech Stack:** Bash (orchestrator), bpftrace (3 collectors), bcc + python3 (3 collectors), Fedora 41 + systemd + dbus + bcc-tools + strace + audit (runner image), Python 3.11+ + Click + Pydantic v2 (host wrapper), pytest with `-m integration` marker, GitHub Actions ubuntu-latest with apt-installed podman/bcc-tools/bpftrace.

---

## Conventions used throughout

- **Working directory:** all commands assume `C:\Users\yizshachuck\source\containerizer\` is the cwd. Use absolute paths in tools (Read/Edit/Write); use relative paths in shell commands.
- **Each task starts on its own feature branch off the latest `main`** (e.g., `feat/m2-task-N-<slug>`). PR per task, signed-commit-per-task, squash-merge through protected `main`. Mirrors the established v0.1.0 followup pattern.
- **Commit signing.** Every commit MUST be signed per the user's global `CLAUDE.md`:
  ```
  git -c user.email="github.v5f9w@bitbucket.onl" \
      -c user.signingkey=BE707B220C995478 \
      commit -S -m "<message>"
  ```
  Never pass `--no-gpg-sign`. Never amend a published commit.
- **Conventional commit subject** per task. `feat(sandbox):` for runner image / orchestrator / collectors; `feat(trace):` for the host wrapper Python modules; `test(trace):` for fixtures and integration tests; `ci:` for the workflow job.
- **Close the matching issue** in each PR body with `Closes #N` so the M2 milestone tracks completion automatically.
- **Coverage gate.** `pyproject.toml` already enforces `--cov-fail-under=90`. Python tasks must keep total coverage ≥ 90%. The integration test does not contribute (it runs only in its own CI job).
- **Don't commit between tasks without a green local gate.** `ruff check . && ruff format --check . && mypy src tests && pytest` must pass before pushing every task.
- **Line endings.** Repo is set up for LF; Windows working copies see CRLF warnings. Benign.

---

## File map

Files created or modified by this plan:

| Path | Purpose | Task |
|---|---|---|
| `pyproject.toml` | Register `integration` pytest marker | 1 |
| `sandbox/runner_image/Containerfile` | Fedora 41 + tooling + orchestrator + collectors | 2 |
| `sandbox/runner_image/trace-orchestrator.sh` | Bash orchestrator | 3, 10, 11 |
| `sandbox/runner_image/collectors/open.bt` | bpftrace open(2) tracer | 4 |
| `sandbox/runner_image/collectors/bind.bt` | bpftrace bind(2) tracer | 5 |
| `sandbox/runner_image/collectors/syscalls.bt` | bpftrace raw syscall rollup | 6 |
| `sandbox/runner_image/collectors/tcpconnect.py` | bcc-tools tcpconnect → JSONL | 7 |
| `sandbox/runner_image/collectors/tcpaccept.py` | bcc-tools tcpaccept → JSONL | 8 |
| `sandbox/runner_image/collectors/capable.py` | bcc-tools capable → JSONL | 9 |
| `src/containerizer/trace/__init__.py` | Package marker | 12 |
| `src/containerizer/trace/image.py` | RunnerImage (hash, exists, build) | 12 |
| `src/containerizer/trace/runner.py` | TraceRunner (argv, run) | 13 |
| `src/containerizer/trace/cli.py` | `containerizer trace` Click subcommand | 14 |
| `src/containerizer/cli.py` | Register the `trace` subcommand on the main group | 14 |
| `tests/unit/test_trace_image.py` | RunnerImage unit tests | 12 |
| `tests/unit/test_trace_runner.py` | TraceRunner unit tests | 13 |
| `tests/unit/test_trace_cli.py` | CLI surface + pre-flight unit tests | 14 |
| `tests/fixtures/trace/synthetic-installer.sh` | Deterministic shell-script fixture | 15 |
| `tests/integration/__init__.py` | Already exists | — |
| `tests/integration/trace/__init__.py` | Trace integration test package marker | 16 |
| `tests/integration/trace/test_trace_pipeline.py` | End-to-end gated test | 16 |
| `.github/workflows/ci.yml` | Add `trace-integration` job | 17 |
| `MANUAL.md` | Add scenario 6 (running trace) | 17 |

Branch protection on `main` gains a new required check (`Trace integration`) as part of Task 17's PR landing. Manual step documented in the task.

---

## Task 1: Register the `integration` pytest marker

**Issue:** prep (no individual issue; supports #36).

**Files:**
- Modify: `pyproject.toml`

The `integration` marker is added to pytest's `markers` config so `--strict-markers` accepts it. This task lands first because every later Python task runs `pytest`, and an unregistered marker error would surface as a noisy red even though tests pass.

- [ ] **Step 1: Read the current `[tool.pytest.ini_options]` block**

Read `pyproject.toml` and locate the `[tool.pytest.ini_options]` section (currently around line 56).

- [ ] **Step 2: Add the `markers` setting next to `testpaths`**

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-ra --strict-markers --cov=src/containerizer --cov-report=term-missing --cov-fail-under=90"
markers = [
    "integration: end-to-end tests requiring podman + Linux kernel with eBPF/BTF; skipped by default in local runs, run via `pytest -m integration`",
]
```

- [ ] **Step 3: Run the full local gate**

```
.venv/Scripts/python.exe -m ruff check . && \
.venv/Scripts/python.exe -m ruff format --check . && \
.venv/Scripts/python.exe -m mypy src tests && \
.venv/Scripts/python.exe -m pytest
```

Expected: all green, coverage stays at 93.99% (no source changes).

- [ ] **Step 4: Commit and open PR**

```
git checkout -b chore/m2-pytest-integration-marker
git add pyproject.toml
git -c user.email="github.v5f9w@bitbucket.onl" \
    -c user.signingkey=BE707B220C995478 \
    commit -S -m "chore(test): register pytest 'integration' marker for M2"
git push -u origin chore/m2-pytest-integration-marker
gh pr create --title "chore(test): register pytest 'integration' marker for M2" \
  --body "Prep for #36 (integration test). Registers the \`integration\` pytest marker so \`--strict-markers\` accepts it before the M2 integration test lands. No test code yet — that arrives in task 16." \
  --label enhancement
```

Wait for CI green, then squash-merge.

---

## Task 2: Sandbox runner image Containerfile + scaffolding

**Issue:** #23

**Files:**
- Create: `sandbox/runner_image/Containerfile`
- Create: `sandbox/runner_image/.gitkeep` (in `collectors/` so the empty dir is tracked)

This task creates the buildable image but does not yet add the orchestrator or collectors — those are tasks 3–10. The image must `podman build` cleanly with just systemd + tooling and no entrypoint.

- [ ] **Step 1: Create the runner image directory**

```
mkdir -p sandbox/runner_image/collectors
```

- [ ] **Step 2: Write the Containerfile**

```dockerfile
# syntax=docker/dockerfile:1
#
# Containerizer trace runner image.
#
# Fedora 41 was picked over Ubuntu / Debian because:
#   * bcc-tools and bpftrace are first-class packages and track upstream
#   * stock Fedora kernel exposes BTF for bcc and bpftrace probe attach
#   * systemd-as-PID-1 inside the container is the supported Fedora pattern
#
# The image is intentionally fat (~600 MB). It is built once per sandbox/
# directory content hash on the user's host (see src/containerizer/trace/image.py)
# and reused across every `containerizer trace` invocation.
FROM fedora:41

RUN dnf install -y --setopt=install_weak_deps=False \
      systemd dbus \
      bcc-tools bpftrace strace audit-libs audit \
      jq python3 \
    && dnf clean all

# Project-specific tooling lives under /opt/containerizer/ so /usr stays clean.
RUN mkdir -p /opt/containerizer/collectors /work/trace
COPY trace-orchestrator.sh /opt/containerizer/trace-orchestrator.sh
COPY collectors/           /opt/containerizer/collectors/
RUN chmod +x /opt/containerizer/trace-orchestrator.sh

ENTRYPOINT ["/opt/containerizer/trace-orchestrator.sh"]
```

- [ ] **Step 3: Add a placeholder orchestrator so the build doesn't fail on the COPY**

The COPY of `trace-orchestrator.sh` requires the file to exist. Add a minimal placeholder:

```bash
#!/usr/bin/env bash
# Placeholder; real orchestrator lands in task 3.
echo "trace-orchestrator: placeholder, no work to do" >&2
exit 0
```

Write to `sandbox/runner_image/trace-orchestrator.sh`.

- [ ] **Step 4: Add a `collectors/.gitkeep` so the directory is tracked**

```
touch sandbox/runner_image/collectors/.gitkeep
```

- [ ] **Step 5: Smoke-test the build (manual, on a Linux host with podman)**

```
podman build -t test-runner sandbox/runner_image/
```

Expected: build succeeds (~3–5 min on cold cache). Inspecting:

```
podman run --rm test-runner
```

prints `trace-orchestrator: placeholder, no work to do` to stderr and exits 0.

If the agentic worker is on Windows, this step is performed manually by the user. The PR's `trace-integration` CI job will validate the build once that job lands in task 17.

- [ ] **Step 6: Commit and open PR**

```
git checkout -b feat/m2-runner-image-scaffolding
git add sandbox/runner_image/
git -c user.email="github.v5f9w@bitbucket.onl" \
    -c user.signingkey=BE707B220C995478 \
    commit -S -m "feat(sandbox): runner image Containerfile and sandbox/ scaffolding

Closes #23

Fedora 41 base, dnf-installed bcc-tools/bpftrace/strace/systemd/dbus,
project-specific tooling under /opt/containerizer/. The orchestrator
is a placeholder that lands in task 3; the COPY happens here so the
Containerfile is self-contained and buildable from this commit alone."
git push -u origin feat/m2-runner-image-scaffolding
gh pr create --title "feat(sandbox): runner image Containerfile and sandbox/ scaffolding" \
  --body "$(cat <<'BODY'
Closes #23. Implements §6.1 of the M2 spec.

## Summary
- Fedora 41 base; dnf-installs systemd, dbus, bcc-tools, bpftrace, strace, audit-libs, audit, jq, python3.
- Lays out \`sandbox/runner_image/{Containerfile, trace-orchestrator.sh, collectors/}\`.
- Orchestrator is a placeholder that prints a stub message and exits; real implementation lands in task 3 (#24).

## Verification
- \`podman build -t test-runner sandbox/runner_image/\` succeeds locally on a Linux host (validated manually by the maintainer).
- \`podman run --rm test-runner\` exits 0 with the placeholder message on stderr.

CI green; integration test job that exercises the image arrives in task 17.
BODY
)" \
  --label enhancement
```

Wait for CI green, then squash-merge.

---

## Task 3: Bash trace-orchestrator skeleton (no collectors yet)

**Issue:** #24 (partial)

**Files:**
- Modify: `sandbox/runner_image/trace-orchestrator.sh`

The orchestrator skeleton runs the installer (passed as `$1`), writes `PHASE_MARKER`, prompts for finalize, and writes `COMPLETE` / `PARTIAL`. **No collectors yet** — those are added in tasks 4-10. Tasks 4-10 each grow `collectors/`, and task 10 wires the orchestrator to launch them.

- [ ] **Step 1: Replace the placeholder script with the real skeleton**

```bash
#!/usr/bin/env bash
# trace-orchestrator: launches collectors, runs the installer, prompts for a
# user-driven smoke test, and finalises the trace. Runs inside the sandbox
# runner image; expects the installer mounted at /installer and the output
# directory at /work/trace.
#
# Exit codes:
#   0  COMPLETE or PARTIAL marker written (PARTIAL still counts as "ran")
#   2  Installer was missing or the host wrapper passed garbage
#
# Lifecycle:
#   1. Launch each collector backgrounded (added in task 10)
#   2. Exec the installer; tee stdout+stderr to install.log
#   3. Write PHASE_MARKER with the monotonic install-finish timestamp
#   4. Read a single line from stdin
#        - on Enter -> finalise COMPLETE
#        - on EOF   -> finalise COMPLETE (lets the integration test drive)
#   5. On SIGINT   -> finalise PARTIAL
set -euo pipefail

INSTALLER="${1:?usage: trace-orchestrator <installer-path>}"
TRACE_DIR="/work/trace"

if [[ ! -r "$INSTALLER" ]]; then
    echo "trace-orchestrator: installer not readable: $INSTALLER" >&2
    exit 2
fi

mkdir -p "$TRACE_DIR"

# Collector wiring lands in task 10. For now collector_pids is empty so the
# finalize path runs cleanly even without any collectors attached.
collector_pids=()

finalize_marker() {
    local marker="$1"  # COMPLETE or PARTIAL
    if (( ${#collector_pids[@]} > 0 )); then
        for pid in "${collector_pids[@]}"; do
            kill -TERM "$pid" 2>/dev/null || true
        done
        sleep 1
        for pid in "${collector_pids[@]}"; do
            kill -KILL "$pid" 2>/dev/null || true
        done
    fi
    : > "$TRACE_DIR/$marker"
}

trap 'finalize_marker PARTIAL; exit 0' INT

echo "trace-orchestrator: running installer $INSTALLER" >&2
"$INSTALLER" 2>&1 | tee "$TRACE_DIR/install.log" || true
echo "monotonic_ns: $(awk 'BEGIN{getline t < "/proc/uptime"; split(t,a,"."); printf "%s%s\n", a[1], a[2]}')" \
    > "$TRACE_DIR/PHASE_MARKER"

echo "trace-orchestrator: installer complete. exercise the software, then press <Enter> here to finalise (or close stdin)." >&2

# read returns non-zero on EOF; we treat both Enter and EOF as the COMPLETE path.
read -r _ || true
finalize_marker COMPLETE
echo "trace-orchestrator: COMPLETE" >&2
```

- [ ] **Step 2: Local sanity check (manual on Linux, optional on Windows)**

Build the image (still no collectors) and run against a no-op installer:

```
podman build -t test-runner sandbox/runner_image/
echo '#!/bin/sh
echo hello' > /tmp/no-op.sh && chmod +x /tmp/no-op.sh
mkdir -p /tmp/trace
echo "" | podman run --rm -i -v /tmp/no-op.sh:/installer:ro -v /tmp/trace:/work/trace test-runner /installer
ls /tmp/trace
```

Expected: `install.log` (with "hello"), `PHASE_MARKER`, `COMPLETE`.

- [ ] **Step 3: Commit and open PR**

```
git checkout -b feat/m2-orchestrator-skeleton
git add sandbox/runner_image/trace-orchestrator.sh
git -c user.email="github.v5f9w@bitbucket.onl" \
    -c user.signingkey=BE707B220C995478 \
    commit -S -m "feat(sandbox): bash trace-orchestrator skeleton with EOF-as-Enter finalize

Refs #24

Implements the orchestrator lifecycle without collectors:
  - exec installer, tee install.log
  - write PHASE_MARKER on exit
  - read stdin (Enter or EOF both finalise COMPLETE)
  - SIGINT trap writes PARTIAL

Collectors are wired up in task 10 once individual collector scripts
have landed in tasks 4-9. This commit alone produces a runnable image."
git push -u origin feat/m2-orchestrator-skeleton
gh pr create --title "feat(sandbox): bash trace-orchestrator skeleton with EOF-as-Enter finalize" \
  --body "Refs #24 (partial; collector wiring lands in task 10).

## Summary
- Implements the orchestrator lifecycle described in M2 spec §6.2.
- No collectors yet; \`collector_pids\` is empty.
- EOF on stdin is treated as Enter so the integration test can drive COMPLETE without typing.

## Verification
- Manually exercised on a Linux host with a no-op installer; produces \`install.log\`, \`PHASE_MARKER\`, \`COMPLETE\` in the bind-mounted output dir." \
  --label enhancement
```

Wait for CI green, then squash-merge.

---

## Task 4: `open.bt` bpftrace collector

**Issue:** #26

**Files:**
- Create: `sandbox/runner_image/collectors/open.bt`

Emits one JSONL record per `openat` syscall to stdout. The orchestrator (task 10) redirects stdout to `/work/trace/open.jsonl`.

- [ ] **Step 1: Write the bpftrace script**

```bpftrace
#!/usr/bin/env bpftrace
/*
 * open.bt — emits {ts_ns, pid, comm, path, flags, mode, ret} JSONL records
 * for every openat(2) syscall. Stdout is captured by the orchestrator into
 * /work/trace/open.jsonl.
 *
 * Notes:
 *   * We track both sys_enter_openat (to capture flags, mode, path) and
 *     sys_exit_openat (to capture ret); join via @args[tid].
 *   * Failed opens (ret < 0) are deliberately included so the analyzer can
 *     distinguish "tried to read" from "actually read".
 */

BEGIN { printf("[\n"); }

tracepoint:syscalls:sys_enter_openat
{
    @args[tid] = (uint64)args->filename;
    @flags[tid] = args->flags;
    @mode[tid] = args->mode;
}

tracepoint:syscalls:sys_exit_openat
/ @args[tid] /
{
    $path = str(@args[tid]);
    printf("{\"ts_ns\":%lld,\"pid\":%d,\"comm\":\"%s\",\"path\":\"%s\",\"flags\":%d,\"mode\":%d,\"ret\":%ld}\n",
        nsecs, pid, comm, $path, @flags[tid], @mode[tid], args->ret);
    delete(@args[tid]);
    delete(@flags[tid]);
    delete(@mode[tid]);
}
```

- [ ] **Step 2: Commit and open PR**

```
git checkout -b feat/m2-collector-open
git add sandbox/runner_image/collectors/open.bt
git -c user.email="github.v5f9w@bitbucket.onl" \
    -c user.signingkey=BE707B220C995478 \
    commit -S -m "feat(sandbox/collectors): open.bt bpftrace tracer for file accesses

Closes #26

Tracepoint pair sys_enter_openat / sys_exit_openat joined on tid so we
emit the {ts_ns, pid, comm, path, flags, mode, ret} schema spec'd in
§6.3. Failed opens (ret < 0) are included intentionally — the M3 analyzer
needs to distinguish 'tried to read' from 'actually read'.

Standalone JSONL emitter; orchestrator wiring lands in task 10."
git push -u origin feat/m2-collector-open
gh pr create --title "feat(sandbox/collectors): open.bt bpftrace tracer for file accesses" \
  --body "Closes #26. Implements §6.3 row 1 of the M2 spec." \
  --label enhancement
```

Wait for CI green, then squash-merge.

---

## Task 5: `bind.bt` bpftrace collector

**Issue:** #27

**Files:**
- Create: `sandbox/runner_image/collectors/bind.bt`

- [ ] **Step 1: Write the bpftrace script**

```bpftrace
#!/usr/bin/env bpftrace
/*
 * bind.bt — emits {ts_ns, pid, comm, family, addr, port, proto} JSONL for
 * every bind(2) syscall. Captures IPv4, IPv6, and AF_UNIX in one stream.
 *
 * proto is "tcp" if the socket was SOCK_STREAM at bind, "udp" if SOCK_DGRAM,
 * "unix" if AF_UNIX, "?" otherwise. We approximate proto by storing the
 * type at socket-create time; tracking it perfectly would require kprobing
 * inet_bind, which has different signatures across kernels.
 */

#include <linux/in.h>
#include <linux/in6.h>
#include <linux/un.h>

BEGIN { printf("[\n"); }

tracepoint:syscalls:sys_enter_socket
{
    @sock_type[tid] = args->type & 0xf;  // SOCK_STREAM=1, SOCK_DGRAM=2
}

tracepoint:syscalls:sys_exit_socket
{
    delete(@sock_type[tid]);
}

tracepoint:syscalls:sys_enter_bind
{
    $umyaddr = (struct sockaddr *)args->umyaddr;
    $family = $umyaddr->sa_family;

    $port = 0;
    $addr_str = "";
    if ($family == AF_INET) {
        $sin = (struct sockaddr_in *)$umyaddr;
        $port = ($sin->sin_port >> 8) | (($sin->sin_port & 0xff) << 8);
        $addr_str = ntop(AF_INET, $sin->sin_addr.s_addr);
    } else if ($family == AF_INET6) {
        $sin6 = (struct sockaddr_in6 *)$umyaddr;
        $port = ($sin6->sin6_port >> 8) | (($sin6->sin6_port & 0xff) << 8);
        $addr_str = ntop(AF_INET6, $sin6->sin6_addr.in6_u.u6_addr8);
    } else if ($family == AF_UNIX) {
        $sun = (struct sockaddr_un *)$umyaddr;
        $addr_str = str($sun->sun_path);
    }

    $proto = "?";
    if (@sock_type[tid] == 1) { $proto = "tcp"; }
    else if (@sock_type[tid] == 2) { $proto = "udp"; }
    else if ($family == AF_UNIX) { $proto = "unix"; }

    printf("{\"ts_ns\":%lld,\"pid\":%d,\"comm\":\"%s\",\"family\":%d,\"addr\":\"%s\",\"port\":%d,\"proto\":\"%s\"}\n",
        nsecs, pid, comm, $family, $addr_str, $port, $proto);
}
```

- [ ] **Step 2: Commit and open PR**

```
git checkout -b feat/m2-collector-bind
git add sandbox/runner_image/collectors/bind.bt
git -c user.email="github.v5f9w@bitbucket.onl" \
    -c user.signingkey=BE707B220C995478 \
    commit -S -m "feat(sandbox/collectors): bind.bt bpftrace tracer for bind() syscalls

Closes #27

sys_enter_bind decoded for AF_INET / AF_INET6 / AF_UNIX with byte-swapped
port and ntop()-rendered address. proto is approximated by tracking the
socket type at sys_enter_socket and joining on tid; AF_UNIX is detected
directly. Schema matches §6.3 row 2 of the M2 spec."
git push -u origin feat/m2-collector-bind
gh pr create --title "feat(sandbox/collectors): bind.bt bpftrace tracer for bind() syscalls" \
  --body "Closes #27. Implements §6.3 row 2 of the M2 spec." \
  --label enhancement
```

Wait for CI green, then squash-merge.

---

## Task 6: `syscalls.bt` bpftrace collector

**Issue:** #28

**Files:**
- Create: `sandbox/runner_image/collectors/syscalls.bt`

- [ ] **Step 1: Write the bpftrace script**

```bpftrace
#!/usr/bin/env bpftrace
/*
 * syscalls.bt — counts every syscall per (pid, syscall_id) and emits one
 * JSONL record per unique tuple at END. First-seen timestamp is recorded
 * so the analyzer can attribute syscalls to the install vs runtime phase
 * by comparing against PHASE_MARKER.
 *
 * The map keys store both pid and syscall_id, encoded as (pid << 16 | id).
 * 16 bits is plenty for syscall_id (current max ~450) but the comm needs
 * its own map keyed on pid.
 */

BEGIN { printf("[\n"); }

tracepoint:raw_syscalls:sys_enter
{
    $key = (((uint64)pid) << 16) | (args->id & 0xffff);
    @count[$key] = count();
    if (!@first_ts[$key]) {
        @first_ts[$key] = nsecs;
        @comm[pid] = comm;
    }
}

END
{
    for ($kv : @count) {
        $key = $kv.0;
        $cnt = $kv.1;
        $pid = (uint32)($key >> 16);
        $sysid = (uint32)($key & 0xffff);
        printf("{\"pid\":%d,\"comm\":\"%s\",\"syscall_id\":%d,\"count\":%llu,\"first_ts_ns\":%llu}\n",
            $pid, @comm[$pid], $sysid, $cnt, @first_ts[$key]);
    }
    clear(@count);
    clear(@first_ts);
    clear(@comm);
}
```

- [ ] **Step 2: Commit and open PR**

```
git checkout -b feat/m2-collector-syscalls
git add sandbox/runner_image/collectors/syscalls.bt
git -c user.email="github.v5f9w@bitbucket.onl" \
    -c user.signingkey=BE707B220C995478 \
    commit -S -m "feat(sandbox/collectors): syscalls.bt bpftrace tracer for syscall rollup

Closes #28

raw_syscalls:sys_enter increments a per-(pid, syscall_id) counter and
records first-seen timestamp. END handler emits one JSONL record per
unique tuple. Schema matches §6.3 row 3 of the M2 spec; syscall_id ->
name mapping is the M3 analyzer's job."
git push -u origin feat/m2-collector-syscalls
gh pr create --title "feat(sandbox/collectors): syscalls.bt bpftrace tracer for syscall rollup" \
  --body "Closes #28. Implements §6.3 row 3 of the M2 spec." \
  --label enhancement
```

Wait for CI green, then squash-merge.

---

## Task 7: `tcpconnect.py` bcc-tools collector

**Issue:** #29

**Files:**
- Create: `sandbox/runner_image/collectors/tcpconnect.py`

- [ ] **Step 1: Write the bcc-tools-backed collector**

```python
#!/usr/bin/env python3
"""tcpconnect.py — emit JSONL for every outbound TCP connect().

Uses the bcc library directly rather than scraping the upstream `tcpconnect`
tool's text output. Stdout is captured by the orchestrator into
/work/trace/connect.jsonl.

Schema (one JSON object per line):
    {ts_ns, pid, comm, saddr, sport, daddr, dport, family}
"""

from __future__ import annotations

import json
import socket
import struct
import sys
import time

from bcc import BPF

BPF_PROGRAM = r"""
#include <net/sock.h>
#include <bcc/proto.h>

struct evt_t {
    u64 ts_ns;
    u32 pid;
    u32 saddr;
    u32 daddr;
    __int128 saddr6;
    __int128 daddr6;
    u16 sport;
    u16 dport;
    u16 family;
    char comm[16];
};
BPF_PERF_OUTPUT(events);

int trace_connect_entry(struct pt_regs *ctx, struct sock *sk) {
    u32 pid = bpf_get_current_pid_tgid() >> 32;
    u16 family = sk->__sk_common.skc_family;

    struct evt_t evt = {};
    evt.ts_ns = bpf_ktime_get_ns();
    evt.pid = pid;
    evt.family = family;
    bpf_get_current_comm(&evt.comm, sizeof(evt.comm));

    if (family == AF_INET) {
        evt.saddr = sk->__sk_common.skc_rcv_saddr;
        evt.daddr = sk->__sk_common.skc_daddr;
    } else if (family == AF_INET6) {
        bpf_probe_read_kernel(&evt.saddr6,
            sizeof(evt.saddr6),
            sk->__sk_common.skc_v6_rcv_saddr.in6_u.u6_addr32);
        bpf_probe_read_kernel(&evt.daddr6,
            sizeof(evt.daddr6),
            sk->__sk_common.skc_v6_daddr.in6_u.u6_addr32);
    }
    evt.sport = sk->__sk_common.skc_num;
    evt.dport = ntohs(sk->__sk_common.skc_dport);
    events.perf_submit(ctx, &evt, sizeof(evt));
    return 0;
}
"""


def main() -> None:
    b = BPF(text=BPF_PROGRAM)
    b.attach_kprobe(event="tcp_v4_connect", fn_name="trace_connect_entry")
    b.attach_kprobe(event="tcp_v6_connect", fn_name="trace_connect_entry")

    def on_event(_cpu: int, data: bytes, _size: int) -> None:
        ev = b["events"].event(data)
        record: dict[str, object] = {
            "ts_ns": int(ev.ts_ns),
            "pid": int(ev.pid),
            "comm": ev.comm.decode("utf-8", "replace").rstrip("\x00"),
            "sport": int(ev.sport),
            "dport": int(ev.dport),
            "family": int(ev.family),
        }
        if ev.family == socket.AF_INET:
            record["saddr"] = socket.inet_ntop(
                socket.AF_INET, struct.pack("I", ev.saddr)
            )
            record["daddr"] = socket.inet_ntop(
                socket.AF_INET, struct.pack("I", ev.daddr)
            )
        elif ev.family == socket.AF_INET6:
            record["saddr"] = socket.inet_ntop(
                socket.AF_INET6, struct.pack("Q" * 2, ev.saddr6 & ((1 << 64) - 1), ev.saddr6 >> 64)
            )
            record["daddr"] = socket.inet_ntop(
                socket.AF_INET6, struct.pack("Q" * 2, ev.daddr6 & ((1 << 64) - 1), ev.daddr6 >> 64)
            )
        sys.stdout.write(json.dumps(record) + "\n")
        sys.stdout.flush()

    b["events"].open_perf_buffer(on_event)
    while True:
        try:
            b.perf_buffer_poll(timeout=1000)
        except KeyboardInterrupt:
            return


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Commit and open PR**

```
git checkout -b feat/m2-collector-tcpconnect
git add sandbox/runner_image/collectors/tcpconnect.py
git -c user.email="github.v5f9w@bitbucket.onl" \
    -c user.signingkey=BE707B220C995478 \
    commit -S -m "feat(sandbox/collectors): tcpconnect bcc-tools wrapper to JSONL

Closes #29

Uses the bcc Python library directly (no scraping of the upstream
tcpconnect tool's text output). Kprobes tcp_v4_connect and tcp_v6_connect,
extracts family-dependent saddr/daddr/sport/dport via perf-buffer, emits
{ts_ns, pid, comm, saddr, sport, daddr, dport, family} JSONL per §6.3
row 4 of the M2 spec.

The script lives inside the runner image; the host wrapper never imports
it. Tested end-to-end in task 16's integration test."
git push -u origin feat/m2-collector-tcpconnect
gh pr create --title "feat(sandbox/collectors): tcpconnect bcc-tools wrapper to JSONL" \
  --body "Closes #29. Implements §6.3 row 4 of the M2 spec." \
  --label enhancement
```

Wait for CI green, then squash-merge.

---

## Task 8: `tcpaccept.py` bcc-tools collector

**Issue:** #30

**Files:**
- Create: `sandbox/runner_image/collectors/tcpaccept.py`

- [ ] **Step 1: Write the bcc-tools-backed collector**

```python
#!/usr/bin/env python3
"""tcpaccept.py — emit JSONL for every inbound TCP accept().

Kretprobes inet_csk_accept and reads the returned struct sock for source
and destination address/port. Schema:
    {ts_ns, pid, comm, laddr, lport, raddr, rport, family}
"""

from __future__ import annotations

import json
import socket
import struct
import sys

from bcc import BPF

BPF_PROGRAM = r"""
#include <net/sock.h>

struct evt_t {
    u64 ts_ns;
    u32 pid;
    u16 family;
    u32 laddr;
    u32 raddr;
    __int128 laddr6;
    __int128 raddr6;
    u16 lport;
    u16 rport;
    char comm[16];
};
BPF_PERF_OUTPUT(events);

int trace_accept_ret(struct pt_regs *ctx) {
    struct sock *sk = (struct sock *)PT_REGS_RC(ctx);
    if (sk == NULL) return 0;

    struct evt_t evt = {};
    evt.ts_ns = bpf_ktime_get_ns();
    evt.pid = bpf_get_current_pid_tgid() >> 32;
    evt.family = sk->__sk_common.skc_family;
    bpf_get_current_comm(&evt.comm, sizeof(evt.comm));

    if (evt.family == AF_INET) {
        evt.laddr = sk->__sk_common.skc_rcv_saddr;
        evt.raddr = sk->__sk_common.skc_daddr;
    } else if (evt.family == AF_INET6) {
        bpf_probe_read_kernel(&evt.laddr6, sizeof(evt.laddr6),
            sk->__sk_common.skc_v6_rcv_saddr.in6_u.u6_addr32);
        bpf_probe_read_kernel(&evt.raddr6, sizeof(evt.raddr6),
            sk->__sk_common.skc_v6_daddr.in6_u.u6_addr32);
    }
    evt.lport = sk->__sk_common.skc_num;
    evt.rport = ntohs(sk->__sk_common.skc_dport);
    events.perf_submit(ctx, &evt, sizeof(evt));
    return 0;
}
"""


def main() -> None:
    b = BPF(text=BPF_PROGRAM)
    b.attach_kretprobe(event="inet_csk_accept", fn_name="trace_accept_ret")

    def on_event(_cpu: int, data: bytes, _size: int) -> None:
        ev = b["events"].event(data)
        record: dict[str, object] = {
            "ts_ns": int(ev.ts_ns),
            "pid": int(ev.pid),
            "comm": ev.comm.decode("utf-8", "replace").rstrip("\x00"),
            "lport": int(ev.lport),
            "rport": int(ev.rport),
            "family": int(ev.family),
        }
        if ev.family == socket.AF_INET:
            record["laddr"] = socket.inet_ntop(
                socket.AF_INET, struct.pack("I", ev.laddr)
            )
            record["raddr"] = socket.inet_ntop(
                socket.AF_INET, struct.pack("I", ev.raddr)
            )
        elif ev.family == socket.AF_INET6:
            record["laddr"] = socket.inet_ntop(
                socket.AF_INET6, struct.pack("Q" * 2, ev.laddr6 & ((1 << 64) - 1), ev.laddr6 >> 64)
            )
            record["raddr"] = socket.inet_ntop(
                socket.AF_INET6, struct.pack("Q" * 2, ev.raddr6 & ((1 << 64) - 1), ev.raddr6 >> 64)
            )
        sys.stdout.write(json.dumps(record) + "\n")
        sys.stdout.flush()

    b["events"].open_perf_buffer(on_event)
    while True:
        try:
            b.perf_buffer_poll(timeout=1000)
        except KeyboardInterrupt:
            return


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Commit and open PR**

Same pattern as task 7. Title: `feat(sandbox/collectors): tcpaccept bcc-tools wrapper to JSONL`. Body: `Closes #30. Implements §6.3 row 5 of the M2 spec.`

---

## Task 9: `capable.py` bcc-tools collector

**Issue:** #31

**Files:**
- Create: `sandbox/runner_image/collectors/capable.py`

- [ ] **Step 1: Write the bcc-tools-backed collector**

```python
#!/usr/bin/env python3
"""capable.py — emit JSONL for every cap_capable() check.

Kprobes cap_capable. Schema:
    {ts_ns, pid, comm, cap, audit, ret}

`cap` is the Linux capability NAME (CAP_NET_BIND_SERVICE etc.), not the
integer id, because the M3 Quadlet generator emits names. Mapping table
is bundled at module-load time and tracks include/uapi/linux/capability.h
as of Linux 6.10.
"""

from __future__ import annotations

import json
import sys

from bcc import BPF

# Linux capability id -> name. Sourced from include/uapi/linux/capability.h.
CAP_NAMES = {
    0: "CAP_CHOWN", 1: "CAP_DAC_OVERRIDE", 2: "CAP_DAC_READ_SEARCH",
    3: "CAP_FOWNER", 4: "CAP_FSETID", 5: "CAP_KILL", 6: "CAP_SETGID",
    7: "CAP_SETUID", 8: "CAP_SETPCAP", 9: "CAP_LINUX_IMMUTABLE",
    10: "CAP_NET_BIND_SERVICE", 11: "CAP_NET_BROADCAST", 12: "CAP_NET_ADMIN",
    13: "CAP_NET_RAW", 14: "CAP_IPC_LOCK", 15: "CAP_IPC_OWNER",
    16: "CAP_SYS_MODULE", 17: "CAP_SYS_RAWIO", 18: "CAP_SYS_CHROOT",
    19: "CAP_SYS_PTRACE", 20: "CAP_SYS_PACCT", 21: "CAP_SYS_ADMIN",
    22: "CAP_SYS_BOOT", 23: "CAP_SYS_NICE", 24: "CAP_SYS_RESOURCE",
    25: "CAP_SYS_TIME", 26: "CAP_SYS_TTY_CONFIG", 27: "CAP_MKNOD",
    28: "CAP_LEASE", 29: "CAP_AUDIT_WRITE", 30: "CAP_AUDIT_CONTROL",
    31: "CAP_SETFCAP", 32: "CAP_MAC_OVERRIDE", 33: "CAP_MAC_ADMIN",
    34: "CAP_SYSLOG", 35: "CAP_WAKE_ALARM", 36: "CAP_BLOCK_SUSPEND",
    37: "CAP_AUDIT_READ", 38: "CAP_PERFMON", 39: "CAP_BPF",
    40: "CAP_CHECKPOINT_RESTORE",
}

BPF_PROGRAM = r"""
#include <linux/sched.h>
struct evt_t {
    u64 ts_ns;
    u32 pid;
    int cap;
    int audit;
    int ret;
    char comm[16];
};
BPF_PERF_OUTPUT(events);

int trace_capable(struct pt_regs *ctx,
                  const struct cred *cred,
                  struct user_namespace *targ_ns,
                  int cap,
                  int audit)
{
    struct evt_t evt = {};
    evt.ts_ns = bpf_ktime_get_ns();
    evt.pid = bpf_get_current_pid_tgid() >> 32;
    evt.cap = cap;
    evt.audit = audit;
    evt.ret = 0;  // entry probe; ret captured by exit handler if added
    bpf_get_current_comm(&evt.comm, sizeof(evt.comm));
    events.perf_submit(ctx, &evt, sizeof(evt));
    return 0;
}
"""


def main() -> None:
    b = BPF(text=BPF_PROGRAM)
    b.attach_kprobe(event="cap_capable", fn_name="trace_capable")

    def on_event(_cpu: int, data: bytes, _size: int) -> None:
        ev = b["events"].event(data)
        record = {
            "ts_ns": int(ev.ts_ns),
            "pid": int(ev.pid),
            "comm": ev.comm.decode("utf-8", "replace").rstrip("\x00"),
            "cap": CAP_NAMES.get(int(ev.cap), f"CAP_UNKNOWN_{int(ev.cap)}"),
            "audit": int(ev.audit),
            "ret": int(ev.ret),
        }
        sys.stdout.write(json.dumps(record) + "\n")
        sys.stdout.flush()

    b["events"].open_perf_buffer(on_event)
    while True:
        try:
            b.perf_buffer_poll(timeout=1000)
        except KeyboardInterrupt:
            return


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Commit and open PR**

Same pattern. Title: `feat(sandbox/collectors): capable bcc-tools wrapper to JSONL`. Body: `Closes #31. Implements §6.3 row 6 of the M2 spec.`

---

## Task 10: Wire orchestrator to launch all six collectors

**Issue:** #24 (completion)

**Files:**
- Modify: `sandbox/runner_image/trace-orchestrator.sh`

This task closes #24 by wiring the collectors that landed in tasks 4-9 into the orchestrator's lifecycle.

- [ ] **Step 1: Replace the placeholder `collector_pids=()` block**

After the `mkdir -p "$TRACE_DIR"` line and before the `finalize_marker` function, insert the launch block. Replace:

```bash
collector_pids=()
```

with:

```bash
# Launch each collector backgrounded. Each writes its own JSONL to TRACE_DIR
# and any errors to TRACE_DIR/<name>.err.
launch_bt() {
    local name="$1"
    local script="$2"
    bpftrace -B none -f json "$script" \
        > "$TRACE_DIR/$name.jsonl" 2> "$TRACE_DIR/$name.err" &
    collector_pids+=("$!")
    echo "trace-orchestrator: launched $name (pid $!)" >&2
}

launch_py() {
    local name="$1"
    local script="$2"
    python3 -u "$script" \
        > "$TRACE_DIR/$name.jsonl" 2> "$TRACE_DIR/$name.err" &
    collector_pids+=("$!")
    echo "trace-orchestrator: launched $name (pid $!)" >&2
}

collector_pids=()
launch_bt open     /opt/containerizer/collectors/open.bt
launch_bt bind     /opt/containerizer/collectors/bind.bt
launch_bt syscalls /opt/containerizer/collectors/syscalls.bt
launch_py connect  /opt/containerizer/collectors/tcpconnect.py
launch_py accept   /opt/containerizer/collectors/tcpaccept.py
launch_py capable  /opt/containerizer/collectors/capable.py

# Give collectors ~2s to attach probes before we exec the installer.
sleep 2
```

- [ ] **Step 2: Commit and open PR**

```
git checkout -b feat/m2-orchestrator-collector-wiring
git add sandbox/runner_image/trace-orchestrator.sh
git -c user.email="github.v5f9w@bitbucket.onl" \
    -c user.signingkey=BE707B220C995478 \
    commit -S -m "feat(sandbox): wire trace-orchestrator to launch all six collectors

Closes #24

Adds launch_bt() and launch_py() helpers that background each collector,
redirect stdout to /work/trace/<name>.jsonl, and stderr to
/work/trace/<name>.err. 2-second grace before the installer runs gives
probes time to attach. SIGTERM cascade in finalize_marker is unchanged.

Collector failures are surfaced via non-zero size .err files; task 11
adds the FALLBACKS.json + strace fallback for attach failures."
git push -u origin feat/m2-orchestrator-collector-wiring
gh pr create --title "feat(sandbox): wire trace-orchestrator to launch all six collectors" \
  --body "Closes #24. All six collectors from tasks 4-9 launch as backgrounded subprocesses with JSONL → /work/trace and errors → /work/trace/<name>.err." \
  --label enhancement
```

Wait for CI green, then squash-merge.

---

## Task 11: Strace fallback in orchestrator

**Issue:** #25

**Files:**
- Modify: `sandbox/runner_image/trace-orchestrator.sh`

- [ ] **Step 1: Add fallback detection after the 2-second attach grace**

Append the following before the `echo "trace-orchestrator: running installer..."` line:

```bash
# After the 2s attach grace, check whether each collector is still alive.
# A dead collector means probe attach failed (e.g., no BTF, kheaders mismatch).
# Record the failure in FALLBACKS.json and start a strace fallback that covers
# the collector's domain.

declare -A fallbacks=()
declare -A domain=( \
    [open]="-e trace=file" \
    [bind]="-e trace=network" \
    [syscalls]="-e trace=all" \
    [connect]="-e trace=network" \
    [accept]="-e trace=network" \
    [capable]="-e trace=%audit" \
)

idx=0
for name in open bind syscalls connect accept capable; do
    pid="${collector_pids[$idx]}"
    if ! kill -0 "$pid" 2>/dev/null; then
        reason=$(tail -n 1 "$TRACE_DIR/$name.err" 2>/dev/null || echo "unknown attach failure")
        fallbacks[$name]="$reason"
        echo "trace-orchestrator: $name failed to attach: $reason" >&2
    fi
    idx=$((idx + 1))
done

if (( ${#fallbacks[@]} > 0 )); then
    # Spawn one strace per failed domain on the installer PID after exec
    # (we cache the args here; actual strace launch happens after the exec).
    :
fi

# Persist fallbacks decision; the strace processes themselves are started
# after the installer exec so we can target -p <pid>.
{
    printf "{"
    first=1
    for k in "${!fallbacks[@]}"; do
        if (( first )); then first=0; else printf ","; fi
        printf '"%s":{"reason":"%s","fallback":"strace %s"}' \
            "$k" "${fallbacks[$k]}" "${domain[$k]}"
    done
    printf "}\n"
} > "$TRACE_DIR/FALLBACKS.json"
```

- [ ] **Step 2: Replace the installer exec block to capture the installer pid before spawning strace**

`tee` in a pipeline makes `$!` point at the rightmost process (`tee`), not the installer, so we route through a coprocess to keep the installer pid addressable:

```bash
echo "trace-orchestrator: running installer $INSTALLER" >&2

# Run installer in the background with stdout+stderr captured through tee.
# Use exec + redirection rather than a pipeline so $! is the installer's pid.
exec 3> >(tee "$TRACE_DIR/install.log")
"$INSTALLER" >&3 2>&3 &
installer_pid="$!"
exec 3>&-

# Spawn one strace per failed collector, targeting the installer pid.
# strace exits when the traced process does.
for name in "${!fallbacks[@]}"; do
    strace -f -o "$TRACE_DIR/$name.fallback.log" \
        $(echo "${domain[$name]}") \
        -p "$installer_pid" &
    collector_pids+=("$!")
done

wait "$installer_pid"
installer_rc="$?"
echo "$installer_rc" > "$TRACE_DIR/installer.exitcode"
```

Key points:
- `exec 3> >(...)` opens a process substitution as fd 3; the installer writes to fd 3 (which tees to install.log).
- Backgrounding the installer (`&`) with no surrounding pipeline means `$!` is the installer's pid, not tee's.
- `exec 3>&-` closes the parent's copy of fd 3 immediately so tee can exit cleanly after the installer does.
- `$(echo "${domain[$name]}")` splits the captured `-e trace=...` argv pieces; quoting `${domain[$name]}` directly would pass the whole string as one argv to strace, which fails.

- [ ] **Step 2: Commit and open PR**

```
git checkout -b feat/m2-orchestrator-strace-fallback
git add sandbox/runner_image/trace-orchestrator.sh
git -c user.email="github.v5f9w@bitbucket.onl" \
    -c user.signingkey=BE707B220C995478 \
    commit -S -m "feat(sandbox): strace fallback when bcc/bpftrace collector fails to attach

Closes #25

After the 2-second attach grace, every collector whose PID is dead is
recorded in /work/trace/FALLBACKS.json with the last line of its .err
file as the reason. A strace -f -o <name>.fallback.log -e trace=<domain>
process is started against the installer PID for each failed collector.

The host wrapper surfaces FALLBACKS.json in its post-run summary so the
user knows their trace was partially downgraded. JSONL produced by the
healthy collectors is unaffected."
git push -u origin feat/m2-orchestrator-strace-fallback
gh pr create --title "feat(sandbox): strace fallback when bcc/bpftrace collector fails to attach" \
  --body "Closes #25. Implements §6.4 of the M2 spec." \
  --label enhancement
```

Wait for CI green, then squash-merge.

---

## Task 12: `image.py` — RunnerImage class

**Issue:** #32

**Files:**
- Create: `src/containerizer/trace/__init__.py`
- Create: `src/containerizer/trace/image.py`
- Create: `tests/unit/test_trace_image.py`

- [ ] **Step 1: Write the failing test first**

`tests/unit/test_trace_image.py`:

```python
"""Tests for the RunnerImage class."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from containerizer.trace.image import RunnerImage


def _write_sandbox(root: Path) -> Path:
    """Build a minimal sandbox dir matching the production layout."""
    sandbox = root / "sandbox" / "runner_image"
    (sandbox / "collectors").mkdir(parents=True)
    (sandbox / "Containerfile").write_text("FROM fedora:41\n", encoding="utf-8")
    (sandbox / "trace-orchestrator.sh").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    (sandbox / "collectors" / "open.bt").write_text("BEGIN{}\n", encoding="utf-8")
    return sandbox


def test_tag_is_localhost_runner_with_sha_prefix(tmp_path: Path) -> None:
    sandbox = _write_sandbox(tmp_path)
    img = RunnerImage(sandbox_dir=sandbox)
    assert re.fullmatch(r"localhost/containerizer-runner:sha-[0-9a-f]{8}", img.tag)


def test_tag_is_deterministic_per_content(tmp_path: Path) -> None:
    sandbox_a = _write_sandbox(tmp_path / "a")
    sandbox_b = _write_sandbox(tmp_path / "b")
    assert RunnerImage(sandbox_dir=sandbox_a).tag == RunnerImage(sandbox_dir=sandbox_b).tag


def test_tag_changes_when_content_changes(tmp_path: Path) -> None:
    sandbox = _write_sandbox(tmp_path)
    tag_before = RunnerImage(sandbox_dir=sandbox).tag
    (sandbox / "Containerfile").write_text("FROM fedora:42\n", encoding="utf-8")
    # cached_property: a fresh instance picks up the change.
    tag_after = RunnerImage(sandbox_dir=sandbox).tag
    assert tag_before != tag_after


@patch("containerizer.trace.image.subprocess.run")
def test_exists_returns_true_when_podman_succeeds(
    mock_run: MagicMock, tmp_path: Path
) -> None:
    mock_run.return_value.returncode = 0
    sandbox = _write_sandbox(tmp_path)
    assert RunnerImage(sandbox_dir=sandbox).exists() is True
    mock_run.assert_called_once()
    args = mock_run.call_args.args[0]
    assert args[:3] == ["podman", "image", "exists"]


@patch("containerizer.trace.image.subprocess.run")
def test_exists_returns_false_when_podman_returns_nonzero(
    mock_run: MagicMock, tmp_path: Path
) -> None:
    mock_run.return_value.returncode = 1
    sandbox = _write_sandbox(tmp_path)
    assert RunnerImage(sandbox_dir=sandbox).exists() is False


@patch("containerizer.trace.image.subprocess.run")
def test_build_invokes_podman_build_with_tag_and_sandbox(
    mock_run: MagicMock, tmp_path: Path
) -> None:
    mock_run.return_value.returncode = 0
    sandbox = _write_sandbox(tmp_path)
    img = RunnerImage(sandbox_dir=sandbox)
    img.build(stderr=None)  # type: ignore[arg-type]
    args = mock_run.call_args.args[0]
    assert args[:3] == ["podman", "build", "-t"]
    assert args[3] == img.tag
    assert args[-1] == str(sandbox)


@patch("containerizer.trace.image.subprocess.run")
def test_build_raises_on_nonzero_exit(mock_run: MagicMock, tmp_path: Path) -> None:
    mock_run.return_value.returncode = 1
    sandbox = _write_sandbox(tmp_path)
    img = RunnerImage(sandbox_dir=sandbox)
    with pytest.raises(subprocess.CalledProcessError):
        img.build(stderr=None)  # type: ignore[arg-type]
```

- [ ] **Step 2: Run the test, confirm it fails on import**

```
.venv/Scripts/python.exe -m pytest tests/unit/test_trace_image.py -v
```

Expected: ImportError because `containerizer.trace.image` does not exist.

- [ ] **Step 3: Create the package marker**

`src/containerizer/trace/__init__.py`:

```python
"""Trace half of the containerizer: sandbox + collectors + host wrapper."""
```

- [ ] **Step 4: Implement `image.py`**

`src/containerizer/trace/image.py`:

```python
"""Lazy podman build of the sandbox runner image.

The runner image is tagged by the SHA-256 of its `sandbox/runner_image/`
content so a rebuild fires only when the inputs change. Tag format:
    localhost/containerizer-runner:sha-<first 8 hex chars>
"""

from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import IO


@dataclass(frozen=True)
class RunnerImage:
    """The sandbox runner image, addressed by sandbox-dir content hash."""

    sandbox_dir: Path

    @cached_property
    def tag(self) -> str:
        """Container tag derived from the sandbox dir's content.

        Walks the sandbox dir, sorts files by relative path (lexicographic,
        forward-slash-normalised), and feeds `relpath_bytes + b"\\x00" +
        content_bytes` for each file into a single SHA-256. First 8 hex chars
        of the digest become the tag suffix.
        """
        digest = hashlib.sha256()
        for path in sorted(
            (p for p in self.sandbox_dir.rglob("*") if p.is_file()),
            key=lambda p: p.relative_to(self.sandbox_dir).as_posix(),
        ):
            rel = path.relative_to(self.sandbox_dir).as_posix().encode("utf-8")
            digest.update(rel)
            digest.update(b"\x00")
            digest.update(path.read_bytes())
        return f"localhost/containerizer-runner:sha-{digest.hexdigest()[:8]}"

    def exists(self) -> bool:
        """Whether the runner image is in the local podman image store."""
        result = subprocess.run(
            ["podman", "image", "exists", self.tag],
            check=False,
        )
        return result.returncode == 0

    def build(self, *, stderr: IO[str] | None) -> None:
        """Run `podman build` for this image, streaming stderr to `stderr`."""
        subprocess.run(
            ["podman", "build", "-t", self.tag, str(self.sandbox_dir)],
            check=True,
            stderr=stderr,
        )
```

- [ ] **Step 5: Run the test, confirm it passes**

```
.venv/Scripts/python.exe -m pytest tests/unit/test_trace_image.py -v
```

Expected: 7 passed.

- [ ] **Step 6: Run the full local gate**

```
.venv/Scripts/python.exe -m ruff check . && \
.venv/Scripts/python.exe -m ruff format --check . && \
.venv/Scripts/python.exe -m mypy src tests && \
.venv/Scripts/python.exe -m pytest
```

Expected: green, coverage stays ≥ 90%.

- [ ] **Step 7: Commit and open PR**

```
git checkout -b feat/m2-trace-image
git add src/containerizer/trace/__init__.py src/containerizer/trace/image.py \
        tests/unit/test_trace_image.py
git -c user.email="github.v5f9w@bitbucket.onl" \
    -c user.signingkey=BE707B220C995478 \
    commit -S -m "feat(trace): RunnerImage with hash-based tag and lazy podman build

Closes #32

Implements §6.5 of the M2 spec: SHA-256 of (sorted relpath + null + content)
across sandbox/runner_image/ → first 8 hex → tag suffix. cached_property so
the same instance reuses the hash; a fresh instance picks up edits.

Unit tests cover tag determinism across sandbox copies, tag invalidation
on content change, and subprocess invocation argv for exists / build."
git push -u origin feat/m2-trace-image
gh pr create --title "feat(trace): RunnerImage with hash-based tag and lazy podman build" \
  --body "Closes #32. Implements §6.5 RunnerImage of the M2 spec." \
  --label enhancement
```

Wait for CI green, then squash-merge.

---

## Task 13: `runner.py` — TraceRunner class

**Issue:** #33

**Files:**
- Create: `src/containerizer/trace/runner.py`
- Create: `tests/unit/test_trace_runner.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/test_trace_runner.py`:

```python
"""Tests for the TraceRunner class."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from containerizer.trace.runner import OutputDirNotEmpty, TraceRunner


def test_argv_is_the_podman_run_command(tmp_path: Path) -> None:
    installer = tmp_path / "install.sh"
    installer.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    output = tmp_path / "trace"
    output.mkdir()

    runner = TraceRunner(
        image_tag="localhost/containerizer-runner:sha-abc12345",
        installer=installer,
        output_dir=output,
    )

    argv = runner.argv()
    assert argv[:2] == ["podman", "run"]
    assert "--rm" in argv
    assert "-it" in argv
    assert "--privileged" in argv
    assert "--pid=host" in argv
    assert "-v" in argv
    assert f"{installer.resolve()}:/installer:ro" in argv
    assert f"{output.resolve()}:/work/trace" in argv
    assert argv[-2] == "localhost/containerizer-runner:sha-abc12345"
    assert argv[-1] == "/installer"


def test_output_dir_with_complete_marker_is_rejected_without_force(tmp_path: Path) -> None:
    installer = tmp_path / "install.sh"
    installer.write_text("", encoding="utf-8")
    output = tmp_path / "trace"
    output.mkdir()
    (output / "COMPLETE").write_text("", encoding="utf-8")

    with pytest.raises(OutputDirNotEmpty):
        TraceRunner(
            image_tag="localhost/containerizer-runner:sha-abc12345",
            installer=installer,
            output_dir=output,
        ).validate_output_dir(force=False)


def test_output_dir_with_complete_marker_is_accepted_with_force(tmp_path: Path) -> None:
    installer = tmp_path / "install.sh"
    installer.write_text("", encoding="utf-8")
    output = tmp_path / "trace"
    output.mkdir()
    (output / "COMPLETE").write_text("", encoding="utf-8")

    TraceRunner(
        image_tag="localhost/containerizer-runner:sha-abc12345",
        installer=installer,
        output_dir=output,
    ).validate_output_dir(force=True)


def test_output_dir_with_partial_marker_is_also_blocked(tmp_path: Path) -> None:
    installer = tmp_path / "install.sh"
    installer.write_text("", encoding="utf-8")
    output = tmp_path / "trace"
    output.mkdir()
    (output / "PARTIAL").write_text("", encoding="utf-8")

    with pytest.raises(OutputDirNotEmpty):
        TraceRunner(
            image_tag="localhost/containerizer-runner:sha-abc12345",
            installer=installer,
            output_dir=output,
        ).validate_output_dir(force=False)


@patch("containerizer.trace.runner.subprocess.run")
def test_run_calls_subprocess_with_argv(mock_run: MagicMock, tmp_path: Path) -> None:
    mock_run.return_value.returncode = 0
    installer = tmp_path / "install.sh"
    installer.write_text("", encoding="utf-8")
    output = tmp_path / "trace"
    output.mkdir()

    runner = TraceRunner(
        image_tag="localhost/containerizer-runner:sha-abc12345",
        installer=installer,
        output_dir=output,
    )
    assert runner.run() == 0
    mock_run.assert_called_once_with(runner.argv(), check=False)
```

- [ ] **Step 2: Run the test, confirm it fails on import**

Expected: ImportError because `containerizer.trace.runner` doesn't exist.

- [ ] **Step 3: Implement `runner.py`**

```python
"""Construct and exec the `podman run` for the trace sandbox."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


class OutputDirNotEmpty(RuntimeError):
    """Raised when the output dir already has a COMPLETE or PARTIAL marker."""


@dataclass(frozen=True)
class TraceRunner:
    """Builds the `podman run` argv and execs it."""

    image_tag: str
    installer: Path
    output_dir: Path

    def argv(self) -> list[str]:
        """Pure: returns the podman command without executing it."""
        return [
            "podman", "run", "--rm", "-it",
            "--privileged", "--pid=host",
            "-v", f"{self.installer.resolve()}:/installer:ro",
            "-v", f"{self.output_dir.resolve()}:/work/trace",
            self.image_tag,
            "/installer",
        ]

    def validate_output_dir(self, *, force: bool) -> None:
        """Refuse to overwrite an existing trace unless `force` is set."""
        for marker in ("COMPLETE", "PARTIAL"):
            if (self.output_dir / marker).exists() and not force:
                raise OutputDirNotEmpty(
                    f"{self.output_dir} already contains a {marker} marker. "
                    f"Use --force to replace or pick a fresh directory."
                )

    def run(self) -> int:
        """Exec the podman command in the foreground."""
        result = subprocess.run(self.argv(), check=False)
        return result.returncode
```

- [ ] **Step 4: Run the test, confirm it passes**

Expected: 5 passed.

- [ ] **Step 5: Run the full local gate**

Same command as task 12 step 6. All green, coverage stays ≥ 90%.

- [ ] **Step 6: Commit and open PR**

```
git checkout -b feat/m2-trace-runner
git add src/containerizer/trace/runner.py tests/unit/test_trace_runner.py
git -c user.email="github.v5f9w@bitbucket.onl" \
    -c user.signingkey=BE707B220C995478 \
    commit -S -m "feat(trace): TraceRunner constructs podman-run argv and execs

Closes #33

Implements §6.5 TraceRunner of the M2 spec. Pure argv() returns the
podman command list; run() shells out; validate_output_dir(force) refuses
to overwrite an existing COMPLETE or PARTIAL marker.

Unit tests cover argv shape, output-dir refusal/override, and
subprocess invocation."
git push -u origin feat/m2-trace-runner
gh pr create --title "feat(trace): TraceRunner constructs podman-run argv and execs" \
  --body "Closes #33. Implements §6.5 TraceRunner of the M2 spec." \
  --label enhancement
```

Wait for CI green, then squash-merge.

---

## Task 14: `cli.py` — `containerizer trace` subcommand

**Issue:** #34

**Files:**
- Create: `src/containerizer/trace/cli.py`
- Modify: `src/containerizer/cli.py` (register the trace subcommand)
- Create: `tests/unit/test_trace_cli.py`

- [ ] **Step 1: Write the failing CLI tests**

`tests/unit/test_trace_cli.py`:

```python
"""Tests for the `containerizer trace` Click subcommand."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from containerizer.cli import main


def test_trace_help_lists_required_options() -> None:
    result = CliRunner().invoke(main, ["trace", "--help"])
    assert result.exit_code == 0
    assert "Statically analyse" not in result.output  # not the probe help
    assert "-o" in result.output or "--output-dir" in result.output
    assert "--force" in result.output


@patch("containerizer.trace.cli._podman_machine_is_running")
def test_trace_refuses_when_podman_machine_is_not_running(
    mock_machine: MagicMock, tmp_path: Path
) -> None:
    mock_machine.return_value = False
    installer = tmp_path / "fake-installer"
    installer.write_bytes(b"\x00")
    output = tmp_path / "out"

    result = CliRunner().invoke(
        main, ["trace", str(installer), "-o", str(output)]
    )
    assert result.exit_code != 0
    assert "podman machine" in result.output.lower()
    assert "start" in result.output.lower()


@patch("containerizer.trace.cli.TraceRunner")
@patch("containerizer.trace.cli.RunnerImage")
@patch("containerizer.trace.cli._podman_machine_is_running")
def test_trace_builds_image_when_missing(
    mock_machine: MagicMock,
    mock_image_cls: MagicMock,
    mock_runner_cls: MagicMock,
    tmp_path: Path,
) -> None:
    mock_machine.return_value = True
    image = MagicMock()
    image.exists.return_value = False
    image.tag = "localhost/containerizer-runner:sha-abcdef12"
    mock_image_cls.return_value = image

    runner = MagicMock()
    runner.run.return_value = 0
    mock_runner_cls.return_value = runner

    installer = tmp_path / "fake-installer"
    installer.write_bytes(b"\x00")
    output = tmp_path / "out"
    output.mkdir()
    (output / "COMPLETE").write_text("", encoding="utf-8")  # written by orchestrator

    result = CliRunner().invoke(
        main, ["trace", str(installer), "-o", str(output)]
    )
    assert result.exit_code == 0
    image.build.assert_called_once()


@patch("containerizer.trace.cli.TraceRunner")
@patch("containerizer.trace.cli.RunnerImage")
@patch("containerizer.trace.cli._podman_machine_is_running")
def test_trace_skips_build_when_image_exists(
    mock_machine: MagicMock,
    mock_image_cls: MagicMock,
    mock_runner_cls: MagicMock,
    tmp_path: Path,
) -> None:
    mock_machine.return_value = True
    image = MagicMock()
    image.exists.return_value = True
    image.tag = "localhost/containerizer-runner:sha-abcdef12"
    mock_image_cls.return_value = image

    runner = MagicMock()
    runner.run.return_value = 0
    mock_runner_cls.return_value = runner

    installer = tmp_path / "fake-installer"
    installer.write_bytes(b"\x00")
    output = tmp_path / "out"
    output.mkdir()
    (output / "COMPLETE").write_text("", encoding="utf-8")

    result = CliRunner().invoke(
        main, ["trace", str(installer), "-o", str(output)]
    )
    assert result.exit_code == 0
    image.build.assert_not_called()


@patch("containerizer.trace.cli.TraceRunner")
@patch("containerizer.trace.cli.RunnerImage")
@patch("containerizer.trace.cli._podman_machine_is_running")
def test_trace_reports_partial_marker(
    mock_machine: MagicMock,
    mock_image_cls: MagicMock,
    mock_runner_cls: MagicMock,
    tmp_path: Path,
) -> None:
    mock_machine.return_value = True
    image = MagicMock()
    image.exists.return_value = True
    image.tag = "localhost/containerizer-runner:sha-abcdef12"
    mock_image_cls.return_value = image

    runner = MagicMock()
    runner.run.return_value = 0
    mock_runner_cls.return_value = runner

    installer = tmp_path / "fake-installer"
    installer.write_bytes(b"\x00")
    output = tmp_path / "out"
    output.mkdir()
    (output / "PARTIAL").write_text("", encoding="utf-8")

    result = CliRunner().invoke(
        main, ["trace", str(installer), "-o", str(output)]
    )
    assert result.exit_code == 0
    assert "PARTIAL" in result.output
```

- [ ] **Step 2: Run the tests; confirm `trace` subcommand is not registered**

Expected: errors because `main` has no `trace` subcommand yet.

- [ ] **Step 3: Implement `containerizer/trace/cli.py`**

```python
"""`containerizer trace <installer> -o <out>` Click subcommand."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import click

from containerizer.trace.image import RunnerImage
from containerizer.trace.runner import OutputDirNotEmpty, TraceRunner


def _sandbox_dir() -> Path:
    """Resolve sandbox/runner_image/ relative to the source tree.

    Assumes editable install (`pip install -e .`) so the runner image source
    is at <repo>/sandbox/runner_image/. Wheel-install support is out of M2.
    """
    return Path(__file__).resolve().parents[3] / "sandbox" / "runner_image"


def _podman_machine_is_running() -> bool:
    """Return True iff at least one podman machine reports State=Running."""
    try:
        result = subprocess.run(
            ["podman", "machine", "ls", "--format", "json"],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return False
    if result.returncode != 0:
        return False
    try:
        machines = json.loads(result.stdout)
    except json.JSONDecodeError:
        return False
    return any(m.get("Running") is True for m in machines)


@click.command("trace")
@click.argument(
    "installer",
    type=click.Path(exists=True, dir_okay=False, readable=True, path_type=Path),
)
@click.option(
    "-o",
    "--output-dir",
    required=True,
    type=click.Path(path_type=Path),
    help="Directory the trace JSONL streams + install.log + markers are written to.",
)
@click.option(
    "--force",
    is_flag=True,
    help="Overwrite output-dir if it already contains a COMPLETE / PARTIAL marker.",
)
def trace_cmd(installer: Path, output_dir: Path, force: bool) -> None:
    """Run INSTALLER inside the trace sandbox and capture observations."""
    if not _podman_machine_is_running():
        raise click.ClickException(
            "Podman machine is not running. Start it with: podman machine start"
        )

    output_dir.mkdir(parents=True, exist_ok=True)

    image = RunnerImage(sandbox_dir=_sandbox_dir())
    if not image.exists():
        click.echo(f"[image] building {image.tag} (first run, ~5 min)...", err=True)
        image.build(stderr=sys.stderr)

    runner = TraceRunner(
        image_tag=image.tag,
        installer=installer.resolve(),
        output_dir=output_dir.resolve(),
    )
    try:
        runner.validate_output_dir(force=force)
    except OutputDirNotEmpty as exc:
        raise click.ClickException(str(exc)) from exc

    exit_code = runner.run()
    _print_summary(output_dir, exit_code=exit_code)


def _print_summary(output_dir: Path, *, exit_code: int) -> None:
    """Post-run summary: marker + per-collector counts + fallback notice."""
    complete = (output_dir / "COMPLETE").exists()
    partial = (output_dir / "PARTIAL").exists()
    if not complete and not partial:
        raise click.ClickException(
            f"Trace did not finalise. Inspect {output_dir}/install.log and "
            f"{output_dir}/*.err for collector errors."
        )

    marker = "COMPLETE" if complete else "PARTIAL"
    click.echo(f"marker: {marker}")
    for name in ("open", "bind", "connect", "accept", "syscalls", "capable"):
        path = output_dir / f"{name}.jsonl"
        count = sum(1 for _ in path.open()) if path.exists() else 0
        click.echo(f"{name:<10}{count:>10} events")
    click.echo(f"trace at {output_dir}  (next: containerizer analyze, not yet implemented)")

    fallbacks = output_dir / "FALLBACKS.json"
    if fallbacks.exists() and fallbacks.stat().st_size > 0:
        click.echo("")
        click.echo("WARNING: one or more collectors fell back to strace:", err=True)
        click.echo(fallbacks.read_text(encoding="utf-8"), err=True)

    if exit_code != 0:
        raise click.ClickException(
            f"podman exited with code {exit_code} (marker was {marker})"
        )
```

- [ ] **Step 4: Register the `trace` subcommand on the main CLI group**

Modify `src/containerizer/cli.py`. Add an import near the top:

```python
from containerizer.trace.cli import trace_cmd
```

After the `@main.command("probe")` block ends, register the trace command:

```python
main.add_command(trace_cmd)
```

- [ ] **Step 5: Run the tests; confirm pass**

Expected: 5 passed.

- [ ] **Step 6: Run the full local gate**

All green. Coverage stays ≥ 90% (cli.py is heavily mocked; should be fine).

- [ ] **Step 7: Commit and open PR**

```
git checkout -b feat/m2-trace-cli
git add src/containerizer/trace/cli.py src/containerizer/cli.py \
        tests/unit/test_trace_cli.py
git -c user.email="github.v5f9w@bitbucket.onl" \
    -c user.signingkey=BE707B220C995478 \
    commit -S -m "feat(trace): containerizer trace subcommand with pre-flight and summary

Closes #34

Implements §6.5 cli.py of the M2 spec: Click subcommand registered on
the main containerizer group; pre-flight verifies the podman machine is
running; ensures the runner image is built (lazy); execs TraceRunner;
prints a post-run summary with marker, per-collector event counts, and
a warning paragraph if any collector fell back to strace.

Unit tests use CliRunner with patched RunnerImage / TraceRunner /
_podman_machine_is_running."
git push -u origin feat/m2-trace-cli
gh pr create --title "feat(trace): containerizer trace subcommand with pre-flight and summary" \
  --body "Closes #34. Implements §6.5 cli.py of the M2 spec." \
  --label enhancement
```

Wait for CI green, then squash-merge.

---

## Task 15: Synthetic-installer test fixture

**Issue:** #35

**Files:**
- Create: `tests/fixtures/trace/synthetic-installer.sh`

- [ ] **Step 1: Write the fixture script**

```bash
#!/bin/sh
# synthetic-installer.sh — deterministic exercise for every collector.
#
# Targets one event per collector minimum:
#   open       — cat /etc/passwd
#   bind/accept — backgrounded nc listener + foreground nc connector
#   connect    — python3 socket().connect((127.0.0.1, 1))  (refused; counts)
#   syscalls   — anything; reads always emit several
#   capable    — chown of a non-existent owner triggers a CAP_CHOWN check
#
# Total runtime is <1 second; the orchestrator's EOF-on-stdin finalises COMPLETE.
set -eu

echo "synthetic-installer: starting"

cat /etc/passwd > /dev/null

python3 - <<'PY'
import socket
try:
    s = socket.socket()
    s.connect(("127.0.0.1", 1))
except OSError:
    pass
PY

python3 - <<'PY'
import socket
s = socket.socket()
s.bind(("127.0.0.1", 0))
s.listen(1)
print("bound on", s.getsockname())
PY

nc -l 127.0.0.1 23456 >/dev/null 2>&1 &
listener_pid=$!
sleep 0.2
echo hi | nc -w 1 127.0.0.1 23456 >/dev/null 2>&1 || true
wait "$listener_pid" 2>/dev/null || true

# Capability check — chown to a non-existent UID triggers cap_capable for CAP_CHOWN
chown 99999:99999 /tmp/synthetic-installer.$$ 2>/dev/null || true

cat /proc/self/status > /dev/null

echo "synthetic-installer: done"
```

- [ ] **Step 2: Commit and open PR**

```
git checkout -b test/m2-synthetic-installer-fixture
chmod +x tests/fixtures/trace/synthetic-installer.sh
git add tests/fixtures/trace/synthetic-installer.sh
git -c user.email="github.v5f9w@bitbucket.onl" \
    -c user.signingkey=BE707B220C995478 \
    commit -S -m "test(trace): synthetic shell-script fixture exercising every collector

Closes #35

POSIX shell script that issues at least one event per collector in
under 1 second: cat /etc/passwd (open), python3 socket.bind (bind),
python3 socket.connect (connect), nc -l + nc client (accept), chown
to a non-existent UID (capable), plus several reads to populate
syscalls.

Used by the integration test in task 16."
git push -u origin test/m2-synthetic-installer-fixture
gh pr create --title "test(trace): synthetic shell-script fixture exercising every collector" \
  --body "Closes #35. Implements §6.6 of the M2 spec." \
  --label enhancement
```

Wait for CI green, then squash-merge.

---

## Task 16: Integration test

**Issue:** #36

**Files:**
- Create: `tests/integration/trace/__init__.py`
- Create: `tests/integration/trace/test_trace_pipeline.py`

- [ ] **Step 1: Create the integration test package marker**

`tests/integration/trace/__init__.py`: empty file.

- [ ] **Step 2: Write the integration test**

`tests/integration/trace/test_trace_pipeline.py`:

```python
"""End-to-end trace pipeline test against the synthetic fixture.

Marked @pytest.mark.integration; skipped by default. Run via:
    pytest -m integration
Requires podman + Linux kernel with eBPF/BTF.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.integration
def test_trace_pipeline_against_synthetic_fixture(tmp_path: Path) -> None:
    fixture = REPO_ROOT / "tests/fixtures/trace/synthetic-installer.sh"
    assert fixture.exists(), f"missing fixture: {fixture}"

    out = tmp_path / "trace"
    out.mkdir()

    result = subprocess.run(
        ["containerizer", "trace", str(fixture), "-o", str(out)],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert result.returncode == 0, (result.stdout, result.stderr)

    assert (out / "COMPLETE").exists(), f"no COMPLETE marker; stderr was: {result.stderr}"
    assert (out / "install.log").stat().st_size > 0

    for collector in ("open", "bind", "connect", "accept", "syscalls", "capable"):
        path = out / f"{collector}.jsonl"
        assert path.exists(), f"missing {path}"
        assert path.stat().st_size > 0, f"empty {path}"

    opens = [json.loads(line) for line in (out / "open.jsonl").read_text().splitlines() if line.strip()]
    assert any(rec.get("path") == "/etc/passwd" for rec in opens), \
        "expected /etc/passwd in open.jsonl"
```

- [ ] **Step 3: Sanity-check that the marker still skips by default**

```
.venv/Scripts/python.exe -m pytest
```

Expected: same 40 tests pass, integration test is collected and DESELECTED (not collected if filtered, just not run). No errors about unknown marker (task 1 registered it).

- [ ] **Step 4: Commit and open PR**

```
git checkout -b test/m2-integration-trace-pipeline
git add tests/integration/trace/
git -c user.email="github.v5f9w@bitbucket.onl" \
    -c user.signingkey=BE707B220C995478 \
    commit -S -m "test(trace): integration test gated on @pytest.mark.integration

Closes #36

End-to-end test that spawns 'containerizer trace' as a subprocess with
stdin=DEVNULL against the synthetic fixture. Asserts COMPLETE marker
exists, every collector produced non-empty JSONL, and /etc/passwd shows
up in open.jsonl (smoke-checks the open collector specifically).

Subprocess (rather than CliRunner.invoke) is mandatory: CliRunner's
stdin interception doesn't propagate to the podman-run subprocess that
actually needs the EOF; see §6.7 of the M2 spec for the full rationale.

Marker is skipped by default; the trace-integration CI job in task 17
runs it."
git push -u origin test/m2-integration-trace-pipeline
gh pr create --title "test(trace): integration test gated on @pytest.mark.integration" \
  --body "Closes #36. Implements §6.7 of the M2 spec." \
  --label enhancement
```

Wait for CI green, then squash-merge.

---

## Task 17: `trace-integration` CI job + MANUAL scenario 6

**Issue:** #37

**Files:**
- Modify: `.github/workflows/ci.yml`
- Modify: `MANUAL.md`

- [ ] **Step 1: Add the `trace-integration` job to `ci.yml`**

Append after the existing `test` matrix job:

```yaml
  trace-integration:
    name: Trace integration
    runs-on: ubuntu-latest
    timeout-minutes: 15
    steps:
      - uses: actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5  # v4.3.1
      - uses: actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065  # v5.6.0
        with:
          python-version: "3.12"
          cache: pip
          cache-dependency-path: pyproject.toml
      - name: Install podman and trace tooling
        run: |
          sudo apt-get update
          sudo apt-get install -y podman bcc-tools bpftrace strace
      - name: Install package
        run: |
          python -m pip install --upgrade pip
          pip install -e ".[dev]"
      - name: Run trace integration test
        run: pytest -m integration -v
```

- [ ] **Step 2: Add scenario 6 to MANUAL.md**

After scenario 5 (base-image routing matrix), add:

```markdown
## Scenario 6 — `containerizer trace`

Run a Linux installer inside the trace sandbox and capture six JSONL observation streams.

Prerequisites: a running Podman machine (`podman machine start`).

The first invocation builds the runner image (~5 min one-time on cold cache):

```pwsh
PS> mkdir C:\Temp\synthetic-trace
PS> containerizer trace .\tests\fixtures\trace\synthetic-installer.sh -o C:\Temp\synthetic-trace
```

Expected output:

```
[image] building localhost/containerizer-runner:sha-...  (first run, ~5 min)
...
trace-orchestrator: running installer /installer
trace-orchestrator: installer complete. exercise the software, then press <Enter> here to finalise (or close stdin).
```

Press Enter. Then:

```
trace-orchestrator: COMPLETE

marker: COMPLETE
open               12 events
bind                3 events
connect             2 events
accept              1 events
syscalls           57 events
capable             4 events
trace at C:\Temp\synthetic-trace  (next: containerizer analyze, not yet implemented)
```

The directory contains: six `*.jsonl` streams, `install.log`, `PHASE_MARKER`, `COMPLETE`. If a collector fell back to strace, a `FALLBACKS.json` file appears and the CLI prints a warning paragraph.

Scenario 6 is also what the new `trace-integration` CI job runs on every PR (against the synthetic fixture, not against a real installer).
```

- [ ] **Step 3: Commit and open PR**

```
git checkout -b ci/m2-trace-integration-job
git add .github/workflows/ci.yml MANUAL.md
git -c user.email="github.v5f9w@bitbucket.onl" \
    -c user.signingkey=BE707B220C995478 \
    commit -S -m "ci: trace-integration job on ubuntu-latest and MANUAL scenario 6

Closes #37

Adds the trace-integration job to ci.yml: ubuntu-latest, apt-installs
podman + bcc-tools + bpftrace + strace, pip-installs the package, runs
pytest -m integration. 15-minute timeout accommodates the ~5 min cold
runner-image build plus the actual trace.

Branch protection on main must be updated to require the new
'Trace integration' status check after this PR merges. Manual step:

  gh api repos/SupremeCommanderHedgehog/containerizer/branches/main/protection/required_status_checks \\
      --method PATCH \\
      --input <json with new contexts list including 'Trace integration'>

(See the PATCH used for issue #6 / PR #15 as a reference for the
required_status_checks payload shape.)

MANUAL.md gets a scenario 6 entry walking through the full trace
flow against the synthetic fixture and explaining what to expect in
the output directory and the post-run summary."
git push -u origin ci/m2-trace-integration-job
gh pr create --title "ci: trace-integration job on ubuntu-latest and MANUAL scenario 6" \
  --body "$(cat <<'BODY'
Closes #37. Implements §6.8 of the M2 spec.

## Summary
- New \`trace-integration\` job in \`.github/workflows/ci.yml\`. ubuntu-latest; apt-installs podman + bcc-tools + bpftrace + strace; pip-installs the package; runs \`pytest -m integration\`. 15-min timeout.
- New scenario 6 in \`MANUAL.md\` walking through the trace flow.

## Branch protection follow-up — REQUIRED before merge

The new \`Trace integration\` check needs to be added to the required status checks on \`main\`. Without it the check will run but won't gate. Use the same \`gh api PATCH\` pattern as PR #15 used for the matrix rename — append \`Trace integration\` (app_id 15368) to the \`checks\` list. Recipe in the commit message.

## Risk
First-run tuning likely. Privileged podman on the runner-provided unprivileged user may need \`sudo podman\`; bcc on ubuntu-latest may need kernel headers despite BTF. Both tractable; expect 1-2 follow-up commits on this branch before CI is green.
BODY
)" \
  --label enhancement
```

Wait for CI green (probably after 1-2 tuning commits), then squash-merge. Then update branch protection per the PR body.

---

## After the plan

Once all 17 tasks have landed, M2 is complete:

1. `containerizer trace <installer> -o trace/` works end to end.
2. Every PR is gated by the integration test.
3. Six JSONL streams + markers are the M3 analyzer's input format.
4. The release-please bot will have queued a 0.3.0 release PR (the wrapper module is a `feat:`).

Next milestone (M3) is filed as issues #38, #39 — analyzer + policy derivation. They take the JSONL produced by M2 as input. M4–M6 follow as #40–#44.
