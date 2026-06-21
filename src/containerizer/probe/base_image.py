"""Base-image suggestion derived from probe metadata.

The picker is intentionally conservative: choose an Ubuntu LTS whose glibc
is new enough to run the binary (ELF), or whose package universe matches the
deb's declared architecture (Debian package).
"""

from __future__ import annotations

from containerizer.probe.schema import BaseImageSuggestion, DebProbe, ElfProbe


def suggest_base_image(probe: ElfProbe | DebProbe) -> BaseImageSuggestion:
    if isinstance(probe, DebProbe):
        return _suggest_for_deb(probe)
    return _suggest_for_elf(probe)


_SUPPORTED_DEB_ARCHS = {"amd64", "arm64", "all"}


def _suggest_for_deb(deb: DebProbe) -> BaseImageSuggestion:
    if deb.arch not in _SUPPORTED_DEB_ARCHS:
        raise ValueError(
            f"unsupported .deb architecture {deb.arch!r}; supported: "
            f"{sorted(_SUPPORTED_DEB_ARCHS)}"
        )
    reasons: list[str] = []
    if deb.arch == "all":
        reasons.append("architecture-independent deb; picked ubuntu:24.04 LTS")
    else:
        reasons.append(f"deb architecture {deb.arch}; picked ubuntu:24.04 LTS")
    return BaseImageSuggestion(image="ubuntu:24.04", reasons=reasons)


def _suggest_for_elf(elf: ElfProbe) -> BaseImageSuggestion:
    reasons: list[str] = []
    image = _pick_for_glibc(elf.glibc_min, reasons)
    reasons.append(f"architecture: {elf.arch}")
    return BaseImageSuggestion(image=image, reasons=reasons)


def _pick_for_glibc(glibc_min: str | None, reasons: list[str]) -> str:
    if glibc_min is None:
        reasons.append("no glibc requirement detected; picked ubuntu:24.04")
        return "ubuntu:24.04"
    try:
        major_s, minor_s = glibc_min.split(".", 1)
        major = int(major_s)
        minor = int(minor_s)
    except (ValueError, AttributeError):
        reasons.append(f"could not parse glibc version '{glibc_min}'; picked ubuntu:24.04")
        return "ubuntu:24.04"
    if (major, minor) > (2, 35):
        reasons.append(f"glibc {glibc_min} requires Ubuntu 24.04 LTS or newer")
        return "ubuntu:24.04"
    if (major, minor) >= (2, 31):
        reasons.append(f"glibc {glibc_min} fits Ubuntu 22.04 LTS")
        return "ubuntu:22.04"
    reasons.append(f"glibc {glibc_min} fits Ubuntu 20.04 LTS")
    return "ubuntu:20.04"
