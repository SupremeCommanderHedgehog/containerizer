# Issue #90 — systemd-as-PID-1 Trace Runner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Boot stock systemd as PID 1 inside the trace runner container so installers that depend on `loginctl`, `systemctl --user`, or the system/session DBus bus work end-to-end. Closes #90 once MANUAL.md scenario 11 (UniFi) passes.

**Architecture:** ENTRYPOINT switches to `/sbin/init`. The existing `trace-orchestrator.sh` runs as a oneshot systemd service wired to `/dev/console` (preserves the "press Enter to finalise" UX). Mode + installer-path flow via `CONTAINERIZER_MODE` / `CONTAINERIZER_INSTALLER` env vars instead of positional argv. Host wrapper drops `--pid=host` (incompatible with systemd-PID-1) and adds `--systemd=always`. Container shuts down via `OnSuccess=poweroff.target` / `OnFailure=poweroff.target`.

**Tech Stack:** Fedora 41, systemd 256+, Podman 4.x+, Python 3.13, pytest, bash. Spec: [`2026-06-09-containerizer-issue-90-systemd-pid1.md`](../specs/2026-06-09-containerizer-issue-90-systemd-pid1.md).

---

## Phasing Overview

| Phase | What | Hard gate |
|---|---|---|
| 0 | Drop `--pid=host` (preflight) | Existing M2 integration test must still produce non-empty `trace.json`. If it regresses, **HALT and re-open the spec**. |
| 1 | Runner image → systemd-PID-1 | Unit tests + image builds cleanly |
| 2 | Integration test for systemd reachability | Synthetic loginctl installer succeeds under new runner; M6 verify-mode regression test passes |
| 3 | Manual scenario 11 acceptance | UniFi installer end-to-end on Windows/WSL2 |
| 4 | Docs + close issue | MANUAL.md updated, PR body has `Closes #90` |

All commits signed with key `BE707B220C995478`, author `github.v5f9w@bitbucket.onl`.

---

## Pre-flight: branch setup

This plan ships as the **implementation PR**, separate from the docs PR that lands this plan + spec. Before starting Phase 0:

```bash
git fetch origin main
git checkout -b feat/issue-90-systemd-pid1 origin/main
```

All Phase 0-4 commits land on `feat/issue-90-systemd-pid1`. The branch is pushed and the PR opened in Task 4.2.

---

## File Structure

**Files modified:**
- `src/containerizer/trace/runner.py` — drop `--pid=host`, add `--systemd=always`, swap argv-positional to env vars
- `sandbox/runner_image/Containerfile` — `ENTRYPOINT ["/sbin/init"]`, COPY new unit files, `systemctl enable` them
- `tests/unit/test_trace_runner.py` — assertions updated for new argv shape
- `MANUAL.md` — scenario 11 status note (post-acceptance)

**Files created:**
- `sandbox/runner_image/containerizer-trace.service` — main service unit
- `sandbox/runner_image/containerizer-trace-env.service` — env-publisher unit
- `tests/integration/trace/test_systemd_pid1.py` — new integration test
- `tests/fixtures/trace/loginctl-installer.sh` — synthetic installer that calls `loginctl`

**Files unchanged:**
- `sandbox/runner_image/trace-orchestrator.sh` — contract preserved (still takes `--mode` + installer-path as argv; the systemd unit synthesises the call)
- `sandbox/runner_image/verify-orchestrator.sh` — untouched

---

## Phase 0: Drop `--pid=host` (preflight validation gate)

### Task 0.1: Update unit tests to expect `--pid=host` absent (RED)

**Files:**
- Modify: `tests/unit/test_trace_runner.py:31` (install-mode test)
- Modify: `tests/unit/test_trace_runner.py:105-136` (verify-mode test)

- [ ] **Step 1: Edit install-mode test**

In `tests/unit/test_trace_runner.py`, replace line 31:

```python
    assert "--pid=host" in argv
```

with:

```python
    assert "--pid=host" not in argv
```

- [ ] **Step 2: Add explicit verify-mode assertion**

In `tests/unit/test_trace_runner.py`, find the `test_verify_mode_argv_includes_image_tar_and_env_vars` function. After the existing `assert not any(":/installer:" in a for a in argv)` line at the end, add:

```python
    assert "--pid=host" not in argv
```

- [ ] **Step 3: Run tests, verify they fail**

Run: `pytest tests/unit/test_trace_runner.py -v`
Expected: FAIL on both `test_argv_is_the_podman_run_command` and `test_verify_mode_argv_includes_image_tar_and_env_vars` (both still see `--pid=host` in argv).

- [ ] **Step 4: Commit**

```bash
git add tests/unit/test_trace_runner.py
git -c user.email="github.v5f9w@bitbucket.onl" -c user.signingkey=BE707B220C995478 commit -S -m "$(cat <<'EOF'
test(trace): assert --pid=host is dropped from podman argv (#90)

Preflight for issue #90: systemd-as-PID-1 is incompatible with
--pid=host (one PID NS, one PID 1). These assertions flip before
the runner.py change so the test failure is the signal.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

### Task 0.2: Remove `--pid=host` from runner.py (GREEN)

**Files:**
- Modify: `src/containerizer/trace/runner.py:101` (install argv)
- Modify: `src/containerizer/trace/runner.py:134` (verify argv)

- [ ] **Step 1: Remove from install argv**

In `src/containerizer/trace/runner.py`, find the install-mode argv builder (`_install_argv`). Delete the two lines:

```python
            "--privileged",
            "--pid=host",
