"""Base-image suggestion derived from probe metadata.

The picker is intentionally conservative: choose an Ubuntu LTS whose glibc is
new enough to run the binary. The user can always override with --base-image.
"""

from __future__ import annotations

from containerizer.probe.schema import BaseImageSuggestion, ElfProbe


def suggest_base_image(elf: ElfProbe) -> BaseImageSuggestion:
    reasons: list[str] = []
    image = _pick_for_glibc(elf.glibc_min, reasons)
    reasons.append(f"architecture: {elf.arch}")
    return BaseImageSuggestion(image=image, reasons=reasons)


def _pick_for_glibc(glibc_min: str | None, reasons: list[str]) -> str:
    if glibc_min is None:
        reasons.append("no glibc requirement detected; picked ubuntu:24.04 as default")
        return "ubuntu:24.04"
    try:
        major_s, minor_s = glibc_min.split(".", 1)
        major = int(major_s)
        minor = int(minor_s)
    except (ValueError, AttributeError):
        reasons.append(
            f"could not parse glibc version '{glibc_min}'; picked ubuntu:24.04 as default"
        )
        return "ubuntu:24.04"
    if (major, minor) >= (2, 35):
        reasons.append(f"glibc {glibc_min} requires Ubuntu 22.04+; picked 24.04 LTS")
        return "ubuntu:24.04"
    if (major, minor) >= (2, 31):
        reasons.append(f"glibc {glibc_min} fits Ubuntu 22.04 LTS")
        return "ubuntu:22.04"
    reasons.append(f"glibc {glibc_min} fits Ubuntu 20.04 LTS")
    return "ubuntu:20.04"
