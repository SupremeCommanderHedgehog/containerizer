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
    bpftrace -B none "$script" \
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

# After the 2s attach grace, check whether each collector is still alive.
# A dead collector means probe attach failed (e.g., no BTF, kheaders mismatch).
declare -A fallbacks=()
declare -A domain=(
    [open]="-e trace=file"
    [bind]="-e trace=network"
    [syscalls]="-e trace=all"
    [connect]="-e trace=network"
    [accept]="-e trace=network"
    [capable]="-e trace=%audit"
)

# collector_pids order matches the launch order in the previous block:
# open, bind, syscalls, connect, accept, capable
collector_names=(open bind syscalls connect accept capable)
for idx in "${!collector_names[@]}"; do
    name="${collector_names[$idx]}"
    pid="${collector_pids[$idx]}"
    if ! kill -0 "$pid" 2>/dev/null; then
        reason=$(tail -n 1 "$TRACE_DIR/$name.err" 2>/dev/null || echo "unknown attach failure")
        fallbacks[$name]="$reason"
        echo "trace-orchestrator: $name failed to attach: $reason" >&2
    fi
done

# Persist the fallbacks decision so the host wrapper can surface it.
{
    printf "{"
    first=1
    for k in "${!fallbacks[@]}"; do
        if (( first )); then first=0; else printf ","; fi
        printf '"%s":{"reason":"%s","fallback":"strace %s"}' \
            "$k" "${fallbacks[$k]}" "${domain[$k]}"
    done
    printf "}\n"
} > "$TRACE_DIR/FALLBACKS.json"

echo "trace-orchestrator: running installer $INSTALLER" >&2

# Run installer in the background with stdout+stderr captured via a process-
# substitution fd, so $! is the installer's pid (not tee's).
exec 3> >(tee "$TRACE_DIR/install.log")
"$INSTALLER" >&3 2>&3 &
installer_pid="$!"
exec 3>&-

# Spawn one strace per failed collector, targeting the installer pid. Each
# strace exits when the traced process does.
for name in "${!fallbacks[@]}"; do
    # shellcheck disable=SC2086  # we WANT word splitting on "${domain[$name]}"
    strace -f -o "$TRACE_DIR/$name.fallback.log" ${domain[$name]} -p "$installer_pid" 2>/dev/null &
    collector_pids+=("$!")
done

wait "$installer_pid"
install_rc="$?"
echo "$install_rc" > "$TRACE_DIR/installer.exitcode"

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
