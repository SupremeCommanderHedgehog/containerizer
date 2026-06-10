# Issue #90 — Boot systemd as PID 1 in the trace runner

**Date:** 2026-06-09
**Status:** Approved (brainstorming)
**Parent spec:** [`2026-06-06-containerizer-design.md`](./2026-06-06-containerizer-design.md)
**Prior milestone specs:** [`2026-06-06-containerizer-m2-sandbox-trace.md`](./2026-06-06-containerizer-m2-sandbox-trace.md), [`2026-06-08-containerizer-m6-build.md`](./2026-06-08-containerizer-m6-build.md)
**Issue:** [#90](https://github.com/SupremeCommanderHedgehog/containerizer/issues/90)

## 1. Overview

The trace runner image ships systemd + dbus (M2 Containerfile, line 16) but does not boot them. PID 1 in the trace container is `trace-orchestrator.sh`. Any installer that calls `loginctl`, `systemctl --user`, `machinectl`, or the system / session DBus bus fails with:

```
ERROR Command "loginctl enable-linger uosserver" failed: System has not been booted with systemd as init system (PID 1). Can't operate.
Failed to connect to system scope bus via local transport: Host is down
```

Reproduced with the UniFi OS Server installer during MANUAL.md scenario 11.

This spec brings the runner image into alignment with the Fedora "systemd-in-container" pattern the M2 Containerfile comment already promised: stock `/sbin/init` runs as PID 1, the existing `trace-orchestrator.sh` runs as a systemd-managed oneshot service, and the container shuts down cleanly when the orchestrator finishes.

## 2. Scope

### In this change

- `sandbox/runner_image/Containerfile`: `ENTRYPOINT` switches from `["/opt/containerizer/trace-orchestrator.sh"]` to `["/sbin/init"]`. Two new systemd unit files (`containerizer-trace-env.service`, `containerizer-trace.service`) are added and enabled.
- `src/containerizer/trace/runner.py`: drop `--pid=host`, add `--systemd=always`, move install mode + installer-path from positional argv to environment variables (`CONTAINERIZER_MODE`, `CONTAINERIZER_INSTALLER`).
- `tests/unit/trace/test_runner.py`: assertions updated to match the new argv shape.
- New integration test exercising `loginctl` under the systemd-PID-1 runner.
- MANUAL.md scenario 11: status note refreshed once the manual gate passes.

### Carried unchanged

- `sandbox/runner_image/trace-orchestrator.sh`: contract preserved. Mode + installer-path still flow as `--mode <m> <path>` argv; the new systemd unit synthesises them from env vars.
- `sandbox/runner_image/verify-orchestrator.sh`: untouched. Nested-podman path is unchanged.
- `src/containerizer/build/pipeline.py` and the M6 build orchestrator. Trace runner argv is constructed by `runner.py`; pipeline doesn't see it.
- Host-side rootful-podman requirement. `--privileged` and `--systemd=always` together still need rootful (rootless support remains explicitly out of scope, parent design §12).
- Per-phase subcommands. `containerizer trace` / `analyze` / `generate` / `verify` / `build` CLI surface is unchanged.

### Out of scope (deferred)

- **Rootless podman support.** Independent of #90.
- **Orchestrator rewrite in Python.** The shell script is fine for what it does; rewriting it expands the change set without addressing #90's root cause.
- **`installer &` backgrounding bug** documented in memory (orchestrator backgrounds the installer with `&` which can break Y/N prompts for some installers). May surface during scenario 11 acceptance; if it does, file a separate follow-up issue rather than expanding this PR.
- **DBus introspection for richer policy generation.** Separate research thread.
- **CI-runnable scenario 11.** Manual gate per parent design §9's CI budget. CI gets the smaller systemd-reachability test described in §5.

## 3. Architecture

### 3.1 Runner image (`sandbox/runner_image/Containerfile`)

```dockerfile
FROM fedora:41

RUN dnf install -y --setopt=install_weak_deps=False \
      systemd dbus \
      bcc-tools bpftrace strace audit-libs audit \
      kernel-headers glibc-headers \
      nmap-ncat \
      jq python3 \
      podman slirp4netns fuse-overlayfs crun conmon shadow-utils \
    && dnf clean all && rm -rf /var/cache/dnf

# Pre-create storage roots for nested podman (unchanged from M6).
RUN mkdir -p /var/lib/containers \
             /var/lib/shared/overlay-images \
             /var/lib/shared/overlay-layers \
             /var/lib/shared/vfs-images \
             /var/lib/shared/vfs-layers && \
    chmod 755 /var/lib/containers

# Project-specific tooling (unchanged paths).
RUN mkdir -p /opt/containerizer/collectors /work/trace
COPY trace-orchestrator.sh   /opt/containerizer/trace-orchestrator.sh
COPY verify-orchestrator.sh  /usr/local/bin/verify-orchestrator.sh
COPY collectors/             /opt/containerizer/collectors/
RUN chmod +x /opt/containerizer/trace-orchestrator.sh /usr/local/bin/verify-orchestrator.sh

# NEW: systemd units for #90.
COPY containerizer-trace.service     /etc/systemd/system/containerizer-trace.service
COPY containerizer-trace-env.service /etc/systemd/system/containerizer-trace-env.service
RUN systemctl enable containerizer-trace.service containerizer-trace-env.service

ENTRYPOINT ["/sbin/init"]
```

### 3.2 Systemd unit: `containerizer-trace.service`

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

Notes:

- `TimeoutStartSec=0` — the orchestrator blocks on `read -r _ || true` while the user exercises the software. systemd's default 90-second start timeout would kill the unit; we need infinite.
- `TTYReset=no TTYVHangup=no` — keeps the user's terminal scrollback intact between systemd grabbing /dev/console and the unit's `read` returning.
- `Conflicts=getty@tty1.service console-getty.service` — fedora's default presets enable a console-getty on `/dev/console`. Without `Conflicts=`, both fight for the pty and the orchestrator's output gets interleaved with login prompts.
- `OnSuccess=poweroff.target` *and* `OnFailure=poweroff.target` — container exits cleanly whether the orchestrator returns 0 (always, per existing contract) or systemd considers the unit failed (e.g., signal exit). Equivalent to `ExecStopPost=systemctl poweroff` but keeps the orchestrator script systemd-agnostic.

### 3.3 Systemd unit: `containerizer-trace-env.service`

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

Why a separate unit: systemd's `EnvironmentFile=` reads a file, not the kernel env. Podman-passed env vars land in PID 1's environment but don't propagate to child units in a readable form. The env-publisher unit captures them once at boot and writes a file the trace unit can consume.

Rejected alternatives:

- `systemctl set-environment` from an ExecStartPre — works but mutates the global manager environment imperatively; harder to inspect after the fact.
- systemd generator unit — generators run before transaction planning; debugging them requires journalctl gymnastics that the file-based approach avoids.

### 3.4 Host wrapper: `src/containerizer/trace/runner.py`

Install-mode argv diff (conceptual):

```diff
 podman run --rm -i [-t]
 --privileged
-  --pid=host
+  --systemd=always
 -v /sys/kernel/debug:/sys/kernel/debug
 -v /sys/kernel/tracing:/sys/kernel/tracing
 -v /sys/kernel/btf:/sys/kernel/btf
 -v /lib/modules:/lib/modules:ro
 -v /usr/src:/usr/src:ro
 -v <installer>:/installer:ro
 -v <output_dir>:/work/trace
+  -e CONTAINERIZER_MODE=install
+  -e CONTAINERIZER_INSTALLER=/installer
 <runner-image-tag>
-  /installer
```

Verify-mode argv (symmetric, no installer env var; existing `VERIFY_*` env vars preserved):

```diff
 podman run --rm --privileged
-  --pid=host
+  --systemd=always
 -v ... (unchanged mounts)
 -e VERIFY_IMAGE_TAG=...
 -e VERIFY_SOAK_SECONDS=...
 -e VERIFY_RUN_FLAGS=...
+  -e CONTAINERIZER_MODE=verify
 <runner-image-tag>
-  /usr/local/bin/trace-orchestrator.sh --mode verify
```

The trailing positional command disappears entirely — the entrypoint is now `/sbin/init`, and the systemd unit invokes `trace-orchestrator.sh` with the right argv synthesised from env vars.

Why `--systemd=always` (vs Podman's default `--systemd=true`): the default auto-detects systemd by inspecting argv[0]. Our entrypoint is `["/sbin/init"]` which should match, but the matcher has had edge cases (symlinks, image-inspect cache). `--systemd=always` removes ambiguity for one extra flag.

What `--systemd=always` does: mounts tmpfs at `/run`, `/run/lock`, `/tmp`, `/var/lib/journal`, and sets up the cgroup slice/scope plumbing systemd needs. No extra capabilities beyond `--privileged`.

## 4. Lifecycle

End-to-end install flow:

1. Host: `podman run --rm -it --privileged --systemd=always -e CONTAINERIZER_MODE=install -e CONTAINERIZER_INSTALLER=/installer -v ... runner-image-tag`.
2. Podman sets up tmpfs/cgroup, allocates a pty as `/dev/console`, execs `/sbin/init`.
3. systemd boots, reaches `multi-user.target`.
4. `containerizer-trace-env.service` runs `env | grep CONTAINERIZER_ > /run/containerizer/env`.
5. `containerizer-trace.service` runs `trace-orchestrator.sh --mode install /installer` with `/dev/console` as its stdio.
6. Orchestrator's existing behavior: launches collectors, runs installer (interactive — installer's `isatty()` checks succeed), waits for user Enter, finalises markers.
7. Orchestrator exits.
8. systemd hits `OnSuccess=poweroff.target` (or `OnFailure=` if signal exit) → orderly shutdown → container exits.

Verify-mode flow is identical except step 4-5 set `CONTAINERIZER_MODE=verify` and the orchestrator dispatches to `verify-orchestrator.sh`.

## 5. Failure modes

| Failure | Behavior |
|---|---|
| Installer exits non-zero | Orchestrator writes `install.status=failed`, finalises PARTIAL, exits 0. Unit reaches `OnSuccess=poweroff.target`. Container exits 0. Host sees PARTIAL marker. (Unchanged from today.) |
| User presses Ctrl-C in interactive run | systemd traps SIGINT at PID 1, forwards via TTY to the unit. Orchestrator's existing INT trap fires, writes PARTIAL, exits 0. Container shuts down. *Validated in Phase 2.* |
| `containerizer-trace-env.service` fails (e.g., /run not writable) | `OnFailure=poweroff.target` triggers immediate shutdown. Trace unit never runs. Trace dir has no markers. Host wrapper sees missing markers + unusual exit timing. |
| `containerizer-trace.service` ExecStart fails to launch (e.g., orchestrator script missing) | Same — `OnFailure=poweroff.target` shuts down. Host sees no markers. |
| Container killed externally (`podman kill`) | Podman sends SIGTERM. systemd shuts down. Orchestrator gets SIGTERM via the unit's stop signal; existing TERM trap writes PARTIAL. *Validated in Phase 2.* |
| systemd fails to boot (missing cgroup mount, bad podman version) | Container exits non-zero immediately. Host wrapper surfaces a new error: "trace runner failed to boot; check `podman --version` >= 4.x and cgroup v2." |

## 6. Testing strategy

### 6.1 Unit tests (Python)

`tests/unit/trace/test_runner.py`:

- Install argv contains `--systemd=always`, omits `--pid=host`.
- Install argv contains `-e CONTAINERIZER_MODE=install` and `-e CONTAINERIZER_INSTALLER=/installer`.
- Install argv does not end with a trailing positional `/installer`.
- Verify argv contains `-e CONTAINERIZER_MODE=verify` and omits `CONTAINERIZER_INSTALLER`.
- Existing TTY-flag invariants from PR #91 preserved (`-t` present iff `tty=True`).

### 6.2 Integration tests

**Phase 0 gate** (before any systemd work, lands as its own PR if green):

A single commit removes `--pid=host` from install + verify argv builders. `tests/integration/trace/test_trace_pipeline.py` runs against the unmodified Containerfile. Acceptance: `trace.json` still populates with non-empty `paths`, `ports`, `caps`, `syscalls` for the synthetic installer. If anything regresses, this spec re-opens before any systemd work starts.

**Phase 2** (new integration test once systemd-PID-1 lands):

A tiny synthetic installer script that calls `loginctl show-user 0` (or `systemctl --user is-system-running` for a non-root variant). Runs under the new runner image. Acceptance: installer exits 0, COMPLETE marker written, `trace.json` populates.

**Verify-mode regression** (existing M5/M6 retrace integration):

Re-run the existing M6 build-pipeline integration tests against the new runner image. Acceptance: `verify.json` produces the same diff shape. If nested-podman fails under the systemd-managed parent (cgroup delegation issue), the fix is `--cgroupns=private` on the host-side argv — listed as known risk §7.

### 6.3 Manual acceptance (gates the PR)

MANUAL.md scenario 11 — UniFi OS Server installer end-to-end on Windows/WSL2. The original blocker. PR description captures the install.log, trace.json snippet, and a screenshot of the install completing cleanly.

## 7. Known risks

1. **Nested-podman cgroup delegation.** Nested podman inside a systemd-managed parent container can hit cgroup v2 delegation errors. Mitigation: if the verify-mode integration test (§6.2) regresses, add `--cgroupns=private` to host-side runner argv. Documented; not blocking.
2. **Boot time regression.** Stock fedora:41 systemd boots ~150 default units; cold-start latency goes from <1s (orchestrator launches directly) to ~2-4s. Mitigation if it bites: `systemctl mask systemd-networkd systemd-timesyncd systemd-resolved nm-online` in the Containerfile. Listed as perf-followup; not blocking the main change.
3. **TTY signal forwarding.** systemd's stdio handling for `StandardInput=tty TTYPath=/dev/console` is documented, but the Ctrl-C → orchestrator INT trap path needs Phase 2 validation. If signals get swallowed, fallback is `KillMode=process KillSignal=SIGINT` on the unit. Documented; will be visible in Phase 2 testing before manual gate.
4. **Latent `installer &` orchestrator bug.** Documented in memory: orchestrator backgrounds the installer in the interactive branch, which can break Y/N prompts for some installers (UniFi-style). May or may not surface during scenario 11. If it does, file a separate follow-up issue and decide whether to fix in-PR or defer. Not part of #90's scope.

## 8. Open questions

None blocking. The five clarifying questions answered during brainstorming locked the architecture:

1. Long-term systemd-as-PID-1 (vs narrow loginctl stub vs defer). **Locked: long-term.**
2. Both install and verify modes use unified runner. **Locked: unified.**
3. Preserve "press Enter to finalise" UX via /dev/console wiring. **Locked: preserve.**
4. Acceptance test = manual UniFi scenario 11. **Locked: manual gate.**
5. Drop `--pid=host` with Phase 0 validation gate. **Locked: validate-first.**

## 9. Implementation phasing

The plan (separate doc, generated by writing-plans) will expand these into TDD tasks:

- **Phase 0** — Validate `--pid=host` removal. Single commit. Goes out as its own PR if green; this spec re-opens if collector data goes empty.
- **Phase 1** — Runner image switches to systemd-as-PID-1. Containerfile + two `.service` units + host runner.py changes + unit tests.
- **Phase 2** — Integration test: synthetic loginctl installer under the new runner image. Validates Ctrl-C signal path while we're there.
- **Phase 3** — Manual scenario 11 (UniFi end-to-end). PR doesn't merge until this passes.
- **Phase 4** — Close #90, refresh MANUAL.md scenario 11 status.

## 10. Spec / PR shape

- This spec ships as a docs-only PR first (per the M3-M6 pattern).
- Plan ships in the same PR or as a follow-up commit.
- Implementation PR follows, one signed commit per phase, gated on manual scenario 11.
- All commits signed with key `BE707B220C995478`, author `github.v5f9w@bitbucket.onl`.
