"""Lazy podman build of the sandbox runner image.

The runner image is tagged by the SHA-256 of its `sandbox/runner_image/`
content so a rebuild fires only when the inputs change. Tag format:
    localhost/containerizer-runner:sha-<first 8 hex chars>
"""

from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import IO


@dataclass(frozen=True)
class RunnerImage:
    """The sandbox runner image, addressed by sandbox-dir content hash."""

    sandbox_dir: Path

    @cached_property
    def tag(self) -> str:
        """Container tag derived from the sandbox dir's content.

        Walks the sandbox dir, sorts files by relative path (lexicographic,
        forward-slash-normalised), and feeds `relpath_bytes + b"\\x00" +
        content_bytes` for each file into a single SHA-256. First 8 hex chars
        of the digest become the tag suffix.
        """
        digest = hashlib.sha256()
        for path in sorted(
            (p for p in self.sandbox_dir.rglob("*") if p.is_file()),
            key=lambda p: p.relative_to(self.sandbox_dir).as_posix(),
        ):
            rel = path.relative_to(self.sandbox_dir).as_posix().encode("utf-8")
            digest.update(rel)
            digest.update(b"\x00")
            digest.update(path.read_bytes())
        return f"localhost/containerizer-runner:sha-{digest.hexdigest()[:8]}"

    def exists(self) -> bool:
        """Whether the runner image is in the local podman image store."""
        result = subprocess.run(
            ["podman", "image", "exists", self.tag],
            check=False,
        )
        return result.returncode == 0

    def build(self, *, stderr: IO[str] | None) -> None:
        """Run `podman build` for this image, streaming stderr to `stderr`."""
        subprocess.run(
            ["podman", "build", "-t", self.tag, str(self.sandbox_dir)],
            check=True,
            stderr=stderr,
        )
