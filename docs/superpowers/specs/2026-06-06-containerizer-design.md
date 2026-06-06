# Containerizer — Design Spec

**Date:** 2026-06-06
**Status:** Approved (brainstorming)
**Repo:** `SupremeCommanderHedgehog/containerizer` (private, Apache-2.0)

## 1. Overview

`containerizer` is a Python CLI tool that ingests a Linux software installer and emits a hardened Podman container for it. The tool runs the installer inside an instrumented sandbox, observes which files, network endpoints, capabilities, and syscalls the software actually uses, and generates a deny-by-default container image plus a systemd Quadlet unit whose exceptions are exactly the ones the trace observed and nothing more.

The driving example is the UniFi OS Server installer (~875 MB Linux ELF, expects systemd, MongoDB, JVM, etc.), but the design is generic: anything that can be installed and exercised inside a privileged Linux container can be containerized this way.

The user runs the tool from PowerShell on Windows. The trace sandbox runs inside the existing Podman machine (WSL2). The output artifacts deploy via `podman build` + `systemctl --user` (Quadlet).

## 2. Goals & non-goals

### Goals

- **Trace-and-learn discovery.** No declarative manifest required for the common case. The tool watches the install and a user-driven smoke test and derives policy automatically.
- **Deny-by-default hardening.** Strict capability drop, deny-by-default seccomp, no-new-privileges, read-only rootfs where viable, tmpfs for ephemeral writes, named volumes only for paths the trace observed being written persistently.
- **Honest relaxations.** Every exception away from the strict default is reported in the generated README, so the user reviews what was loosened and why.
- **Reproducible artifacts.** Given the same installer and an equivalent smoke test, the generated `Containerfile`, `<name>.container`, and `seccomp.json` should be deterministic enough to commit and diff.
- **Modern Podman idiom.** Output is a Quadlet `.container` unit, not a shell script or compose file.

### Non-goals

