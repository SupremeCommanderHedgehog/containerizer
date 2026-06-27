"""Path classifier (7 rules, first match wins) + aggregation.

See spec §5.2 (rules table) and §5.3 (aggregation).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from containerizer.analyze.schema import TracePath

# open(2) flag bits we care about.
O_WRONLY = 1
O_RDWR = 2
O_CREAT = 64

# Rule classes (literal type names match TracePath.class_).
Klass = Literal[
    "image_static",
    "persistent_rw",
    "ephemeral_rw",
    "host_config_ro",
    "device",
    "unknown_rw",
    "unknown_ro",
]

IMAGE_STATIC_PREFIXES = ("/opt/", "/usr/lib/", "/usr/share/")
PERSISTENT_ROOTS = ("/var/lib/", "/var/log/", "/var/spool/")
EPHEMERAL_ROOTS = ("/tmp/", "/run/", "/var/run/", "/var/tmp/", "/dev/shm/")
HOST_CONFIG_PATHS = frozenset(
    {
        "/etc/resolv.conf",
        "/etc/hosts",
        "/etc/localtime",
        "/etc/timezone",
    }
)
# /proc and /sys are kernel pseudo-filesystems. /var/lib/containers is the
# trace sandbox's own podman storage: the nested deb-install runs
# podman-in-podman and, under rootful podman, writes there — that's tracer
# infrastructure, never a workload volume (#119).
FILTERED_ROOTS = ("/proc/", "/sys/", "/var/lib/containers/")


@dataclass
class _RawPathEvent:
    path: str
    op: Literal["read", "write", "mkdir", "stat", "exec"]
    comm: str


def classify_runtime(events: Iterable[dict[str, object]]) -> list[TracePath]:
    """Take a list of open.jsonl-shaped records (runtime phase only) and
    return aggregated TracePath entries (one per mount-relevant root).

    Implements the 7-rule classifier from spec §5.2 and the aggregation
    rules from spec §5.3. First-match-wins ordering. Mixed-class collisions
    under the same aggregation key (image_static + a *_rw class) bump the
    whole aggregate to unknown_rw per spec §5.3.
    """

    raw = [_to_raw(e) for e in events if isinstance(e.get("path"), str)]
    # Filter rule 6 first — /proc, /sys never reach aggregation.
    raw = [r for r in raw if not _is_filtered(r.path)]

    # Bucket by (class, aggregation_key)
    buckets: dict[tuple[Klass, str], tuple[set[str], set[str]]] = {}
    for r in raw:
        klass, agg_key = _classify_one(r)
        ops, comms = buckets.setdefault((klass, agg_key), (set(), set()))
        ops.add(r.op)
        comms.add(r.comm)

    # Detect collisions: same agg_key under different classes that include
    # both image_static (read-only) AND a write-emitting class. Promote
    # whole aggregate to unknown_rw.
    by_key: dict[str, list[Klass]] = {}
    for (klass, agg_key), _ in buckets.items():
        by_key.setdefault(agg_key, []).append(klass)

    collided: set[str] = set()
    for agg_key, classes in by_key.items():
        if "image_static" in classes and any(
            k.endswith("_rw") for k in classes if k != "image_static"
        ):
            collided.add(agg_key)

    out: list[TracePath] = []
    if collided:
        # Merge all entries under a collided key into one unknown_rw aggregate.
        merged: dict[str, tuple[set[str], set[str]]] = {}
        for (_klass, agg_key), (ops, comms) in buckets.items():
            if agg_key in collided:
                m_ops, m_comms = merged.setdefault(agg_key, (set(), set()))
                m_ops.update(ops)
                m_comms.update(comms)
        for agg_key, (ops, comms) in merged.items():
            out.append(
                TracePath(  # type: ignore[call-arg]
                    path=agg_key,
                    ops=sorted(ops),  # type: ignore[arg-type]
                    class_="unknown_rw",
                    by=sorted(comms),
                )
            )
        # Then add non-collided entries.
        for (klass, agg_key), (ops, comms) in buckets.items():
            if agg_key in collided:
                continue
            out.append(
                TracePath(  # type: ignore[call-arg]
                    path=agg_key,
                    ops=sorted(ops),  # type: ignore[arg-type]
                    class_=klass,
                    by=sorted(comms),
                )
            )
    else:
        for (klass, agg_key), (ops, comms) in buckets.items():
            out.append(
                TracePath(  # type: ignore[call-arg]
                    path=agg_key,
                    ops=sorted(ops),  # type: ignore[arg-type]
                    class_=klass,
                    by=sorted(comms),
                )
            )
    out.sort(key=lambda p: p.path)
    return out


def _to_raw(e: dict[str, object]) -> _RawPathEvent:
    path = str(e.get("path", ""))
    flags_raw = e.get("flags", 0)
    flags = int(flags_raw) if isinstance(flags_raw, (int, str)) else 0
    op: Literal["read", "write", "mkdir", "stat", "exec"] = (
        "write" if flags & (O_WRONLY | O_RDWR) else "read"
    )
    return _RawPathEvent(path=path, op=op, comm=str(e.get("comm", "?")))


def _is_filtered(path: str) -> bool:
    return any(path == r.rstrip("/") or path.startswith(r) for r in FILTERED_ROOTS)


def _classify_one(r: _RawPathEvent) -> tuple[Klass, str]:
    p = r.path
    # Rule 4 — exact match host config (before rule 1 since these live
    # under /etc but aren't covered by /etc/* in rule 1).
    if p in HOST_CONFIG_PATHS:
        return ("host_config_ro", p)
    # Rule 5 — /dev/<leaf>
    if p.startswith("/dev/"):
        return ("device", p)
    # Rule 1 — image_static (only if op is non-write)
    for prefix in IMAGE_STATIC_PREFIXES:
        if p.startswith(prefix):
            key = _first_component_under(p, prefix)
            if r.op == "write":
                return ("unknown_rw", key)
            return ("image_static", key)
    # Rule 2 — persistent_rw (only if write)
    for prefix in PERSISTENT_ROOTS:
        if p.startswith(prefix):
            key = _first_component_under(p, prefix)
            if r.op == "write":
                return ("persistent_rw", key)
            # read under persistent root with no writes anywhere — treat as
            # unknown_ro so the user notices. Rule says "AND write ∈ ops",
            # so a pure read here doesn't match rule 2.
            return ("unknown_ro", p)
    # Rule 3 — ephemeral_rw (only if write)
    for prefix in EPHEMERAL_ROOTS:
        if p.startswith(prefix):
            key = prefix.rstrip("/")
            if r.op == "write":
                return ("ephemeral_rw", key)
            return ("unknown_ro", p)
    # Rule 7 — fallthrough
    if r.op == "write":
        return ("unknown_rw", p)
    return ("unknown_ro", p)


def _first_component_under(p: str, prefix: str) -> str:
    """For p like '/opt/example-app/lib/x' and prefix '/opt/', return '/opt/example-app'."""
    rest = p[len(prefix) :]
    first = rest.split("/", 1)[0]
    return prefix.rstrip("/") + "/" + first
