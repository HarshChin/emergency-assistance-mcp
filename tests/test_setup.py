"""The project installs with the pinned versions the spec names."""

from importlib.metadata import version

import pytest


@pytest.mark.req("NFR-03")
def test_pinned_versions_are_installed():
    assert version("mcp") == "2.3.0"
    assert version("pydantic") == "2.14.4"
