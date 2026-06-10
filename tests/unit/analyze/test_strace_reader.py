"""Tests for analyze.strace_reader -- parses strace -e trace=network output
into the bpftrace JSON-event shape produced by bind.bt / tcpconnect.bt /
tcpaccept.bt, so the analyzer can consume fallback logs from BTF-less hosts."""

from __future__ import annotations

from pathlib import Path

from containerizer.analyze.strace_reader import parse_strace_network_log


def _write(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "fallback.log"
    p.write_text(body, encoding="utf-8")
    return p


def _socket(pid: int, family: str, sock_type: str, proto: str, fd: int) -> str:
    return f"[pid {pid}] socket({family}, {sock_type}, {proto}) = {fd}\n"


def _bind_inet(pid: int, fd: int, port: int, addr: str = "0.0.0.0") -> str:
    sockaddr = f'{{sa_family=AF_INET, sin_port=htons({port}), sin_addr=inet_addr("{addr}")}}'
    return f"[pid {pid}] bind({fd}, {sockaddr}, 16) = 0\n"


def _bind_inet6(pid: int, fd: int, port: int, addr: str = "::1") -> str:
    sockaddr = (
        f"{{sa_family=AF_INET6, sin6_port=htons({port}), sin6_flowinfo=htonl(0), "
        f'inet_pton(AF_INET6, "{addr}", &sin6_addr), sin6_scope_id=0}}'
    )
    return f"[pid {pid}] bind({fd}, {sockaddr}, 28) = 0\n"


def _bind_unix(pid: int, fd: int, path: str) -> str:
    return f'[pid {pid}] bind({fd}, {{sa_family=AF_UNIX, sun_path="{path}"}}, 110) = 0\n'


def _connect_inet(pid: int, fd: int, port: int, addr: str) -> str:
    sockaddr = f'{{sa_family=AF_INET, sin_port=htons({port}), sin_addr=inet_addr("{addr}")}}'
    return f"[pid {pid}] connect({fd}, {sockaddr}, 16) = 0\n"


def _connect_inet6(pid: int, fd: int, port: int, addr: str) -> str:
    sockaddr = (
        f"{{sa_family=AF_INET6, sin6_port=htons({port}), sin6_flowinfo=htonl(0), "
        f'inet_pton(AF_INET6, "{addr}", &sin6_addr), sin6_scope_id=0}}'
    )
    return f"[pid {pid}] connect({fd}, {sockaddr}, 28) = 0\n"


def _accept4_inet(pid: int, fd: int, port: int, addr: str, new_fd: int) -> str:
    sockaddr = f'{{sa_family=AF_INET, sin_port=htons({port}), sin_addr=inet_addr("{addr}")}}'
    return f"[pid {pid}] accept4({fd}, {sockaddr}, [16], SOCK_CLOEXEC) = {new_fd}\n"


def test_empty_log_returns_empty_lists(tmp_path: Path) -> None:
    out = parse_strace_network_log(_write(tmp_path, ""))
    assert out == {"bind": [], "connect": [], "accept": []}


def test_socket_then_bind_ipv4_tcp_infers_proto(tmp_path: Path) -> None:
    """socket(AF_INET, SOCK_STREAM, ...) returns fd; subsequent bind() on
    that fd is tcp. Proto inference is the whole point of tracking socket()."""
    log = _write(
        tmp_path,
        _socket(12345, "AF_INET", "SOCK_STREAM", "IPPROTO_TCP", 5) + _bind_inet(12345, 5, 8080),
    )
    out = parse_strace_network_log(log)
    assert len(out["bind"]) == 1
    ev = out["bind"][0]
    assert ev["pid"] == 12345
    assert ev["family"] == 2  # AF_INET
    assert ev["addr"] == "0.0.0.0"
    assert ev["port"] == 8080
    assert ev["proto"] == "tcp"


def test_socket_with_flags_or_d_in_type(tmp_path: Path) -> None:
    """socket() type field often has SOCK_CLOEXEC|SOCK_NONBLOCK OR'd in;
    proto inference must mask flags and match SOCK_STREAM / SOCK_DGRAM only."""
    log = _write(
        tmp_path,
        _socket(7, "AF_INET", "SOCK_DGRAM|SOCK_CLOEXEC|SOCK_NONBLOCK", "IPPROTO_UDP", 9)
        + _bind_inet(7, 9, 53, "127.0.0.1"),
    )
    out = parse_strace_network_log(log)
    assert out["bind"][0]["proto"] == "udp"
    assert out["bind"][0]["port"] == 53


def test_bind_without_prior_socket_is_unknown_proto(tmp_path: Path) -> None:
    """If strace attaches after the socket() syscall, we have no fd->proto
    mapping; the bind event still emits with proto='?' so the port is at
    least visible to the aggregator."""
    log = _write(tmp_path, _bind_inet(99, 5, 443))
    out = parse_strace_network_log(log)
    assert out["bind"][0]["proto"] == "?"


def test_bind_ipv6(tmp_path: Path) -> None:
    log = _write(
        tmp_path,
        _socket(1, "AF_INET6", "SOCK_STREAM", "IPPROTO_TCP", 5) + _bind_inet6(1, 5, 8443, "::1"),
    )
    out = parse_strace_network_log(log)
    ev = out["bind"][0]
    assert ev["family"] == 10  # AF_INET6
    assert ev["addr"] == "::1"
    assert ev["port"] == 8443
    assert ev["proto"] == "tcp"


def test_bind_af_unix(tmp_path: Path) -> None:
    log = _write(
        tmp_path,
        _socket(1, "AF_UNIX", "SOCK_STREAM", "0", 5) + _bind_unix(1, 5, "/run/uos/uosserver.sock"),
    )
    out = parse_strace_network_log(log)
    ev = out["bind"][0]
    assert ev["family"] == 1  # AF_UNIX
    assert ev["addr"] == "/run/uos/uosserver.sock"
    assert ev["port"] == 0
    assert ev["proto"] == "unix"


def test_connect_ipv4(tmp_path: Path) -> None:
    log = _write(tmp_path, _connect_inet(1, 6, 443, "1.2.3.4"))
    out = parse_strace_network_log(log)
    assert len(out["connect"]) == 1
    ev = out["connect"][0]
    assert ev["family"] == 2
    assert ev["daddr"] == "1.2.3.4"
    assert ev["dport"] == 443


def test_connect_ipv6(tmp_path: Path) -> None:
    log = _write(tmp_path, _connect_inet6(1, 6, 443, "2607:f8b0:4005:80a::200e"))
    out = parse_strace_network_log(log)
    ev = out["connect"][0]
    assert ev["family"] == 10
    assert ev["daddr"] == "2607:f8b0:4005:80a::200e"
    assert ev["dport"] == 443


def test_accept4_ipv4(tmp_path: Path) -> None:
    """accept and accept4 are both captured; the peer (raddr/rport) is what
    strace shows in the sockaddr arg."""
    log = _write(tmp_path, _accept4_inet(1, 5, 54321, "192.168.1.10", 6))
    out = parse_strace_network_log(log)
    assert len(out["accept"]) == 1
    ev = out["accept"][0]
    assert ev["family"] == 2
    assert ev["raddr"] == "192.168.1.10"
    assert ev["rport"] == 54321


def test_accept_returning_negative_is_skipped(tmp_path: Path) -> None:
    """accept that returned -1 (EAGAIN etc.) carries no useful peer info."""
    err = "-1 EAGAIN (Resource temporarily unavailable)"
    log = _write(
        tmp_path,
        f"[pid 1] accept4(5, NULL, NULL, SOCK_CLOEXEC) = {err}\n",
    )
    out = parse_strace_network_log(log)
    assert out["accept"] == []


def test_bare_pid_prefix_format(tmp_path: Path) -> None:
    """Some strace builds emit 'PID  <syscall>' instead of '[pid PID] <syscall>'."""
    bind_sa = '{sa_family=AF_INET, sin_port=htons(22), sin_addr=inet_addr("0.0.0.0")}'
    log = _write(
        tmp_path,
        f"55  socket(AF_INET, SOCK_STREAM, IPPROTO_TCP) = 3\n55  bind(3, {bind_sa}, 16) = 0\n",
    )
    out = parse_strace_network_log(log)
    assert out["bind"][0]["pid"] == 55
    assert out["bind"][0]["port"] == 22


def test_no_pid_prefix_format(tmp_path: Path) -> None:
    """Without -f strace omits the PID prefix entirely; pid defaults to 0."""
    bind_sa = '{sa_family=AF_INET, sin_port=htons(22), sin_addr=inet_addr("0.0.0.0")}'
    log = _write(
        tmp_path,
        f"socket(AF_INET, SOCK_STREAM, IPPROTO_TCP) = 3\nbind(3, {bind_sa}, 16) = 0\n",
    )
    out = parse_strace_network_log(log)
    assert out["bind"][0]["pid"] == 0
    assert out["bind"][0]["port"] == 22


def test_strace_status_lines_skipped(tmp_path: Path) -> None:
    log = _write(
        tmp_path,
        "strace: Process 12345 attached\n"
        + _socket(12345, "AF_INET", "SOCK_STREAM", "IPPROTO_TCP", 5)
        + _bind_inet(12345, 5, 80)
        + "strace: Process 12345 detached\n",
    )
    out = parse_strace_network_log(log)
    assert len(out["bind"]) == 1


def test_signal_lines_skipped(tmp_path: Path) -> None:
    log = _write(
        tmp_path,
        _socket(1, "AF_INET", "SOCK_STREAM", "IPPROTO_TCP", 5)
        + "[pid 1] --- SIGCHLD {si_signo=SIGCHLD, si_code=CLD_EXITED, si_pid=2} ---\n"
        + _bind_inet(1, 5, 80)
        + "[pid 1] +++ exited with 0 +++\n",
    )
    out = parse_strace_network_log(log)
    assert len(out["bind"]) == 1


def test_unfinished_resumed_reassembly(tmp_path: Path) -> None:
    """bind() interrupted at syscall entry; resumed on a later line.
    The two lines must be reassembled into a single parseable event."""
    sockaddr = '{sa_family=AF_INET, sin_port=htons(8080), sin_addr=inet_addr("0.0.0.0")}'
    log = _write(
        tmp_path,
        _socket(1, "AF_INET", "SOCK_STREAM", "IPPROTO_TCP", 5)
        + f"[pid 1] bind(5, {sockaddr}, 16 <unfinished ...>\n"
        + "[pid 1] <... bind resumed>) = 0\n",
    )
    out = parse_strace_network_log(log)
    assert len(out["bind"]) == 1
    assert out["bind"][0]["port"] == 8080
    assert out["bind"][0]["proto"] == "tcp"


def test_unfinished_resumed_with_signal_between(tmp_path: Path) -> None:
    """Signal lines arriving between <unfinished> and <... resumed> must not
    discard the pending continuation."""
    sockaddr = '{sa_family=AF_INET, sin_port=htons(443), sin_addr=inet_addr("1.2.3.4")}'
    log = _write(
        tmp_path,
        _socket(1, "AF_INET", "SOCK_STREAM", "IPPROTO_TCP", 5)
        + f"[pid 1] connect(5, {sockaddr}, 16 <unfinished ...>\n"
        + "[pid 1] --- SIGCHLD {si_signo=SIGCHLD} ---\n"
        + "[pid 1] <... connect resumed>) = 0\n",
    )
    out = parse_strace_network_log(log)
    assert len(out["connect"]) == 1
    assert out["connect"][0]["dport"] == 443


def test_truncated_last_line_dropped(tmp_path: Path) -> None:
    """A SIGKILL during write leaves a trailing line with no '= retval' --
    skip it silently rather than raise."""
    log = _write(
        tmp_path,
        _socket(1, "AF_INET", "SOCK_STREAM", "IPPROTO_TCP", 5)
        + '[pid 1] bind(5, {sa_family=AF_INET, sin_port=htons(80), sin_addr=inet_addr("0.0',
    )
    out = parse_strace_network_log(log)
    assert out["bind"] == []


def test_close_does_not_purge_fd_map(tmp_path: Path) -> None:
    """We deliberately don't track close() -- the parser runs once at end of
    trace and doesn't need to free entries. Verifies subsequent socket() on
    the same fd value overrides the previous mapping (last-wins per pid+fd)."""
    log = _write(
        tmp_path,
        _socket(1, "AF_INET", "SOCK_STREAM", "IPPROTO_TCP", 5)
        + "[pid 1] close(5) = 0\n"
        + _socket(1, "AF_INET", "SOCK_DGRAM", "IPPROTO_UDP", 5)
        + _bind_inet(1, 5, 53),
    )
    out = parse_strace_network_log(log)
    assert out["bind"][0]["proto"] == "udp"


def test_per_pid_fd_isolation(tmp_path: Path) -> None:
    """fd 5 in pid A and fd 5 in pid B are different sockets; proto map must
    be keyed on (pid, fd) not fd alone."""
    log = _write(
        tmp_path,
        _socket(100, "AF_INET", "SOCK_STREAM", "IPPROTO_TCP", 5)
        + _socket(200, "AF_INET", "SOCK_DGRAM", "IPPROTO_UDP", 5)
        + _bind_inet(100, 5, 80)
        + _bind_inet(200, 5, 53),
    )
    out = parse_strace_network_log(log)
    by_port = {ev["port"]: ev["proto"] for ev in out["bind"]}
    assert by_port == {80: "tcp", 53: "udp"}


def test_missing_log_file_returns_empty(tmp_path: Path) -> None:
    out = parse_strace_network_log(tmp_path / "does_not_exist.log")
    assert out == {"bind": [], "connect": [], "accept": []}
