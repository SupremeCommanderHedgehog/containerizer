"""Tests for the RunnerImage class."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from containerizer.trace.image import RunnerImage


def _write_sandbox(root: Path) -> Path:
    """Build a minimal sandbox dir matching the production layout."""
    sandbox = root / "sandbox" / "runner_image"
    (sandbox / "collectors").mkdir(parents=True)
    (sandbox / "Containerfile").write_text("FROM fedora:41\n", encoding="utf-8")
    (sandbox / "trace-orchestrator.sh").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    (sandbox / "collectors" / "open.bt").write_text("BEGIN{}\n", encoding="utf-8")
    return sandbox


def test_tag_is_localhost_runner_with_sha_prefix(tmp_path: Path) -> None:
    sandbox = _write_sandbox(tmp_path)
    img = RunnerImage(sandbox_dir=sandbox)
    assert re.fullmatch(r"localhost/containerizer-runner:sha-[0-9a-f]{8}", img.tag)


def test_tag_is_deterministic_per_content(tmp_path: Path) -> None:
    sandbox_a = _write_sandbox(tmp_path / "a")
    sandbox_b = _write_sandbox(tmp_path / "b")
    assert RunnerImage(sandbox_dir=sandbox_a).tag == RunnerImage(sandbox_dir=sandbox_b).tag


def test_tag_changes_when_content_changes(tmp_path: Path) -> None:
    sandbox = _write_sandbox(tmp_path)
    tag_before = RunnerImage(sandbox_dir=sandbox).tag
    (sandbox / "Containerfile").write_text("FROM fedora:42\n", encoding="utf-8")
    # cached_property: a fresh instance picks up the change.
    tag_after = RunnerImage(sandbox_dir=sandbox).tag
    assert tag_before != tag_after


@patch("containerizer.trace.image.subprocess.run")
def test_exists_returns_true_when_podman_succeeds(mock_run: MagicMock, tmp_path: Path) -> None:
    mock_run.return_value.returncode = 0
    sandbox = _write_sandbox(tmp_path)
    assert RunnerImage(sandbox_dir=sandbox).exists() is True
    mock_run.assert_called_once()
    args = mock_run.call_args.args[0]
    assert args[:3] == ["podman", "image", "exists"]


@patch("containerizer.trace.image.subprocess.run")
def test_exists_returns_false_when_podman_returns_nonzero(
    mock_run: MagicMock, tmp_path: Path
) -> None:
    mock_run.return_value.returncode = 1
    sandbox = _write_sandbox(tmp_path)
    assert RunnerImage(sandbox_dir=sandbox).exists() is False


@patch("containerizer.trace.image.subprocess.run")
def test_build_invokes_podman_build_with_tag_and_sandbox(
    mock_run: MagicMock, tmp_path: Path
) -> None:
    mock_run.return_value.returncode = 0
    sandbox = _write_sandbox(tmp_path)
    img = RunnerImage(sandbox_dir=sandbox)
    img.build(stderr=None)
    args = mock_run.call_args.args[0]
    assert args[:3] == ["podman", "build", "-t"]
    assert args[3] == img.tag
    assert args[-1] == str(sandbox)


@patch("containerizer.trace.image.subprocess.run")
def test_build_raises_on_nonzero_exit(mock_run: MagicMock, tmp_path: Path) -> None:
    mock_run.side_effect = subprocess.CalledProcessError(1, ["podman", "build"])
    sandbox = _write_sandbox(tmp_path)
    img = RunnerImage(sandbox_dir=sandbox)
    with pytest.raises(subprocess.CalledProcessError):
        img.build(stderr=None)
