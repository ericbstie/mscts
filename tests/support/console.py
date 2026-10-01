"""A failing test shows the tail of each Instance's console (a pytest plugin).

An Instance's console is its `mscts-console.log`. When a test fails or errors, its report
gets one section per Instance the test used, `Instance console (<label>)`, holding the
last lines of that console: the same lines a RunnerError quotes (`runner.log_tail`). A
test that passes gets none.

The root conftest registers this plugin, so every tier has it.
"""

from collections.abc import Generator
from pathlib import Path

import pytest

from mscts.runner import Instance, log_tail

SECTION = "Instance console"


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(
    item: pytest.Item,
) -> Generator[None, pytest.TestReport, pytest.TestReport]:
    """Add the console tail of each Instance to the report of a test that failed."""
    report = yield
    if report.failed:
        for log, label in consoles(item).items():
            report.sections.append((f"{SECTION} ({label})", "\n".join(log_tail(log))))
    return report


def consoles(item: pytest.Item) -> dict[Path, str]:
    """The console of every Instance `item` used, with the label that names it."""
    if not isinstance(item, pytest.Function):
        return {}
    return {
        value.log_path: name for name, value in item.funcargs.items() if isinstance(value, Instance)
    }
