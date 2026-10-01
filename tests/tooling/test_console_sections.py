"""A failing test shows the tail of each Instance's console, and a passing one shows nothing.

`support.console` is a plugin the root conftest registers; each test here runs pytest on
a small suite of its own, with that plugin, through `pytester`.
"""

import pytest

from mscts.runner import LOG_TAIL_LINES

SECTION = "Instance console"

CONFTEST = """
import pytest
from mscts.net import Endpoint
from mscts.runner import Instance

pytest_plugins = ["support.console"]


@pytest.fixture
def reference(tmp_path):
    log = tmp_path / "somewhere-else.log"
    log.write_text("\\n".join(f"console line {n}" for n in range(1, 101)) + "\\n")
    return Instance(
        endpoint=Endpoint("127.1.2.3", 25565), pid=1, launched_ns=0, ready_ns=0, log_path=log
    )
"""


@pytest.fixture
def suite(pytester: pytest.Pytester) -> pytest.Pytester:
    """A pytester directory with the conftest above, and an ini that keeps pytest-asyncio quiet."""
    pytester.makeini("[pytest]\nasyncio_default_fixture_loop_scope = function\n")
    pytester.makeconftest(CONFTEST)
    return pytester


def test_a_failing_test_shows_the_tail_of_the_console_of_an_instance_it_was_given(
    suite: pytest.Pytester,
) -> None:
    suite.makepyfile("def test_fails(reference):\n    assert False\n")

    result = suite.runpytest()

    result.assert_outcomes(failed=1)
    result.stdout.fnmatch_lines([f"*{SECTION} (reference)*", "console line 100"])


def test_the_section_names_the_console_file_and_shows_only_its_last_lines(
    suite: pytest.Pytester,
) -> None:
    suite.makepyfile("def test_fails(reference):\n    assert False\n")

    out = suite.runpytest().stdout.str()

    assert f"last {LOG_TAIL_LINES} lines of " in out, out
    assert "somewhere-else.log\nconsole line 61\n" in out, out
    assert "console line 60\n" not in out, out


def test_a_passing_test_shows_no_console(suite: pytest.Pytester) -> None:
    """Pin: `-rA` prints what a passing test's report holds, sections included."""
    suite.makepyfile("def test_passes(reference):\n    assert True\n")

    result = suite.runpytest("-rA")

    result.assert_outcomes(passed=1)
    assert SECTION not in result.stdout.str(), result.stdout.str()


def test_a_failing_test_shows_the_console_of_an_instance_a_fixture_got_through_another(
    suite: pytest.Pytester,
) -> None:
    """Pin: the shared Reference reaches a test through `reference_attached`, not by name."""
    suite.makeconftest(
        CONFTEST + "\n\n@pytest.fixture\ndef attached(reference):\n    return reference.endpoint\n"
    )
    suite.makepyfile("def test_fails(attached):\n    assert False\n")

    result = suite.runpytest()

    result.assert_outcomes(failed=1)
    result.stdout.fnmatch_lines([f"*{SECTION} (reference)*", "console line 100"])


def test_a_failing_test_shows_the_console_of_an_instance_it_started_below_its_tmp_path(
    suite: pytest.Pytester,
) -> None:
    source = """
def test_fails(tmp_path):
    console = tmp_path / "selfcheck" / "0" / "candidate"
    console.mkdir(parents=True)
    (console / "mscts-console.log").write_text("the candidate said: boom\\n")
    assert False
"""
    suite.makepyfile(source)

    result = suite.runpytest()

    result.assert_outcomes(failed=1)
    result.stdout.fnmatch_lines(
        [f"*{SECTION} (selfcheck/0/candidate)*", "the candidate said: boom"]
    )
