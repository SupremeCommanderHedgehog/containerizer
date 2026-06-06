"""ELF binary probe.

Reads architecture, bit width, endianness, interpreter, dynamic-vs-static, NEEDED
libraries, and minimum glibc requirement from a Linux ELF file using pyelftools.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from elftools.elf.dynamic import DynamicSection
from elftools.elf.elffile import ELFFile

from containerizer.probe.schema import ElfProbe

_ARCH_FROM_E_MACHINE: dict[str, str] = {
    "EM_X86_64": "x86_64",
    "EM_386": "i386",
    "EM_AARCH64": "aarch64",
    "EM_ARM": "arm",
    "EM_PPC64": "ppc64",
    "EM_PPC": "ppc",
    "EM_RISCV": "riscv",
}


def probe_elf(path: Path) -> ElfProbe:
    """Inspect *path* as an ELF binary and return a typed probe."""
    with path.open("rb") as fh:
        elf = ELFFile(fh)
        arch = _ARCH_FROM_E_MACHINE.get(elf["e_machine"], elf["e_machine"])
        bit: Literal[32, 64] = 64 if elf.elfclass == 64 else 32
        endianness: Literal["little", "big"] = (
            "little" if elf.little_endian else "big"
        )
        interpreter = _read_interpreter(elf)
        needed_libs, has_dynamic = _read_dynamic(elf)
        is_static = interpreter is None and not has_dynamic
        glibc_min = _read_glibc_min(elf)
    return ElfProbe(
        arch=arch,
        bit=bit,
        endianness=endianness,
        interpreter=interpreter,
        is_static=is_static,
        needed_libs=needed_libs,
        glibc_min=glibc_min,
    )


def _read_interpreter(elf: ELFFile) -> str | None:
    for segment in elf.iter_segments():
        if segment["p_type"] == "PT_INTERP":
            raw: Any = segment.get_interp_name()  # type: ignore[attr-defined]
            return raw if isinstance(raw, str) else raw.decode("utf-8", "replace")
    return None


def _read_dynamic(elf: ELFFile) -> tuple[list[str], bool]:
    needed: list[str] = []
    section = elf.get_section_by_name(".dynamic")
    if not isinstance(section, DynamicSection):
        return needed, False
    for tag in section.iter_tags():
        if tag.entry.d_tag == "DT_NEEDED":
            needed.append(str(tag.needed))  # type: ignore[attr-defined]
    return needed, True


def _read_glibc_min(elf: ELFFile) -> str | None:
    section = elf.get_section_by_name(".gnu.version_r")
    if section is None:
        return None
    best: tuple[int, int] = (0, 0)
    for verneed, vernaux_iter in section.iter_versions():  # type: ignore[attr-defined]
        if verneed.name != "libc.so.6":
            continue
        for vernaux in vernaux_iter:
            name = vernaux.name
            if not name.startswith("GLIBC_"):
                continue
            parts = name.removeprefix("GLIBC_").split(".")
            try:
                ver = (int(parts[0]), int(parts[1]) if len(parts) > 1 else 0)
            except ValueError:
                continue
            best = max(best, ver)
    return f"{best[0]}.{best[1]}" if best != (0, 0) else None
