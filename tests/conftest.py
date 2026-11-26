"""Shared test fixtures."""

import pytest

from assistance import seed


@pytest.fixture
def db(tmp_path, monkeypatch):
    """A fresh seeded database in a temporary folder, selected through the environment."""
    path = tmp_path / "assistance.db"
    monkeypatch.setenv("ASSISTANCE_DB_PATH", str(path))
    seed.reset(path)
    return path
