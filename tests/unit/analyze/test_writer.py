"""Tests for analyze.writer."""

from __future__ import annotations

import json
from pathlib import Path

from containerizer.analyze.schema import (
    ExecutableInstaller,
    PolicyImage,
    PolicyJson,
    PolicyRuntime,
    TraceJson,
    TracePath,
    TracePhase,
)
from containerizer.analyze.writer import write_policy_json, write_trace_json

EMPTY_PHASE = TracePhase(
    duration_s=0.0,
    paths=[],
    ports=[],
    outbound=[],
    caps=[],
    syscalls=[],
    execs=[],
)


def _trace_with_path() -> TraceJson:
    return TraceJson(
        phase_marker_ns=12,
        marker="COMPLETE",
        install=EMPTY_PHASE,
        runtime=TracePhase(
            duration_s=1.0,
            paths=[
                TracePath(  # type: ignore[call-arg]
                    path="/x", ops=["read"], class_="image_static", by=["a"]
                )
            ],
            ports=[],
            outbound=[],
            caps=[],
            syscalls=[],
            execs=[],
        ),
        warnings=[],
    )


def _policy_minimal() -> PolicyJson:
    return PolicyJson(
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


def test_trace_writer_pretty_with_class_alias(tmp_path: Path) -> None:
    out = tmp_path / "trace.json"
    write_trace_json(_trace_with_path(), out)
    text = out.read_text(encoding="utf-8")
    assert "  " in text  # pretty
    obj = json.loads(text)
    assert obj["schema_version"] == 1
    assert obj["runtime"]["paths"][0]["class"] == "image_static"
    assert "class_" not in obj["runtime"]["paths"][0]


def test_policy_writer_round_trip(tmp_path: Path) -> None:
    out = tmp_path / "policy.json"
    write_policy_json(_policy_minimal(), out)
    obj = json.loads(out.read_text())
    pj = PolicyJson.model_validate(obj)
    assert pj == _policy_minimal()
