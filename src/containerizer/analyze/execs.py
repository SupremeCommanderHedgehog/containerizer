"""SYS_execve filter over syscalls.jsonl -> sorted unique comm list."""

from __future__ import annotations

from collections.abc import Iterable

# syscall numbers from the kernel; x86_64-only for M3.
SYS_EXECVE_X86_64 = 59


def aggregate_execs(events: Iterable[dict[str, object]]) -> list[str]:
    """Return sorted unique comm strings from execve events."""
    seen: set[str] = set()
    for e in events:
        if e.get("syscall_id") != SYS_EXECVE_X86_64:
            continue
        comm = e.get("comm")
        if isinstance(comm, str):
            seen.add(comm)
    return sorted(seen)
