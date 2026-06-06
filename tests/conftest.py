"""Shared pytest fixtures."""

from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    """Directory containing test fixtures."""
    return Path(__file__).parent / "fixtures"
