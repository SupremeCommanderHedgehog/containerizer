"""Tests for analyze.execs."""

from __future__ import annotations

from containerizer.analyze.execs import aggregate_execs

SYS_EXECVE = 59  # x86_64


def test_filters_to_execve_and_dedups() -> None:
    events: list[dict[str, object]] = [
        {"syscall_id": SYS_EXECVE, "comm": "java"},
        {"syscall_id": SYS_EXECVE, "comm": "mongod"},
        {"syscall_id": SYS_EXECVE, "comm": "java"},
        {"syscall_id": 1, "comm": "irrelevant"},
    ]
    assert aggregate_execs(events) == ["java", "mongod"]


def test_empty() -> None:
    assert aggregate_execs([]) == []