- Containerizing software that does not run on Linux.
- GUI tooling. The CLI is the surface area.
- Running the trace anywhere other than a Linux Podman host. We support exactly one sandbox topology: a privileged container on the user's existing Podman machine.
- Replacing or wrapping `podman build` / `podman run`. The tool emits artifacts; the user deploys them.
- Automatic egress filtering. The trace reports outbound destinations the software contacted at runtime, but the generated Quadlet does not enforce an egress allowlist (network policy belongs to the deployer's network layer, not this tool).
- Auto-discovering smoke tests. The user always drives the smoke test interactively.

## 3. Target user and UX

The user is a developer comfortable with Podman, shell, and git, who wants their daemonized software (UniFi controller, home-lab apps, internal services) to run in a tight rootless container without hand-curating mounts, ports, caps, and seccomp.

Primary flow:

```pwsh
PS> containerizer doctor                  # preflight: podman, machine, BPF, disk
PS> containerizer build .\unifi-installer.bin --name unifi-os
[probe]    elf x86_64, glibc 2.35+, base image suggestion: ubuntu:24.04
[sandbox]  starting trace-runner container...
[trace]    running installer (this can take a while)...
[trace]    installer complete. starting daemon.
[trace]    software is running. exercise it now (e.g., visit https://localhost:8443).
           press Enter in this terminal when done.
[trace]    finalising trace... 14 file paths classified, 6 ports observed, 38 syscalls used
[generate] writing Containerfile, unifi-os.container, seccomp.json, README.md
[done]     artifacts: ./out/unifi-os/
```

Per-phase subcommands (`probe`, `trace`, `analyze`, `generate`, `verify`) exist for iteration and debugging but the default UX is the single `build` command.

## 4. Architecture

```
                    Windows host
   +-------------------------------------------------+
   |  containerizer (Python 3.11+, runs in PowerShell)|
   |  +-- podman.exe subprocess  -------+            |
   +------------------------------------|------------+
                                        v
                       Podman machine (WSL2 Linux)
   +-----------------------------------------------------+
   |  Trace-runner container (privileged, systemd=always)|
   |  +------------------------------------------------+ |
   |  | trace-orchestrator.sh                          | |
   |  |   starts collectors -> runs installer -> marks | |
   |  |   phase -> starts daemon -> waits for user     | |
   |  |   "done" -> stops collectors -> exits          | |
   |  +------------------------------------------------+ |
   |  Collectors: opensnoop, execsnoop, tcpconnect,      |
   |  tcpaccept, capable (bcc/bpftrace) + bpftrace       |
   |  syscall and bind tracers + strace fallback.        |
   |  Output: JSONL on a bind-mounted work directory.    |
   +-----------------------------------------------------+
                                        |
                                        v
       Analyzer (host)  ->  Generator  ->  ./out/<name>/
                                          Containerfile
                                          <name>.container
                                          seccomp.json
                                          README.md
```

Two structural splits anchor the design:

- **Install phase vs runtime phase.** The orchestrator writes a marker file when the installer exits successfully; the analyzer uses the marker's timestamp to partition every collector's event stream. Install-phase observations inform build-time decisions (base distro packages, file layout). Runtime-phase observations alone inform runtime policy (mounts, ports, caps, seccomp). Apt repo contacts during install do not become runtime egress allowances.
- **Build-time policy vs runtime policy.** The Containerfile bakes in the install result. The Quadlet + seccomp profile govern execution. The two artifacts are decoupled: the generator can be re-run on a saved trace to refine the Quadlet without rebuilding the image.

## 5. Components

Each component lives in its own subpackage under `src/containerizer/`. Files are kept under ~300 LOC where practical; modules expose typed interfaces.

### 5.1 CLI (`cli.py`)

Click-based. Entry point `containerizer`. Subcommands:

- `build <installer> --name <n> [--base-image …] [--out ./out] [--keep-intermediates] [--debug]` — full pipeline.
- `doctor` — preflight checks: `podman --version`, `podman machine list`, BPF support inside the machine, ≥10 GB free disk.
- `probe <installer> -o probe.json` — phase 1 only.
- `trace <installer> --probe probe.json -o trace/` — phases 2+3 only.
- `analyze trace/ -o trace.json` — phase 4 only.
- `generate trace.json -o ./out/<name>/` — phase 5 only.
- `verify ./out/<name>/` — rebuild and run the generated image briefly under strict policy, diff observed behavior against the captured trace, surface anything not previously seen.

### 5.2 Installer probe (`probe/`)

Static analysis of the input file. No execution. Outputs `probe.json`:

```json
{
  "schema_version": 1,
  "kind": "elf",
  "arch": "x86_64",
  "glibc_min": "2.35",
  "needed_libs": ["libc.so.6", "libpthread.so.0", "..."],
  "interpreter": "/lib64/ld-linux-x86-64.so.2",
  "base_image_suggestion": "ubuntu:24.04",
  "base_image_reasons": ["glibc 2.35 -> ubuntu 22.04+", "x86_64"]
}
```

Detects: ELF (via magic + `readelf`-equivalent in `pyelftools`), `.deb` (ar archive + `control` parsing), `.rpm` (lead + header), `.AppImage` (squashfs marker), shell installer (`#!` + heuristic), tarball.

Base-image selection rules (overridable with `--base-image`):

- ELF requiring glibc ≥ 2.35 → `ubuntu:24.04`
- ELF requiring glibc 2.31–2.34 → `ubuntu:22.04`
- `.deb` → matching Ubuntu/Debian
- `.rpm` → matching Fedora/RHEL
- AppImage / shell installer → `ubuntu:24.04` (most compatible)

### 5.3 Sandbox runner (`sandbox/`)

Owns the trace-runner image: a single Containerfile checked into the repo, built once and cached locally. Contents:

- Base `fedora:40` (best systemd-in-container support)
- `systemd`, `dbus`, `bcc-tools`, `bpftrace`, `strace`, `audit`, `jq`, `python3`, the orchestrator script

Launch flags:

```
podman run --rm --privileged --systemd=always \
  --cap-add=ALL --security-opt label=disable \
  --network=bridge --publish 8080:8080 --publish 8443:8443 \
  -v <installer>:/installer:ro \
  -v <work_dir>:/work \
  -it <runner-image> \
  /usr/local/bin/trace-orchestrator.sh /installer
```

(Port publishes during trace are wide-open by design: we don't yet know what ports the software will bind; the orchestrator narrows after observing.)

### 5.4 Trace orchestrator (`sandbox/runner_image/trace-orchestrator.sh`)

Bash script that runs inside the sandbox. Sequence:

1. Start each collector backgrounded, writing JSONL to `/work/trace/<collector>.jsonl`. Each line carries `{ts_ns, pid, comm, event, ...}`.
2. Execute the installer (`/installer` or `bash /installer` depending on kind). On non-zero exit: capture `/work/install.log`, write `/work/install.status=failed`, signal the host, exit.
3. On installer success, write `/work/trace/PHASE_MARKER` with the current monotonic timestamp. This is the phase boundary the analyzer uses.
4. Detect daemon: prefer the systemd unit installed by the installer (`systemctl list-units --type=service --state=running --plain --no-legend` diff vs pre-install); fall back to a probe hint (`--start-cmd` flag) or a heuristic (the new long-running PID with most open files).
5. Wait for the daemon to log a "ready" line or for any port to be bound (whichever first), up to a configurable timeout.
6. Print: `software is running. exercise it now. press Enter in this terminal when done.`
7. Read stdin. On Enter: send `SIGTERM` to collectors with a grace period, flush JSONL, write `/work/trace/COMPLETE`, exit 0.
8. On `SIGINT` (Ctrl-C) propagated from the host: same finalize path as Enter, but write `/work/trace/PARTIAL` instead of `COMPLETE`.

### 5.5 Trace collectors

Each collector is a process spawned by the orchestrator. Output is one JSONL per collector under `/work/trace/`:

- `opensnoop.jsonl` — `open()`/`openat()`: `{ts_ns, pid, comm, path, flags, ret}`
- `execsnoop.jsonl` — `execve()`: `{ts_ns, pid, ppid, comm, argv, ret}`
- `tcpconnect.jsonl` — outbound TCP: `{ts_ns, pid, comm, daddr, dport, saddr, sport}`
- `tcpaccept.jsonl` — inbound TCP: `{ts_ns, pid, comm, laddr, lport, raddr, rport}`
- `bind.jsonl` (bpftrace) — `bind()` syscall: `{ts_ns, pid, comm, family, addr, port, proto}` (covers UDP listeners too)
- `syscalls.jsonl` (bpftrace) — `raw_syscalls:sys_enter` rolled up per `(pid, syscall_id)` with counts and first timestamp
- `capable.jsonl` (bcc `capable`) — capability checks: `{ts_ns, pid, comm, cap, audit, ret}`

Fallbacks: if a bcc tool fails to attach (kernel without BTF, missing kheaders), the orchestrator logs a warning and falls back to `strace -f -e trace=file,network` on the daemon PID for that coverage area, downgrading confidence.

### 5.6 Trace analyzer (`trace/analyzer.py`, `trace/schema.py`, `trace/paths.py`)

Pure Python. No Podman dependency — operates on the JSONL files alone. This is the module with the most testable logic and the heaviest unit-test investment.

Outputs `trace.json` (Pydantic model, schema-versioned):

```json
{
  "schema_version": 1,
  "phase_marker_ns": 123456789000,
  "install": { "duration_s": 142.3, "exit": 0, "apt_packages": ["openjdk-17-jre", "..."] },
  "runtime": {
    "duration_s": 421.7,
    "paths": [
      {"path": "/var/lib/unifi", "ops": ["read","write","mkdir"], "class": "persistent_rw", "by": ["unifi", "mongod"]},
      {"path": "/etc/resolv.conf", "ops": ["read"], "class": "host_config_ro", "by": ["unifi"]},
      "..."
    ],
    "ports": [
      {"port": 8443, "proto": "tcp", "by": "unifi", "ipv4": true, "ipv6": true},
      {"port": 3478, "proto": "udp", "by": "unifi"}
    ],
    "outbound": [{"daddr": "203.0.113.10", "dport": 443, "comm": "unifi"}],
    "caps": ["CAP_NET_BIND_SERVICE"],
    "syscalls": [0, 1, 2, 3, 5, 9, "..."],
    "execs": ["mongod", "java", "..."]
  },
  "warnings": ["collector capable.bt fell back to strace audit; results may be incomplete"]
}
```

Path classification (`paths.py`) rules, applied in order, first match wins:

1. Path is under the install prefix (`/opt/<app>`, `/usr/lib/<app>`, `/usr/share/<app>`) and only read → `image_static` (no mount; baked into image).
2. Path is under a known persistent root (`/var/lib`, `/var/log`, `/var/spool`) and is written → `persistent_rw` (named volume).
3. Path is under `/tmp`, `/run`, `/var/run`, `/var/tmp`, or `/dev/shm` and is written → `ephemeral_rw` (tmpfs).
4. Path is `/etc/resolv.conf`, `/etc/hosts`, `/etc/localtime`, `/etc/timezone` → `host_config_ro` (bind RO from host).
5. Path is `/dev/<name>` access → `device` (add `--device=` if essential, else flagged).
6. Path is under a known proc/sys path (`/proc`, `/sys`) → ignored (mounted by default).
7. Everything else → `unknown`, surfaced in the README for user triage.

Rules are tabular and live in `paths.py`, intentionally easy to extend.

### 5.7 Policy derivation (collapsed into `trace/analyzer.py`)

From `trace.json` the analyzer derives `policy.json`, the input to the generator:

```json
{
  "image": {
    "base": "ubuntu:24.04",
    "apt_packages": ["openjdk-17-jre", "..."],
    "installer_path": "/installer",
    "post_install_cleanup": ["/var/cache/apt/archives/*", "/installer"],
    "systemd_required": true,
    "entrypoint": ["/sbin/init"]
  },
  "runtime": {
    "volumes": [{"name": "unifi-data", "mount": "/var/lib/unifi"}],
    "tmpfs": ["/tmp", "/run", "/var/run"],
    "binds_ro": ["/etc/resolv.conf", "/etc/localtime"],
    "publish_ports": [{"host": 8443, "container": 8443, "proto": "tcp"}],
    "caps_add": ["CAP_NET_BIND_SERVICE"],
    "caps_drop": ["ALL"],
    "seccomp_syscalls": [0, 1, 2, "..."],
    "read_only_rootfs": true,
    "no_new_privileges": true
  }
}
```

`read_only_rootfs` is `true` only if every runtime-phase write was captured by one of the mapped persistent_rw / ephemeral_rw / volume / tmpfs entries. Otherwise it's `false` and the README explains which path forced it off.

### 5.8 Generators (`generate/`)

- `containerfile.py` — Jinja-templates `Containerfile`. Body:

  ```Dockerfile
  FROM {{ image.base }}
  RUN apt-get update && \
      DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        {{ image.apt_packages | join(' ') }} && \
      rm -rf /var/lib/apt/lists/*
  COPY installer {{ image.installer_path }}
  RUN chmod +x {{ image.installer_path }} && {{ image.installer_path }}
  RUN rm -rf {{ image.post_install_cleanup | join(' ') }}
  ENTRYPOINT {{ image.entrypoint | tojson }}
  ```

  `image.entrypoint` is `/sbin/init` when `image.systemd_required` is `true` (the installer registered a systemd unit and the daemon is expected to be supervised by it); otherwise it is the direct `argv` of the daemon (e.g., `["/opt/myapp/bin/myapp", "--config", "/etc/myapp.conf"]`), captured by the orchestrator at the moment it observed the daemon start. The orchestrator records both flags in `policy.json`; the generator templates them in unchanged.

- `quadlet.py` — Jinja-templates `<name>.container`. Body sketch:

  ```ini
  [Unit]
  Description=Containerized {{ name }}
  After=network-online.target
  Wants=network-online.target

  [Container]
  Image={{ image_ref }}
  ContainerName={{ name }}
  AutoUpdate=registry

  {% for v in runtime.volumes %}Volume={{ v.name }}:{{ v.mount }}
  {% endfor %}
  {% for t in runtime.tmpfs %}Tmpfs={{ t }}
  {% endfor %}
  {% for b in runtime.binds_ro %}Volume={{ b }}:{{ b }}:ro
  {% endfor %}
  {% for p in runtime.publish_ports %}PublishPort={{ p.host }}:{{ p.container }}/{{ p.proto }}
  {% endfor %}
  DropCapability=ALL
  {% for c in runtime.caps_add %}AddCapability={{ c }}
  {% endfor %}
  NoNewPrivileges=true
  ReadOnly={{ "true" if runtime.read_only_rootfs else "false" }}
  SecurityLabelDisable=false
  GlobalArgs=--security-opt seccomp=%h/.config/containers/seccomp/{{ name }}.json

  [Service]
  Restart=on-failure

  [Install]
  WantedBy=default.target
  ```

- `seccomp.py` — emits `seccomp.json` in the Docker/Podman OCI-compatible format: `defaultAction: SCMP_ACT_ERRNO`, `syscalls: [{ names: [...], action: SCMP_ACT_ALLOW }]`. Syscall numbers from the trace are mapped to names via a bundled lookup table (the OCI seccomp schema is name-based).

The generators also write `README.md` summarising the trace, listing each volume/port/cap/syscall added with a one-line reason ("`CAP_NET_BIND_SERVICE`: unifi bound port 443"), and listing every classifier `unknown` for user triage.

## 6. Data flow and schemas

Pipeline IO, each step's input and output:

| Phase | In | Out |
|-------|-----|------|
| probe | `<installer>` | `probe.json` |
| trace | `<installer>`, `probe.json` | `trace/*.jsonl`, `install.log`, `PHASE_MARKER`, `COMPLETE` or `PARTIAL` |
| analyze | `trace/*.jsonl`, `PHASE_MARKER` | `trace.json`, `policy.json` |
| generate | `policy.json`, `probe.json` | `Containerfile`, `<name>.container`, `seccomp.json`, `README.md` |
| verify | `./out/<name>/` | exit code + diff report |

Every schema is a Pydantic model in `trace/schema.py` carrying a `schema_version: int`. Bumping a schema requires keeping the previous shape readable so old fixtures still load.

Intermediates default to a tempdir, cleaned on successful `build`, preserved on any failure (path printed in the error message). `--keep-intermediates` forces preservation into `out/<name>/.intermediates/`.

## 7. Hardening defaults

The generator starts strict and only relaxes what the trace observed:

| Knob | Default | Relaxed when |
|------|---------|--------------|
| `DropCapability` | `ALL` | A capability appears in `capable.jsonl` runtime-phase events with `ret=0` |
| Seccomp | deny-all + traced allowlist | The traced syscall set drives the allowlist directly |
| `NoNewPrivileges` | `true` | Never relaxed |
| `ReadOnly` (rootfs) | `true` | A runtime-phase write is observed outside mapped volumes/tmpfs/binds |
| Volumes | none | Each `persistent_rw` path becomes a named volume |
| Tmpfs | `/tmp /run /var/run` | Always set if any write was observed in those locations |
| Binds RO | none | Each `host_config_ro` path becomes a `:ro` bind |
| Network | bridge, publish only traced binds | Always; ports come from `bind.jsonl` |
| User namespace | rootless (default Podman) | Always |
| SELinux/AppArmor label | not disabled | Only disabled with explicit `--no-mac` flag |

Every relaxation is logged in `README.md` with the trace event that justified it. The README is the audit trail.

## 8. Error handling

Each failure mode has one surfaced message and one recovery path. No silent fallbacks.

| Failure | Behavior |
|---------|----------|
| Preflight (no podman, machine down, no BPF) | `containerizer doctor` style report; abort before any container starts |
| Trace-runner image build fails | Stream the build log; suggest `--debug` to drop a shell |
| Sandbox container won't start | Stream container logs; abort |
| Installer exits non-zero | Capture `install.log`, preserve intermediates, print likely causes (missing systemd-as-PID-1, DNS, disk), abort |
| Collector produces empty output | Analyzer flags affected phases as low-confidence; tool continues but README warns |
| Smoke test cancelled (Ctrl-C) | First Ctrl-C prompts "finalise from partial trace [y/N]?". `y` proceeds with a partial-trace warning in README. `N` or a second Ctrl-C aborts and discards artifacts |
| Generated container fails `verify` | `verify` diffs observed denials against the trace and prints which paths/ports/caps/syscalls weren't captured; user can re-run `build` with a longer smoke test |

The CLI exits non-zero on every failure; the failure category is in the message.

## 9. Testing strategy

### Unit tests (the bulk)

- **Analyzer.** Recorded trace JSONL fixtures live in `tests/fixtures/`. Each fixture is a real capture from a past sandbox run, scrubbed of host-specific noise. Tests assert classification decisions, phase splitting, policy derivation. No Podman required.
- **Path classifier.** Table-driven tests cover every rule. New rule? Add a fixture row.
- **Generators.** Golden-file tests: feed a fixed `policy.json`, diff the rendered `Containerfile` / `<name>.container` / `seccomp.json` against committed expected outputs.
- **Probe.** Real `.deb`, `.rpm`, ELF, AppImage samples (tiny ones, committed under `tests/fixtures/probe/`) drive the probe and assert the produced `probe.json`.

### Integration (CI, ubuntu-latest)

A synthetic mini-installer — a Bash script that touches a known path set under `/var/lib/synthetic/`, binds TCP port 7777, runs for a few seconds — drives the full pipeline. Validates orchestration without requiring the real UniFi installer. Runtime budget: under 3 minutes.

### Acceptance (manual)

The real UniFi OS Server installer is the acceptance test. Run by the developer, not in CI. Outcomes:

- Containerized UniFi serves its admin UI on the published port.
- Restarting the Quadlet preserves state via the named volume.
- `containerizer verify ./out/unifi-os/` reports zero new denials after a representative session.

## 10. Repository and GitHub setup

### Repo

- `SupremeCommanderHedgehog/containerizer`, private, Apache-2.0.
- Default branch `main`. Strict protection: PR required, status checks must pass, signed commits required, linear history. No direct pushes to `main` from any account, including the owner.
- Local git config uses the signing key documented in the user's global `CLAUDE.md` (`BE707B220C995478`, author `github.v5f9w@bitbucket.onl`).

### CI (`.github/workflows/`)

- `ci.yml` — runs on PR and push to `main`. Jobs:
  - `lint`: `ruff check` + `ruff format --check`.
  - `typecheck`: `mypy src/containerizer`.
  - `test`: `pytest -q` across a Python 3.11 and 3.12 matrix on `ubuntu-latest`. Includes the synthetic-installer integration test.
- `codeql.yml` — CodeQL Python analysis on PRs and weekly schedule.
- `release-please.yml` — release-please action on push to `main`. Conventional-commit history drives version bumps and `CHANGELOG.md`.

### Dependabot (`.github/dependabot.yml`)

Weekly cadence, grouped per ecosystem:

- `pip` for `pyproject.toml` — one grouped PR/week.
- `github-actions` for `.github/workflows/` — one grouped PR/week.
- `docker` for the trace-runner Containerfile — one grouped PR/week.

### Issue templates (`.github/ISSUE_TEMPLATE/`)

YAML issue forms:

- `bug.yml` — reproduction, expected/actual, environment (podman version, machine kernel, installer kind).
- `feature.yml` — proposed change, motivation, acceptance.
- `software-support.yml` — "request support for software X": installer URL/source, what it does, smoke test description, known issues.

### Other meta

- `SECURITY.md` — private vulnerability reporting enabled, disclosure timeline.
- `CODEOWNERS` — `*  @SupremeCommanderHedgehog`.
- `README.md` (repo root) — short overview + link to this design spec.

### Project (Projects v2)

- Name: `containerizer roadmap`.
- Views: Kanban (default) + Table.
- Fields:
  - `Status`: Todo, In progress, Blocked, In review, Done.
  - `Priority`: P0, P1, P2, P3.
  - `Area`: probe, sandbox, trace, generate, cli, meta.
- Auto-add workflow: any new issue or PR in the repo is added to the project automatically.

## 11. Risks and open questions

| Risk | Mitigation |
|------|------------|
| BPF support inside the Podman machine kernel may be uneven; bcc tools have kernel-version sensitivity | `doctor` probes for BTF + bcc availability and reports concretely; strace fallback for affected coverage areas |
| Systemd-in-container is finicky on some hosts; the installer may fail in subtle ways the real host wouldn't show | `--debug` drops a shell in the sandbox; failure logs are preserved verbatim |
| Trace volume for a fat installer (UniFi + MongoDB + JVM warm-up) could be hundreds of MB of JSONL | Collectors filter known-noisy paths (`/proc/<pid>/`, `/sys/kernel/`); analyzer streams rather than loads-all |
| Path classifier is a heuristic and will mis-classify edge cases | Every `unknown` is surfaced in README; rules table is intentionally easy to extend; per-project override file in a later milestone |
| Seccomp profile is brittle: a missed syscall breaks the daemon | `verify` reproduces under strict policy and reports diffs; partial-trace warning in README |
| The interactive smoke test is human-bandwidth-limited | Documented as a design choice; scripted smoke tests can be added later as `--smoke-cmd` |

Open questions (deferred to implementation, not blockers):

- How aggressively to filter `/proc` and `/sys` noise in the collectors vs the analyzer. Defer until we see real UniFi trace volumes.
- Whether to bundle a curated list of "common runtime egress" allowances (DNS, NTP) in the README's policy notes by default.
- Whether `verify` should auto-suggest a relaxation diff, or only report.

## 12. Out of scope (for this spec)

- Multi-installer composition (one container running two services).
- Cross-architecture (arm64 hosts, x86 cross-build).
- Egress allowlisting / network policy enforcement.
- TUI front-end.
- Anything other than Linux ELF / `.deb` / `.rpm` / AppImage / shell installers.
- Image-signing / Cosign / supply-chain attestation. (Worth adding later, but not in v0.1.)

## 13. Rough milestones

Indicative phasing for the implementation plan. The plan-writing skill will refine.

1. **M0 — Repo bootstrap.** Local git init, push to GitHub, branch protection, project, CI skeleton, Dependabot, release-please, CodeQL, issue forms, SECURITY.md, CODEOWNERS, README stub.
2. **M1 — Skeleton CLI + probe.** `containerizer probe` produces `probe.json` from the local installer.
3. **M2 — Sandbox + trace.** Trace-runner image, orchestrator, collectors. `containerizer trace` produces raw JSONL.
4. **M3 — Analyzer + policy.** Path classifier, phase splitting, `trace.json` + `policy.json`. Heaviest unit-test investment.
5. **M4 — Generators.** Containerfile, Quadlet, seccomp.json, README. Golden-file tests.
6. **M5 — `verify` + error polish.** Diff-against-trace verifier, recovery prompts, doctor.
7. **M6 — Acceptance.** Real UniFi installer end-to-end. Iterate on classifier rules.
8. **M7 — 0.1.0 release.** release-please cuts the tag.
