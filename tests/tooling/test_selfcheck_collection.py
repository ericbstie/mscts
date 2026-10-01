"""The Self-check tier has one test per registered Group, named by the Group's id (#84).

Each test runs a small suite inline, with the same hook the tier's `tests/selfcheck/conftest.py`
imports, so registering a Group is the only thing that adds a test.
"""

from collections.abc import Iterator

import pytest

import mscts.groups  # noqa: F401 - registers the shipped Groups
from mscts import group as group_module
from mscts.group import GROUPS, GroupContext, group

CONFTEST = "from support.selfcheck import pytest_generate_tests  # noqa: F401\n"
TEST = "def test_selfcheck(group_id):\n    pass\n"


async def _nothing(_: GroupContext) -> None:
    pass


@pytest.fixture
def registering() -> Iterator[None]:
    """Let a test register Groups; forget them afterwards, so no other test sees them."""
    registered = group_module._REGISTERED  # noqa: SLF001 - undo what the test registered
    before = dict(registered)
    yield
    registered.clear()
    registered.update(before)


@pytest.fixture
def suite(pytester: pytest.Pytester) -> pytest.Pytester:
    # The outer run's `filterwarnings = error` reaches the inner one, and pytest-asyncio
    # warns about an unset loop scope when it is configured.
    pytester.makeini("[pytest]\nasyncio_default_fixture_loop_scope = function\n")
    pytester.makeconftest(CONFTEST)
    pytester.makepyfile(TEST)
    return pytester


@pytest.mark.usefixtures("registering")
def test_registering_a_group_adds_one_test_named_by_its_id(suite: pytest.Pytester) -> None:
    group("fake/added")(_nothing)

    result = suite.runpytest("--collect-only", "-q")

    result.stdout.fnmatch_lines(["*::test_selfcheck[[]fake/added[]]"])


def test_there_is_a_test_for_every_registered_group_and_no_other(suite: pytest.Pytester) -> None:
    result = suite.runpytest("--collect-only", "-q")

    collected = [line for line in result.outlines if "::test_selfcheck[" in line]
    assert [line.split("[", 1)[1].rstrip("]") for line in collected] == list(GROUPS)
