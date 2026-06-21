# Manual: Try out `containerizer`

Step-by-step instructions for setting up the project and exercising every code path it currently has. Assumes a Windows host (PowerShell), but everything except where noted works the same on Linux/macOS shells too.

## What you can test today

As of v0.2.1 the only user-facing command is `containerizer probe`. It statically inspects a Linux installer file and emits a typed JSON probe describing what it found. Concretely:

- **ELF binaries and `.deb` packages** are fully probed — for ELF: architecture, bit width, endianness, dynamic loader, NEEDED libraries, minimum glibc requirement, and a suggested Ubuntu LTS base image; for `.deb`: control metadata plus the embedded ELF analysis.
- **`.rpm`, AppImage, shell scripts, tarballs** are *detected* (magic-byte sniff) but probing them raises a clear "not yet supported" error. The detection paths are what you can exercise here.
- **Everything else** is reported as `kind: "unknown"` and probing raises the same not-supported error.

The trace/learn portion (running an installer in a sandbox and recording its behaviour) is not built yet — that's milestone M2.

## Prerequisites

- **Python 3.11 or 3.12** on PATH. Confirm with `python --version`.
- **git** on PATH.
- **Optional, only for scenario 2:** Podman with a running machine (`podman machine start`), so you can pull an ELF binary out of a Linux image. The repo's own README lists Podman as the supported container runtime.

## 1. Clone and install

```pwsh
git clone https://github.com/SupremeCommanderHedgehog/containerizer.git
cd containerizer
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

Activate the venv for the rest of the session so `containerizer` resolves on PATH:

```pwsh
.\.venv\Scripts\Activate.ps1
```

Verify the install:

```pwsh
containerizer --version
# Expected: containerizer, version 0.2.1
containerizer probe --help
```

## 2. Sanity-check the test suite

Before testing the CLI on real inputs, make sure the suite passes in your environment. This also confirms the coverage gate is wired:

```pwsh
pytest
```

Expected: `40 passed`, ending with `Required test coverage of 90% reached. Total coverage: 93.99%`. If pytest fails to collect because `cov` isn't found, your venv didn't pick up the dev extras — re-run `pip install -e ".[dev]"`.

## Scenario 1 — probe the bundled ELF fixture

The repo ships a 35 KB ELF binary (a stripped `/usr/bin/true` from `debian:bookworm-slim`) at `tests/fixtures/probe/elf-dynamic-x86_64`. Easiest first probe:

```pwsh
containerizer probe tests\fixtures\probe\elf-dynamic-x86_64
```

You should see a JSON document like:

```json
{
  "schema_version": 1,
  "kind": "elf",
  "arch": "x86_64",
  "elf": {
    "schema_version": 1,
    "arch": "x86_64",
    "bit": 64,
    "endianness": "little",
    "interpreter": "/lib64/ld-linux-x86-64.so.2",
    "is_static": false,
    "needed_libs": ["libc.so.6"],
    "glibc_min": "2.34"
  },
  "base_image": {
    "image": "ubuntu:22.04",
    "reasons": [
      "glibc 2.34 fits Ubuntu 22.04 LTS",
      "architecture: x86_64"
    ]
  }
}
```

The exact `glibc_min` depends on the binary the fixture was carved from, but `base_image.image` should match the routing in `src/containerizer/probe/base_image.py:_pick_for_glibc` (see scenario 5).

## Scenario 2 — probe a fresh ELF from a real image

To exercise the probe against something more interesting, pull a binary straight out of a public image. With the Podman machine running:

```pwsh
podman run --rm -v C:\Temp:/out debian:bookworm-slim cp /usr/bin/dpkg /out/dpkg-bookworm.bin
containerizer probe C:\Temp\dpkg-bookworm.bin
```

The bind-mount + `cp` form is deliberate. Don't try to "simplify" with a PowerShell redirect (`> C:\Temp\out.bin`) — see the pitfalls section below.

`/usr/bin/dpkg` is Debian's own package manager and is guaranteed to be present in any Debian image. `needed_libs` is short — just `libmd.so.0`, `libselinux.so.1`, `libc.so.6` (dpkg loads compression libs like libbz2/liblzma/libzstd via dlopen, so they don't appear in DT_NEEDED). `glibc_min` should be `2.34` and the suggested base image should be `ubuntu:22.04` (glibc 2.31–2.35 routes there since v0.2.1).

Other useful targets to try:

| Image | Binary | What it tests |
|---|---|---|
| `ubuntu:20.04` | `/usr/bin/ls` | glibc 2.31 → `ubuntu:22.04` |
| `ubuntu:24.04` | `/usr/bin/find` | glibc 2.39 → `ubuntu:24.04` (glibc > 2.35) |
| `alpine:latest` | `/bin/busybox` | musl-linked, expect `interpreter` ending in `ld-musl-*.so.1` and `glibc_min: null` |
| `arm64v8/debian:bookworm-slim` (with `--platform linux/arm64`) | `/usr/bin/true` | `arch: aarch64`, `bit: 64` |

Slim Debian and minimal Ubuntu images ship only what's strictly required (no `curl`, no `python3`, no `wget`), so stick to binaries from coreutils, findutils, dpkg, apt, or bash when picking targets — or pull from a fatter image like `python:3.12-slim` if you specifically want a Python binary.

The musl case is interesting: it should detect as ELF, find no `.gnu.version_r` glibc entries, and report `glibc_min: null`. The base-image picker then falls back to `ubuntu:24.04` with the reason `no glibc requirement detected; picked ubuntu:24.04`.

## Scenario 3 — exercise the non-ELF detection paths

The CLI rejects non-ELF kinds with a clear error, but you can confirm the *detection* logic works by writing minimal magic-byte fixtures and probing them.

In PowerShell:

```pwsh
# .rpm
[System.IO.File]::WriteAllBytes(
  "C:\Temp\fake.rpm",
  [byte[]](0xed,0xab,0xee,0xdb) + (,0 * 32))
