"""Tests for containerizer.verify.diff."""

from __future__ import annotations

from containerizer.analyze.schema import (
    TraceJson,
    TracePath,
    TracePhase,
    TracePort,
)
from containerizer.verify.diff import diff_traces


def _phase(
    *,
    paths: list[TracePath] | None = None,
    ports: list[TracePort] | None = None,
    caps: list[str] | None = None,
    syscalls: list[int] | None = None,
    execs: list[str] | None = None,
) -> TracePhase:
    return TracePhase(
        duration_s=1.0,
        paths=paths or [],
        ports=ports or [],
        outbound=[],
        caps=caps or [],
        syscalls=syscalls or [],
        execs=execs or [],
    )


def _trace(
    *,
    runtime: TracePhase | None = None,
    marker: str = "COMPLETE",
) -> TraceJson:
    return TraceJson(
        phase_marker_ns=1000,
        marker=marker,  # type: ignore[arg-type]
        install=_phase(),
        runtime=runtime or _phase(),
        warnings=[],
    )


def test_identical_traces_produce_empty_diff() -> None:
    p = TracePath(  # type: ignore[call-arg]
        path="/var/lib/x", ops=["read"], class_="persistent_rw", by=["a"]
    )
    runtime = _phase(paths=[p], caps=["CAP_FOO"], syscalls=[1, 2], execs=["app"])
    t = _trace(runtime=runtime)
    report = diff_traces(t, t)
    assert report.diff.new_paths == []
    assert report.diff.new_ports == []
    assert report.diff.new_caps == []
    assert report.diff.new_syscalls == []
    assert report.diff.new_execs == []
    assert report.warnings == []


def test_new_path_surfaced() -> None:
    p1 = TracePath(  # type: ignore[call-arg]
        path="/a", ops=["read"], class_="persistent_rw", by=["x"]
    )
    p2 = TracePath(  # type: ignore[call-arg]
        path="/b", ops=["read"], class_="persistent_rw", by=["x"]
    )
    orig = _trace(runtime=_phase(paths=[p1]))
    obs = _trace(runtime=_phase(paths=[p1, p2]))
    report = diff_traces(orig, obs)
    assert len(report.diff.new_paths) == 1
    assert report.diff.new_paths[0].path == "/b"


def test_same_path_different_class_counts_as_new() -> None:
    p_orig = TracePath(  # type: ignore[call-arg]
        path="/a", ops=["read"], class_="unknown_rw", by=["x"]
    )
    p_obs = TracePath(  # type: ignore[call-arg]
        path="/a", ops=["read"], class_="persistent_rw", by=["x"]
    )
    orig = _trace(runtime=_phase(paths=[p_orig]))
    obs = _trace(runtime=_phase(paths=[p_obs]))
    report = diff_traces(orig, obs)
    assert len(report.diff.new_paths) == 1
    assert report.diff.new_paths[0].class_ == "persistent_rw"


def test_new_port_surfaced_by_port_proto_key() -> None:
    p_orig = TracePort(port=80, proto="tcp", by="x", ipv4=True, ipv6=False)
    p_obs_new = TracePort(port=443, proto="tcp", by="x", ipv4=True, ipv6=False)
    orig = _trace(runtime=_phase(ports=[p_orig]))
    obs = _trace(runtime=_phase(ports=[p_orig, p_obs_new]))
    report = diff_traces(orig, obs)
    assert [p.port for p in report.diff.new_ports] == [443]


def test_same_port_different_family_does_not_count_as_new() -> None:
    # ipv4 vs ipv6 flag changes don't gate the diff per spec 4.7
    p_orig = TracePort(port=80, proto="tcp", by="x", ipv4=True, ipv6=False)
    p_obs = TracePort(port=80, proto="tcp", by="x", ipv4=False, ipv6=True)
    orig = _trace(runtime=_phase(ports=[p_orig]))
    obs = _trace(runtime=_phase(ports=[p_obs]))
    report = diff_traces(orig, obs)
    assert report.diff.new_ports == []


def test_new_cap_surfaced() -> None:
    orig = _trace(runtime=_phase(caps=["CAP_FOO"]))
    obs = _trace(runtime=_phase(caps=["CAP_FOO", "CAP_BAR"]))
    report = diff_traces(orig, obs)
    assert report.diff.new_caps == ["CAP_BAR"]


def test_new_syscall_surfaced() -> None:
    orig = _trace(runtime=_phase(syscalls=[1, 2]))
    obs = _trace(runtime=_phase(syscalls=[1, 2, 59]))
    report = diff_traces(orig, obs)
    assert report.diff.new_syscalls == [59]


def test_new_exec_surfaced() -> None:
    orig = _trace(runtime=_phase(execs=["app"]))
    obs = _trace(runtime=_phase(execs=["app", "worker"]))
    report = diff_traces(orig, obs)
    assert report.diff.new_execs == ["worker"]


def test_multiple_categories_all_surface() -> None:
    p_new = TracePath(  # type: ignore[call-arg]
        path="/x", ops=["read"], class_="persistent_rw", by=["a"]
    )
    orig = _trace(runtime=_phase(caps=["CAP_A"], syscalls=[1]))
    obs = _trace(
        runtime=_phase(
            paths=[p_new],
            ports=[TracePort(port=80, proto="tcp", by="a", ipv4=True, ipv6=False)],
            caps=["CAP_A", "CAP_B"],
            syscalls=[1, 2],
            execs=["new"],
        )
    )
    report = diff_traces(orig, obs)
    d = report.diff
    assert len(d.new_paths) == 1
    assert len(d.new_ports) == 1
    assert d.new_caps == ["CAP_B"]
    assert d.new_syscalls == [2]
    assert d.new_execs == ["new"]
    # Summary warning lists each category count
    assert any("5 events not present" in w for w in report.warnings)


def test_install_phase_differences_ignored() -> None:
    p_install_only = TracePath(  # type: ignore[call-arg]
        path="/install-only", ops=["write"], class_="persistent_rw", by=["x"]
    )
    orig = TraceJson(
        phase_marker_ns=1000,
        marker="COMPLETE",
        install=_phase(paths=[p_install_only]),
        runtime=_phase(),
        warnings=[],
    )
    obs = TraceJson(
        phase_marker_ns=1000,
        marker="COMPLETE",
        install=_phase(),  # different install phase
        runtime=_phase(),
        warnings=[],
    )
    report = diff_traces(orig, obs)
    assert report.diff.new_paths == []


def test_partial_marker_on_either_input_warns() -> None:
    orig = _trace(marker="PARTIAL")
    obs = _trace()
    report = diff_traces(orig, obs)
    assert any("original trace marker is PARTIAL" in w for w in report.warnings)
    assert report.original_marker == "PARTIAL"
    assert report.observed_marker == "COMPLETE"


def test_partial_marker_on_observed_warns() -> None:
    orig = _trace()
    obs = _trace(marker="PARTIAL")
    report = diff_traces(orig, obs)
    assert any("observed trace marker is PARTIAL" in w for w in report.warnings)


def test_new_paths_sorted_for_determinism() -> None:
    pb = TracePath(  # type: ignore[call-arg]
        path="/b", ops=["read"], class_="persistent_rw", by=["x"]
    )
    pa = TracePath(  # type: ignore[call-arg]
        path="/a", ops=["read"], class_="persistent_rw", by=["x"]
    )
    orig = _trace()
    obs = _trace(runtime=_phase(paths=[pb, pa]))  # observed in non-sorted order
    report = diff_traces(orig, obs)
    assert [p.path for p in report.diff.new_paths] == ["/a", "/b"]
