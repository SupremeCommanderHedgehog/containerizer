"""Assemble a normalized TraceJson from a TraceBundle.

Promoted from analyze/cli.py for M6 so build/pipeline.py can reuse the
same path. The behavior is byte-identical to the previous private
helper; only the location and visibility changed.
"""

from __future__ import annotations

from containerizer.analyze.caps import aggregate_caps
from containerizer.analyze.derive import SENTINEL_ENTRYPOINT, systemd_required_for
from containerizer.analyze.execs import aggregate_execs
from containerizer.analyze.paths import classify_runtime
from containerizer.analyze.phases import split_phases
from containerizer.analyze.ports import aggregate_ports
from containerizer.analyze.reader import TraceBundle
from containerizer.analyze.schema import TraceJson, TracePhase
from containerizer.analyze.syscalls import aggregate_syscalls

SENTINEL_WARNING = f"entrypoint is sentinel [{SENTINEL_ENTRYPOINT!r}]; M4 must refuse this policy"


def assemble_trace_json(bundle: TraceBundle) -> TraceJson:
    """Build a TraceJson from a raw TraceBundle. Pure given the bundle."""
    open_install, open_runtime = split_phases(
        bundle.events["open"], phase_marker_ns=bundle.phase_marker_ns, marker=bundle.marker
    )
    bind_install, bind_runtime = split_phases(
        bundle.events["bind"], phase_marker_ns=bundle.phase_marker_ns, marker=bundle.marker
    )
    sys_install, sys_runtime = split_phases(
        bundle.events["syscalls"], phase_marker_ns=bundle.phase_marker_ns, marker=bundle.marker
    )
    capable_install, capable_runtime = split_phases(
        bundle.events["capable"], phase_marker_ns=bundle.phase_marker_ns, marker=bundle.marker
    )

    warnings = list(bundle.warnings)
    for collector, info in bundle.fallbacks.items():
        warnings.append(
            f"collector {collector}: fellback to {info.get('fallback', '?')} "
            f"(reason: {info.get('reason', '?')})"
        )

    install = TracePhase(
        duration_s=0.0,
        paths=classify_runtime(open_install),
        ports=aggregate_ports(bind_install),
        outbound=[],
        caps=aggregate_caps(capable_install),
        syscalls=aggregate_syscalls(sys_install),
        execs=aggregate_execs(sys_install),
    )
    runtime = TracePhase(
        duration_s=0.0,
        paths=classify_runtime(open_runtime),
        ports=aggregate_ports(bind_runtime),
        outbound=[],
        caps=aggregate_caps(capable_runtime),
        syscalls=aggregate_syscalls(sys_runtime),
        execs=aggregate_execs(sys_runtime),
    )

    for path in runtime.paths:
        if path.class_ == "unknown_rw":
            warnings.append(f"unknown_rw aggregate: {path.path}")
        elif path.class_ == "device":
            warnings.append(f"device aggregate: {path.path}")

    provisional = TraceJson(
        phase_marker_ns=bundle.phase_marker_ns,
        marker=bundle.marker,
        install=install,
        runtime=runtime,
        warnings=warnings,
    )
    if not systemd_required_for(provisional):
        warnings.append(SENTINEL_WARNING)
        return provisional.model_copy(update={"warnings": warnings})
    return provisional
