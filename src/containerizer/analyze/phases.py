"""Split collector events into install and runtime by PHASE_MARKER.

PHASE_MARKER carries a `monotonic_ns:` line written by the orchestrator
right after the installer exits. bpftrace's `nsecs` and `/proc/uptime`
are both CLOCK_MONOTONIC, so direct comparison with event ts_ns is
apples-to-apples. If a future collector switches clock sources, this
will silently misclassify — keep the comment.
"""

from __future__ import annotations

from typing import Literal


def split_phases(
    events: list[dict[str, object]],
    *,
    phase_marker_ns: int | None,
    marker: Literal["COMPLETE", "PARTIAL"],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """Return (install_events, runtime_events).

    Behavior:
      - PARTIAL marker: every event -> install; runtime is empty.
      - COMPLETE + phase_marker_ns: events with ts_ns < phase_marker_ns -> install;
        events with ts_ns >= phase_marker_ns -> runtime.
      - COMPLETE without phase_marker_ns: treat all as install (defensive).
      - An event without a ts_ns field is sent to install.
    """
    if marker == "PARTIAL" or phase_marker_ns is None:
        return list(events), []

    install: list[dict[str, object]] = []
    runtime: list[dict[str, object]] = []
    for e in events:
        ts = e.get("ts_ns")
        if not isinstance(ts, int):
            install.append(e)
            continue
        if ts < phase_marker_ns:
            install.append(e)
        else:
            runtime.append(e)
    return install, runtime
