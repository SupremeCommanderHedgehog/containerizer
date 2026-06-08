"""Tests for analyze.derive."""

from __future__ import annotations

from containerizer.analyze.derive import derive_policy
from containerizer.analyze.schema import (
    TraceJson,
    TracePath,
    TracePhase,
    TracePort,
)

EMPTY_PHASE = TracePhase(
    duration_s=0.0,
    paths=[],
    ports=[],
    outbound=[],
    caps=[],
    syscalls=[],
    execs=[],
)


def _make_trace(
    *,
    install: TracePhase = EMPTY_PHASE,
    runtime: TracePhase = EMPTY_PHASE,
    marker: str = "COMPLETE",
    warnings: list[str] | None = None,
) -> TraceJson:
    return TraceJson(
        phase_marker_ns=100 if marker == "COMPLETE" else None,
        marker=marker,  # type: ignore[arg-type]
        install=install,
        runtime=runtime,
        warnings=warnings or [],
    )


def test_systemd_heuristic_true_when_execs_include_systemd() -> None:
    runtime = TracePhase(
        duration_s=1.0,
        paths=[],
        ports=[],
        outbound=[],
        caps=[],
        syscalls=[],
        execs=["systemd", "java"],
    )
    policy = derive_policy(_make_trace(runtime=runtime))
    assert policy.image.systemd_required is True
    assert policy.image.entrypoint == ["/sbin/init"]


def test_systemd_heuristic_false_emits_sentinel_entrypoint() -> None:
    runtime = TracePhase(
        duration_s=1.0,
        paths=[],
        ports=[],
        outbound=[],
        caps=[],
        syscalls=[],
        execs=["java"],
    )
    policy = derive_policy(_make_trace(runtime=runtime))
    assert policy.image.systemd_required is False
    assert policy.image.entrypoint == ["__UNSET__"]


def test_conservative_defaults_in_minimal_trace() -> None:
    policy = derive_policy(_make_trace())
    assert policy.image.apt_packages == []
    assert policy.image.installer_path == "/installer"
    assert policy.image.post_install_cleanup == ["/var/cache/apt/archives/*", "/installer"]
    assert policy.runtime.read_only_rootfs is False
    assert policy.runtime.no_new_privileges is True
    assert policy.runtime.caps_drop == ["ALL"]


def test_volumes_from_persistent_rw_paths() -> None:
    runtime = TracePhase(
        duration_s=1.0,
        paths=[
            TracePath(  # type: ignore[call-arg]
                path="/var/lib/example-app", ops=["read", "write"], class_="persistent_rw", by=["m"]
            ),
            TracePath(  # type: ignore[call-arg]
                path="/var/log/example-app", ops=["write"], class_="persistent_rw", by=["m"]
            ),
        ],
        ports=[],
        outbound=[],
        caps=[],
        syscalls=[],
        execs=[],
    )
    policy = derive_policy(_make_trace(runtime=runtime))
    names = sorted(v.name for v in policy.runtime.volumes)
    mounts = sorted(v.mount for v in policy.runtime.volumes)
    assert mounts == ["/var/lib/example-app", "/var/log/example-app"]
    # Both leaf components are "example-app"; expect disambiguation.
    assert "example-app-data" in names
    assert any(n != "example-app-data" for n in names)


def test_tmpfs_from_ephemeral_rw_paths() -> None:
    runtime = TracePhase(
        duration_s=1.0,
        paths=[
            TracePath(path="/tmp", ops=["write"], class_="ephemeral_rw", by=["x"]),  # type: ignore[call-arg]
            TracePath(path="/run", ops=["write"], class_="ephemeral_rw", by=["x"]),  # type: ignore[call-arg]
        ],
        ports=[],
        outbound=[],
        caps=[],
        syscalls=[],
        execs=[],
    )
    policy = derive_policy(_make_trace(runtime=runtime))
    assert sorted(policy.runtime.tmpfs) == ["/run", "/tmp"]


def test_binds_ro_from_host_config_paths() -> None:
    runtime = TracePhase(
        duration_s=1.0,
        paths=[
            TracePath(  # type: ignore[call-arg]
                path="/etc/resolv.conf", ops=["read"], class_="host_config_ro", by=["x"]
            )
        ],
        ports=[],
        outbound=[],
        caps=[],
        syscalls=[],
        execs=[],
    )
    policy = derive_policy(_make_trace(runtime=runtime))
    assert policy.runtime.binds_ro == ["/etc/resolv.conf"]


def test_single_persistent_path_uses_bare_leaf_data_name() -> None:
    runtime = TracePhase(
        duration_s=1.0,
        paths=[
            TracePath(  # type: ignore[call-arg]
                path="/var/lib/postgres", ops=["write"], class_="persistent_rw", by=["x"]
            )
        ],
        ports=[],
        outbound=[],
        caps=[],
        syscalls=[],
        execs=[],
    )
    policy = derive_policy(_make_trace(runtime=runtime))
    assert [v.name for v in policy.runtime.volumes] == ["postgres-data"]
    assert [v.mount for v in policy.runtime.volumes] == ["/var/lib/postgres"]


def test_systemd_required_when_install_writes_systemd_unit() -> None:
    install = TracePhase(
        duration_s=1.0,
        paths=[
            TracePath(  # type: ignore[call-arg]
                path="/etc/systemd/system/example-app.service",
                ops=["write"],
                class_="persistent_rw",
                by=["x"],
            )
        ],
        ports=[],
        outbound=[],
        caps=[],
        syscalls=[],
        execs=[],
    )
    policy = derive_policy(_make_trace(install=install))
    assert policy.image.systemd_required is True
    assert policy.image.entrypoint == ["/sbin/init"]


def test_publish_ports_filtered_to_tcp_udp() -> None:
    runtime = TracePhase(
        duration_s=1.0,
        paths=[],
        ports=[
            TracePort(port=8443, proto="tcp", by="x", ipv4=True, ipv6=False),
            TracePort(port=0, proto="unix", by="x", ipv4=True, ipv6=False),
            TracePort(port=53, proto="udp", by="x", ipv4=True, ipv6=False),
        ],
        outbound=[],
        caps=[],
        syscalls=[],
        execs=[],
    )
    policy = derive_policy(_make_trace(runtime=runtime))
    protos = sorted(p.proto for p in policy.runtime.publish_ports)
    assert protos == ["tcp", "udp"]
