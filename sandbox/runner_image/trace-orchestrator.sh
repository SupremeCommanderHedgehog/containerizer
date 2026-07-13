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

# M6: optional --mode {install,verify}. Default is install (M2 behavior).
MODE="install"
while [[ $# -gt 0 ]]; do
    case "$1" in
        --mode)
            MODE="${2:?--mode requires an argument}"
            shift 2
            ;;
        --mode=*)
            MODE="${1#--mode=}"
            shift
            ;;
        *)
            break
            ;;
    esac
done
case "$MODE" in
    install|verify) ;;
    *) echo "trace-orchestrator: unknown --mode $MODE" >&2; exit 64 ;;
esac

TRACE_DIR="/work/trace"

if [[ "$MODE" == "install" ]]; then
    INSTALLER="${1:?usage: trace-orchestrator [--mode install] <installer-path>}"
    if [[ ! -r "$INSTALLER" ]]; then
        echo "trace-orchestrator: installer not readable: $INSTALLER" >&2
        exit 2
    fi
fi

mkdir -p "$TRACE_DIR"

# Launch each collector backgrounded. Each writes its own JSONL to TRACE_DIR
# and any errors to TRACE_DIR/<name>.err.
launch_bt() {
    local name="$1"
    local script="$2"
    # -q suppresses bpftrace's "Attaching N probes..." status line, which
    # otherwise lands as a non-JSON line at the head of <name>.jsonl and
    # breaks per-line json.loads parsing downstream.
    bpftrace -q -B none "$script" \
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
launch_bt connect  /opt/containerizer/collectors/tcpconnect.bt
launch_bt accept   /opt/containerizer/collectors/tcpaccept.bt
launch_py capable  /opt/containerizer/collectors/capable.py

# Give collectors time to attach probes before we exec the installer.
# bpftrace attaches in <1s; bcc compiles its BPF program at startup and
# can take 5-10s, so 2s was too short for the bcc collectors. Override
# with CONTAINERIZER_ATTACH_GRACE_SECONDS for interactive runs that want
# a faster turnaround at the cost of some early events.
sleep "${CONTAINERIZER_ATTACH_GRACE_SECONDS:-15}"

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

_detect_kind() {
    # Echo one of: elf, deb, unknown. Reads the first 8 bytes.
    # Note: $(...) strips trailing newlines, which can clip the 8th byte of
    # the deb magic (!<arch>\n). Matching just the "!<arch>" prefix is
    # sufficient -- no ELF or other relevant kind starts with "!".
    local path="$1"
    local head
    head=$(dd if="$path" bs=8 count=1 2>/dev/null)
    if [[ "$head" == $'\x7fELF'* ]]; then
        echo "elf"
        return
    fi
    if [[ "$head" == "!<arch>"* ]]; then
        echo "deb"
        return
    fi
    echo "unknown"
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

run_elf_install() {
    # ---- existing M2 install-mode workload, extracted into a function
    # so Phase 3 can dispatch between ELF and .deb installer kinds.
    echo "trace-orchestrator: running installer $INSTALLER" >&2

    # Decide interactive vs non-interactive. Under systemd-PID-1 (#90) the
    # unit's stdio is wired to /dev/console (a pty) regardless of whether
    # the *user* ran containerizer trace from a terminal or from a CI
    # script -- so the old `[[ -t 1 ]]` TTY probe always reads "TTY" and
    # can't distinguish the two. runner.py sets CONTAINERIZER_INTERACTIVE
    # from the host's actual stdin TTY status, and the env-publisher unit
    # makes it visible to us. Fall back to the TTY probe when the env var
    # is unset (e.g., running the orchestrator outside the systemd path).
    if [[ -n "${CONTAINERIZER_INTERACTIVE:-}" ]]; then
        interactive="${CONTAINERIZER_INTERACTIVE}"
    elif [[ -t 1 ]]; then
        interactive=1
    else
        interactive=0
    fi

    if [[ "$interactive" == 1 ]]; then
        # Interactive run (podman run -it from a real terminal): let
        # installer stdio flow through to the host terminal so
        # isatty(STDOUT_FILENO) is true and so the installer's stdin
        # reads see the user's keystrokes. Interactive installers commonly
        # check both before showing a Y/N prompt.
        #
        # The `<&0` is load-bearing (#95): bash's documented behavior is
        # to auto-redirect the standard input of asynchronous (`&`)
        # commands to /dev/null when job control is off -- which is
        # always the case under a systemd unit's ExecStart. Without an
        # explicit stdin redirect, an interactive Y/N prompt's readline sees
        # EOF immediately and aborts with "User cancelled operation".
        # `<&0` inherits bash's stdin (the /dev/console pty set up by
        # the systemd unit's StandardInput=tty), bypassing the auto
        # /dev/null. Backgrounding stays in place so strace fallbacks
        # can still attach to the installer's PID below.
        "$INSTALLER" <&0 &
        installer_pid="$!"
    else
        # Non-interactive run (CI, integration tests, scripted invocations):
        # tee stdout+stderr to install.log for offline debugging. Process
        # substitution so $! is the installer's pid (not tee's).
        exec 3> >(tee "$TRACE_DIR/install.log")
        "$INSTALLER" >&3 2>&3 &
        installer_pid="$!"
        exec 3>&-
    fi

    # Spawn one strace per failed collector, targeting the installer pid. Each
    # strace exits when the traced process does.
    for name in "${!fallbacks[@]}"; do
        # shellcheck disable=SC2086  # we WANT word splitting on "${domain[$name]}"
        strace -f -o "$TRACE_DIR/$name.fallback.log" ${domain[$name]} -p "$installer_pid" 2>/dev/null &
        collector_pids+=("$!")
    done

    install_rc=0
    wait "$installer_pid" || install_rc=$?
    echo "$install_rc" > "$TRACE_DIR/installer.exitcode"

    if (( install_rc != 0 )); then
        echo "failed" > "$TRACE_DIR/install.status"
        echo "trace-orchestrator: installer exited non-zero ($install_rc); finalising PARTIAL" >&2
        finalize_marker PARTIAL
        exit 0
    fi
    awk '{split($1,a,"."); printf "monotonic_ns: %s%09d\n", a[1], a[2]*10000000}' /proc/uptime \
        > "$TRACE_DIR/PHASE_MARKER"

    if [[ -n "${CONTAINERIZER_START_CMD:-}" ]]; then
        echo "trace-orchestrator: starting daemon(s) via --start-cmd" >&2
        start_rc=0
        bash -c "$CONTAINERIZER_START_CMD" \
            > "$TRACE_DIR/start.log" 2>&1 || start_rc=$?
        echo "$start_rc" > "$TRACE_DIR/start.exitcode"

        deadline=$(( $(date +%s) + ${CONTAINERIZER_START_READY_SECONDS:-60} ))
        ready=0
        while (( $(date +%s) < deadline )); do
            if ss -tlnp 2>/dev/null | grep -q LISTEN; then
                echo "trace-orchestrator: daemon ready (LISTEN observed)" >&2
                ready=1
                break
            fi
            sleep 2
        done
        if (( ready == 0 )); then
            echo "trace-orchestrator: ready-poll timed out after ${CONTAINERIZER_START_READY_SECONDS:-60}s; proceeding" >&2
        fi

        sleep "${CONTAINERIZER_VERIFY_SOAK_SECONDS:-30}"
    fi

    if [[ "$interactive" == 1 ]]; then
        echo "trace-orchestrator: installer complete. exercise the software, then press <Enter> here to finalise (or close stdin)." >&2
        # read returns non-zero on EOF; we treat both Enter and EOF as the COMPLETE path.
        read -r _ || true
    else
        # Non-interactive: finalise immediately. Under systemd-PID-1 the
        # unit's stdin is wired to /dev/console; EOF from podman's stdin
        # does not reliably propagate to the pty slave, so blocking on
        # read here would hang CI runs forever even with `< /dev/null`.
        echo "trace-orchestrator: installer complete (non-interactive); finalising" >&2
    fi
    finalize_marker COMPLETE
    echo "trace-orchestrator: COMPLETE" >&2
}

run_deb_install() {
    # .deb install workload (#99). Runs apt-get install inside a nested
    # ubuntu:24.04 container under --systemd=always so postinst's
    # `systemctl start <unit>` actually works. Collectors observe events
    # on the outer Fedora kernel and see the nested container's syscalls
    # natively. Install-phase activity (pull, apt-get update, dpkg) lands
    # before PHASE_MARKER and the analyzer excludes it from runtime policy.

    # First-run pull of ubuntu:24.04. Cached on subsequent runs.
    podman pull docker.io/library/ubuntu:24.04 > "$TRACE_DIR/deb-pull.log" 2>&1

    # Nested install container: plain sleep-forever ubuntu:24.04.
    # We don't boot systemd here (would need Delegate=yes on the outer
    # containerizer-trace.service plus a working cgroup-v2 delegation
    # chain). Ubuntu's /usr/sbin/policy-rc.d returns 101 in non-systemd
    # containers so postinst's `systemctl start` no-ops cleanly without
    # crashing the install. Trade-off: daemon-shaped packages install
    # but the daemon is NOT running inside the nested container -- the
    # user can't smoke-test a live daemon via `podman exec deb-install
    # <cmd>`. Trace integration (test fixture, CI) doesn't care because
    # PHASE_MARKER finalises immediately on non-interactive runs.
    # NB: nested-mount path ends in .deb. apt-get install determines
    # local-file-vs-package-name purely by extension: with just
    # `/installer` apt treats it as a package name and fails with
    # `E: Unsupported file /installer given on commandline`. The
    # OUTER /installer mount (from the host wrapper) is unchanged.
    # Issue #102: collect extras + keys mounted by the outer runner. The outer
    # TraceRunner argv (trace/runner.py) puts extras at /installer-NN.deb and
    # keys at /work/apt-keys/<basename>. Re-mount into the nested container at
    # the same paths so apt-prep + apt-install can find them. `shopt -s
    # nullglob` is required because each glob expands at this scope: without
    # it, `/installer-??.deb` would expand to itself literally when no extras
    # are present and we'd try to mount a non-existent path.
    extra_mounts=()
    shopt -s nullglob
    for f in /installer-??.deb; do
        extra_mounts+=(-v "$f:$f:ro")
    done
    for f in /work/apt-keys/*; do
        extra_mounts+=(-v "$f:$f:ro")
    done
    # Issue #102: apt-sources are transported via a file written by the host
    # CLI to output_dir/apt-sources.list (visible here at
    # /work/trace/apt-sources.list since output_dir is bind-mounted at
    # /work/trace). Re-mount it into the nested container so apt-prep can read
    # it. Env-var transport truncated multi-source input at the first NUL byte.
    if [ -e /work/trace/apt-sources.list ]; then
        extra_mounts+=(-v "/work/trace/apt-sources.list:/work/trace/apt-sources.list:ro")
    fi

    run_rc=0
    podman run -d --rm --name deb-install \
        --privileged \
        --network=host \
        -v "$INSTALLER:/installer.deb:ro" \
        "${extra_mounts[@]}" \
        docker.io/library/ubuntu:24.04 \
        sleep infinity \
        > "$TRACE_DIR/deb-install.cid" 2> "$TRACE_DIR/deb-install.err" || run_rc=$?

    # Capture state for post-mortem if anything below fails. Always written.
    {
        echo "=== run exit code: $run_rc ==="
        echo "=== podman version ==="
        podman version 2>&1 || true
        echo "=== podman info (driver) ==="
        podman info --format '{{.Store.GraphDriverName}} {{.Host.CgroupVersion}} {{.Host.CgroupManager}}' 2>&1 || true
        echo "=== ps -a ==="
        podman ps -a 2>&1 || true
        echo "=== inspect deb-install ==="
        podman inspect deb-install 2>&1 | head -200 || true
        echo "=== logs deb-install ==="
        podman logs deb-install 2>&1 | head -50 || true
        echo "=== deb-install.cid contents ==="
        cat "$TRACE_DIR/deb-install.cid" 2>&1 || true
        echo "=== deb-install.err contents ==="
        cat "$TRACE_DIR/deb-install.err" 2>&1 || true
    } > "$TRACE_DIR/deb-debug.log" 2>&1
    echo "trace-orchestrator: nested container run rc=$run_rc; debug at $TRACE_DIR/deb-debug.log" >&2

    # Extend the INT/TERM trap so Ctrl-C during install does not leak the
    # nested container. The outer trap (set at line ~107 of this script)
    # already fires finalize_marker PARTIAL; we add `podman stop` in front.
    trap 'podman stop -t 2 deb-install >/dev/null 2>&1 || true; finalize_marker PARTIAL; exit 0' INT TERM

    # Sync apt + install /installer.deb inside the nested container. apt-get
    # runs synchronously (foreground); `apt-get -y` needs no stdin so the
    # #95 `<&0` redirect required for backgrounded interactive installers
    # does not apply.
    #
    # Note: under `set -e`, a non-zero exit from podman exec would abort
    # the script BEFORE we capture $?. Use `|| install_rc=$?` to
    # short-circuit set -e, matching the pattern in run_elf_install
    # (`install_rc=0; wait ... || install_rc=$?`).
    # Issue #102: apt-source + keyring prep. No-op when neither was passed
    # (the for-loop over /work/apt-keys/* hits a missing dir guard, and the
    # apt-sources.list file check is false). Runs BEFORE apt-get update so
    # the new sources are visible to the index refresh.
    podman exec deb-install bash -c '
        set -e
        install -dv /etc/apt/keyrings /etc/apt/sources.list.d
        if [ -d /work/apt-keys ]; then
            for key in /work/apt-keys/*; do
                [ -e "$key" ] || continue
                cp -fv "$key" "/etc/apt/keyrings/$(basename "$key")"
            done
        fi
        if [ -e /work/trace/apt-sources.list ]; then
            cp -fv /work/trace/apt-sources.list /etc/apt/sources.list.d/containerizer.list
        fi
    ' > "$TRACE_DIR/apt-prep.log" 2>&1

    install_rc=0
    podman exec deb-install bash -c '
        shopt -s nullglob
        export DEBIAN_FRONTEND=noninteractive
        apt-get update &&
        apt-get install -y /installer.deb /installer-??.deb
    ' > "$TRACE_DIR/install.log" 2>&1 || install_rc=$?
    echo "$install_rc" > "$TRACE_DIR/installer.exitcode"

    if (( install_rc != 0 )); then
        echo "failed" > "$TRACE_DIR/install.status"
        podman stop -t 5 deb-install >/dev/null 2>&1 || true
        echo "trace-orchestrator: deb install failed (rc=$install_rc); finalising PARTIAL" >&2
        finalize_marker PARTIAL
        exit 0
    fi

    awk '{split($1,a,"."); printf "monotonic_ns: %s%09d\n", a[1], a[2]*10000000}' /proc/uptime \
        > "$TRACE_DIR/PHASE_MARKER"

    if [[ -n "${CONTAINERIZER_START_CMD:-}" ]]; then
        echo "trace-orchestrator: starting daemon(s) via --start-cmd" >&2
        start_rc=0
        podman exec deb-install bash -c "$CONTAINERIZER_START_CMD" \
            > "$TRACE_DIR/start.log" 2>&1 || start_rc=$?
        echo "$start_rc" > "$TRACE_DIR/start.exitcode"

        # Ready-poll: any LISTEN line in the nested container, timeout fallback.
        deadline=$(( $(date +%s) + ${CONTAINERIZER_START_READY_SECONDS:-60} ))
        ready=0
        while (( $(date +%s) < deadline )); do
            if podman exec deb-install ss -tlnp 2>/dev/null | grep -q LISTEN; then
                echo "trace-orchestrator: daemon ready (LISTEN observed)" >&2
                ready=1
                break
            fi
            sleep 2
        done
        if (( ready == 0 )); then
            echo "trace-orchestrator: ready-poll timed out after ${CONTAINERIZER_START_READY_SECONDS:-60}s; proceeding" >&2
        fi

        # Runtime soak: let the daemon do real work before finalize. Reuses
        # CONTAINERIZER_VERIFY_SOAK_SECONDS (governs both install and verify
        # observation windows) -- pipeline resolves to max(60, start_ready_seconds)
        # when --start-cmd is set.
        sleep "${CONTAINERIZER_VERIFY_SOAK_SECONDS:-30}"
    fi

    if [[ -n "${CONTAINERIZER_INTERACTIVE:-}" ]]; then
        interactive="${CONTAINERIZER_INTERACTIVE}"
    elif [[ -t 1 ]]; then
        interactive=1
    else
        interactive=0
    fi

    if [[ "$interactive" == 1 ]]; then
        echo "trace-orchestrator: deb installed. exercise the software (podman exec deb-install <cmd>), then press <Enter> here to finalise." >&2
        read -r _ || true
    else
        echo "trace-orchestrator: deb installed (non-interactive); finalising" >&2
    fi

    podman stop -t 10 deb-install >/dev/null 2>&1 || true
    finalize_marker COMPLETE
    echo "trace-orchestrator: COMPLETE" >&2
}

if [[ "$MODE" == "install" ]]; then
    INSTALLER_KIND="$(_detect_kind "$INSTALLER")"
    echo "trace-orchestrator: installer kind=$INSTALLER_KIND" >&2
    case "$INSTALLER_KIND" in
        deb)
            run_deb_install
            ;;
        elf|*)
            # ELF / shell scripts / .run files / anything else: hand off to
            # run_elf_install, which just exec's the installer. _detect_kind
            # only positively identifies ELF and DEB, but the orchestrator's
            # pre-#99 contract was to run whatever was mounted at /installer
            # regardless of kind. Preserve that fallback so shell-script
            # installers (e.g. fixtures, .run wrappers) keep working.
            run_elf_install
            ;;
    esac
else
    # ---- M6 verify-mode workload ----
    echo "trace-orchestrator: dispatching to verify-orchestrator (mode=verify)" >&2
    /usr/local/bin/verify-orchestrator.sh || true
    # verify-orchestrator wrote its own markers (PHASE_MARKER + a final
    # LOAD_FAILED/READY_FAILED/RAN_AND_DIED/COMPLETE). Stop the collectors so
    # their JSONL is flushed; do NOT write an extra marker.
    if (( ${#collector_pids[@]} > 0 )); then
        for pid in "${collector_pids[@]}"; do
            kill -TERM "$pid" 2>/dev/null || true
        done
        sleep 1
        for pid in "${collector_pids[@]}"; do
            kill -KILL "$pid" 2>/dev/null || true
        done
    fi
    echo "trace-orchestrator: verify mode complete" >&2
fi
