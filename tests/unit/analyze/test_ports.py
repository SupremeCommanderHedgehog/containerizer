"""Tests for analyze.ports."""

from __future__ import annotations

from containerizer.analyze.ports import aggregate_ports


def test_dedup_per_port_proto_comm() -> None:
    events: list[dict[str, object]] = [
        {"family": 2, "port": 8443, "proto": "tcp", "comm": "unifi"},
        {"family": 2, "port": 8443, "proto": "tcp", "comm": "unifi"},  # dup
        {"family": 10, "port": 8443, "proto": "tcp", "comm": "unifi"},  # v6 same comm
    ]
    aggregated = aggregate_ports(events)
    assert len(aggregated) == 1
    p = aggregated[0]
    assert p.port == 8443
    assert p.proto == "tcp"
    assert p.by == "unifi"
    assert p.ipv4 is True
    assert p.ipv6 is True


def test_distinct_comm_separate_entries() -> None:
    events: list[dict[str, object]] = [
        {"family": 2, "port": 5432, "proto": "tcp", "comm": "postgres"},
        {"family": 2, "port": 5432, "proto": "tcp", "comm": "pgbouncer"},
    ]
    assert len(aggregate_ports(events)) == 2


def test_unix_and_unknown_proto_kept() -> None:
    events: list[dict[str, object]] = [
        {"family": 1, "port": 0, "proto": "unix", "comm": "app"},
        {"family": 2, "port": 7777, "proto": "?", "comm": "app"},
    ]
    aggregated = aggregate_ports(events)
    protos = sorted(p.proto for p in aggregated)
    assert protos == ["?", "unix"]
