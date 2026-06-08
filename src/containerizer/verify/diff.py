"""Pure diff of two TraceJson documents: observed.runtime \\ original.runtime."""

from __future__ import annotations

from containerizer.analyze.schema import TraceJson
from containerizer.verify.schema import VerifyDiff, VerifyReport


def diff_traces(original: TraceJson, observed: TraceJson) -> VerifyReport:
    """Compute observed.runtime \\ original.runtime per category.

    One-directional. Install phase ignored. Path comparison keyed on
    (path, class_); port comparison keyed on (port, proto); caps/syscalls/
    execs by simple set membership. Each `new_*` list sorted deterministically.
    """
    orig_path_keys = {(p.path, p.class_) for p in original.runtime.paths}
    new_paths = sorted(
        (p for p in observed.runtime.paths if (p.path, p.class_) not in orig_path_keys),
        key=lambda p: (p.path, p.class_),
    )

    orig_port_keys = {(p.port, p.proto) for p in original.runtime.ports}
    new_ports = sorted(
        (p for p in observed.runtime.ports if (p.port, p.proto) not in orig_port_keys),
        key=lambda p: (p.port, p.proto),
    )

    new_caps = sorted(set(observed.runtime.caps) - set(original.runtime.caps))
    new_syscalls = sorted(set(observed.runtime.syscalls) - set(original.runtime.syscalls))
    new_execs = sorted(set(observed.runtime.execs) - set(original.runtime.execs))

    warnings: list[str] = []
    if original.marker == "PARTIAL":
        warnings.append("original trace marker is PARTIAL; comparison may be incomplete")
    if observed.marker == "PARTIAL":
        warnings.append("observed trace marker is PARTIAL; comparison may be incomplete")

    diff = VerifyDiff(
        new_paths=new_paths,
        new_ports=new_ports,
        new_caps=new_caps,
        new_syscalls=new_syscalls,
        new_execs=new_execs,
    )
    total = len(new_paths) + len(new_ports) + len(new_caps) + len(new_syscalls) + len(new_execs)
    if total:
        warnings.append(
            f"observed runtime has {total} events not present in original "
            f"({len(new_paths)} paths, {len(new_ports)} ports, "
            f"{len(new_caps)} caps, {len(new_syscalls)} syscalls, "
            f"{len(new_execs)} execs)"
        )

    return VerifyReport(
        original_marker=original.marker,
        observed_marker=observed.marker,
        diff=diff,
        warnings=warnings,
    )
