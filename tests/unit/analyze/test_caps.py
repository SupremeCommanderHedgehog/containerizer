"""Tests for analyze.caps."""

from __future__ import annotations

from containerizer.analyze.caps import aggregate_caps


def test_basic_dedup() -> None:
    events: list[dict[str, object]] = [
        {"cap_name": "CAP_NET_BIND_SERVICE"},
        {"cap_name": "CAP_NET_BIND_SERVICE"},
        {"cap_name": "CAP_CHOWN"},
    ]
    assert aggregate_caps(events) == ["CAP_CHOWN", "CAP_NET_BIND_SERVICE"]


def test_dac_superset_filter() -> None:
    events: list[dict[str, object]] = [
        {"cap_name": "CAP_DAC_OVERRIDE"},
        {"cap_name": "CAP_DAC_READ_SEARCH"},
    ]
    # CAP_DAC_OVERRIDE includes CAP_DAC_READ_SEARCH; latter dropped.
    assert aggregate_caps(events) == ["CAP_DAC_OVERRIDE"]


def test_kept_when_superset_absent() -> None:
    events: list[dict[str, object]] = [{"cap_name": "CAP_DAC_READ_SEARCH"}]
    assert aggregate_caps(events) == ["CAP_DAC_READ_SEARCH"]


def test_alternative_field_name_capa() -> None:
    # Some bcc capable variants emit "cap" instead of "cap_name"; tolerate.
    events: list[dict[str, object]] = [{"cap": "CAP_NET_RAW"}]
    assert aggregate_caps(events) == ["CAP_NET_RAW"]