containerizer probe C:\Temp\fake.rpm

# shell script
Set-Content -Path C:\Temp\install.sh -Value "#!/bin/sh`necho hi" -Encoding ascii
containerizer probe C:\Temp\install.sh

# gzip tarball
[System.IO.File]::WriteAllBytes(
  "C:\Temp\fake.tar.gz",
  [byte[]](0x1f,0x8b) + (,0 * 32))
containerizer probe C:\Temp\fake.tar.gz
```

Each call should exit non-zero and print a message like:

```
Error: installer kind 'rpm' is not yet supported: C:\Temp\fake.rpm
```

That confirms `detect_kind` correctly identifies the magic bytes and the CLI surfaces the not-yet-supported case cleanly.

## Scenario 4 — unknown kinds

Anything whose magic bytes match no branch is reported as `unknown` and surfaces the same not-supported error with `kind 'unknown'`:

```pwsh
"hello world" | Out-File -Encoding ascii C:\Temp\mystery.dat
containerizer probe C:\Temp\mystery.dat
# Error: installer kind 'unknown' is not yet supported: C:\Temp\mystery.dat
```

## Scenario 5 — base-image routing matrix

If you want to feel out the glibc → Ubuntu LTS mapping without finding seven real binaries, the routing table is the source of truth:

| `glibc_min` | Suggested base image |
|---|---|
| `null` (musl, static, or undetected) | `ubuntu:24.04` |
| `< 2.31` (e.g. example-app installers on 2.30) | `ubuntu:20.04` |
| `2.31`–`2.35` | `ubuntu:22.04` |
| `>= 2.36` | `ubuntu:24.04` |

Scenarios 2 and 3 together let you trip all of these. The "fits Ubuntu 22.04 LTS" wording for the 2.35 case is intentional — Ubuntu 22.04 ships glibc 2.35, so a 2.35 binary is satisfied by 22.04 rather than needing 24.04 (issue #3).

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

## Scenario 7 — Analyze a captured trace

After `containerizer trace` produces a trace directory, run the analyzer to derive structured outputs:

```pwsh
PS> containerizer analyze .\example-app-trace\ -o .\example-app-analyze\
wrote example-app-analyze\trace.json and example-app-analyze\policy.json
```

`trace.json` is the normalized view of the raw collector streams (paths classified into image_static / persistent_rw / ephemeral_rw / host_config_ro / device / unknown_rw / unknown_ro, ports aggregated, capabilities deduped, syscalls listed). `policy.json` is the derived input to the M4 generator (volumes, tmpfs, binds_ro, publish_ports, caps_add, seccomp_syscalls, entrypoint). See `docs/specs/2026-06-07-containerizer-m3-analyzer-policy.md` for the full schema.

## Scenario 8 — Generate hardened container artifacts

After `containerizer analyze` produces a `policy.json`, run the generator to emit the container build context and runtime policy:

```pwsh
PS> containerizer generate .\example-app-analyze\policy.json -n example-app -o .\example-app-build\
sentinel entrypoint detected — skipping Containerfile and example-app.container
```

The generator writes `Containerfile`, `<name>.container` (a systemd Quadlet unit), `seccomp.json` (OCI-format syscall allowlist), and `README.md` (audit trail) into `<out-dir>`. When the policy's entrypoint is the sentinel `["__UNSET__"]` (no recognizable daemon was traced), the Containerfile and Quadlet are skipped; the seccomp profile and README still ship so you can diff against future runs. See `docs/specs/2026-06-07-containerizer-m4-generators.md` for the full contract.

## Scenario 9 — Verify the generated policy

After running `containerizer generate` to produce artifacts, rebuild the image, run it briefly, capture a fresh trace, run `containerizer analyze` on that trace, and then diff the new `trace.json` against the original with `verify`:

```pwsh
PS> containerizer verify --original .\example-app-analyze\trace.json --observed .\example-app-rerun-analyze\trace.json -o .\example-app-verify\
verify: 1 new paths, 0 new ports, 0 new caps, 2 new syscalls, 0 new execs
```

The exit code is 0 if the observed trace's runtime events are a subset of the original's, or 1 if any new events appear. `verify.json` lists exactly what was new in each category so you can decide whether to re-run with a longer interaction or to relax the policy. See `docs/specs/2026-06-08-containerizer-m5-verify.md` for the full contract. (Rebuilding + re-tracing the generated container will land in M6's `build` subcommand; for now those steps are manual.)

## Scenario 10 — Synthetic installer end-to-end through `build`

**Goal:** Validate the M6 `build` pipeline against a real Podman machine
without exercising the real example-app installer.

**Prerequisites:** A running Podman machine on Linux/macOS/Windows. At
least 10 GB free in the machine. A small ELF or shell-script installer
that runs in under a few seconds (an idempotent install + a simple
daemon that binds a port). If you don't already have one, the same
synthetic test installer referenced by `tests/integration/trace/` will
do.

**Procedure:**

```pwsh
# 1. Fresh out-dir
Remove-Item -Recurse -Force .\out\synthetic -ErrorAction SilentlyContinue

