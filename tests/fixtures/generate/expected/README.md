# Containerizer output for synthetic-os

## SKIPPED

`Containerfile` and `synthetic-os.container` were NOT generated because the policy's entrypoint is the sentinel `['__UNSET__']`. The seccomp profile and this README still ship so you can diff future runs.

Relevant warning:

> entrypoint is sentinel ['__UNSET__']; M4 must refuse this policy

## What was generated

- `seccomp.json`
- `README.md` (this file)

## Audit trail

- collector connect: .jsonl present but empty
- collector accept: .jsonl present but empty
- entrypoint is sentinel ['__UNSET__']; M4 must refuse this policy

## Runtime allowlist

- Volumes: 1
  - `app-data` -> `/var/lib/app`
- Tmpfs: 0
- Read-only binds: 1
  - `/etc/resolv.conf`
- Published ports: 1
  - `7777:7777/tcp`
- Added capabilities: 1
  - `CAP_NET_BIND_SERVICE`
- Seccomp syscalls allowed: 2

## Next steps

```sh
# Build the image:
podman build -t synthetic-os:latest .

# Install seccomp profile + Quadlet unit:
mkdir -p ~/.config/containers/seccomp ~/.config/containers/systemd
cp seccomp.json ~/.config/containers/seccomp/synthetic-os.json
cp synthetic-os.container ~/.config/containers/systemd/

# Start under systemd --user:
systemctl --user daemon-reload
systemctl --user start synthetic-os.service
```
