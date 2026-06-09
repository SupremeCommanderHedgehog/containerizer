"""Append the Verify results section to an M4-shape README.

Idempotent: re-running on already-rewritten text replaces the previous
Verify results section, never duplicates it.
"""

from __future__ import annotations

import re
from typing import Literal

from containerizer.verify.schema import VerifyReport

VERIFY_SECTION_HEADER = "## Verify results"
NEXT_STEPS_HEADER = "## Next steps"
_MAX_DETAILS = 5


def rewrite_readme_with_verify(
    readme_text: str,
    *,
    verify: VerifyReport | None,
    skip_reason: Literal["sentinel", "flag"] | None,
) -> str:
    """Return the README with a `## Verify results` section inserted.

    Section placement: immediately before the trailing `## Next steps`
    section if present, else appended at the end. Existing Verify results
    sections are stripped first to guarantee idempotency.
    """
    if verify is None and skip_reason is None:
        return readme_text

    stripped = _strip_existing_verify_section(readme_text)
    section = _render_section(verify=verify, skip_reason=skip_reason)
    return _insert_before_next_steps(stripped, section)


def _strip_existing_verify_section(text: str) -> str:
    pattern = re.compile(
        rf"{re.escape(VERIFY_SECTION_HEADER)}.*?(?=^## |\Z)",
        flags=re.DOTALL | re.MULTILINE,
    )
    return pattern.sub("", text)


def _insert_before_next_steps(text: str, section: str) -> str:
    if NEXT_STEPS_HEADER in text:
        head, _, tail = text.partition(NEXT_STEPS_HEADER)
        head = head.rstrip() + "\n\n"
        return head + section.rstrip() + "\n\n" + NEXT_STEPS_HEADER + tail
    return text.rstrip() + "\n\n" + section.rstrip() + "\n"


def _render_section(
    *,
    verify: VerifyReport | None,
    skip_reason: Literal["sentinel", "flag"] | None,
) -> str:
    if skip_reason == "sentinel":
        return (
            f"{VERIFY_SECTION_HEADER}\n\n"
            "Verify skipped: no entrypoint detected. Re-run with "
            "`--start-cmd '<cmd>'` to enable the verify pass.\n"
        )
    if skip_reason == "flag":
        return f"{VERIFY_SECTION_HEADER}\n\nVerify skipped: `--skip-verify` was set.\n"

    assert verify is not None  # narrowed by caller
    diff = verify.diff
    total = (
        len(diff.new_paths)
        + len(diff.new_ports)
        + len(diff.new_caps)
        + len(diff.new_syscalls)
        + len(diff.new_execs)
    )
    if total == 0:
        return f"{VERIFY_SECTION_HEADER}\n\nNo new events observed.\n"

    rows = [
        ("New paths", len(diff.new_paths), [f"`{p.path}`" for p in diff.new_paths]),
        ("New ports", len(diff.new_ports), [f"{p.port}/{p.proto}" for p in diff.new_ports]),
        ("New caps", len(diff.new_caps), [f"`{c}`" for c in diff.new_caps]),
        ("New syscalls", len(diff.new_syscalls), [str(s) for s in diff.new_syscalls]),
        ("New execs", len(diff.new_execs), [f"`{e}`" for e in diff.new_execs]),
    ]

    lines = [
        VERIFY_SECTION_HEADER,
        "",
        "The generated container was rebuilt and exercised under strict policy. "
        "These entries appeared in the verify trace but not the original:",
        "",
        "| Category | Count | Details |",
        "|---|---|---|",
    ]
    for label, count, details in rows:
        shown = ", ".join(details[:_MAX_DETAILS])
        if len(details) > _MAX_DETAILS:
            shown += ", ..."
        if not shown:
            shown = "-"
        lines.append(f"| {label} | {count} | {shown} |")
    lines.append("")
    lines.append("Full diff: see `verify.json`.")
    lines.append("")
    return "\n".join(lines)