# 2. Run build with intermediates kept so the trace artifacts are inspectable.
containerizer build .\path\to\synthetic.sh `
    --name synthetic `
    --verify-soak-seconds 15 `
    --keep-intermediates `
    --debug
```

**Expected:**

- `[probe]` line within 1s.
- `[trace]` lines stream as collectors start and the installer runs.
- An interactive prompt: "exercise the software, then press <Enter> here to finalise".
- After Enter: `[analyze]`, `[generate]`, `[build]`, `[verify]` lines.
- Exit 0.
- `out/synthetic/` contains `Containerfile`, `synthetic.container`,
  `seccomp.json`, `README.md`, `verify.json`.
- `out/synthetic/.intermediates/trace/verify/COMPLETE` exists.
- `README.md` has a `## Verify results` section.

**Common failure modes:**

- "podman not found" → check `$env:PATH`; install podman.
- "no podman machine is running" → run `podman machine start`.
- "podman build failed" → inspect `out/synthetic/Containerfile` and the
  build log under `.intermediates/`.
- "generated container failed to come up under strict policy" → the
  verify retrace's `READY_FAILED` marker fired. Look at
  `.intermediates/verify/target.err` and the collector JSONL under
  `.intermediates/trace/verify/` for syscall denials.

## Scenario 11 — example-app installer end-to-end through `build`

