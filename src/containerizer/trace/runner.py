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

        /sys/kernel/{debug,tracing,btf} are all bind-mounted so bpftrace
        and bcc inside the container can reach the host kernel's tracing
        infrastructure:

        * /sys/kernel/debug — older kernels host tracefs here as
          /sys/kernel/debug/tracing.
        * /sys/kernel/tracing — modern kernels mount tracefs separately
          at this path.
        * /sys/kernel/btf — bcc compiles its BPF programs against the
          running kernel's BTF (`vmlinux`) so it works without bundled
          kernel headers.

        /lib/modules and /usr/src are also bound read-only so bcc and
        bpftrace can find the running kernel's headers when CO-RE is
        not enough (e.g., for bpftrace scripts that #include <linux/in.h>).
        The host needs `linux-headers-$(uname -r)` installed for these
        to be useful.
        """
        return [
            "podman",
            "run",
            "--rm",
            "-i",
            "--privileged",
            "--pid=host",
            "-v",
            "/sys/kernel/debug:/sys/kernel/debug",
            "-v",
            "/sys/kernel/tracing:/sys/kernel/tracing",
            "-v",
            "/sys/kernel/btf:/sys/kernel/btf",
            "-v",
            "/lib/modules:/lib/modules:ro",
            "-v",
            "/usr/src:/usr/src:ro",
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
