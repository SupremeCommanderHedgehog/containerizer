#!/usr/bin/env python3
"""tcpaccept.py — emit JSONL for every inbound TCP accept().

Kretprobes inet_csk_accept and reads the returned struct sock for source
and destination address/port. Schema:
    {ts_ns, pid, comm, laddr, lport, raddr, rport, family}
"""

from __future__ import annotations

import json
import socket
import struct
import sys

from bcc import BPF

BPF_PROGRAM = r"""
#include <net/sock.h>

struct evt_t {
    u64 ts_ns;
    u32 pid;
    u16 family;
    u32 laddr;
    u32 raddr;
    __int128 laddr6;
    __int128 raddr6;
    u16 lport;
    u16 rport;
    char comm[16];
};
BPF_PERF_OUTPUT(events);

int trace_accept_ret(struct pt_regs *ctx) {
    struct sock *sk = (struct sock *)PT_REGS_RC(ctx);
    if (sk == NULL) return 0;

    struct evt_t evt = {};
    evt.ts_ns = bpf_ktime_get_ns();
    evt.pid = bpf_get_current_pid_tgid() >> 32;
    evt.family = sk->__sk_common.skc_family;
    bpf_get_current_comm(&evt.comm, sizeof(evt.comm));

    if (evt.family == AF_INET) {
        evt.laddr = sk->__sk_common.skc_rcv_saddr;
        evt.raddr = sk->__sk_common.skc_daddr;
    } else if (evt.family == AF_INET6) {
        bpf_probe_read_kernel(&evt.laddr6, sizeof(evt.laddr6),
            sk->__sk_common.skc_v6_rcv_saddr.in6_u.u6_addr32);
        bpf_probe_read_kernel(&evt.raddr6, sizeof(evt.raddr6),
            sk->__sk_common.skc_v6_daddr.in6_u.u6_addr32);
    }
    evt.lport = sk->__sk_common.skc_num;
    evt.rport = ntohs(sk->__sk_common.skc_dport);
    events.perf_submit(ctx, &evt, sizeof(evt));
    return 0;
}
"""


def main() -> None:
    b = BPF(text=BPF_PROGRAM)
    b.attach_kretprobe(event="inet_csk_accept", fn_name="trace_accept_ret")

    def on_event(_cpu: int, data: bytes, _size: int) -> None:
        ev = b["events"].event(data)
        record: dict[str, object] = {
            "ts_ns": int(ev.ts_ns),
            "pid": int(ev.pid),
            "comm": ev.comm.decode("utf-8", "replace").rstrip("\x00"),
            "lport": int(ev.lport),
            "rport": int(ev.rport),
            "family": int(ev.family),
        }
        if ev.family == socket.AF_INET:
            record["laddr"] = socket.inet_ntop(socket.AF_INET, struct.pack("I", ev.laddr))
            record["raddr"] = socket.inet_ntop(socket.AF_INET, struct.pack("I", ev.raddr))
        elif ev.family == socket.AF_INET6:
            record["laddr"] = socket.inet_ntop(
                socket.AF_INET6, struct.pack("Q" * 2, ev.laddr6 & ((1 << 64) - 1), ev.laddr6 >> 64)
            )
            record["raddr"] = socket.inet_ntop(
                socket.AF_INET6, struct.pack("Q" * 2, ev.raddr6 & ((1 << 64) - 1), ev.raddr6 >> 64)
            )
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
