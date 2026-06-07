"""bind.jsonl events -> TracePort list (one per (port, proto, comm))."""

from __future__ import annotations

from collections.abc import Iterable

from containerizer.analyze.schema import TracePort

# Address-family constants from <sys/socket.h>.
AF_INET = 2
AF_INET6 = 10


def aggregate_ports(events: Iterable[dict[str, object]]) -> list[TracePort]:
    """Dedup bind events on (port, proto, comm). ipv4/ipv6 OR across families."""
    buckets: dict[tuple[int, str, str], list[bool]] = {}
    for e in events:
        port_raw = e.get("port", 0) or 0
        port = int(port_raw) if isinstance(port_raw, (int, str)) else 0
        proto = str(e.get("proto", "?"))
        comm = str(e.get("comm", "?"))
        family_raw = e.get("family", 0) or 0
        family = int(family_raw) if isinstance(family_raw, (int, str)) else 0
        key = (port, proto, comm)
        v4_v6 = buckets.setdefault(key, [False, False])
        if family == AF_INET:
            v4_v6[0] = True
        elif family == AF_INET6:
            v4_v6[1] = True
    out: list[TracePort] = []
    for (port, proto, comm), (v4, v6) in buckets.items():
        if proto not in ("tcp", "udp", "unix", "?"):
            continue
        out.append(
            TracePort(
                port=port,
                proto=proto,  # type: ignore[arg-type]
                by=comm,
                ipv4=v4,
                ipv6=v6,
            )
        )
    out.sort(key=lambda p: (p.proto, p.port, p.by))
    return out
