"""Tests for analyze.syscalls."""

from __future__ import annotations

from containerizer.analyze.syscalls import aggregate_syscalls


def test_sorted_unique() -> None:
    events: list[dict[str, object]] = [
        {"syscall_id": 5, "pid": 1, "count": 10},
        {"syscall_id": 1, "pid": 1, "count": 3},
        {"syscall_id": 5, "pid": 2, "count": 1},
        {"syscall_id": 3, "pid": 1, "count": 2},
    ]
    assert aggregate_syscalls(events) == [1, 3, 5]


def test_empty() -> None:
    assert aggregate_syscalls([]) == []


def test_skips_missing_syscall_id() -> None:
    events: list[dict[str, object]] = [{"pid": 1, "count": 1}, {"syscall_id": 42}]
    assert aggregate_syscalls(events) == [42]
