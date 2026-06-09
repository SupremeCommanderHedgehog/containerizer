# Containerizer output for demo

## What was generated

- `Containerfile`
- `demo.container`
- `seccomp.json`
- `README.md` (this file)

## Audit trail

(no warnings from the analyzer)

## Runtime allowlist

- Volumes: 0
- Tmpfs: 1
  - `/tmp`
- Read-only binds: 0
- Published ports: 1
  - 8443:8443/tcp
- Capabilities added: 1
  - `CAP_NET_BIND_SERVICE`
- Seccomp syscalls allowed: 38

## Next steps

```
cp seccomp.json ~/.config/containers/seccomp/demo.json
podman build -t demo:local .
cp demo.container ~/.config/containers/systemd/
systemctl --user daemon-reload && systemctl --user start demo
```
