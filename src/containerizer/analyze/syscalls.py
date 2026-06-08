"""syscalls.jsonl -> sorted unique syscall_id ints (runtime phase events)."""

from __future__ import annotations

from collections.abc import Iterable


def aggregate_syscalls(events: Iterable[dict[str, object]]) -> list[int]:
    """Return sorted unique syscall_id ints across the given events."""
    seen: set[int] = set()
    for e in events:
        sid = e.get("syscall_id")
        if isinstance(sid, int):
            seen.add(sid)
    return sorted(seen)
