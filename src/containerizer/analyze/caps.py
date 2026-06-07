"""capable.jsonl -> deduped + superset-filtered capability list."""

from __future__ import annotations

from collections.abc import Iterable

# {superset_cap: {capabilities subsumed by it}}
SUPERSETS: dict[str, frozenset[str]] = {
    "CAP_DAC_OVERRIDE": frozenset({"CAP_DAC_READ_SEARCH"}),
    "CAP_SYS_ADMIN": frozenset({"CAP_BPF", "CAP_PERFMON"}),
    "CAP_NET_ADMIN": frozenset({"CAP_NET_RAW"}),
}


def aggregate_caps(events: Iterable[dict[str, object]]) -> list[str]:
    """Dedup capability events; drop subsumed caps when their superset is present."""
    seen: set[str] = set()
    for e in events:
        name = e.get("cap_name") or e.get("cap")
        if isinstance(name, str):
            seen.add(name)
    # Drop subsumed caps when their superset is present.
    for superset, subsumed in SUPERSETS.items():
        if superset in seen:
            seen -= subsumed
    return sorted(seen)
