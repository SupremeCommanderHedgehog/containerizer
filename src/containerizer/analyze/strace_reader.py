"""Parse strace ``-e trace=network`` fallback logs into bpftrace-shaped
event dicts.

The trace-orchestrator spawns ``strace -f -e trace=network -p <pid>`` for
each bpftrace collector that failed to attach (typically on BTF-less
kernels like Microsoft's WSL2 kernel). The output is written to
``<name>.fallback.log``. This module turns that into the same per-event
dict shape that ``bind.jsonl`` / ``tcpconnect.jsonl`` / ``tcpaccept.jsonl``
would have produced, so downstream aggregators don't care which source
the events came from.

Fields not derivable from strace output are filled with placeholders:
  * ``ts_ns`` -- the orchestrator invokes strace without ``-t`` / ``-tt``,
    so timestamps are unavailable. All events get ``ts_ns=0``. Phase
    splitting then puts every fallback event in the "install" bucket
    (before any phase marker), which matches the only mode where the
    fallback runs today.
  * ``comm`` -- strace doesn't include comm. We use ``"?"``. Aggregators
    that key on comm will collapse all fallback events into one bucket;
    acceptable degradation for the fallback path.
  * accept events have ``laddr`` / ``lport`` set to placeholders because
    strace's accept arg is the *peer* (remote) sockaddr, not the listening
    socket. Reconstructing the local side would require correlating with
    the matching bind, which isn't worth the complexity given accept
    events aren't consumed by the analyzer today.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

# Address-family numeric constants used in the emitted dicts to match
# what bpftrace's tracepoint args report.
_AF_UNIX = 1
_AF_INET = 2
_AF_INET6 = 10

# Socket type values from <linux/net.h>; SOCK_STREAM=1, SOCK_DGRAM=2.
# Strace prints these symbolically (SOCK_STREAM|SOCK_CLOEXEC), so we
# match on the symbol rather than masking an integer.
_SOCK_TYPE_TO_PROTO = {
    "SOCK_STREAM": "tcp",
    "SOCK_DGRAM": "udp",
}

# Prefix patterns: strace emits either "[pid N] ..." (default with -f for
# children) or "N<spaces>..." (older builds, or the leading process in
# some configurations) or no prefix at all (without -f).
_PREFIX_BRACKETED = re.compile(r"^\[pid\s+(\d+)\]\s+(.*)$")
_PREFIX_BARE = re.compile(r"^(\d+)\s{2,}(.*)$")

# Match an unfinished marker -- syscall name comes before the first '('.
_UNFINISHED_RE = re.compile(r"^(\w+)\(.*<unfinished\s*\.\.\.>\s*$")

# Match the resumed marker; capture the syscall name and the remainder.
_RESUMED_RE = re.compile(r"^<\.\.\.\s+(\w+)\s+resumed>\s*(.*)$")

# Match a complete syscall line: name(args) = retval (with optional errno suffix)
_SYSCALL_RE = re.compile(r"^(\w+)\((.*)\)\s*=\s*(-?\d+|\?)(?:\s.*)?$")

# sockaddr inner-field extractors. We don't try to parse the full struct;
# we just pull the fields the downstream events need.
_SIN_PORT_RE = re.compile(r"sin6?_port=htons\((\d+)\)")
_SIN_ADDR_RE = re.compile(r'sin_addr=inet_addr\("([^"]+)"\)')
_SIN6_ADDR_RE = re.compile(r'inet_pton\(AF_INET6,\s*"([^"]+)"')
_SUN_PATH_RE = re.compile(r'sun_path="([^"]+)"')


def parse_strace_network_log(path: Path) -> dict[str, list[dict[str, Any]]]:
    """Parse a strace ``-e trace=network -f`` log into per-collector event lists.

    Returns ``{"bind": [...], "connect": [...], "accept": [...]}`` regardless
    of which collector originally requested the fallback -- callers pick the
    list relevant to the missing collector. Missing or empty file returns
    empty lists (not an error).
    """
    bind_events: list[dict[str, Any]] = []
    connect_events: list[dict[str, Any]] = []
    accept_events: list[dict[str, Any]] = []

    # (pid, fd) -> "tcp" | "udp" | "unix". Populated from socket() return,
    # consumed by bind() to set proto. Never garbage-collected on close():
    # we make one pass over a finished file, so the last socket() per fd
    # wins (verified by test_close_does_not_purge_fd_map).
    fd_proto: dict[tuple[int, int], str] = {}

    # Pending unfinished syscalls, keyed (pid, syscall) so that signals or
    # other interleavings between <unfinished> and <... resumed> don't drop
    # the partial. Strace serializes per-tid, so (pid, name) is unique
    # enough in practice.
    pending: dict[tuple[int, str], str] = {}

    if not path.exists():
        return {"bind": bind_events, "connect": connect_events, "accept": accept_events}
    raw_lines = path.read_text(encoding="utf-8", errors="replace").splitlines()

    for raw in raw_lines:
        pid, body = _strip_pid_prefix(raw)
        if not body:
            continue
        # Drop strace's own informational lines, signals, exit notifications.
        if body.startswith("strace:") or body.startswith("---") or body.startswith("+++"):
            continue

        # Resume a pending continuation if we see "<... NAME resumed> ..."
        resumed = _RESUMED_RE.match(body)
        if resumed:
            name = resumed.group(1)
            tail = resumed.group(2)
            head = pending.pop((pid, name), None)
            if head is None:
                # Saw a resumed without a matching unfinished -- strace
                # likely attached mid-syscall. Nothing useful to do.
                continue
            body = head + tail

        # If this line is itself unfinished, stash it for later and move on.
        unfin = _UNFINISHED_RE.match(body)
        if unfin:
            name = unfin.group(1)
            head = body.replace("<unfinished ...>", "").rstrip()
            pending[(pid, name)] = head
            continue

        # socket() return value populates the fd->proto map.
        if body.startswith("socket("):
            _record_socket(body, pid, fd_proto)
            continue

        sysc = _SYSCALL_RE.match(body)
        if not sysc:
            continue
        name = sysc.group(1)
        args = sysc.group(2)
        retval = sysc.group(3)

        if name == "bind":
            ev = _parse_bind(args, pid, fd_proto)
            if ev is not None:
                bind_events.append(ev)
        elif name == "connect":
            ev = _parse_connect(args, pid)
            if ev is not None:
                connect_events.append(ev)
        elif name in ("accept", "accept4"):
            # accept(2) returns the new fd on success; -1 / ? means the
            # peer info in args is uninitialized or meaningless.
            if not retval.lstrip("-").isdigit() or int(retval) < 0:
                continue
            ev = _parse_accept(args, pid)
            if ev is not None:
                accept_events.append(ev)

    return {"bind": bind_events, "connect": connect_events, "accept": accept_events}


def _strip_pid_prefix(line: str) -> tuple[int, str]:
    m = _PREFIX_BRACKETED.match(line)
    if m:
        return int(m.group(1)), m.group(2)
    m = _PREFIX_BARE.match(line)
    if m:
        return int(m.group(1)), m.group(2)
    return 0, line


def _record_socket(body: str, pid: int, fd_proto: dict[tuple[int, int], str]) -> None:
    # "socket(AF_INET, SOCK_STREAM|SOCK_CLOEXEC, IPPROTO_TCP) = 5"
    head, _, retval = body.rpartition("=")
    fd_str = retval.strip().split()[0] if retval.strip() else ""
    if not fd_str.lstrip("-").isdigit():
        return
    fd = int(fd_str)
    if fd < 0:
        return
    # Parse the args between the first '(' and the matching ')'.
    inner = head[head.find("(") + 1 : head.rfind(")")]
    parts = [p.strip() for p in inner.split(",")]
    if len(parts) < 2:
        return
    family = parts[0]
    type_field = parts[1]
    if family == "AF_UNIX":
        proto = "unix"
    else:
        proto = "?"
        for token in type_field.split("|"):
            mapped = _SOCK_TYPE_TO_PROTO.get(token.strip())
            if mapped:
                proto = mapped
                break
    fd_proto[(pid, fd)] = proto


def _parse_bind(
    args: str,
    pid: int,
    fd_proto: dict[tuple[int, int], str],
) -> dict[str, Any] | None:
    # bind(fd, {sa_family=..., ...}, addrlen)
    fd_str, rest = args.split(",", 1)
    fd_str = fd_str.strip()
    if not fd_str.lstrip("-").isdigit():
        return None
    fd = int(fd_str)
    family_token = _extract_family(rest)
    if family_token is None:
        return None

    if family_token == "AF_INET":
        port_m = _SIN_PORT_RE.search(rest)
        addr_m = _SIN_ADDR_RE.search(rest)
        if not port_m or not addr_m:
            return None
        return {
            "ts_ns": 0,
            "pid": pid,
            "comm": "?",
            "family": _AF_INET,
            "addr": addr_m.group(1),
            "port": int(port_m.group(1)),
            "proto": fd_proto.get((pid, fd), "?"),
        }
    if family_token == "AF_INET6":
        port_m = _SIN_PORT_RE.search(rest)
        addr_m = _SIN6_ADDR_RE.search(rest)
        if not port_m or not addr_m:
            return None
        return {
            "ts_ns": 0,
            "pid": pid,
            "comm": "?",
            "family": _AF_INET6,
            "addr": addr_m.group(1),
            "port": int(port_m.group(1)),
            "proto": fd_proto.get((pid, fd), "?"),
        }
    if family_token == "AF_UNIX":
        path_m = _SUN_PATH_RE.search(rest)
        if not path_m:
            return None
        return {
            "ts_ns": 0,
            "pid": pid,
            "comm": "?",
            "family": _AF_UNIX,
            "addr": path_m.group(1),
            "port": 0,
            "proto": "unix",
        }
    return None


def _parse_connect(args: str, pid: int) -> dict[str, Any] | None:
    _, rest = args.split(",", 1)
    family_token = _extract_family(rest)
    if family_token == "AF_INET":
        port_m = _SIN_PORT_RE.search(rest)
        addr_m = _SIN_ADDR_RE.search(rest)
        if not port_m or not addr_m:
            return None
        return {
            "ts_ns": 0,
            "pid": pid,
            "comm": "?",
            "family": _AF_INET,
            "saddr": "0.0.0.0",
            "sport": 0,
            "daddr": addr_m.group(1),
            "dport": int(port_m.group(1)),
        }
    if family_token == "AF_INET6":
        port_m = _SIN_PORT_RE.search(rest)
        addr_m = _SIN6_ADDR_RE.search(rest)
        if not port_m or not addr_m:
            return None
        return {
            "ts_ns": 0,
            "pid": pid,
            "comm": "?",
            "family": _AF_INET6,
            "saddr": "::",
            "sport": 0,
            "daddr": addr_m.group(1),
            "dport": int(port_m.group(1)),
        }
    return None


def _parse_accept(args: str, pid: int) -> dict[str, Any] | None:
    # accept(fd, peer_sockaddr, addrlen[, flags]) -- peer is what strace shows.
    _, rest = args.split(",", 1)
    family_token = _extract_family(rest)
    if family_token == "AF_INET":
        port_m = _SIN_PORT_RE.search(rest)
        addr_m = _SIN_ADDR_RE.search(rest)
        if not port_m or not addr_m:
            return None
        return {
            "ts_ns": 0,
            "pid": pid,
            "comm": "?",
            "family": _AF_INET,
            "laddr": "0.0.0.0",
            "lport": 0,
            "raddr": addr_m.group(1),
            "rport": int(port_m.group(1)),
        }
    if family_token == "AF_INET6":
        port_m = _SIN_PORT_RE.search(rest)
        addr_m = _SIN6_ADDR_RE.search(rest)
        if not port_m or not addr_m:
            return None
        return {
            "ts_ns": 0,
            "pid": pid,
            "comm": "?",
            "family": _AF_INET6,
            "laddr": "::",
            "lport": 0,
            "raddr": addr_m.group(1),
            "rport": int(port_m.group(1)),
        }
    return None


def _extract_family(rest: str) -> str | None:
    m = re.search(r"sa_family=(AF_\w+)", rest)
    return m.group(1) if m else None
