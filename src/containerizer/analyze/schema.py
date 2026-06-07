"""Pydantic models for the analyzer's trace.json and policy.json outputs.

This module is the contract every other analyze/ module depends on.
Nothing in analyze/ should import from outside this file's siblings;
everything imports from here.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class TracePath(BaseModel):
    """One aggregated path entry in trace.json.

    The aggregator collapses many per-file events into one entry keyed
    on the mount-relevant root (see spec §5.3).
    """

    model_config = ConfigDict(populate_by_name=True)

    path: str
    ops: list[Literal["read", "write", "mkdir", "stat", "exec"]]
    class_: Literal[
        "image_static",
        "persistent_rw",
        "ephemeral_rw",
        "host_config_ro",
        "device",
        "unknown_rw",
        "unknown_ro",
    ] = Field(alias="class", serialization_alias="class")
    by: list[str]


class TracePort(BaseModel):
    port: int
    proto: Literal["tcp", "udp", "unix", "?"]
    by: str
    ipv4: bool
    ipv6: bool


class TraceOutbound(BaseModel):
    daddr: str
    dport: int
    comm: str


class TracePhase(BaseModel):
    duration_s: float
    exit: int | None = None
    paths: list[TracePath]
    ports: list[TracePort]
    outbound: list[TraceOutbound]
    caps: list[str]
    syscalls: list[int]
    execs: list[str]


class TraceJson(BaseModel):
    schema_version: Literal[1] = 1
    phase_marker_ns: int | None
    marker: Literal["COMPLETE", "PARTIAL"]
    install: TracePhase
    runtime: TracePhase
    warnings: list[str]


class PolicyImage(BaseModel):
    base: str
    apt_packages: list[str]
    installer_path: str = "/installer"
    post_install_cleanup: list[str]
    systemd_required: bool
    entrypoint: list[str]


class PolicyVolume(BaseModel):
    name: str
    mount: str


class PolicyPort(BaseModel):
    host: int
    container: int
    proto: Literal["tcp", "udp"]


class PolicyRuntime(BaseModel):
    volumes: list[PolicyVolume]
    tmpfs: list[str]
    binds_ro: list[str]
    publish_ports: list[PolicyPort]
    caps_add: list[str]
    caps_drop: list[str] = ["ALL"]
    seccomp_syscalls: list[int]
    read_only_rootfs: bool
    no_new_privileges: bool = True


class PolicyJson(BaseModel):
    schema_version: Literal[1] = 1
    image: PolicyImage
    runtime: PolicyRuntime
