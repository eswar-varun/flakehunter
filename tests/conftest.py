from __future__ import annotations

import pytest
from helpers import execution

# pytester runs real pytest sessions in a temp dir, so the pytest-format tests parse the XML
# that the installed pytest actually writes rather than a hand-written approximation.
pytest_plugins = ["pytester"]


@pytest.fixture
def ex():
    return execution
