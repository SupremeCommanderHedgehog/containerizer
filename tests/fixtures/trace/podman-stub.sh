#!/usr/bin/env bash
# Recording stub used by tests/unit/test_orchestrator_dispatch.py.
# Echoes its argv (one line per call) to $PODMAN_STUB_LOG and exits 0.
# When the first arg is "run -d" the stub prints a fake CID on stdout
# so the orchestrator's `> "$TRACE_DIR/deb-install.cid"` capture works.
set -euo pipefail
log="${PODMAN_STUB_LOG:-/tmp/podman-stub.log}"
{ printf 'podman'; for a in "$@"; do printf ' %q' "$a"; done; printf '\n'; } >> "$log"

case "${1:-}" in
    pull)
        # pretend to pull
        ;;
    run)
        # `run -d --rm --name ... ubuntu:24.04` -- print a fake CID on stdout.
        echo "stub-cid-$$"
        ;;
    exec)
        # pretend apt-get install succeeded
        ;;
    stop)
        ;;
    *)
        ;;
esac
exit 0
