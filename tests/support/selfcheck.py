"""What the Self-check tier (`tests/selfcheck/`) is made of: a test per registered Group.

`tests/selfcheck/conftest.py` imports `pytest_generate_tests` from here, so a test that takes a
`group_id` runs once for each Group in `GROUPS`, with the Group's id as its test id. Nothing
else needs to be written when a Group is registered (#84).
"""

import pytest

import mscts.groups  # noqa: F401 - registers the shipped Groups
from mscts.group import GROUPS


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    """Give every test that takes a `group_id` one run per registered Group."""
    if "group_id" in metafunc.fixturenames:
        metafunc.parametrize("group_id", list(GROUPS))
