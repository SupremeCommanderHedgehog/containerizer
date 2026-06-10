"""Construct and exec the `podman run` for the trace sandbox.

The runner supports two modes:

* `mode="install"` (default): the M2 behavior. Mounts the installer at
  /installer and runs trace-orchestrator.sh. Interactive (-i) so the
  user can press Enter when the smoke test is done.

* `mode="verify"` (M6): no installer; bind-mounts a saved image tarball
  and the final seccomp profile, sets env vars consumed by
  verify-orchestrator.sh, passes `--mode verify` to the orchestrator.
  Non-interactive (no -i) because the soak window is fixed.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


class OutputDirNotEmpty(RuntimeError):
    """Raised when the output dir already has a COMPLETE or PARTIAL marker."""


@dataclass(frozen=True)
class TraceRunner:
    """Builds the `podman run` argv and execs it for one trace phase."""

    image_tag: str
    installer: Path | None
    output_dir: Path
    mode: Literal["install", "verify"] = "install"
    # Install mode only. When True, append `-t` to `podman run` so the
    # container gets a TTY -- needed for interactive installers like UniFi
    # that abort if their stdin prompt detects no terminal. Ignored in
    # verify mode (which is non-interactive by design).
    tty: bool = False

    # Verify-mode-only fields. All default to None; validated in __post_init__.
    verify_image_tar: Path | None = None
    verify_image_tag: str | None = None
    verify_run_flags: tuple[str, ...] = field(default_factory=tuple)
    verify_soak_seconds: int | None = None
    verify_seccomp_path: Path | None = None

    def __post_init__(self) -> None:
        if self.mode == "install":
            if self.installer is None:
                raise ValueError("install mode requires installer")
        else:
            missing = [
                name
                for name, val in (
                    ("verify_image_tar", self.verify_image_tar),
                    ("verify_image_tag", self.verify_image_tag),
                    ("verify_soak_seconds", self.verify_soak_seconds),
                    ("verify_seccomp_path", self.verify_seccomp_path),
                )
                if val is None
            ]
            if missing:
                raise ValueError(f"verify mode requires: {', '.join(missing)}")

    def argv(self) -> list[str]:
        """Pure: returns the podman command without executing it."""
        if self.mode == "install":
            return self._install_argv()
        return self._verify_argv()

    def _install_argv(self) -> list[str]:
        """Install-mode argv (M2 behavior).

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
        assert self.installer is not None
        # Always allocate a TTY. The systemd-PID-1 runner (#90) wires the
        # trace unit's stdio to /dev/console which only exists when podman
        # allocates a pty. Without -t the container has no /dev/console and
        # systemd fails the unit with "Failed at step STDIN". On non-TTY
        # parents (CI, pipes) the pty just sees EOF, which the orchestrator's
        # `read -r _ || true` handles. self.tty stays as the signal of
        # whether the *user's* stdin is a TTY, but argv is unconditional.
        return [
            "podman",
            "run",
            "--rm",
            "-i",
            "-t",
            "--privileged",
            "--systemd=always",
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
            "-e",
            "CONTAINERIZER_MODE=install",
            "-e",
            "CONTAINERIZER_INSTALLER=/installer",
            self.image_tag,
        ]

    def _verify_argv(self) -> list[str]:
        """Verify-mode argv (M6 retrace)."""
        assert self.verify_image_tar is not None
        assert self.verify_image_tag is not None
        assert self.verify_soak_seconds is not None
        assert self.verify_seccomp_path is not None

        run_flags_env = "VERIFY_RUN_FLAGS=" + " ".join(self.verify_run_flags)

        # Always allocate a TTY (same reasoning as _install_argv: the
        # systemd unit requires /dev/console). Verify mode has no user
        # interaction, but the pty is still needed for the unit to start.
        return [
            "podman",
            "run",
            "--rm",
            "-i",
            "-t",
            "--privileged",
            "--systemd=always",
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
            f"{self.verify_image_tar.resolve()}:/work/verify/image.tar:ro",
            "-v",
            f"{self.verify_seccomp_path.resolve()}:/work/verify/seccomp.json:ro",
            "-v",
            f"{self.output_dir.resolve()}:/work/trace",
            "-e",
            f"VERIFY_IMAGE_TAG={self.verify_image_tag}",
            "-e",
            f"VERIFY_SOAK_SECONDS={self.verify_soak_seconds}",
            "-e",
            run_flags_env,
            "-e",
            "CONTAINERIZER_MODE=verify",
            self.image_tag,
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
