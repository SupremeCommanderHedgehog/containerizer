"""Tests for analyze schema models."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from containerizer.analyze.schema import (
    DebInstaller,
    ExecutableInstaller,
    PolicyImage,
    PolicyJson,
    PolicyPort,
    PolicyRuntime,
    PolicyVolume,
    TraceJson,
    TraceOutbound,
    TracePath,
    TracePhase,
    TracePort,
)


def _empty_phase() -> TracePhase:
    return TracePhase(
        duration_s=0.0,
        paths=[],
        ports=[],
        outbound=[],
        caps=[],
        syscalls=[],
        execs=[],
    )


def test_tracepath_serializes_class_alias() -> None:
    p = TracePath(path="/var/lib/x", ops=["write"], class_="persistent_rw", by=["app"])  # type: ignore[call-arg]
    dumped = json.loads(p.model_dump_json(by_alias=True))
    assert dumped["class"] == "persistent_rw"
    assert "class_" not in dumped


def test_tracepath_class_invalid_rejected() -> None:
    with pytest.raises(ValidationError):
        TracePath(path="/x", ops=["read"], class_="nonsense", by=[])  # type: ignore[call-arg]


def test_tracejson_round_trip() -> None:
    tj = TraceJson(
        phase_marker_ns=12345,
        marker="COMPLETE",
        install=_empty_phase(),
        runtime=_empty_phase(),
        warnings=["x"],
    )
    s = tj.model_dump_json(by_alias=True)
    tj2 = TraceJson.model_validate_json(s)
    assert tj2 == tj
    assert tj2.schema_version == 1


def test_tracejson_partial_marker_allows_none_phase_marker() -> None:
    tj = TraceJson(
        phase_marker_ns=None,
        marker="PARTIAL",
        install=_empty_phase(),
        runtime=_empty_phase(),
        warnings=[],
    )
    assert tj.phase_marker_ns is None


def test_policyjson_defaults_and_round_trip() -> None:
    pj = PolicyJson(
        image=PolicyImage(
            base="ubuntu:24.04",
            installer=ExecutableInstaller(path="/installer"),
            apt_packages=[],
            post_install_cleanup=["/installer"],
            systemd_required=False,
            entrypoint=["__UNSET__"],
        ),
        runtime=PolicyRuntime(
            volumes=[],
            tmpfs=[],
            binds_ro=[],
            publish_ports=[],
            caps_add=[],
            seccomp_syscalls=[],
            read_only_rootfs=False,
        ),
    )
    s = pj.model_dump_json(by_alias=True)
    pj2 = PolicyJson.model_validate_json(s)
    assert pj2 == pj
    assert pj2.schema_version == 3
    assert isinstance(pj2.image.installer, ExecutableInstaller)
    assert pj2.image.installer.path == "/installer"
    assert pj2.runtime.caps_drop == ["ALL"]
    assert pj2.runtime.no_new_privileges is True


def test_policyport_proto_restricted() -> None:
    PolicyPort(host=8443, container=8443, proto="tcp")
    PolicyPort(host=53, container=53, proto="udp")
    with pytest.raises(ValidationError):
        PolicyPort(host=1, container=1, proto="unix")  # type: ignore[arg-type]


def test_policyvolume_basic() -> None:
    v = PolicyVolume(name="example-app-data", mount="/var/lib/example-app")
    assert v.name == "example-app-data"
    assert v.mount == "/var/lib/example-app"


def test_traceport_basic() -> None:
    tp = TracePort(port=8443, proto="tcp", by="app", ipv4=True, ipv6=False)
    assert tp.port == 8443
    assert tp.proto == "tcp"


def test_traceoutbound_basic() -> None:
    ob = TraceOutbound(daddr="1.2.3.4", dport=443, comm="curl")
    assert ob.daddr == "1.2.3.4"
    assert ob.dport == 443


def test_policy_json_v3_has_warnings_field() -> None:
    policy = PolicyJson(
        image=PolicyImage(
            base="ubuntu:24.04",
            installer=ExecutableInstaller(path="/installer"),
            apt_packages=[],
            post_install_cleanup=[],
            systemd_required=False,
            entrypoint=["__UNSET__"],
        ),
        runtime=PolicyRuntime(
            volumes=[],
            tmpfs=[],
            binds_ro=[],
            publish_ports=[],
            caps_add=[],
            seccomp_syscalls=[],
            read_only_rootfs=False,
        ),
        warnings=["unknown_rw aggregate: /var/lib/foo"],
    )
    assert policy.schema_version == 3
    assert policy.warnings == ["unknown_rw aggregate: /var/lib/foo"]


def test_policy_json_warnings_defaults_to_empty_list() -> None:
    policy = PolicyJson(
        image=PolicyImage(
            base="ubuntu:24.04",
            installer=ExecutableInstaller(path="/installer"),
            apt_packages=[],
            post_install_cleanup=[],
            systemd_required=False,
            entrypoint=["__UNSET__"],
        ),
        runtime=PolicyRuntime(
            volumes=[],
            tmpfs=[],
            binds_ro=[],
            publish_ports=[],
            caps_add=[],
            seccomp_syscalls=[],
            read_only_rootfs=False,
        ),
    )
    assert policy.warnings == []


def test_tracejson_round_trips_start_cmd_when_set() -> None:
    tj = TraceJson(
        phase_marker_ns=123,
        marker="COMPLETE",
        install=_empty_phase(),
        runtime=_empty_phase(),
        warnings=[],
        start_cmd="/etc/init.d/mongod start && /etc/init.d/example-app start",
    )
    s = tj.model_dump_json(by_alias=True)
    tj2 = TraceJson.model_validate_json(s)
    assert tj2 == tj
    assert tj2.start_cmd == "/etc/init.d/mongod start && /etc/init.d/example-app start"


def test_tracejson_start_cmd_defaults_to_none_for_backwards_compat() -> None:
    # Old v1 trace.json had no start_cmd field -- parsing must still succeed
    # with start_cmd resolved to None via the Pydantic default.
    payload = {
        "schema_version": 1,
        "phase_marker_ns": 123,
        "marker": "COMPLETE",
        "install": _empty_phase().model_dump(),
        "runtime": _empty_phase().model_dump(),
        "warnings": [],
    }
    tj = TraceJson.model_validate(payload)
    assert tj.start_cmd is None


def _runtime() -> PolicyRuntime:
    return PolicyRuntime(
        volumes=[],
        tmpfs=[],
        binds_ro=[],
        publish_ports=[],
        caps_add=[],
        seccomp_syscalls=[],
        read_only_rootfs=False,
    )


def test_policy_schema_version_is_three() -> None:
    policy = PolicyJson(
        image=PolicyImage(
            base="ubuntu:24.04",
            installer=ExecutableInstaller(path="/installer"),
            post_install_cleanup=[],
            systemd_required=False,
            entrypoint=["/x"],
        ),
        runtime=_runtime(),
    )
    assert policy.schema_version == 3


def test_executable_installer_roundtrips_via_json() -> None:
    policy = PolicyJson(
        image=PolicyImage(
            base="ubuntu:24.04",
            installer=ExecutableInstaller(path="/installer"),
            post_install_cleanup=[],
            systemd_required=False,
            entrypoint=["/x"],
        ),
        runtime=_runtime(),
    )
    blob = policy.model_dump_json()
    back = PolicyJson.model_validate_json(blob)
    assert isinstance(back.image.installer, ExecutableInstaller)
    assert back.image.installer.path == "/installer"


def test_deb_installer_roundtrips_via_json() -> None:
    policy = PolicyJson(
        image=PolicyImage(
            base="ubuntu:24.04",
            installer=DebInstaller(paths=["/tmp/foo.deb", "/tmp/bar.deb"]),
            apt_sources=["deb http://example/x noble main"],
            apt_keys=["example.gpg"],
            post_install_cleanup=["/tmp/*.deb"],
            systemd_required=False,
            entrypoint=["/x"],
        ),
        runtime=_runtime(),
    )
    blob = policy.model_dump_json()
    back = PolicyJson.model_validate_json(blob)
    assert isinstance(back.image.installer, DebInstaller)
    assert back.image.installer.paths == ["/tmp/foo.deb", "/tmp/bar.deb"]
    assert back.image.apt_sources == ["deb http://example/x noble main"]
    assert back.image.apt_keys == ["example.gpg"]


def test_installer_path_field_is_rejected() -> None:
    """The legacy installer_path field is gone; extra='forbid' rejects it."""
    raw = json.dumps(
        {
            "schema_version": 3,
            "image": {
                "base": "ubuntu:24.04",
                "installer_path": "/installer",
                "apt_packages": [],
                "post_install_cleanup": [],
                "systemd_required": False,
                "entrypoint": ["/x"],
            },
            "runtime": {
                "volumes": [],
                "tmpfs": [],
                "binds_ro": [],
                "publish_ports": [],
                "caps_add": [],
                "caps_drop": ["ALL"],
                "seccomp_syscalls": [],
                "read_only_rootfs": False,
                "no_new_privileges": True,
            },
            "warnings": [],
        }
    )
    with pytest.raises(ValidationError):
        PolicyJson.model_validate_json(raw)
