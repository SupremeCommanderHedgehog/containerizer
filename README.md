# containerizer

> Trace-and-learn tool that turns Linux installers into hardened Podman containers.

`containerizer` ingests a Linux software installer, runs it in an instrumented
sandbox, observes what files, ports, capabilities and syscalls the resulting
software actually uses, and emits a deny-by-default `Containerfile` plus a
systemd Quadlet unit whose exceptions are exactly those the trace observed and
nothing more.

**Status:** very early. See
[`docs/superpowers/specs/2026-06-06-containerizer-design.md`](docs/superpowers/specs/2026-06-06-containerizer-design.md)
for the design spec.

## Requirements

- Windows host with a running Podman machine (or any Linux host with Podman)
- Python 3.11+

## Install (development)

```pwsh
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

## Usage

### `containerizer probe`

Statically inspect an installer and print a typed probe JSON document. For
Linux ELF binaries this reports architecture, glibc requirement, dynamic
loader, NEEDED libraries, and a suggested base image:

```pwsh
PS> containerizer probe .\some-installer.bin
```

Sample output:

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
    "glibc_min": "2.35"
  },
  "base_image": {
    "image": "ubuntu:24.04",
    "reasons": [
      "glibc 2.35 requires Ubuntu 22.04+; picked 24.04 LTS",
      "architecture: x86_64"
    ]
  }
}
```

Write the same JSON to a file instead:

```pwsh
PS> containerizer probe .\some-installer.bin -o .\probe.json
```

ELF binaries and `.deb` packages are supported. Other installer kinds
(`.rpm`, AppImage, shell, tarball) are detected but probing them raises a
clear error until later releases add their parsers.

## License

Apache-2.0 — see [LICENSE](LICENSE).
