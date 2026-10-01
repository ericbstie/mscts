"""A failing test shows the tail of each Instance's console (a pytest plugin).

An Instance's console is its `mscts-console.log`. When a test fails or errors, its report
gets one section per Instance the test used, `Instance console (<label>)`, holding the
last lines of that console: the same lines a RunnerError quotes (`runner.log_tail`). A
test that passes gets none.

The test used an Instance when
- a fixture it requested is one: the label is the fixture's name (the session's
  `reference`); or
- it started one in a directory below its own `tmp_path`, which is what the tests that boot
  a server themselves do: the label is that directory, relative to `tmp_path`.

The root conftest registers this plugin, so every tier has it.
"""

from collections.abc import Generator
from pathlib import Path

import pytest

from mscts.runner import CONSOLE_LOG, Instance, log_tail

SECTION = "Instance console"


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(
    item: pytest.Item,
) -> Generator[None, pytest.TestReport, pytest.TestReport]:
    """Add the console tail of each Instance to the report of a test that failed."""
    report = yield
    if report.failed:
        for log, label in consoles(item).items():
            report.sections.append((f"{SECTION} ({label})", _quote(log)))
    return report


def consoles(item: pytest.Item) -> dict[Path, str]:
    """The console of every Instance `item` used, with the label that names it."""
    if not isinstance(item, pytest.Function):
        return {}
    found = {
        value.log_path: name for name, value in item.funcargs.items() if isinstance(value, Instance)
    }
    tmp_path = item.funcargs.get("tmp_path")
    if isinstance(tmp_path, Path):
        for log in sorted(tmp_path.rglob(CONSOLE_LOG)):
            found.setdefault(log, log.parent.relative_to(tmp_path).as_posix())
    return found


def _quote(log: Path) -> str:
    lines = log_tail(log)
    return "\n".join((f"last {len(lines)} lines of {log}", *lines))
