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

# Launch each collector backgrounded. Each writes its own JSONL to TRACE_DIR
# and any errors to TRACE_DIR/<name>.err.
launch_bt() {
    local name="$1"
    local script="$2"
    bpftrace -B none -f json "$script" \
        > "$TRACE_DIR/$name.jsonl" 2> "$TRACE_DIR/$name.err" &
    collector_pids+=("$!")
    echo "trace-orchestrator: launched $name (pid $!)" >&2
}

launch_py() {
    local name="$1"
    local script="$2"
    python3 -u "$script" \
        > "$TRACE_DIR/$name.jsonl" 2> "$TRACE_DIR/$name.err" &
    collector_pids+=("$!")
    echo "trace-orchestrator: launched $name (pid $!)" >&2
}

collector_pids=()
launch_bt open     /opt/containerizer/collectors/open.bt
launch_bt bind     /opt/containerizer/collectors/bind.bt
launch_bt syscalls /opt/containerizer/collectors/syscalls.bt
launch_py connect  /opt/containerizer/collectors/tcpconnect.py
launch_py accept   /opt/containerizer/collectors/tcpaccept.py
launch_py capable  /opt/containerizer/collectors/capable.py

# Give collectors ~2s to attach probes before we exec the installer.
sleep 2

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

trap 'finalize_marker PARTIAL; exit 0' INT TERM

echo "trace-orchestrator: running installer $INSTALLER" >&2

# Capture the installer's exit code (PIPESTATUS[0]) without letting `set -e` /
# `pipefail` abort the orchestrator — we want to finalise PARTIAL on failure,
# not crash out.
set +o pipefail
"$INSTALLER" 2>&1 | tee "$TRACE_DIR/install.log"
install_rc=${PIPESTATUS[0]}
set -o pipefail

if (( install_rc != 0 )); then
    echo "failed" > "$TRACE_DIR/install.status"
    echo "trace-orchestrator: installer exited non-zero ($install_rc); finalising PARTIAL" >&2
    finalize_marker PARTIAL
    exit 0
fi
awk '{split($1,a,"."); printf "monotonic_ns: %s%09d\n", a[1], a[2]*10000000}' /proc/uptime \
    > "$TRACE_DIR/PHASE_MARKER"

echo "trace-orchestrator: installer complete. exercise the software, then press <Enter> here to finalise (or close stdin)." >&2

# read returns non-zero on EOF; we treat both Enter and EOF as the COMPLETE path.
read -r _ || true
finalize_marker COMPLETE
echo "trace-orchestrator: COMPLETE" >&2
