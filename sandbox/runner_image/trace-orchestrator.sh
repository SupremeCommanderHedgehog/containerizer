#!/usr/bin/env bash
# trace-orchestrator: launches collectors, runs the installer, prompts for a
# user-driven smoke test, and finalises the trace. Runs inside the sandbox
# runner image; expects the installer mounted at /installer and the output
# directory at /work/trace.
#
# Exit codes:
#   0  COMPLETE or PARTIAL marker written (PARTIAL still counts as "ran")
#   2  Installer was missing or the host wrapper passed garbage
#
# Lifecycle:
#   1. Launch each collector backgrounded (added in task 10)
#   2. Exec the installer; tee stdout+stderr to install.log
#   3. Write PHASE_MARKER with the monotonic install-finish timestamp
#   4. Read a single line from stdin
#        - on Enter -> finalise COMPLETE
#        - on EOF   -> finalise COMPLETE (lets the integration test drive)
#   5. On SIGINT   -> finalise PARTIAL
set -euo pipefail

INSTALLER="${1:?usage: trace-orchestrator <installer-path>}"
TRACE_DIR="/work/trace"

if [[ ! -r "$INSTALLER" ]]; then
    echo "trace-orchestrator: installer not readable: $INSTALLER" >&2
    exit 2
fi

mkdir -p "$TRACE_DIR"

# Collector wiring lands in task 10. For now collector_pids is empty so the
# finalize path runs cleanly even without any collectors attached.
collector_pids=()

finalize_marker() {
    local marker="$1"  # COMPLETE or PARTIAL
    if (( ${#collector_pids[@]} > 0 )); then
        for pid in "${collector_pids[@]}"; do
            kill -TERM "$pid" 2>/dev/null || true
        done
        sleep 1
        for pid in "${collector_pids[@]}"; do
            kill -KILL "$pid" 2>/dev/null || true
        done
    fi
    : > "$TRACE_DIR/$marker"
}

trap 'finalize_marker PARTIAL; exit 0' INT

echo "trace-orchestrator: running installer $INSTALLER" >&2
"$INSTALLER" 2>&1 | tee "$TRACE_DIR/install.log" || true
echo "monotonic_ns: $(awk 'BEGIN{getline t < "/proc/uptime"; split(t,a,"."); printf "%s%s\n", a[1], a[2]}')" \
    > "$TRACE_DIR/PHASE_MARKER"

echo "trace-orchestrator: installer complete. exercise the software, then press <Enter> here to finalise (or close stdin)." >&2

# read returns non-zero on EOF; we treat both Enter and EOF as the COMPLETE path.
read -r _ || true
finalize_marker COMPLETE
echo "trace-orchestrator: COMPLETE" >&2
