"""Tests for analyze.derive."""

from __future__ import annotations

from containerizer.analyze.derive import derive_policy
from containerizer.analyze.reader import InstallInputs
from containerizer.analyze.schema import (
    DebInstaller,
    ExecutableInstaller,
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
    start_cmd: str | None = None,
) -> TraceJson:
    return TraceJson(
        phase_marker_ns=100 if marker == "COMPLETE" else None,
        marker=marker,  # type: ignore[arg-type]
        install=install,
        runtime=runtime,
        warnings=warnings or [],
        start_cmd=start_cmd,
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
    assert isinstance(policy.image.installer, ExecutableInstaller)
    assert policy.image.installer.path == "/installer"
    assert policy.image.post_install_cleanup == ["/var/cache/apt/archives/*", "/installer"]
    assert policy.image.apt_sources == []
    assert policy.image.apt_keys == []
    assert policy.runtime.read_only_rootfs is False
    assert policy.runtime.no_new_privileges is True
    assert policy.runtime.caps_drop == ["ALL"]


def test_volumes_from_persistent_rw_paths() -> None:
    runtime = TracePhase(
        duration_s=1.0,
        paths=[
            TracePath(  # type: ignore[call-arg]
                path="/var/lib/unifi", ops=["read", "write"], class_="persistent_rw", by=["m"]
            ),
            TracePath(  # type: ignore[call-arg]
                path="/var/log/unifi", ops=["write"], class_="persistent_rw", by=["m"]
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
    assert mounts == ["/var/lib/unifi", "/var/log/unifi"]
    # Both leaf components are "unifi"; expect disambiguation.
    assert "unifi-data" in names
    assert any(n != "unifi-data" for n in names)


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
                path="/etc/systemd/system/unifi.service",
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


def test_derive_policy_forwards_warnings_to_policy() -> None:
    trace = _make_trace()
    msgs = ["unknown_rw aggregate: /var/lib/x", "device aggregate: /dev/foo"]
    policy = derive_policy(trace, warnings=msgs)
    assert policy.warnings == msgs


def test_derive_policy_warnings_defaults_to_empty() -> None:
    trace = _make_trace()
    policy = derive_policy(trace)
    assert policy.warnings == []


def test_entrypoint_uses_start_cmd_when_no_systemd() -> None:
    runtime = TracePhase(
        duration_s=1.0,
        paths=[],
        ports=[],
        outbound=[],
        caps=[],
        syscalls=[],
        execs=["java"],  # no systemd in execs
    )
    policy = derive_policy(
        _make_trace(runtime=runtime, start_cmd="/etc/init.d/unifi start"),
    )
    assert policy.image.systemd_required is False
    assert policy.image.entrypoint == ["bash", "-c", "/etc/init.d/unifi start"]
    # No "start_cmd ignored" warning when systemd is not required.
    assert not any("start_cmd ignored" in w for w in policy.warnings)


def test_entrypoint_ignores_start_cmd_when_systemd_with_warning() -> None:
    runtime = TracePhase(
        duration_s=1.0,
        paths=[],
        ports=[],
        outbound=[],
        caps=[],
        syscalls=[],
        execs=["systemd", "java"],  # systemd in execs triggers systemd_required
    )
    policy = derive_policy(
        _make_trace(runtime=runtime, start_cmd="/etc/init.d/unifi start"),
    )
    assert policy.image.systemd_required is True
    assert policy.image.entrypoint == ["/sbin/init"]
    assert (
        "start_cmd ignored: systemd detected as required; using /sbin/init as entrypoint"
        in policy.warnings
    )


def test_derive_installer_deb_single() -> None:
    inputs = InstallInputs(installers=("foo.deb",))
    policy = derive_policy(_make_trace(), install_inputs=inputs)
    assert isinstance(policy.image.installer, DebInstaller)
    assert policy.image.installer.paths == ["/tmp/foo.deb"]


def test_derive_installer_deb_multi() -> None:
    inputs = InstallInputs(
        installers=("primary.deb", "extra1.deb", "extra2.deb"),
    )
    policy = derive_policy(_make_trace(), install_inputs=inputs)
    assert isinstance(policy.image.installer, DebInstaller)
    assert policy.image.installer.paths == [
        "/tmp/primary.deb",
        "/tmp/extra1.deb",
        "/tmp/extra2.deb",
    ]


def test_derive_installer_executable_when_primary_not_deb() -> None:
    inputs = InstallInputs(installers=("unifi-installer.bin",))
    policy = derive_policy(_make_trace(), install_inputs=inputs)
    assert isinstance(policy.image.installer, ExecutableInstaller)
    assert policy.image.installer.path == "/installer"


def test_derive_apt_sources_propagated() -> None:
    inputs = InstallInputs(
        installers=("foo.deb",),
        apt_sources=("deb http://example/x noble main",),
    )
    policy = derive_policy(_make_trace(), install_inputs=inputs)
    assert policy.image.apt_sources == ["deb http://example/x noble main"]


def test_derive_apt_keys_propagated_as_basenames() -> None:
    inputs = InstallInputs(
        installers=("foo.deb",),
        apt_keys=("mongodb.gpg", "extra.asc"),
    )
    policy = derive_policy(_make_trace(), install_inputs=inputs)
    assert policy.image.apt_keys == ["mongodb.gpg", "extra.asc"]


def test_derive_post_install_cleanup_for_deb() -> None:
    inputs = InstallInputs(installers=("foo.deb",))
    policy = derive_policy(_make_trace(), install_inputs=inputs)
    assert policy.image.post_install_cleanup == [
        "/tmp/*.deb",
        "/var/lib/apt/lists/*",
        "/var/cache/apt/archives/*",
    ]


def test_derive_no_install_inputs_falls_back_to_executable() -> None:
    """Backwards-compatible: derive_policy() with no install_inputs
    behaves as today (sentinel single-executable shape)."""
    policy = derive_policy(_make_trace())
    assert isinstance(policy.image.installer, ExecutableInstaller)
    assert policy.image.installer.path == "/installer"


def _phase_with_syscalls(ids: list[int]) -> TracePhase:
    return TracePhase(
        duration_s=1.0,
        paths=[],
        ports=[],
        outbound=[],
        caps=[],
        syscalls=ids,
        execs=[],
    )


def test_seccomp_syscalls_union_install_and_runtime() -> None:
    trace = _make_trace(
        install=_phase_with_syscalls([1, 2]),
        runtime=_phase_with_syscalls([3]),
    )
    policy = derive_policy(trace)
    assert policy.runtime.seccomp_syscalls == [1, 2, 3]


def test_seccomp_syscalls_includes_install_when_runtime_empty() -> None:
    # Issue #116: a syscall first observed during install must still land in the
    # seccomp allowlist even though runtime.syscalls is empty (the collector
    # buckets each syscall into the phase of its first occurrence).
    trace = _make_trace(
        install=_phase_with_syscalls([10, 20, 30]),
        runtime=_phase_with_syscalls([]),
    )
    policy = derive_policy(trace)
    assert policy.runtime.seccomp_syscalls == [10, 20, 30]


def test_seccomp_syscalls_deduped_and_sorted() -> None:
    trace = _make_trace(
        install=_phase_with_syscalls([59, 1]),
        runtime=_phase_with_syscalls([1, 2]),
    )
    policy = derive_policy(trace)
    assert policy.runtime.seccomp_syscalls == [1, 2, 59]
