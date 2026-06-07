#!/usr/bin/env python3
"""capable.py — emit JSONL for every cap_capable() check.

Kprobes cap_capable. Schema:
    {ts_ns, pid, comm, cap, audit, ret}

`cap` is the Linux capability NAME (CAP_NET_BIND_SERVICE etc.), not the
integer id, because the M3 Quadlet generator emits names. Mapping table
is bundled at module-load time and tracks include/uapi/linux/capability.h
as of Linux 6.10.
"""

from __future__ import annotations

import json
import sys

from bcc import BPF

# Linux capability id -> name. Sourced from include/uapi/linux/capability.h.
CAP_NAMES = {
    0: "CAP_CHOWN",
    1: "CAP_DAC_OVERRIDE",
    2: "CAP_DAC_READ_SEARCH",
    3: "CAP_FOWNER",
    4: "CAP_FSETID",
    5: "CAP_KILL",
    6: "CAP_SETGID",
    7: "CAP_SETUID",
    8: "CAP_SETPCAP",
    9: "CAP_LINUX_IMMUTABLE",
    10: "CAP_NET_BIND_SERVICE",
    11: "CAP_NET_BROADCAST",
    12: "CAP_NET_ADMIN",
    13: "CAP_NET_RAW",
    14: "CAP_IPC_LOCK",
    15: "CAP_IPC_OWNER",
    16: "CAP_SYS_MODULE",
    17: "CAP_SYS_RAWIO",
    18: "CAP_SYS_CHROOT",
    19: "CAP_SYS_PTRACE",
    20: "CAP_SYS_PACCT",
    21: "CAP_SYS_ADMIN",
    22: "CAP_SYS_BOOT",
    23: "CAP_SYS_NICE",
    24: "CAP_SYS_RESOURCE",
    25: "CAP_SYS_TIME",
    26: "CAP_SYS_TTY_CONFIG",
    27: "CAP_MKNOD",
    28: "CAP_LEASE",
    29: "CAP_AUDIT_WRITE",
    30: "CAP_AUDIT_CONTROL",
    31: "CAP_SETFCAP",
    32: "CAP_MAC_OVERRIDE",
    33: "CAP_MAC_ADMIN",
    34: "CAP_SYSLOG",
    35: "CAP_WAKE_ALARM",
    36: "CAP_BLOCK_SUSPEND",
    37: "CAP_AUDIT_READ",
    38: "CAP_PERFMON",
    39: "CAP_BPF",
    40: "CAP_CHECKPOINT_RESTORE",
}

BPF_PROGRAM = r"""
#include <linux/sched.h>
struct evt_t {
    u64 ts_ns;
    u32 pid;
    int cap;
    int audit;
    int ret;
    char comm[16];
};
BPF_PERF_OUTPUT(events);

int trace_capable(struct pt_regs *ctx,
                  const struct cred *cred,
                  struct user_namespace *targ_ns,
                  int cap,
                  int audit)
{
    struct evt_t evt = {};
    evt.ts_ns = bpf_ktime_get_ns();
    evt.pid = bpf_get_current_pid_tgid() >> 32;
    evt.cap = cap;
    evt.audit = audit;
    evt.ret = 0;  // entry probe; ret captured by exit handler if added
    bpf_get_current_comm(&evt.comm, sizeof(evt.comm));
    events.perf_submit(ctx, &evt, sizeof(evt));
    return 0;
}
"""


def main() -> None:
    b = BPF(text=BPF_PROGRAM)
    b.attach_kprobe(event="cap_capable", fn_name="trace_capable")

    def on_event(_cpu: int, data: bytes, _size: int) -> None:
        ev = b["events"].event(data)
        record = {
            "ts_ns": int(ev.ts_ns),
            "pid": int(ev.pid),
            "comm": ev.comm.decode("utf-8", "replace").rstrip("\x00"),
            "cap": CAP_NAMES.get(int(ev.cap), f"CAP_UNKNOWN_{int(ev.cap)}"),
            "audit": int(ev.audit),
            "ret": int(ev.ret),
        }
        sys.stdout.write(json.dumps(record) + "\n")
        sys.stdout.flush()

    b["events"].open_perf_buffer(on_event)
    while True:
        try:
            b.perf_buffer_poll(timeout=1000)
        except KeyboardInterrupt:
            return


if __name__ == "__main__":
    main()