**Status (2026-06-10, post-#90):** Mechanically unblocked through the
`loginctl enable-linger` failure point — #90's systemd-PID-1 runner
boots stock systemd cleanly, `systemd-logind` is reachable, the system
DBus bus is up, and the example-app installer launches successfully and
reaches its `Proceed? (y/N):` prompt. example-app then instant-aborts with
`User cancelled operation` before reading user input. Reproduced both
backgrounded and foregrounded inside the orchestrator, so this is a
separate stdin-mode issue inside the example-app installer itself, not a
process-group or job-control problem with the orchestrator. Tracked
as a follow-up to #90; end-to-end Scenario 11 acceptance is gated on
that follow-up landing.

**Goal:** Run the real example application installer end-to-end. Closes the
design §11 open question about classifier rules at real-installer scale.

**Prerequisites:** Same as scenario 10 plus the example-app installer binary
(~875 MB; not committed to the repo). At least 30 GB free in the
podman machine. A web browser to exercise the admin UI during the
trace's interactive smoke phase.

**Procedure:**

```pwsh
containerizer build .\example-app-installer.bin `
    --name example-app `
    --keep-intermediates `
    --verify-soak-seconds 60
```

**Expected:**

- `[trace]` shows the installer running for several minutes (example-app
  installs MongoDB + JVM + the controller).
- Interactive prompt; exercise the admin UI on `https://localhost:8443`
  briefly (load the dashboard, navigate a few pages), then press Enter.
- Build succeeds; `[verify]` produces either "no new events" or a small
  diff. Either is acceptable for v0.1.0.
- `out/example-app/` contains the full final-artifact set.
- The README's `## Verify results` section enumerates any deltas for
  triage; widen `policy.json` by hand and re-run `build` if needed.

**What success looks like for the milestone:** The container starts under
the Quadlet without manual fixup; the admin UI responds; restarting the
unit preserves state via the named volume.

**Common failure modes:**

- Trace volume too large (example-app + MongoDB + JVM can produce hundreds of
  MB of JSONL). If the analyze phase OOMs, set
  `CONTAINERIZER_TRACE_DIR=/scratch` or similar on a larger filesystem.
- Daemon doesn't bind a port within 30s of installer-complete: the
  trace orchestrator's daemon-ready detection times out and the smoke
  test runs in degraded mode. Press Enter sooner and rely on the
  follow-up `verify` pass to validate.
- Classifier produces `unknown_rw` aggregates: these get surfaced in
  README's audit trail. Triage them manually; consider adding rules to
  `src/containerizer/analyze/paths.py` if a pattern emerges.

## Output to a file

Every scenario above can also write the JSON to disk instead of stdout — useful for diffing two probes:

```pwsh
containerizer probe C:\Temp\curl-bookworm.bin -o C:\Temp\curl.probe.json
Get-Content C:\Temp\curl.probe.json
```

## Reading the JSON

Every probe response is a `ProbeResult`:

- `schema_version` — bump signals a breaking change to this output shape (currently `1`).
- `kind` — one of `elf | deb | rpm | appimage | shell | tarball | unknown`.
- `arch` — container-style arch string (`x86_64`, `aarch64`, `riscv64`, …). RISC-V correctly distinguishes `riscv32` vs `riscv64` from the ELF class as of v0.2.1.
- `elf` — present only for `kind: elf`; contains the per-ELF details.
- `base_image` — always present; `image` is the Docker-style tag, `reasons` is an ordered audit trail of why it was chosen.

The model is `frozen=True` end-to-end (`pydantic` v2), so any downstream code that tries to mutate a `ProbeResult` will raise a `ValidationError` rather than silently succeed.

## Common pitfalls

- **"file not found" on the fixture path** — make sure you're at the repo root. The fixture lives at `tests/fixtures/probe/elf-dynamic-x86_64`.
- **`containerizer: command not found`** — your venv isn't activated; either run `.\.venv\Scripts\Activate.ps1` or invoke explicitly with `.\.venv\Scripts\python.exe -m containerizer ...`.
- **`podman` not on PATH** — Podman Desktop installs to `C:\Users\<you>\AppData\Local\Programs\Podman\`; either add that to PATH or use the full path. Confirm with `Get-Command podman`.
- **`podman run` complains "Cannot connect to Podman"** — the Podman machine isn't running. `podman machine start` once per boot, then retry.
- **PowerShell's `>` operator corrupts the captured binary** — `podman run ... cat /usr/bin/X > out.bin` looks reasonable but PowerShell routes `>` through `Out-File`, which treats stdout as text and re-encodes it as UTF-16 LE. The resulting file starts with the BOM (`ff fe`) and every original byte gets a null byte interleaved after it, so the probe sees `kind: 'unknown'` instead of ELF. That's why scenario 2 uses bind-mount + `cp` instead of a redirect. (If you do want a redirect, `cmd /c "podman run ... cat /usr/bin/X > out.bin"` works because `cmd.exe`'s redirect is byte-clean — but the bind-mount form is cleaner.)
- **`UnsupportedInstallerKind` for what looks like an ELF** — confirm the file actually starts with `\x7fELF`. AppImages start with ELF *and* have `AI\x02` near the head; they're detected as `appimage` and currently rejected.

## What's *not* in this manual

- **Trace-and-learn** (running the installer, capturing syscalls/files/network). Not built yet — see the design spec at `docs/specs/2026-06-06-containerizer-design.md` for the M2 plan.
- **`Containerfile` / Quadlet emission.** Same — depends on M2 output.
- **Anything inside a Podman machine.** The probe is pure static analysis; it doesn't need Podman, a sandbox, or root.

If you hit something that doesn't match the manual, the repo's issue tracker is the right place: <https://github.com/SupremeCommanderHedgehog/containerizer/issues>.

## Scenario 12 — Real example-app + locally-supplied mongodb-org-server (`--installer`)

**Goal.** Containerize the real `example-app_sysvinit_all.deb` against a locally-downloaded `mongodb-org-server_8.0.x_amd64.deb`. Validates the `--installer` flow against a non-trivial real package.

**Setup.**

1. Place `example-app_sysvinit_all.deb` (10.4.x sysvinit variant) in the repo root.
2. Download `mongodb-org-server_8.0.7_amd64.deb` (or any 8.0.x build) from `repo.mongodb.org/apt/ubuntu/dists/noble/mongodb-org/8.0/multiverse/binary-amd64/` and place it in the repo root.

**Run.**

```pwsh
PS> containerizer build .\example-app_sysvinit_all.deb `
        --name example-app `
        --installer .\mongodb-org-server_8.0.7_amd64.deb `
        --keep-intermediates --skip-verify
```

**Acceptance.**

- Build exits 0.
- `out/example-app/.intermediates/trace/original/install.log` shows `apt-get install` succeeding for both packages.
- `out/example-app/README.md` includes an `## Install inputs` section listing both debs.
- `out/example-app/seccomp.json` exists. (Containerfile + Quadlet depend on entrypoint detection — may still be SKIPPED if the postinst doesn't expose a daemon under sleep-infinity; document whichever outcome.)

## Scenario 13 — Real example-app via `--apt-source` against `repo.mongodb.org`

**Goal.** Same example-app install but using the upstream MongoDB Inc repo signed with their official key. Validates `--apt-source` + `--apt-key` end-to-end against a real third-party repo.

**Setup.**

1. `example-app_sysvinit_all.deb` in repo root.
2. Download the MongoDB Inc GPG key:
   ```pwsh
   PS> Invoke-WebRequest https://www.mongodb.org/static/pgp/server-8.0.asc `
           -OutFile .\mongodb-server-8.0.asc
   ```

**Run.**

```pwsh
PS> containerizer build .\example-app_sysvinit_all.deb `
        --name example-app `
        --apt-source 'deb [signed-by=/etc/apt/keyrings/mongodb-server-8.0.asc] https://repo.mongodb.org/apt/ubuntu noble/mongodb-org/8.0 multiverse' `
        --apt-key .\mongodb-server-8.0.asc `
        --keep-intermediates --skip-verify
```

**Acceptance.**

- Build exits 0.
- `apt-prep.log` shows the keyring `cp -f` and the sources.list write.
- `install.log` shows apt fetching `mongodb-org-server` from `repo.mongodb.org`.
- README's `## Install inputs` lists the apt-source with `[signed-by=…]` stripped.
