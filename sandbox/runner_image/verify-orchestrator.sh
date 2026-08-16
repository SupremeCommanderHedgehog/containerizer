#!/bin/bash
# M6 verify-mode workload. Loads the generated image tarball, runs it
# under strict policy, waits for ready, soaks the observation window,
# stops the container. Writes phase markers consumed by build/pipeline.py.
#
# Invoked by trace-orchestrator.sh when called with --mode verify.
# The outer trace-orchestrator owns collector start/stop; this script
# owns only the verify workload.

set -uo pipefail
# NOTE: -e intentionally NOT set so we can write failure markers and
# continue to collector teardown rather than killing the bash process on
# the first error.

: "${VERIFY_IMAGE_TAG:?required}"
: "${VERIFY_SOAK_SECONDS:?required}"
: "${VERIFY_RUN_FLAGS:?required}"

WORK=/work/trace
VERIFY=/work/verify

mkdir -p "$WORK"

# 1. Load the generated image. The tarball was produced by `podman save`
#    on the host and bind-mounted at /work/verify/image.tar:ro.
if ! podman load < "$VERIFY/image.tar" > "$VERIFY/load.log" 2>&1; then
    touch "$WORK/LOAD_FAILED"
    cat "$VERIFY/load.log" >&2
    exit 1
fi

# 2. Write the phase marker immediately (verify mode has no install phase).
date +%s%N > "$WORK/PHASE_MARKER"

# 3. Run the generated container detached. $VERIFY_RUN_FLAGS is shell-
#    word-split intentionally (caller builds it from policy.runtime).
# shellcheck disable=SC2086
if ! podman run -d --name target $VERIFY_RUN_FLAGS \
        "$VERIFY_IMAGE_TAG" > "$VERIFY/target.cid" 2> "$VERIFY/target.err"; then
    touch "$WORK/READY_FAILED"
    cat "$VERIFY/target.err" >&2
    exit 1
fi

# 4. Wait for ready: any port bound OR "ready" in logs OR 30s timeout.
READY_DEADLINE=$(( $(date +%s) + 30 ))
while [ "$(date +%s)" -lt "$READY_DEADLINE" ]; do
    if podman exec target ss -tlnp 2>/dev/null | grep -q LISTEN; then
        break
    fi
    if podman logs target 2>/dev/null | grep -qi "ready"; then
        break
    fi
    sleep 1
done
if [ "$(date +%s)" -ge "$READY_DEADLINE" ]; then
    touch "$WORK/READY_FAILED"
    podman stop -t 2 target >/dev/null 2>&1 || true
    exit 1
fi

# 5. Soak for the configured observation window.
sleep "$VERIFY_SOAK_SECONDS"

# 6. Detect whether the daemon survived the soak.
if ! podman container exists target; then
    touch "$WORK/RAN_AND_DIED"
else
    podman stop -t 5 target >/dev/null 2>&1 || true
    EXIT_CODE="$(podman inspect target --format '{{.State.ExitCode}}' 2>/dev/null || echo 0)"
    if [ "$EXIT_CODE" -ne 0 ]; then
        touch "$WORK/RAN_AND_DIED"
    fi
fi

touch "$WORK/COMPLETE"