```

and replace with just:

```python
            "--privileged",
```

- [ ] **Step 2: Remove from verify argv**

In `src/containerizer/trace/runner.py`, find the verify-mode argv builder (`_verify_argv`). Delete the two lines:

```python
            "--privileged",
            "--pid=host",
```

and replace with just:

```python
            "--privileged",
```

- [ ] **Step 3: Run tests, verify they pass**

Run: `pytest tests/unit/test_trace_runner.py -v`
Expected: PASS for all tests in that file.

- [ ] **Step 4: Commit**

```bash
git add src/containerizer/trace/runner.py
git -c user.email="github.v5f9w@bitbucket.onl" -c user.signingkey=BE707B220C995478 commit -S -m "$(cat <<'EOF'
fix(trace): drop --pid=host from podman argv (#90 preflight)

--pid=host shares the host PID namespace with the container, which
is incompatible with systemd-as-PID-1 (one PID NS, one PID 1). The
M2 spec's reasoning ("required for bcc/bpftrace to see the
installer's process tree") was overcautious: BPF programs run in
the host kernel regardless of container PID namespace, so collector
pid fields remain host PIDs either way. The analyzer aggregates
across all observed PIDs in the trace window without filtering by
installer PID, so no data fidelity loss is expected.

Phase 0 of #90: validates this assumption via the existing M2
integration test before any systemd work begins.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

### Task 0.3: Validation gate — run M2 integration test

**Files:**
- Read: `tests/integration/trace/test_trace_pipeline.py`

- [ ] **Step 1: Run integration test**

Requires podman + Linux host with eBPF/BTF (Linux dev machine or WSL2).

Run: `pytest tests/integration/trace/test_trace_pipeline.py -v -m integration`
Expected: PASS. `trace.json` populates with non-empty `paths`, `ports`, `caps`, `syscalls`.

- [ ] **Step 2: HARD STOP decision point**

- **If the test PASSES:** continue to Phase 1.
- **If the test FAILS or `trace.json` is empty:** revert Tasks 0.1 and 0.2 (`git reset --hard HEAD~2`), re-open the spec to discuss `--pid=host` removal — possibly chase `--userns=keep-id` or other PID-NS preservation. Do NOT proceed to Phase 1.

If the test is unrunnable in the current environment (e.g., no podman, Windows-only checkout), defer Phase 0.3 to a Linux host and do not start Phase 1 until it's been run somewhere.

---

## Phase 1: Runner image → systemd-PID-1

### Task 1.1: Create `containerizer-trace.service` unit file

**Files:**
- Create: `sandbox/runner_image/containerizer-trace.service`

- [ ] **Step 1: Write the unit file**

Create `sandbox/runner_image/containerizer-trace.service` with this exact content:

```ini
[Unit]
Description=Containerizer trace orchestrator
After=multi-user.target containerizer-trace-env.service
Requires=containerizer-trace-env.service
Conflicts=getty@tty1.service console-getty.service

[Service]
Type=oneshot
RemainAfterExit=no
EnvironmentFile=/run/containerizer/env
ExecStart=/opt/containerizer/trace-orchestrator.sh --mode ${CONTAINERIZER_MODE} ${CONTAINERIZER_INSTALLER}
StandardInput=tty
StandardOutput=tty
StandardError=tty
TTYPath=/dev/console
TTYReset=no
TTYVHangup=no
TimeoutStartSec=0
OnSuccess=poweroff.target
OnFailure=poweroff.target

[Install]
WantedBy=multi-user.target
```

Note: in verify mode `CONTAINERIZER_INSTALLER` will be unset (empty), so `ExecStart` resolves to `... --mode verify ` (trailing empty arg). systemd strips trailing empty args from `ExecStart=` expansion, so this works without a separate verify unit.

- [ ] **Step 2: Verify LF line endings**

This file is consumed inside a Linux container. CRLF would break systemd parsing.

Run from Bash: `file sandbox/runner_image/containerizer-trace.service`
Expected output: `... ASCII text` (NOT `... CRLF line terminators`)

If CRLF appears, re-save with LF. (`.gitattributes` already pins `*.service` to LF? Verify — if not, the next step adds it.)

- [ ] **Step 3: Pin LF in .gitattributes if not already**

Check `.gitattributes` for a `*.service` rule. If absent, append:

```
*.service text eol=lf
```

- [ ] **Step 4: Commit**

```bash
git add sandbox/runner_image/containerizer-trace.service .gitattributes
git -c user.email="github.v5f9w@bitbucket.onl" -c user.signingkey=BE707B220C995478 commit -S -m "$(cat <<'EOF'
feat(runner): add containerizer-trace systemd unit (#90)

Oneshot unit that runs trace-orchestrator.sh after systemd reaches
multi-user.target. Wired to /dev/console with TTYReset=no so the
user's interactive "press Enter to finalise" UX survives the move
to systemd-PID-1.

OnSuccess=poweroff.target ensures the container exits cleanly when
the orchestrator finishes (which it always does, exit 0, per the
M2 orchestrator contract). OnFailure=poweroff.target covers signal
exit and other non-zero paths.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

### Task 1.2: Create `containerizer-trace-env.service` unit file

**Files:**
- Create: `sandbox/runner_image/containerizer-trace-env.service`

- [ ] **Step 1: Write the unit file**

Create `sandbox/runner_image/containerizer-trace-env.service` with this exact content:

```ini
[Unit]
Description=Publish podman-passed env to /run/containerizer/env
DefaultDependencies=no
Before=containerizer-trace.service
After=local-fs.target
RequiresMountsFor=/run

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStartPre=/usr/bin/mkdir -p /run/containerizer
ExecStart=/usr/bin/sh -c 'env | grep -E "^CONTAINERIZER_" > /run/containerizer/env'
OnFailure=poweroff.target

[Install]
WantedBy=multi-user.target
```

This unit reads PID 1's environment (where Podman places the `-e VAR=value` env vars), filters to `CONTAINERIZER_*`, and writes them to a file that the trace unit's `EnvironmentFile=` can consume. systemd's `EnvironmentFile=` reads files, not the live environment, so this hand-off is required.

- [ ] **Step 2: Verify LF line endings**

Same check as Task 1.1 Step 2.

- [ ] **Step 3: Commit**

```bash
git add sandbox/runner_image/containerizer-trace-env.service
git -c user.email="github.v5f9w@bitbucket.onl" -c user.signingkey=BE707B220C995478 commit -S -m "$(cat <<'EOF'
feat(runner): add containerizer-trace-env systemd unit (#90)

Captures podman -e CONTAINERIZER_* env vars from PID 1's
environment into /run/containerizer/env at boot, before
containerizer-trace.service starts. Required because systemd's
EnvironmentFile= reads files, not the live process environment.

OnFailure=poweroff.target halts the container if env capture
fails (e.g., /run not writable) so we get a clear "no markers
written" signal upstream rather than a hang.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

### Task 1.3: Update Containerfile (`ENTRYPOINT`, COPY, enable)

**Files:**
- Modify: `sandbox/runner_image/Containerfile`

- [ ] **Step 1: Update Containerfile**

Replace the entire contents of `sandbox/runner_image/Containerfile` with:

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
# As of issue #90 the runner BOOTS systemd as PID 1 (ENTRYPOINT=/sbin/init).
# The existing trace-orchestrator.sh runs as a oneshot systemd service.
#
# The image is intentionally fat (~600 MB). It is built once per sandbox/
# directory content hash on the user's host (see src/containerizer/trace/image.py)
# and reused across every `containerizer trace` invocation.
FROM fedora:41

RUN dnf install -y --setopt=install_weak_deps=False \
      systemd dbus \
      bcc-tools bpftrace strace audit-libs audit \
      kernel-headers glibc-headers \
      nmap-ncat \
      jq python3 \
    && dnf clean all

# Project-specific tooling lives under /opt/containerizer/ so /usr stays clean.
RUN mkdir -p /opt/containerizer/collectors /work/trace
COPY trace-orchestrator.sh /opt/containerizer/trace-orchestrator.sh
COPY collectors/           /opt/containerizer/collectors/
RUN chmod +x /opt/containerizer/trace-orchestrator.sh

# M6: nested podman so the trace-runner can rebuild and exercise the
# generated container under strict policy during the verify pass.
RUN dnf install -y \
        podman \
        slirp4netns \
        fuse-overlayfs \
        crun \
        conmon \
        shadow-utils && \
    dnf clean all && \
    rm -rf /var/cache/dnf

# Pre-create storage roots so the first nested `podman load` doesn't pay
# cold-cache setup latency inside the trace window.
RUN mkdir -p /var/lib/containers \
             /var/lib/shared/overlay-images \
             /var/lib/shared/overlay-layers \
             /var/lib/shared/vfs-images \
             /var/lib/shared/vfs-layers && \
    chmod 755 /var/lib/containers

COPY verify-orchestrator.sh /usr/local/bin/verify-orchestrator.sh
RUN chmod +x /usr/local/bin/verify-orchestrator.sh

# Issue #90: boot systemd as PID 1 so installers that need loginctl /
# systemctl --user / the system DBus bus work end-to-end. The orchestrator
# runs as a oneshot service wired to /dev/console.
COPY containerizer-trace.service     /etc/systemd/system/containerizer-trace.service
COPY containerizer-trace-env.service /etc/systemd/system/containerizer-trace-env.service
RUN systemctl enable containerizer-trace.service containerizer-trace-env.service

ENTRYPOINT ["/sbin/init"]
```

- [ ] **Step 2: Build the image locally**

Requires podman + Linux (or WSL2).

Run: `cd sandbox/runner_image && podman build -t containerizer-runner:issue-90-local .`
Expected: build succeeds. The `systemctl enable` step creates symlinks under `/etc/systemd/system/multi-user.target.wants/`.

- [ ] **Step 3: Smoke-test boot**

Run: `podman run --rm --privileged --systemd=always -e CONTAINERIZER_MODE=install -e CONTAINERIZER_INSTALLER=/bin/true containerizer-runner:issue-90-local`
Expected: systemd boots, env-publisher unit writes `/run/containerizer/env`, trace unit starts orchestrator with `--mode install /bin/true`, orchestrator runs (briefly — `/bin/true` exits 0 instantly), `OnSuccess=poweroff.target` halts the container, `podman run` returns within ~5-10 seconds.

If it hangs > 60 seconds: Ctrl-C, `podman ps -a`, `podman logs <id>` to inspect.

- [ ] **Step 4: Commit**

```bash
git add sandbox/runner_image/Containerfile
git -c user.email="github.v5f9w@bitbucket.onl" -c user.signingkey=BE707B220C995478 commit -S -m "$(cat <<'EOF'
feat(runner): boot systemd as PID 1 (#90)

ENTRYPOINT switches from trace-orchestrator.sh to /sbin/init. The
orchestrator now runs as a oneshot systemd service
(containerizer-trace.service) which is wired to /dev/console for
the interactive "press Enter" UX, and triggers
OnSuccess/OnFailure=poweroff.target to shut the container down
when finished.

trace-orchestrator.sh itself is unchanged -- its CLI contract
(--mode + installer-path argv) is preserved; the systemd unit
synthesises the call from CONTAINERIZER_MODE + CONTAINERIZER_INSTALLER
env vars published by the env-publisher unit at boot.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

### Task 1.4: Update unit tests for new install-mode argv shape (RED)

**Files:**
- Modify: `tests/unit/test_trace_runner.py`

- [ ] **Step 1: Replace `test_argv_is_the_podman_run_command`**

In `tests/unit/test_trace_runner.py`, replace the entire `test_argv_is_the_podman_run_command` function (lines 13-41 in the current file) with:

```python
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
    assert "-i" in argv
    assert "-t" not in argv
    assert "--privileged" in argv
    assert "--pid=host" not in argv
    assert "--systemd=always" in argv
    assert "-v" in argv
    assert "/sys/kernel/debug:/sys/kernel/debug" in argv
    assert "/sys/kernel/tracing:/sys/kernel/tracing" in argv
    assert "/sys/kernel/btf:/sys/kernel/btf" in argv
    assert "/lib/modules:/lib/modules:ro" in argv
    assert "/usr/src:/usr/src:ro" in argv
    assert f"{installer.resolve()}:/installer:ro" in argv
    assert f"{output.resolve()}:/work/trace" in argv
    # Mode + installer path now flow via env vars, not positional argv.
    assert "CONTAINERIZER_MODE=install" in argv
    assert "CONTAINERIZER_INSTALLER=/installer" in argv
    # The image tag is the last token; no trailing positional command.
    assert argv[-1] == "localhost/containerizer-runner:sha-abc12345"
```

- [ ] **Step 2: Update `test_install_mode_unchanged`**

This test currently asserts `"--mode" not in argv` and the install-mode-specific mount. Update it to also assert the new env-var shape. Replace the entire function with:

```python
def test_install_mode_unchanged(tmp_path: Path) -> None:
    installer = tmp_path / "installer.sh"
    installer.write_text("echo hi", encoding="utf-8")
    out = tmp_path / "install-trace"

    runner = TraceRunner(
        image_tag="runner:latest",
        installer=installer,
        output_dir=out,
    )
    argv = runner.argv()
    # Default mode is "install"; argv shape stable across both M2 and #90.
    assert "-i" in argv
    assert any(":/installer:ro" in a for a in argv)
    # Mode flows via env var, not argv.
    assert "--mode" not in argv
    assert "CONTAINERIZER_MODE=install" in argv
```

- [ ] **Step 3: Run tests, verify they fail**

Run: `pytest tests/unit/test_trace_runner.py::test_argv_is_the_podman_run_command tests/unit/test_trace_runner.py::test_install_mode_unchanged -v`
Expected: FAIL on both. `--systemd=always` not in argv, `CONTAINERIZER_MODE=install` not in argv, `argv[-1]` is `/installer` not the image tag.

- [ ] **Step 4: Commit**

```bash
git add tests/unit/test_trace_runner.py
git -c user.email="github.v5f9w@bitbucket.onl" -c user.signingkey=BE707B220C995478 commit -S -m "$(cat <<'EOF'
test(trace): install-mode argv asserts --systemd=always + env vars (#90)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

### Task 1.5: Update runner.py install-mode argv (GREEN)

**Files:**
- Modify: `src/containerizer/trace/runner.py:72-118` (`_install_argv`)

- [ ] **Step 1: Replace `_install_argv` return body**

In `src/containerizer/trace/runner.py`, replace the `_install_argv` method's return list (currently lines 94-118) with:

```python
        assert self.installer is not None
        interactive_flags = ["-i", "-t"] if self.tty else ["-i"]
        return [
            "podman",
            "run",
            "--rm",
            *interactive_flags,
            "--privileged",
            "--systemd=always",
            "-v",
            "/sys/kernel/debug:/sys/kernel/debug",
            "-v",
            "/sys/kernel/tracing:/sys/kernel/tracing",
            "-v",
            "/sys/kernel/btf:/sys/kernel/btf",
            "-v",
            "/lib/modules:/lib/modules:ro",
            "-v",
            "/usr/src:/usr/src:ro",
            "-v",
            f"{self.installer.resolve()}:/installer:ro",
            "-v",
            f"{self.output_dir.resolve()}:/work/trace",
            "-e",
            "CONTAINERIZER_MODE=install",
            "-e",
            "CONTAINERIZER_INSTALLER=/installer",
            self.image_tag,
        ]
```

- [ ] **Step 2: Run install-mode tests, verify they pass**

Run: `pytest tests/unit/test_trace_runner.py::test_argv_is_the_podman_run_command tests/unit/test_trace_runner.py::test_install_mode_unchanged tests/unit/test_trace_runner.py::test_install_mode_with_tty_appends_t_flag -v`
Expected: PASS for all three.

- [ ] **Step 3: Commit**

```bash
git add src/containerizer/trace/runner.py
git -c user.email="github.v5f9w@bitbucket.onl" -c user.signingkey=BE707B220C995478 commit -S -m "$(cat <<'EOF'
feat(trace): install-mode argv passes mode + installer via env vars (#90)

Drops the trailing positional /installer arg and replaces it with
-e CONTAINERIZER_MODE=install -e CONTAINERIZER_INSTALLER=/installer.
Adds --systemd=always so Podman sets up the tmpfs/cgroup bind mounts
systemd needs at boot.

The systemd unit inside the runner image reads these env vars and
constructs the trace-orchestrator.sh invocation. The orchestrator's
own CLI contract (--mode + installer-path) is unchanged.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

### Task 1.6: Update unit tests for new verify-mode argv shape (RED)

**Files:**
- Modify: `tests/unit/test_trace_runner.py:105-136` (`test_verify_mode_argv_includes_image_tar_and_env_vars`)

- [ ] **Step 1: Replace the verify-mode test**

Replace the entire `test_verify_mode_argv_includes_image_tar_and_env_vars` function with:

```python
def test_verify_mode_argv_includes_image_tar_and_env_vars(tmp_path: Path) -> None:
    image_tar = tmp_path / "image.tar"
    image_tar.write_bytes(b"x")
    seccomp = tmp_path / "seccomp.json"
    seccomp.write_text("{}", encoding="utf-8")
    out = tmp_path / "verify-trace"

    runner = TraceRunner(
        image_tag="runner:latest",
        installer=None,
        output_dir=out,
        mode="verify",
        verify_image_tar=image_tar,
        verify_image_tag="demo:m6-verify",
        verify_run_flags=("--cap-drop=ALL", "--read-only"),
        verify_soak_seconds=15,
        verify_seccomp_path=seccomp,
    )
    argv = runner.argv()

    # Mode flows via env var, not argv positional.
    assert "--mode" not in argv
    assert "CONTAINERIZER_MODE=verify" in argv
    # Verify mode does NOT set CONTAINERIZER_INSTALLER.
    assert not any(a.startswith("CONTAINERIZER_INSTALLER=") for a in argv)

    assert f"{image_tar.resolve()}:/work/verify/image.tar:ro" in argv
    assert f"{seccomp.resolve()}:/work/verify/seccomp.json:ro" in argv
    assert any(a == "VERIFY_IMAGE_TAG=demo:m6-verify" for a in argv)
    assert any(a == "VERIFY_SOAK_SECONDS=15" for a in argv)
    # VERIFY_RUN_FLAGS is one env var carrying the whole arg list, space-joined.
    assert any(a.startswith("VERIFY_RUN_FLAGS=--cap-drop=ALL --read-only") for a in argv)
    # Verify mode does not run interactively.
    assert "-i" not in argv
    # The original /installer mount is NOT present in verify mode.
    assert not any(":/installer:" in a for a in argv)
    # --pid=host is gone in #90; --systemd=always is present.
    assert "--pid=host" not in argv
    assert "--systemd=always" in argv
    # The image tag is the last token; no trailing positional command.
    assert argv[-1] == "runner:latest"
```

- [ ] **Step 2: Run verify-mode test, verify it fails**

Run: `pytest tests/unit/test_trace_runner.py::test_verify_mode_argv_includes_image_tar_and_env_vars -v`
Expected: FAIL — `CONTAINERIZER_MODE=verify` missing, `--systemd=always` missing, `argv[-1]` is `verify` not `runner:latest`.

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_trace_runner.py
git -c user.email="github.v5f9w@bitbucket.onl" -c user.signingkey=BE707B220C995478 commit -S -m "$(cat <<'EOF'
test(trace): verify-mode argv asserts --systemd=always + env vars (#90)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

### Task 1.7: Update runner.py verify-mode argv (GREEN)

**Files:**
- Modify: `src/containerizer/trace/runner.py:120-161` (`_verify_argv`)

- [ ] **Step 1: Replace `_verify_argv` return body**

In `src/containerizer/trace/runner.py`, replace the `_verify_argv` method's return list (currently lines 129-161) with:

```python
        assert self.verify_image_tar is not None
        assert self.verify_image_tag is not None
        assert self.verify_soak_seconds is not None
        assert self.verify_seccomp_path is not None

        run_flags_env = "VERIFY_RUN_FLAGS=" + " ".join(self.verify_run_flags)

        return [
            "podman",
            "run",
            "--rm",
            "--privileged",
            "--systemd=always",
            "-v",
            "/sys/kernel/debug:/sys/kernel/debug",
            "-v",
            "/sys/kernel/tracing:/sys/kernel/tracing",
            "-v",
            "/sys/kernel/btf:/sys/kernel/btf",
            "-v",
            "/lib/modules:/lib/modules:ro",
            "-v",
            "/usr/src:/usr/src:ro",
            "-v",
            f"{self.verify_image_tar.resolve()}:/work/verify/image.tar:ro",
            "-v",
            f"{self.verify_seccomp_path.resolve()}:/work/verify/seccomp.json:ro",
            "-v",
            f"{self.output_dir.resolve()}:/work/trace",
            "-e",
            f"VERIFY_IMAGE_TAG={self.verify_image_tag}",
            "-e",
            f"VERIFY_SOAK_SECONDS={self.verify_soak_seconds}",
            "-e",
            run_flags_env,
            "-e",
            "CONTAINERIZER_MODE=verify",
            self.image_tag,
        ]
```

- [ ] **Step 2: Run all runner tests, verify they pass**

Run: `pytest tests/unit/test_trace_runner.py -v`
Expected: PASS for the entire file.

- [ ] **Step 3: Run the full unit test suite to confirm no regressions elsewhere**

Run: `pytest tests/unit -v`
Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add src/containerizer/trace/runner.py
git -c user.email="github.v5f9w@bitbucket.onl" -c user.signingkey=BE707B220C995478 commit -S -m "$(cat <<'EOF'
feat(trace): verify-mode argv passes mode via env var (#90)

Drops the trailing positional "/usr/local/bin/trace-orchestrator.sh
--mode verify" args and replaces them with -e CONTAINERIZER_MODE=verify.
Adds --systemd=always (symmetric with install mode).

The systemd unit reads CONTAINERIZER_MODE and dispatches to the
right orchestrator codepath. CONTAINERIZER_INSTALLER is not set
in verify mode; the unit's ${CONTAINERIZER_INSTALLER} expansion
resolves to an empty arg which systemd strips from ExecStart.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Phase 2: Integration test for systemd reachability

### Task 2.1: Create synthetic loginctl-calling installer fixture

**Files:**
- Create: `tests/fixtures/trace/loginctl-installer.sh`

- [ ] **Step 1: Write the fixture script**

Create `tests/fixtures/trace/loginctl-installer.sh` with this exact content:

```bash
#!/usr/bin/env bash
# Synthetic installer for issue #90 integration test.
#
# Exercises the systemd-PID-1 surface without needing a real installer:
#   * loginctl  -- requires systemd-logind to be running, which requires
#                  systemd-as-PID-1 + a working system DBus.
#   * systemctl status -- proves the system bus is reachable.
#
# Exits 0 on success so the orchestrator marks the trace COMPLETE.
set -euo pipefail

echo "[loginctl-installer] checking systemd-logind reachability..."
loginctl show-user 0 || loginctl list-users
echo "[loginctl-installer] systemd-logind OK"

echo "[loginctl-installer] checking system bus..."
systemctl status systemd-logind.service --no-pager
echo "[loginctl-installer] system bus OK"

# Touch a path the open.bt collector will pick up, so the trace has at
# least one observable event the analyzer can verify post-mortem.
touch /tmp/loginctl-installer.done
echo "[loginctl-installer] complete"
```

- [ ] **Step 2: Mark executable + LF line endings**

Run from Bash: `chmod +x tests/fixtures/trace/loginctl-installer.sh && file tests/fixtures/trace/loginctl-installer.sh`
Expected: `... executable, ASCII text` with no CRLF.

- [ ] **Step 3: Commit**

```bash
git add tests/fixtures/trace/loginctl-installer.sh
git -c user.email="github.v5f9w@bitbucket.onl" -c user.signingkey=BE707B220C995478 commit -S -m "$(cat <<'EOF'
test(trace): loginctl-calling synthetic installer fixture (#90)

Exercises systemd-logind + system DBus reachability without needing
a real installer. Drives the Phase 2 integration test that proves
the systemd-PID-1 runner image actually boots systemd successfully.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

### Task 2.2: Write the integration test

**Files:**
- Create: `tests/integration/trace/test_systemd_pid1.py`

- [ ] **Step 1: Write the test**

Create `tests/integration/trace/test_systemd_pid1.py` with this exact content:

```python
"""End-to-end test that the runner image boots systemd as PID 1 (#90).

Marked @pytest.mark.integration; skipped by default. Run via:
    pytest tests/integration/trace/test_systemd_pid1.py -v -m integration
Requires podman + Linux kernel with eBPF/BTF.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.integration
def test_loginctl_installer_succeeds_under_systemd_pid1(tmp_path: Path) -> None:
    """If systemd is NOT PID 1, loginctl fails with 'System has not been
    booted with systemd as init system'. This test fails the same way the
    UniFi installer did pre-#90."""
    fixture = REPO_ROOT / "tests/fixtures/trace/loginctl-installer.sh"
    assert fixture.exists(), f"missing fixture: {fixture}"

    out = tmp_path / "trace"
    out.mkdir()

    result = subprocess.run(
        ["containerizer", "trace", str(fixture), "-o", str(out)],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=180,
    )

    # Container must exit cleanly (systemd OnSuccess=poweroff.target).
    assert result.returncode == 0, (
        f"containerizer trace exited {result.returncode}\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )

    # Orchestrator must finalise COMPLETE (installer exited 0).
    assert (out / "COMPLETE").exists(), (
        f"no COMPLETE marker; stderr was:\n{result.stderr}"
    )

    # Installer's own success line must appear in install.log (or stdout
    # if the interactive branch fired -- this test runs non-interactive
    # via stdin=DEVNULL, so install.log is the relevant artifact).
    install_log = out / "install.log"
    if install_log.exists():
        log_text = install_log.read_text(encoding="utf-8", errors="replace")
        assert "systemd-logind OK" in log_text, (
            f"loginctl reachability check did not pass; install.log:\n{log_text}"
        )
        assert "system bus OK" in log_text


@pytest.mark.integration
def test_runner_image_entrypoint_is_sbin_init(tmp_path: Path) -> None:
    """Belt-and-braces: inspect the built image and confirm ENTRYPOINT
    is /sbin/init. Cheap, catches Containerfile regressions."""
    # The image tag the containerizer trace path builds; mirror the same
    # naming convention image.py uses (sha-prefix based). We just need
    # *some* image with the same Containerfile; the trace command will
    # build it on first run, so trigger that first.
    result = subprocess.run(
        ["containerizer", "trace", "--help"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0

    images = subprocess.run(
        ["podman", "images", "--format", "{{.Repository}}:{{.Tag}}"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    runner_images = [
        line for line in images.stdout.splitlines()
        if "containerizer-runner" in line
    ]
    if not runner_images:
        pytest.skip("no runner image built yet; this test runs after another integration test")

    inspect = subprocess.run(
        ["podman", "inspect", "--format", "{{json .Config.Entrypoint}}", runner_images[0]],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert inspect.returncode == 0
    assert "/sbin/init" in inspect.stdout, (
        f"image {runner_images[0]} entrypoint is {inspect.stdout!r}, expected /sbin/init"
    )
```

- [ ] **Step 2: Run the test**

Requires podman + Linux. First run will build the new runner image (slow — ~3-5 minutes).

Run: `pytest tests/integration/trace/test_systemd_pid1.py -v -m integration`
Expected: PASS. Both tests succeed.

If `test_loginctl_installer_succeeds_under_systemd_pid1` fails with `loginctl: System has not been booted with systemd as init system`: the Containerfile change in Task 1.3 did not actually swap ENTRYPOINT — re-check, re-build, re-run.

If it fails with `Container failed to boot`: check `podman logs` of the most recent container; likely a unit-file syntax error in Task 1.1 or 1.2.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/trace/test_systemd_pid1.py
git -c user.email="github.v5f9w@bitbucket.onl" -c user.signingkey=BE707B220C995478 commit -S -m "$(cat <<'EOF'
test(trace): integration test for systemd-PID-1 reachability (#90)

Two integration tests:

1. loginctl-installer end-to-end: proves systemd-logind + system DBus
   are reachable inside the runner -- the exact thing #90 broke.
   Marked @pytest.mark.integration so it doesn't run in unit-test CI.

2. ENTRYPOINT inspection: belt-and-braces that the built image's
   Config.Entrypoint is /sbin/init.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

### Task 2.3: Verify M6 build/verify-mode regression

**Files:** none (re-runs existing test)

- [ ] **Step 1: Run M6 build integration smoke**

Run: `pytest tests/integration/build/test_build_smoke.py -v -m integration`
Expected: PASS. The end-to-end build pipeline (which includes verify-mode retrace under nested podman inside the now-systemd-managed parent) still produces a valid `verify.json`.

- [ ] **Step 2: If nested-podman fails with cgroup delegation error**

Symptom: `cgroup: cannot enter cgroup ...` or `OCI runtime error: cgroup ...` inside the verify-mode container logs.

Fix: add `--cgroupns=private` to the verify-mode argv in `src/containerizer/trace/runner.py` `_verify_argv`, just after `--systemd=always`. Add a corresponding assertion in `test_verify_mode_argv_includes_image_tar_and_env_vars` (`assert "--cgroupns=private" in argv`).

- [ ] **Step 3: If Step 2 was triggered, commit the fix**

```bash
git add src/containerizer/trace/runner.py tests/unit/test_trace_runner.py
git -c user.email="github.v5f9w@bitbucket.onl" -c user.signingkey=BE707B220C995478 commit -S -m "$(cat <<'EOF'
fix(trace): verify mode needs --cgroupns=private under systemd parent (#90)

Nested podman inside the systemd-managed runner hits cgroup v2
delegation errors when sharing the host cgroup namespace.
--cgroupns=private gives the nested container its own cgroup root.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Phase 3: Manual scenario 11 acceptance gate

### Task 3.1: Run MANUAL.md scenario 11

**Files:** none

- [ ] **Step 1: Read MANUAL.md scenario 11**

Run: `grep -n -A 50 "Scenario 11" MANUAL.md`
Follow the documented steps.

- [ ] **Step 2: Execute scenario 11 on Windows/WSL2 with the UniFi installer**

Per MANUAL.md, this requires the UniFi OS Server installer binary (`24e0-linux-x64-5.1.15-...`) and rootful podman on the host.

Expected: the installer that previously failed with `loginctl enable-linger uosserver` now completes. Trace markers (COMPLETE), `install.log`, `trace.json`, and `policy.json` all populate.

- [ ] **Step 3: Capture artifacts for the PR description**

Save and stage (do NOT commit binaries; just paste excerpts into the PR description):

- The last ~30 lines of `install.log` showing the successful `loginctl enable-linger` line.
- The `trace.json` summary (`paths`, `ports`, `caps` counts).
- A screenshot of the installer's final success screen.

These go into the PR body under a `## Scenario 11 acceptance` section, not into the repo.

- [ ] **Step 4: Decision point**

- **If scenario 11 passes:** proceed to Phase 4.
- **If scenario 11 fails with a different systemd-side error:** diagnose, possibly add another follow-up commit (e.g., enable an additional service in the Containerfile). Re-run.
- **If scenario 11 fails with the `installer &` backgrounding bug** (Y/N prompt instant-aborts despite TTY being attached): file a separate follow-up issue, document in PR body that #90 is mechanically fixed but a different (latent) bug blocks scenario 11. Maintainer decides whether to fix in-PR or merge #90 alone.

---

## Phase 4: Documentation + close issue

### Task 4.1: Update MANUAL.md scenario 11 status

**Files:**
- Modify: `MANUAL.md`

- [ ] **Step 1: Find scenario 11 status note**

Run: `grep -n "Scenario 11" MANUAL.md`
Find the status header for scenario 11 (likely a line like `**Status:** Blocked on #90 (systemd PID 1)` or similar).

- [ ] **Step 2: Update it**

Edit the status line to:

```
**Status:** Passes as of 2026-MM-DD (post-#90).
```

(Replace `2026-MM-DD` with the actual scenario-11 run date.)

- [ ] **Step 3: Commit**

```bash
git add MANUAL.md
git -c user.email="github.v5f9w@bitbucket.onl" -c user.signingkey=BE707B220C995478 commit -S -m "$(cat <<'EOF'
docs(manual): scenario 11 passes post-#90 (systemd PID 1)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

### Task 4.2: Open the PR with `Closes #90`

**Files:** none

- [ ] **Step 1: Push the feature branch**

Run: `git push -u origin feat/issue-90-systemd-pid1`

(Branch was created off `origin/main` in the Pre-flight step before Phase 0.)

- [ ] **Step 2: Open the PR**

Run:

```bash
gh pr create --title "feat(runner): boot systemd as PID 1 for trace runner" --body "$(cat <<'EOF'
## Summary

- Runner image boots stock systemd as PID 1 (`ENTRYPOINT=["/sbin/init"]`).
- Existing `trace-orchestrator.sh` runs as a oneshot systemd service wired to `/dev/console` (preserves "press Enter" UX).
- Host wrapper drops `--pid=host` (incompatible with systemd-PID-1) and adds `--systemd=always`.
- Mode + installer-path move from positional argv to `CONTAINERIZER_MODE` / `CONTAINERIZER_INSTALLER` env vars.

Spec: `docs/superpowers/specs/2026-06-09-containerizer-issue-90-systemd-pid1.md`
Plan: `docs/superpowers/plans/2026-06-09-containerizer-issue-90-systemd-pid1.md`

Closes #90.

## Scenario 11 acceptance

[Paste install.log excerpt, trace.json summary, screenshot per Task 3.1 Step 3]

## Test plan

- [x] Unit tests: `pytest tests/unit/test_trace_runner.py`
- [x] M2 integration regression (Phase 0): `pytest tests/integration/trace/test_trace_pipeline.py -m integration`
- [x] systemd-PID-1 integration: `pytest tests/integration/trace/test_systemd_pid1.py -m integration`
- [x] M6 verify-mode regression: `pytest tests/integration/build/test_build_smoke.py -m integration`
- [x] Manual scenario 11 (UniFi end-to-end on Windows/WSL2)

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 3: Verify PR shows correct linked issue**

Run: `gh pr view --json closingIssuesReferences`
Expected: includes #90 in the closing references.

---

## Self-review checklist (executed at plan-writing time, not at execution)

**Spec coverage:**
- §2 In-scope: Containerfile (Task 1.3 ✓), runner.py (Tasks 0.2 + 1.5 + 1.7 ✓), test_runner.py (Tasks 0.1 + 1.4 + 1.6 ✓), integration test (Task 2.2 ✓), MANUAL.md (Task 4.1 ✓).
- §3 Architecture: service unit (Task 1.1 ✓), env-publisher unit (Task 1.2 ✓), Containerfile (Task 1.3 ✓), runner.py changes (Tasks 1.5 + 1.7 ✓).
- §4 Lifecycle: validated by Task 1.3 Step 3 smoke + Task 2.2 integration.
- §5 Failure modes: Ctrl-C path noted as "validated in Phase 2" — Task 2.2 doesn't explicitly test Ctrl-C, but the integration test runs non-interactive (stdin=DEVNULL), so the stdin-EOF path is covered. Ctrl-C signal handling is a fall-through risk noted in spec §7, not blocking #90 mechanically.
- §6 Testing: unit (Tasks 0.1 + 1.4 + 1.6), integration (Tasks 0.3 + 2.2 + 2.3), manual (Task 3.1) all covered.
- §7 Known risks: #1 cgroup delegation has explicit Task 2.3 mitigation. #2 boot time deferred (perf-followup, not blocking). #3 TTY signals deferred. #4 `installer &` orchestrator bug has explicit Task 3.1 Step 4 decision branch.
- §9 Phasing: matches plan phases 0-4.

**Placeholder scan:** No TBDs, no "add appropriate error handling", every code step contains the actual code, every command step contains the exact command. Pass.

**Type consistency:** `CONTAINERIZER_MODE` and `CONTAINERIZER_INSTALLER` used consistently across spec, runner.py code, systemd unit, integration test, env-publisher unit. `--systemd=always` consistent. Pass.

---

## End-of-plan notes

This plan is dense by design — the runner image change has a lot of moving parts (Containerfile + 2 systemd units + host wrapper + tests + manual gate) and the "drop --pid=host" preflight has to be a hard gate. The subagent-driven approach is well-suited because each task has tight RED→GREEN→COMMIT loops that are easy to verify in isolation.
