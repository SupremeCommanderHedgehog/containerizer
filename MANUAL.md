# Manual: Try out `containerizer`

Step-by-step instructions for setting up the project and exercising every code path it currently has. Assumes a Windows host (PowerShell), but everything except where noted works the same on Linux/macOS shells too.

## What you can test today

As of v0.2.1 the only user-facing command is `containerizer probe`. It statically inspects a Linux installer file and emits a typed JSON probe describing what it found. Concretely:

- **ELF binaries** are fully probed — architecture, bit width, endianness, dynamic loader, NEEDED libraries, minimum glibc requirement, and a suggested Ubuntu LTS base image.
- **`.deb`, `.rpm`, AppImage, shell scripts, tarballs** are *detected* (magic-byte sniff) but probing them raises a clear "not yet supported" error. The detection paths are what you can exercise here.
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
podman run --rm debian:bookworm-slim cat /usr/bin/curl > C:\Temp\curl-bookworm.bin
containerizer probe C:\Temp\curl-bookworm.bin
```

`needed_libs` should be long (libc, libssl, libcrypto, libz, …) and `glibc_min` should be `2.34` or higher. The suggested base image should be `ubuntu:22.04` (glibc 2.31–2.35 routes there since v0.2.1).

Other useful targets to try:

| Image | Binary | What it tests |
|---|---|---|
| `ubuntu:20.04` | `/usr/bin/ls` | glibc 2.31 → `ubuntu:22.04` |
| `ubuntu:24.04` | `/usr/bin/python3` | glibc 2.39 → `ubuntu:24.04` (glibc > 2.35) |
| `alpine:latest` | `/bin/busybox` | musl-linked, expect `interpreter` ending in `ld-musl-*.so.1` and `glibc_min: null` |
| `arm64v8/debian:bookworm-slim` (with `--platform linux/arm64`) | `/usr/bin/true` | `arch: aarch64`, `bit: 64` |

The musl case is interesting: it should detect as ELF, find no `.gnu.version_r` glibc entries, and report `glibc_min: null`. The base-image picker then falls back to `ubuntu:24.04` with the reason `no glibc requirement detected; picked ubuntu:24.04`.

## Scenario 3 — exercise the non-ELF detection paths

The CLI rejects non-ELF kinds with a clear error, but you can confirm the *detection* logic works by writing minimal magic-byte fixtures and probing them.

In PowerShell:

```pwsh
# .deb (ar archive)
[System.IO.File]::WriteAllBytes(
  "C:\Temp\fake.deb",
  [byte[]](0x21,0x3c,0x61,0x72,0x63,0x68,0x3e,0x0a) + (,0 * 32))
containerizer probe C:\Temp\fake.deb

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
Error: installer kind 'deb' is not yet supported: C:\Temp\fake.deb
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
| `< 2.31` (e.g. UniFi installers on 2.30) | `ubuntu:20.04` |
| `2.31`–`2.35` | `ubuntu:22.04` |
| `>= 2.36` | `ubuntu:24.04` |

Scenarios 2 and 3 together let you trip all of these. The "fits Ubuntu 22.04 LTS" wording for the 2.35 case is intentional — Ubuntu 22.04 ships glibc 2.35, so a 2.35 binary is satisfied by 22.04 rather than needing 24.04 (issue #3).

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
- **The `cat`-out-of-image trick produces an empty file** — your shell ate the redirect. Use PowerShell as shown, not `cmd.exe`.
- **`UnsupportedInstallerKind` for what looks like an ELF** — confirm the file actually starts with `\x7fELF`. AppImages start with ELF *and* have `AI\x02` near the head; they're detected as `appimage` and currently rejected.

## What's *not* in this manual

- **Trace-and-learn** (running the installer, capturing syscalls/files/network). Not built yet — see the design spec at `docs/superpowers/specs/2026-06-06-containerizer-design.md` for the M2 plan.
- **`Containerfile` / Quadlet emission.** Same — depends on M2 output.
- **Anything inside a Podman machine.** The probe is pure static analysis; it doesn't need Podman, a sandbox, or root.

If you hit something that doesn't match the manual, the repo's issue tracker is the right place: <https://github.com/SupremeCommanderHedgehog/containerizer/issues>.
