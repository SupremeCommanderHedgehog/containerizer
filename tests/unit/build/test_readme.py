"""Golden tests for the README rewrite that appends the Verify results section."""

from __future__ import annotations

from pathlib import Path

from containerizer.analyze.schema import TracePath
from containerizer.build.readme import rewrite_readme_with_verify
from containerizer.verify.schema import VerifyDiff, VerifyReport

FIXTURES = Path("tests/fixtures/build")


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _empty_report() -> VerifyReport:
    return VerifyReport(
        original_marker="COMPLETE",
        observed_marker="COMPLETE",
        diff=VerifyDiff(new_paths=[], new_ports=[], new_caps=[], new_syscalls=[], new_execs=[]),
    )


def _populated_report() -> VerifyReport:
    return VerifyReport(
        original_marker="COMPLETE",
        observed_marker="COMPLETE",
        diff=VerifyDiff(
            new_paths=[
                TracePath(  # type: ignore[call-arg]
                    path="/etc/foo", ops=["read"], class_="host_config_ro", by=["app"]
                )
            ],
            new_ports=[],
            new_caps=["CAP_SYS_CHROOT"],
            new_syscalls=[437],
            new_execs=[],
        ),
    )


def test_rewrite_with_empty_diff_matches_golden() -> None:
    before = _read(FIXTURES / "readme-before.md")
    after = rewrite_readme_with_verify(before, verify=_empty_report(), skip_reason=None)
    assert after == _read(FIXTURES / "expected" / "readme-empty-diff.md")


def test_rewrite_with_populated_diff_matches_golden() -> None:
    before = _read(FIXTURES / "readme-before.md")
    after = rewrite_readme_with_verify(before, verify=_populated_report(), skip_reason=None)
    assert after == _read(FIXTURES / "expected" / "readme-with-diff.md")


def test_rewrite_sentinel_skip_matches_golden() -> None:
    before = _read(FIXTURES / "readme-before.md")
    after = rewrite_readme_with_verify(before, verify=None, skip_reason="sentinel")
    assert after == _read(FIXTURES / "expected" / "readme-sentinel-skip.md")


def test_rewrite_flag_skip_matches_golden() -> None:
    before = _read(FIXTURES / "readme-before.md")
    after = rewrite_readme_with_verify(before, verify=None, skip_reason="flag")
    assert after == _read(FIXTURES / "expected" / "readme-flag-skip.md")


def test_rewrite_is_idempotent() -> None:
    before = _read(FIXTURES / "readme-before.md")
    once = rewrite_readme_with_verify(before, verify=_populated_report(), skip_reason=None)
    twice = rewrite_readme_with_verify(once, verify=_populated_report(), skip_reason=None)
    assert once == twice


def test_rewrite_both_none_returns_unchanged() -> None:
    before = _read(FIXTURES / "readme-before.md")
    after = rewrite_readme_with_verify(before, verify=None, skip_reason=None)
    assert after == before
