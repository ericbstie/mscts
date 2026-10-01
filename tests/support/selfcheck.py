"""What the Self-check tier (`tests/selfcheck/`) is made of: a test per registered Group.

`tests/selfcheck/conftest.py` imports `pytest_generate_tests` from here, so a test that takes a
`group_id` runs once for each Group in `GROUPS`, with the Group's id as its test id. Nothing
else needs to be written when a Group is registered (#84).
"""

from collections.abc import Mapping

import pytest

import mscts.groups  # noqa: F401 - registers the shipped Groups
from mscts.group import GROUPS

REPEAT_VAR = "MSCTS_SELFCHECK_REPEAT"
DEFAULT_REPEAT = 3
"""How many times a Group is played by default; a Group's PR runs 20 once, by hand."""


def repeat_from(environ: Mapping[str, str]) -> int:
    """How many times to play each Group: `MSCTS_SELFCHECK_REPEAT` in `environ`, else 3.

    Raises:
        ValueError: The variable is set to anything but a whole number of at least 1.
    """
    text = environ.get(REPEAT_VAR, "")
    if not text:
        return DEFAULT_REPEAT
    try:
        repeat = int(text)
    except ValueError:
        repeat = 0
    if repeat < 1:
        msg = f"{REPEAT_VAR} is {text!r}: it must be a whole number of at least 1"
        raise ValueError(msg)
    return repeat


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    """Give every test that takes a `group_id` one run per registered Group."""
    if "group_id" in metafunc.fixturenames:
        metafunc.parametrize("group_id", list(GROUPS))
