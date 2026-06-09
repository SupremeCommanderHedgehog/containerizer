"""Shared orchestration for rendering the M4 artifact set to disk.

Both the standalone `containerizer generate` subcommand and the M6 `build`
pipeline's generate phase need the same logic: render seccomp + README
always, render Containerfile + Quadlet only when the policy is non-sentinel.
This module hoists that logic out of the two CLI surfaces so they share
exactly one implementation.

This module is the disk-touching layer for the generate phase -- the
"only `cli.py` touches disk" guideline from M3/M4/M5 does not apply here;
this *is* the layer that `cli.py` and `pipeline.py` delegate filesystem
work to. It still avoids subprocess and stderr output, leaving warning
emission to its callers.
"""

from __future__ import annotations

from pathlib import Path

from containerizer.analyze.derive import SENTINEL_ENTRYPOINT
from containerizer.analyze.schema import PolicyJson
from containerizer.generate.containerfile import render_containerfile
from containerizer.generate.quadlet import render_quadlet
from containerizer.generate.readme import render_readme
from containerizer.generate.seccomp import render_seccomp


def generate_all(policy: PolicyJson, name: str, out_dir: Path) -> list[int]:
    """Render the M4 artifact set into `out_dir`.

    Writes:
      * `seccomp.json`                (always)
      * `README.md`                   (always; flagged SKIPPED on sentinel)
      * `Containerfile`               (only when non-sentinel)
      * `<name>.container`            (only when non-sentinel)

    Returns the list of syscall IDs that were dropped because they were
    not found in the bundled syscall table. Callers decide whether to
    surface that as a stderr warning.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    is_sentinel = policy.image.entrypoint == [SENTINEL_ENTRYPOINT]

    seccomp_bytes, unknown_ids = render_seccomp(policy)
    (out_dir / "seccomp.json").write_bytes(seccomp_bytes)

    if not is_sentinel:
        (out_dir / "Containerfile").write_text(
            render_containerfile(policy),
            encoding="utf-8",
        )
        (out_dir / f"{name}.container").write_text(
            render_quadlet(policy, name),
            encoding="utf-8",
        )

    (out_dir / "README.md").write_text(
        render_readme(policy, name, skipped=is_sentinel, unknown_syscall_ids=unknown_ids),
        encoding="utf-8",
    )

    return unknown_ids
