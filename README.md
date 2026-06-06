# containerizer

> Trace-and-learn tool that turns Linux installers into hardened Podman containers.

`containerizer` ingests a Linux software installer, runs it in an instrumented
sandbox, observes what files, ports, capabilities and syscalls the resulting
software actually uses, and emits a deny-by-default `Containerfile` plus a
systemd Quadlet unit whose exceptions are exactly those the trace observed and
nothing more.

**Status:** very early. See
[`docs/specs/2026-06-06-containerizer-design.md`](docs/specs/2026-06-06-containerizer-design.md)
for the design spec.

## Requirements

- Windows host with a running Podman machine (or any Linux host with Podman)
- Python 3.11+

## Install (development)

```pwsh
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

## License

Apache-2.0 — see [LICENSE](LICENSE).
