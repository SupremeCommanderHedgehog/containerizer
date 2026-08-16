#!/usr/bin/env python3
"""Regenerate src/containerizer/generate/syscall_table.py from the upstream
Linux kernel's arch/x86/entry/syscalls/syscall_64.tbl.

Not run in CI. Invoke by hand whenever the kernel adds new syscalls and you
want the bundled table to cover them. The currently-pinned kernel tag is the
constant TBL_URL at the top.

Usage:
    python sandbox/regen_syscall_table.py
"""

from __future__ import annotations

import re
import sys
import urllib.request
from pathlib import Path

# Pin to a specific kernel tag so regeneration is reproducible. Bump as needed.
KERNEL_TAG = "v6.6"
TBL_URL = (
    f"https://raw.githubusercontent.com/torvalds/linux/{KERNEL_TAG}/"
    f"arch/x86/entry/syscalls/syscall_64.tbl"
)

OUTPUT_PATH = (
    Path(__file__).resolve().parent.parent
    / "src"
    / "containerizer"
    / "generate"
    / "syscall_table.py"
)

# syscall_64.tbl lines look like:
#   0       common  read                    sys_read
#   1       common  write                   sys_write
# We want columns 1 (number), 2 (abi), 3 (name).
# Skip lines starting with '#', empty lines, and abi=='x32' (32-bit compat).
LINE_RE = re.compile(r"^\s*(\d+)\s+(\S+)\s+(\S+)\s+\S+\s*(?:#.*)?$")


def fetch_table(url: str) -> str:
    with urllib.request.urlopen(url, timeout=30) as resp:
        return resp.read().decode("utf-8")


def parse(text: str) -> dict[int, str]:
    table: dict[int, str] = {}
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = LINE_RE.match(line)
        if not match:
            continue
        sysno, abi, name = match.group(1), match.group(2), match.group(3)
        if abi == "x32":
            continue
        table[int(sysno)] = name
    return table


def render(table: dict[int, str], source_tag: str) -> str:
    lines = [
        '"""Bundled x86_64 syscall_id -> name lookup table.',
        "",
        "DO NOT HAND-EDIT. Regenerate via:",
        "    python sandbox/regen_syscall_table.py",
        "",
        f"Source: torvalds/linux@{source_tag} arch/x86/entry/syscalls/syscall_64.tbl",
        '"""',
        "",
        "from __future__ import annotations",
        "",
        "SYSCALL_NAMES: dict[int, str] = {",
    ]
    for sysno in sorted(table):
        # Use double-quoted strings so the rendered file matches ruff format
        # without needing a follow-up `ruff format` invocation.
        lines.append(f'    {sysno}: "{table[sysno]}",')
    lines.append("}")
    return "\n".join(lines) + "\n"


def main() -> int:
    print(f"fetching {TBL_URL}", file=sys.stderr)
    text = fetch_table(TBL_URL)
    table = parse(text)
    print(f"parsed {len(table)} entries", file=sys.stderr)
    OUTPUT_PATH.write_text(render(table, KERNEL_TAG), encoding="utf-8")
    print(f"wrote {OUTPUT_PATH}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
