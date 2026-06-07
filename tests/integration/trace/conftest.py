"""Auto-skip integration tests unless `-m integration` is selected.

The `integration` pytest marker (registered in pyproject.toml) is documented
as "skipped by default in local runs". Registering a marker does not by
itself deselect tests, so this conftest enforces that contract for tests in
this package: if the run did not opt in via `-m integration` (or any other
`-m` expression that selects `integration`), tests marked `integration` are
skipped.
"""

from __future__ import annotations

import pytest


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    markexpr = config.getoption("-m", default="") or ""
    if "integration" in markexpr:
        return
    skip_integration = pytest.mark.skip(reason="integration test; run with `pytest -m integration`")
    for item in items:
        if item.get_closest_marker("integration") is not None:
            item.add_marker(skip_integration)
