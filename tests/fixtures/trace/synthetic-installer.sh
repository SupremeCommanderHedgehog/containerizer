#!/bin/sh
# synthetic-installer.sh — deterministic exercise for every collector.
#
# Targets one event per collector minimum:
#   open       — cat /etc/passwd
#   bind/accept — backgrounded nc listener + foreground nc connector
#   connect    — python3 socket().connect((127.0.0.1, 1))  (refused; counts)
#   syscalls   — anything; reads always emit several
#   capable    — chown of a non-existent owner triggers a CAP_CHOWN check
#
# Total runtime is <1 second; the orchestrator's EOF-on-stdin finalises COMPLETE.
set -eu

echo "synthetic-installer: starting"

cat /etc/passwd > /dev/null

python3 - <<'PY'
import socket
try:
    s = socket.socket()
    s.connect(("127.0.0.1", 1))
except OSError:
    pass
PY

python3 - <<'PY'
import socket
s = socket.socket()
s.bind(("127.0.0.1", 0))
s.listen(1)
print("bound on", s.getsockname())
PY

nc -l 127.0.0.1 23456 >/dev/null 2>&1 &
listener_pid=$!
sleep 0.2
echo hi | nc -w 1 127.0.0.1 23456 >/dev/null 2>&1 || true
wait "$listener_pid" 2>/dev/null || true

# Capability check — chown to a non-existent UID triggers cap_capable for CAP_CHOWN
chown 99999:99999 /tmp/synthetic-installer.$$ 2>/dev/null || true

cat /proc/self/status > /dev/null

echo "synthetic-installer: done"
