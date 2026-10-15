"""Every mise task that boots live Instances waits for the live-tier lock first."""

import re
import tomllib
from pathlib import Path

import pytest

MISE = Path(__file__).resolve().parents[1] / "mise.toml"
_LIVE = ("test:reference", "test:selfcheck", "test:candidate", "test:statistical")


@pytest.mark.parametrize("task", _LIVE)
def test_a_live_tier_runs_under_the_live_lock(task: str) -> None:
    command = tomllib.loads(MISE.read_text())["tasks"][task]["run"]

    assert re.search(r"scripts/live_lock\.py (--tier \w+ )?-- uv run pytest -m ", command), command
