"""Tests for the bundled syscall table."""

from __future__ import annotations

from containerizer.generate.syscall_table import SYSCALL_NAMES


def test_table_pins_well_known_x86_64_syscalls() -> None:
    # If any of these change, x86_64 ABI is broken or our parser is wrong.
    assert SYSCALL_NAMES[0] == "read"
    assert SYSCALL_NAMES[1] == "write"
    assert SYSCALL_NAMES[2] == "open"
    assert SYSCALL_NAMES[3] == "close"
    assert SYSCALL_NAMES[59] == "execve"
    assert SYSCALL_NAMES[60] == "exit"


def test_table_size_is_reasonable() -> None:
    # Kernel v6.6 has roughly 380 x86_64 syscalls. A wide range catches both
    # accidental truncation and accidental inclusion of x32 entries.
    assert 300 <= len(SYSCALL_NAMES) <= 500


def test_table_values_are_unique() -> None:
    # Two syscall IDs mapping to the same name would be a parser bug.
    assert len(set(SYSCALL_NAMES.values())) == len(SYSCALL_NAMES)
