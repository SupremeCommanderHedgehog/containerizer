# Issue #99 — Debian `.deb` installer support end-to-end

**Date:** 2026-06-20
**Status:** Draft (brainstorming)
**Parent spec:** [`2026-06-06-containerizer-design.md`](./2026-06-06-containerizer-design.md)
**Prior milestone specs:** [`2026-06-06-containerizer-m2-sandbox-trace.md`](./2026-06-06-containerizer-m2-sandbox-trace.md), [`2026-06-07-containerizer-m3-analyzer-policy.md`](./2026-06-07-containerizer-m3-analyzer-policy.md), [`2026-06-08-containerizer-m6-build.md`](./2026-06-08-containerizer-m6-build.md)
**Issue:** [#99](https://github.com/SupremeCommanderHedgehog/containerizer/issues/99)

## 1. Overview

`containerizer` today supports exactly one installer kind: a Linux ELF binary. `src/containerizer/probe/installer.py:43-44` already recognises Debian `.deb` archives (by their `!<arch>\n` magic) and `src/containerizer/probe/schema.py` reserves `InstallerKind.deb`, but the probe path raises `UnsupportedInstallerKind` and the trace runner has no way to install one.

This spec adds end-to-end `.deb` support: probe parses control metadata, the trace runner installs the deb in a nested Ubuntu container under `--systemd=always` so postinst scripts behave normally, and the existing `analyze` → `generate` → `verify` → `build` pipeline consumes the trace unchanged. After this change, `containerizer build foo.deb --name foo` produces a hardened Containerfile + Quadlet + seccomp the same way it does for an ELF installer today.

Context: issue #90 (systemd as PID 1 in the trace runner) shipped via PRs #96 and #97 just before this spec was written. The outer trace runner now boots `/sbin/init`; the orchestrator runs as a `containerizer-trace.service` oneshot wired to `/dev/console`; an `interactive` flag (`CONTAINERIZER_INTERACTIVE`) flows from the host's stdin-TTY state through to the orchestrator. This spec assumes that world.

The driving example is a small daemon-shaped fixture deb (CI) plus, eventually, real packages like `redis-server` or `nginx-light`. UniFi's installer remains the ELF flagship for scenario 11; `.deb` opens the door to standard distro packages as a containerization target.

## 2. Scope

### In this change

- `src/containerizer/probe/deb.py` — new module. Parses a `.deb` (ar archive of `debian-binary` + `control.tar.*` + `data.tar.*`) using stdlib `tarfile` and a ~50-line ar reader. Returns a frozen pydantic `DebProbe`.
- `src/containerizer/probe/schema.py` — adds the `DebProbe` model and a `deb: DebProbe | None = None` field on `ProbeResult`.
- `src/containerizer/probe/base_image.py` — `suggest_base_image` accepts either an `ElfProbe` or a `DebProbe`. For deb, picks `ubuntu:24.04` for `amd64`/`arm64`, errors out for other architectures with a clear message.
- `src/containerizer/probe/installer.py` — dispatches `InstallerKind.deb` to `probe_deb()` instead of raising.
- `sandbox/runner_image/trace-orchestrator.sh` — installer-kind dispatch. When `/installer` matches the deb magic, the orchestrator runs the install workload as a detached nested container (`--systemd=always ubuntu:24.04`), `podman exec`s the install command into it, marks the phase, waits for user Enter, then `podman stop`s the nested container. First run pays a `ubuntu:24.04` pull cost (~80 MB, all install-side activity that PHASE_MARKER excludes from runtime policy). Cached on subsequent runs.
- `tests/unit/probe/test_deb.py` — new. Covers ar parsing, control extraction, systemd-unit discovery, base-image dispatch, schema round-trip.
- `tests/integration/trace/test_deb_pipeline.py` — new. Builds a tiny fixture deb during the test and runs the full trace against it.
- `tests/integration/build/test_build_deb.py` — new. End-to-end `containerizer build` against the fixture deb.

### Carried unchanged

- `src/containerizer/analyze/*` — the analyzer consumes JSONL emitted by the collectors and splits events on `PHASE_MARKER`. Both work identically for deb installs because BPF collectors run on the host kernel and observe events regardless of container boundaries.
- `src/containerizer/generate/*`, `src/containerizer/verify/*`, `src/containerizer/build/pipeline.py` — kind-agnostic; consume the post-analyze policy.
- `src/containerizer/trace/runner.py` — argv shape unchanged. The installer file is still mounted at `/installer:ro`; the orchestrator decides what to do with it based on magic bytes.
- `sandbox/runner_image/verify-orchestrator.sh` — untouched.
- `containerizer probe`, `trace`, `analyze`, `generate`, `verify`, `build` CLI surface — unchanged.

### Out of scope (deferred)

- **`.rpm` support.** Mirrors this design but lives in a separate issue.
- **AppImage, shell, tarball installers.** Detected, refused. Same as today.
- **Cross-architecture installs** (`arm64` deb on `amd64` host, or vice versa). Errors out at probe time with a clear message.
- **Pre-vendored offline dep bundles.** Network during install is acceptable; the trace phase boundary excludes apt/dpkg activity from runtime policy automatically.
- **Non-daemon packages** (library debs, one-shot CLI debs). The containerizer pipeline assumes a long-running smoke-testable workload. A library-only deb installs cleanly but has nothing to smoke-test; the trace finishes with COMPLETE but the runtime phase is empty, and the generated container has no useful policy. We document this as a known gap rather than supporting it specially.
- **Apt source list pinning / mirror selection.** The nested ubuntu container uses its stock sources. Network policy is the deployer's problem (parent design §2 non-goals).
- **Generated container base-image switch.** The generated container's base image is still chosen by `suggest_base_image`. For deb installs that picks `ubuntu:24.04`. We do **not** carry the deb's runtime deps from the nested install container into the generated container automatically — `generate` derives that from observed file accesses, same as for ELF. (This is a deliberate design decision: trust the trace, not the package's declared `Depends`.)

## 3. Architecture

### 3.1 Probe (`src/containerizer/probe/deb.py`)

The `.deb` format is an `ar` archive containing exactly three regular members in this order:

1. `debian-binary` — a short text file. First line is the format version (`2.0\n`).
2. `control.tar{,.gz,.xz,.zst}` — packaging metadata (`control`, `md5sums`, maintainer scripts).
3. `data.tar{,.gz,.xz,.zst}` — the actual filesystem payload.

Parser strategy (stdlib only, no `python-debian` dependency):

```python
@dataclass(frozen=True)
class _ArMember:
    name: str
    size: int
    offset: int  # byte offset of member data within the file

def _iter_ar_members(fh: BinaryIO) -> Iterator[_ArMember]:
    """Yields ar members. Format: 8-byte global header '!<arch>\\n',
    then per-member 60-byte headers (name[16], mtime[12], owner[6],
    group[6], mode[8], size[10], end['`\\n']). Member data is padded
    to even byte boundary."""
```

Control parsing reads `control.tar.*` as a tar stream, finds the `control` file, parses it as Debian RFC822-ish fields (key/value, continuation lines starting with space, paragraphs separated by blank lines — we only care about the first paragraph). Helper:

```python
def _parse_control(text: str) -> dict[str, str]:
    """Parses Debian control's first paragraph into a flat dict.
    Continuation lines are joined with their leading space preserved
    (matching dpkg's behavior for Description fields)."""
```

Systemd-unit discovery reads `data.tar.*` and notes any regular file under `lib/systemd/system/` or `usr/lib/systemd/system/`. The probe records unit names (basenames) only, not unit contents.

`DebProbe` schema:

```python
class DebProbe(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = 1
    package: str             # Package: field
    version: str             # Version: field
    arch: str                # Architecture: field (debian-style: amd64, arm64, all, ...)
    depends: list[str] = Field(default_factory=list)       # parsed as raw strings, no version constraint splitting
    pre_depends: list[str] = Field(default_factory=list)
    recommends: list[str] = Field(default_factory=list)
    maintainer: str | None = None
    description: str | None = None  # first line of Description
    systemd_units: list[str] = Field(default_factory=list)
```

`ProbeResult` gains `deb: DebProbe | None = None`. We do **not** unify `ElfProbe` and `DebProbe` behind a common type; the existing pattern uses a discriminator (`kind`) plus an optional typed field per kind, and we keep that.

### 3.2 Base-image suggestion (`src/containerizer/probe/base_image.py`)

`suggest_base_image` becomes a kind-dispatching function:

```python
def suggest_base_image(probe: ElfProbe | DebProbe) -> BaseImageSuggestion:
    if isinstance(probe, DebProbe):
        return _suggest_for_deb(probe)
    return _suggest_for_elf(probe)
```

For deb:

| `Architecture:` value | Suggestion | Reasoning |
|---|---|---|
| `amd64` | `ubuntu:24.04` | Match deb's target arch; LTS is the safe default. |
| `arm64` | `ubuntu:24.04` | Same, ARM variant resolves via the multi-arch tag. |
| `all` | `ubuntu:24.04` | Architecture-independent (Python, shell, JVM, etc.). |
| `i386`, `armhf`, others | error | Unsupported for v0.x; user can override with `--base-image` (CLI flag exists per parent design §3). |

Existing ELF callers (`probe()`) need a one-line change to pass the right typed argument; the public signature is now a union.

### 3.3 Trace runner: installer-kind dispatch

The runner image stays Fedora 41. No image-build-time changes: pre-pulling `ubuntu:24.04` would require podman-in-podman during `podman build`, which is much harder to keep working than the verify-mode runtime nested podman that's already established. Instead, the first deb trace run pulls `ubuntu:24.04` at orchestrator startup time (before the install phase begins). The pull lands on the install side of `PHASE_MARKER` and is excluded from runtime policy. Subsequent runs reuse the cached image.

`trace-orchestrator.sh` gains a kind-dispatch block. Pseudocode for the install branch:

```bash
# Detect installer kind by magic bytes (cheap; readelf etc. not needed).
INSTALLER_KIND="$(_detect_kind "$INSTALLER")"
echo "trace-orchestrator: installer kind=$INSTALLER_KIND" >&2

case "$INSTALLER_KIND" in
    elf)
        run_elf_install
        ;;
    deb)
        run_deb_install
        ;;
    *)
        echo "trace-orchestrator: unsupported installer kind: $INSTALLER_KIND" >&2
        finalize_marker PARTIAL
        exit 0
        ;;
esac
```

`run_elf_install` is the existing M2 codepath (background-exec + wait + PHASE_MARKER + read).

`run_deb_install` is new. It mirrors the ELF path's interactive/non-interactive split that #97 added (orchestrator.sh:158-164, 216-226) so CI integration runs don't hang on `read`:

```bash
run_deb_install() {
    # Pre-pull happens here on first run; cached on subsequent runs. This
    # is install-side activity (before PHASE_MARKER) and excluded from
    # runtime policy by the analyzer's existing phase split.
    podman pull docker.io/library/ubuntu:24.04 > "$TRACE_DIR/deb-pull.log" 2>&1

    # Start a long-lived nested ubuntu container with systemd as PID 1.
    # --network=host shares the nested container's network ns with the
    # outer trace runner. --privileged so apt can write to /var/cache and
    # postinst can adjust sysctl/nftables if asked.
    podman run -d --rm --name deb-install \
        --systemd=always --privileged \
        --network=host \
        -v "$INSTALLER:/installer:ro" \
        docker.io/library/ubuntu:24.04 \
        > "$TRACE_DIR/deb-install.cid" 2> "$TRACE_DIR/deb-install.err"

    # Run apt install inside the nested container. systemd is PID 1 there,
    # so postinst's systemctl start works. Runs synchronously (foreground);
    # apt-get -y needs no stdin, so the #95 `<&0` issue does not apply.
    podman exec deb-install bash -c '
        export DEBIAN_FRONTEND=noninteractive
        apt-get update &&
        apt-get install -y /installer
    ' > "$TRACE_DIR/install.log" 2>&1
    install_rc=$?
    echo "$install_rc" > "$TRACE_DIR/installer.exitcode"

    if (( install_rc != 0 )); then
        echo "failed" > "$TRACE_DIR/install.status"
        podman stop -t 5 deb-install >/dev/null 2>&1 || true
        finalize_marker PARTIAL
        exit 0
    fi

    # Mark the phase boundary: apt activity is now before this point;
    # the user-driven smoke test runs after it.
    awk '{split($1,a,"."); printf "monotonic_ns: %s%09d\n", a[1], a[2]*10000000}' /proc/uptime \
        > "$TRACE_DIR/PHASE_MARKER"

    if [[ "$interactive" == 1 ]]; then
        echo "trace-orchestrator: deb installed. exercise the software (podman exec deb-install <cmd>), then press <Enter> here to finalise." >&2
        read -r _ || true
    else
        echo "trace-orchestrator: deb installed (non-interactive); finalising" >&2
    fi

    podman stop -t 10 deb-install >/dev/null 2>&1 || true
    finalize_marker COMPLETE
    echo "trace-orchestrator: COMPLETE" >&2
}
```

The `$interactive` variable is defined earlier in the orchestrator (lines 158-164 of current `trace-orchestrator.sh`) from `CONTAINERIZER_INTERACTIVE`. Both branches share the same source.

Key choices:

- **`--rm` on the nested container** — orchestrator owns lifecycle; the container is throwaway. If `podman stop` fails (e.g., user already killed it), `--rm` still cleans up.
- **`--network=host`** (nested → outer) — the nested install container shares the outer trace runner's network namespace. The outer runner today does not itself use `--network=host` (`src/containerizer/trace/runner.py:95-118`), so this does not magically expose the daemon's ports on the user's host. The user smoke-tests via `podman exec deb-install <cmd>` from a second host shell, OR by running `podman exec -it <runner-name> nmap-ncat / curl` against the nested daemon. This is the same ergonomic cliff that exists for ELF installs today; the spec calls it out but does not solve it. See known risk §7.7 for a follow-up issue suggesting `--network=host` (or `-p`) at the outer-runner level.
- **`--systemd=always`** — necessary so deb postinst's `systemctl start <unit>` works. Without this, packages like nginx, redis, postgresql would install cleanly but the service wouldn't be running for the user to smoke-test.
- **`--privileged`** — needed because some debs (e.g., kernel modules, networking tools) call privileged syscalls during postinst. The outer trace container is already `--privileged`; the nested one needs to be too for consistent behavior.
- **Network access during `apt-get update`** — apt fetches the index from Ubuntu archives, then downloads any uncached `Depends`. All of this is on the install side of `PHASE_MARKER`, so the analyzer's existing phase split excludes it from policy.
- **No fallback strace targeting** — for ELF the orchestrator spawns one `strace -p <installer_pid>` per failed collector. For deb the installer's `pid` is `podman exec`'s pid, which is nearly useless to strace. We accept the loss: if a collector fails to attach for a deb run, the user sees the gap in `FALLBACKS.json` and re-runs after fixing the kernel headers / BTF situation. Documented as known risk §7.
- **INT/TERM trap extends to stop the nested container.** The current trap at orchestrator.sh:107 (`trap 'finalize_marker PARTIAL; exit 0' INT TERM`) does not know about `deb-install`. Implementation must replace it (inside the deb branch only) with something equivalent to `trap 'podman stop -t 2 deb-install >/dev/null 2>&1 || true; finalize_marker PARTIAL; exit 0' INT TERM` so Ctrl-C doesn't leak the nested container.

### 3.4 Probe → trace shape end-to-end

```text
host:  containerizer build foo.deb --name foo
       └─> probe(foo.deb)
             └─> detect_kind() -> InstallerKind.deb
             └─> probe_deb() -> DebProbe{ package, version, arch, ... }
             └─> suggest_base_image(DebProbe) -> ubuntu:24.04
       └─> trace.runner.argv() (unchanged; mounts foo.deb at /installer)
       └─> podman run --privileged ... runner-image:tag
                                    │
                                    ▼
runner: trace-orchestrator.sh
        └─> launch collectors (bpftrace, bcc) on outer kernel
        └─> detect_kind(/installer) -> deb
        └─> run_deb_install:
              podman run -d --name deb-install --systemd=always ubuntu:24.04
              podman exec deb-install apt-get install -y /installer
              write PHASE_MARKER
              wait for user Enter
              podman stop deb-install
        └─> finalize_marker COMPLETE
       └─> analyze (reads PHASE_MARKER, splits install vs runtime events)
       └─> generate (deny-by-default Containerfile + Quadlet + seccomp from runtime events)
       └─> verify (M6: reload generated container, soak)
```

The probe's `DebProbe` is logged and surfaced in the generated README but does **not** drive the generated container's policy. Policy comes from runtime trace events only — same principle as the ELF flow.

## 4. Lifecycle (deb mode)

End-to-end install flow:

1. Host: `containerizer build foo.deb --name foo`.
2. Host probe: `detect_kind(foo.deb) → deb`, `probe_deb` returns `DebProbe`, `suggest_base_image` returns `ubuntu:24.04`. Logged.
3. Host trace runner: `podman run --rm -it --privileged --systemd=always -e CONTAINERIZER_MODE=install -e CONTAINERIZER_INSTALLER=/installer -e CONTAINERIZER_INTERACTIVE=1 ...` boots the runner; systemd reaches `multi-user.target`; `containerizer-trace-env.service` publishes the env vars to `/run/containerizer/env`; `containerizer-trace.service` starts `trace-orchestrator.sh --mode install /installer` on `/dev/console`.
4. Inside runner: collectors launch, attach grace passes.
5. Inside runner: `trace-orchestrator.sh` detects `.deb` magic on `/installer`, branches to `run_deb_install`.
6. Inside runner: `podman run -d --rm --name deb-install --systemd=always --privileged --network=host ubuntu:24.04` starts a nested container. systemd boots inside it (~2-4s).
7. Inside runner: `podman exec deb-install apt-get update && apt-get install -y /installer`. Apt fetches deps; dpkg unpacks; postinst runs (including any `systemctl start <unit>` calls — these succeed because systemd is PID 1 in the nested container).
8. Inside runner: orchestrator writes `PHASE_MARKER`, prints "press Enter when smoke-tested."
9. User host-side: from a second shell, `podman exec -it <runner-container-name> podman exec -it deb-install <smoke-test-cmd>` (or any equivalent path that lands inside the nested container's network namespace). For interactive web UIs, the user can `podman exec deb-install curl http://localhost:<port>` to confirm the daemon is up. Direct host-to-nested-daemon connectivity is **not** wired up; see §3.3 `--network=host` note and §7.7.
10. User presses Enter.
11. Inside runner: orchestrator `podman stop deb-install` → systemd shuts the nested container down cleanly → `--rm` removes it.
12. Inside runner: orchestrator stops collectors, writes COMPLETE marker, exits.
13. Host: trace finalises, pipeline continues into analyze/generate/verify.

## 5. Failure modes

| Failure | Behavior |
|---|---|
| `apt-get update` fails (no network in runner) | `install_rc != 0`, `install.status=failed`, nested container stopped, PARTIAL marker, exit 0. Host wrapper surfaces "deb install failed; check network in trace runner". |
| `apt-get install` fails (missing dep, wrong arch, broken postinst) | Same as above. `install.log` has dpkg's output for debugging. |
| Nested container fails to start (image missing, podman storage issue) | `podman run -d` returns non-zero; `deb-install.err` captures the reason; PARTIAL + exit 0. Host wrapper surfaces. |
| Postinst fails partway (e.g., `systemctl start` errors) | apt-get exits non-zero. Same failure path. |
| User presses Ctrl-C during install | Extended trap (per §3.3 note) fires `podman stop deb-install` then `finalize_marker PARTIAL` then exit 0. `--rm` cleans up the nested container after stop. PARTIAL marker visible to host. |
| Deb installs but ships no systemd unit (library-only deb, one-shot CLI) | apt succeeds, PHASE_MARKER written, user has nothing to smoke-test. User can either exercise the CLI manually inside the nested container (`podman exec deb-install <cmd>`) or press Enter immediately. Runtime trace will be near-empty; generated policy will be the deny-by-default baseline. Documented in generated README. |
| ubuntu:24.04 image not in runner storage (image rebuilt without pre-pull) | `podman run` pulls during the trace, adding 10-30s of install-phase noise. Functionally correct, just slower. Falls under existing install-side activity that PHASE_MARKER filters. |
| User's smoke test takes longer than the runner's image lifetime | No timeout on the orchestrator's `read -r _`; user can take as long as they want. Same as ELF flow today. |

## 6. Testing strategy

### 6.1 Unit tests (Python)

`tests/unit/probe/test_deb.py`:

- ar header parsing (`!<arch>\n` magic, member iteration, padding).
- `control.tar.gz`, `control.tar.xz`, `control.tar.zst` all parse (compression-format coverage).
- Control field parsing: single-line fields, multi-line `Description`, missing-optional-field tolerance.
- Systemd-unit discovery: data.tar member under `lib/systemd/system/*.service`, under `usr/lib/systemd/system/*.service`, and absence (CLI-only deb).
- `DebProbe` schema: `extra="forbid"`, frozen, round-trips through JSON.

`tests/unit/probe/test_base_image.py` (existing file extended):

- `suggest_base_image(DebProbe{arch="amd64"})` → `ubuntu:24.04`, reasons mention deb arch.
- `suggest_base_image(DebProbe{arch="arm64"})` → `ubuntu:24.04`, reasons mention arm64.
- `suggest_base_image(DebProbe{arch="all"})` → `ubuntu:24.04`, reasons mention "architecture-independent".
- `suggest_base_image(DebProbe{arch="i386"})` raises (or returns an error suggestion — match existing error UX).
- Existing ELF tests still pass.

`tests/unit/probe/test_installer.py`:

- `probe(some.deb)` returns `ProbeResult{kind=deb, deb=DebProbe{...}, base_image=BaseImageSuggestion{image="ubuntu:24.04"}}`.
- `UnsupportedInstallerKind` no longer raised for `InstallerKind.deb`.

### 6.2 Trace-orchestrator shell tests

`tests/unit/trace/test_orchestrator_dispatch.sh` (or pytest harness invoking bash):

- `_detect_kind` returns `deb` for a fixture deb, `elf` for a fixture ELF, `unknown` otherwise.
- `run_deb_install` is callable in isolation (mock `podman` with a stub that records argv).

### 6.3 Integration tests

`tests/integration/trace/test_deb_pipeline.py`:

Build a tiny fixture deb at test setup using `dpkg-deb -b` inside the runner image (or hand-assemble the ar+tar in pure Python). The deb installs a single-file ExecStart script that runs `python3 -m http.server 8080` as a systemd `simple` service. Acceptance:

- Trace runs to COMPLETE (test driver closes stdin to simulate user-press-Enter immediately after detecting the bound port).
- `trace.json` has runtime events for the http.server (port 8080 bound, socket() syscall observed, etc.).
- Apt's PID is NOT in the runtime event set (validates phase boundary).

`tests/integration/build/test_build_deb.py`:

Run the full `containerizer build` against the same fixture deb. Acceptance:

- Generated `Containerfile` exists and references `ubuntu:24.04`.
- Generated `<name>.container` (Quadlet) exists.
- `seccomp.json` exists and contains the `bind` / `accept4` / `socket` allowlist for the smoke-tested daemon.
- `README.md` documents the deb's `DebProbe` (package, version, declared Depends — informational only).

### 6.4 CI integration

Add the new integration tests to the existing `trace-integration` job (already exercised by M3 PR #80, M5 PR #84, M6 PR #86). Estimated runtime: +90 seconds on top of the existing job. Acceptable.

### 6.5 Manual acceptance

Run `containerizer build` against a real package — `nginx-light` is small (~3 MB, fast install) and ships a working systemd unit. Verify the trace captures nginx's runtime ports (80) and the generated Quadlet starts nginx successfully on a clean host. Documented as a MANUAL.md scenario 12 once the change lands.

## 7. Known risks

1. **First-run pull adds ~80 MB + 10-30s of network activity at install start.** Mitigation: warmth via reuse — second run is instant. Both the `ubuntu:24.04` pull and `apt-get update`/install network activity sit before `PHASE_MARKER` and don't pollute runtime policy. No code-side mitigation needed; just call this out in the user-facing CLI output ("first deb trace pulls ubuntu:24.04, this is a one-time cost").
2. **Strace fallback degraded for deb mode.** The orchestrator can't usefully target a single pid for strace when the install runs as `podman exec` inside a nested container. If bpftrace/bcc collectors fail to attach, the deb run will have a more sparse trace than the ELF equivalent. Mitigation: surface this in the host wrapper's error path; suggest the user check kernel headers / BTF before re-running.
3. **User-Ctrl-C must not leak the nested container.** The shipped orchestrator's INT trap (trace-orchestrator.sh:107) does not know about `deb-install`. Mitigation in §3.3: deb branch installs a wider trap that stops `deb-install` before finalising PARTIAL. Trivial, but explicitly called out as a tasking line item so the implementer doesn't skip it.
4. **Library-only debs produce empty runtime traces and useless generated policy.** Not a bug, but a UX cliff: a user runs `containerizer build libfoo.deb` expecting something useful and gets a deny-by-default container with nothing to do. Mitigation: probe-time warning when `DebProbe.systemd_units` is empty AND the deb's data.tar contains no executable under `usr/{,s}bin/`. Documented in §2 out-of-scope.
5. **Nested-podman cgroup delegation.** Mirrors issue #90 risk #1. If verify-mode already works under the systemd-PID-1 runner, install-mode nested podman should too. Same `--cgroupns=private` fallback applies.
6. **Interaction with issue #90 (systemd as PID 1).** Already shipped via PR #96 (boot systemd) and PR #97 (UniFi Y/N stdin fix). This spec's orchestrator changes are written against that world: `run_deb_install` consumes the existing `$interactive` variable; `CONTAINERIZER_INTERACTIVE` flows through the env-publisher unit the same as ELF's interactive flag. No conflict.
7. **Smoke-test ergonomics are awkward.** Without `--network=host` or `-p <port>` on the outer trace runner, the user cannot reach the nested daemon's ports from their host; they have to chain `podman exec` calls. Same cliff exists for ELF today, so this issue does not regress UX, but it's worth filing a follow-up to either add `--network=host` to the outer trace runner or expose a `containerizer trace --publish <port>` flag.

## 8. Open questions

None blocking. The four clarifying questions answered during brainstorming locked the architecture:

1. Scope = full pipeline (probe → trace → generate). **Locked.**
2. Install command = `apt-get install -y ./pkg.deb` with network on. **Locked.**
3. Apt noise handling = phase boundary, trace only runtime. **Locked.**
4. Where apt runs = nested `ubuntu:24.04` container with `--systemd=always`. **Locked.**

## 9. Implementation phasing

The plan (separate doc, generated by `superpowers:writing-plans`) will expand these into TDD tasks:

- **Phase 1** — Probe. Add `probe_deb`, `DebProbe`, dispatch in `installer.py`, kind-aware `suggest_base_image`. Pure Python, fast tests, no sandbox dependency. Lands first as its own commit.
- **Phase 2** — Orchestrator refactor. Extract the existing install workload (trace-orchestrator.sh:146-228) into a `run_elf_install` function. No behavior change; just function extraction. Ships as a refactor-only commit so the next phase's diff is small.
- **Phase 3** — Orchestrator dispatch + deb path. Add `_detect_kind` and `run_deb_install` to `trace-orchestrator.sh`. Wire the dispatch block. Extend the INT/TERM trap inside `run_deb_install` to stop the nested container. Unit-test the shell with a podman stub.
- **Phase 4** — Integration tests. Fixture-deb generator (~30 lines of Python that assembles a minimal ar+tar deb), trace integration test, build integration test. Wire into `trace-integration` CI job.
- **Phase 5** — Manual scenario 12 (nginx-light end-to-end). Optional gate; lands as a docs-only commit after the implementation merges.

## 10. Spec / PR shape

- This spec ships as a docs-only PR (per the M3-M6 pattern), alongside the implementation plan written by `superpowers:writing-plans`.
- Implementation PR follows. Recommended shape: one signed commit per phase 1-4, plus a docs commit for scenario 12.
- Gate on `trace-integration` CI green before merging.
- All commits signed with key `BE707B220C995478`, author `github.v5f9w@bitbucket.onl`.
