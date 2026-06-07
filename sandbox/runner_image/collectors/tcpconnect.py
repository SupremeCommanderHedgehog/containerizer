#!/usr/bin/env python3
"""tcpconnect.py — emit JSONL for every outbound TCP connect().

Uses the bcc library directly rather than scraping the upstream `tcpconnect`
tool's text output. Stdout is captured by the orchestrator into
/work/trace/connect.jsonl.

Schema (one JSON object per line):
    {ts_ns, pid, comm, saddr, sport, daddr, dport, family}
"""

from __future__ import annotations

import json
import socket
import struct
import sys

from bcc import BPF

BPF_PROGRAM = r"""
#include <net/sock.h>
#include <bcc/proto.h>

struct evt_t {
    u64 ts_ns;
    u32 pid;
    u32 saddr;
    u32 daddr;
    __int128 saddr6;
    __int128 daddr6;
    u16 sport;
    u16 dport;
    u16 family;
    char comm[16];
};
BPF_PERF_OUTPUT(events);

int trace_connect_entry(struct pt_regs *ctx, struct sock *sk) {
    u32 pid = bpf_get_current_pid_tgid() >> 32;
    u16 family = sk->__sk_common.skc_family;

    struct evt_t evt = {};
    evt.ts_ns = bpf_ktime_get_ns();
    evt.pid = pid;
    evt.family = family;
    bpf_get_current_comm(&evt.comm, sizeof(evt.comm));

    if (family == AF_INET) {
        evt.saddr = sk->__sk_common.skc_rcv_saddr;
        evt.daddr = sk->__sk_common.skc_daddr;
    } else if (family == AF_INET6) {
        bpf_probe_read_kernel(&evt.saddr6,
            sizeof(evt.saddr6),
            sk->__sk_common.skc_v6_rcv_saddr.in6_u.u6_addr32);
        bpf_probe_read_kernel(&evt.daddr6,
            sizeof(evt.daddr6),
            sk->__sk_common.skc_v6_daddr.in6_u.u6_addr32);
    }
    evt.sport = sk->__sk_common.skc_num;
    evt.dport = ntohs(sk->__sk_common.skc_dport);
    events.perf_submit(ctx, &evt, sizeof(evt));
    return 0;
}
"""


def main() -> None:
    b = BPF(text=BPF_PROGRAM)
    b.attach_kprobe(event="tcp_v4_connect", fn_name="trace_connect_entry")
    b.attach_kprobe(event="tcp_v6_connect", fn_name="trace_connect_entry")

    def on_event(_cpu: int, data: bytes, _size: int) -> None:
        ev = b["events"].event(data)
        record: dict[str, object] = {
            "ts_ns": int(ev.ts_ns),
            "pid": int(ev.pid),
            "comm": ev.comm.decode("utf-8", "replace").rstrip("\x00"),
            "sport": int(ev.sport),
            "dport": int(ev.dport),
            "family": int(ev.family),
        }
        if ev.family == socket.AF_INET:
            record["saddr"] = socket.inet_ntop(
                socket.AF_INET, struct.pack("I", ev.saddr)
            )
            record["daddr"] = socket.inet_ntop(
                socket.AF_INET, struct.pack("I", ev.daddr)
            )
        elif ev.family == socket.AF_INET6:
            record["saddr"] = socket.inet_ntop(
                socket.AF_INET6, struct.pack("Q" * 2, ev.saddr6 & ((1 << 64) - 1), ev.saddr6 >> 64)
            )
            record["daddr"] = socket.inet_ntop(
                socket.AF_INET6, struct.pack("Q" * 2, ev.daddr6 & ((1 << 64) - 1), ev.daddr6 >> 64)
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
