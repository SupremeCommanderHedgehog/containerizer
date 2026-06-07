"""Construct and exec the `podman run` for the trace sandbox."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


class OutputDirNotEmpty(RuntimeError):
    """Raised when the output dir already has a COMPLETE or PARTIAL marker."""


@dataclass(frozen=True)
class TraceRunner:
    """Builds the `podman run` argv and execs it."""

    image_tag: str
    installer: Path
    output_dir: Path

    def argv(self) -> list[str]:
        """Pure: returns the podman command without executing it.

        /sys/kernel/debug and /sys/kernel/tracing are both bind-mounted so
        bpftrace inside the container can attach to syscall tracepoints.
        On older kernels tracefs lives at /sys/kernel/debug/tracing; on
        modern kernels it has its own mount at /sys/kernel/tracing while
        debugfs at /sys/kernel/debug remains separate. Mounting both keeps
        bpftrace working across the range.
        """
        return [
            "podman",
            "run",
            "--rm",
            "-it",
            "--privileged",
            "--pid=host",
            "-v",
            "/sys/kernel/debug:/sys/kernel/debug",
            "-v",
            "/sys/kernel/tracing:/sys/kernel/tracing",
            "-v",
            f"{self.installer.resolve()}:/installer:ro",
            "-v",
            f"{self.output_dir.resolve()}:/work/trace",
            self.image_tag,
            "/installer",
        ]

    def validate_output_dir(self, *, force: bool) -> None:
        """Refuse to overwrite an existing trace unless `force` is set."""
        for marker in ("COMPLETE", "PARTIAL"):
            if (self.output_dir / marker).exists() and not force:
                raise OutputDirNotEmpty(
                    f"{self.output_dir} already contains a {marker} marker. "
                    f"Use --force to replace or pick a fresh directory."
                )

    def run(self) -> int:
        """Exec the podman command in the foreground."""
        result = subprocess.run(self.argv(), check=False)
        return result.returncode
