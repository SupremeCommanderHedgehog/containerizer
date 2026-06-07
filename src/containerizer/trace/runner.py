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
        """Pure: returns the podman command without executing it."""
        return [
            "podman",
            "run",
            "--rm",
            "-it",
            "--privileged",
            "--pid=host",
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
