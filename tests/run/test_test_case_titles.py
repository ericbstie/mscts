"""The status Groups' actual Comparisons have documented titles (#12)."""

from collections.abc import Callable
from pathlib import Path

import pytest

from mscts.case_titles import TITLES
from mscts.group import GROUPS
from mscts.run import Server, run_results
from tests.docs.replay import report_from_sample


@pytest.mark.asyncio
async def test_every_status_test_case_from_fake_servers_has_a_title(
    fake_server: Callable[..., Server], tmp_path: Path
) -> None:
    groups = [group for name, group in GROUPS.items() if name.startswith("status/")]
    result = await run_results(
        groups,
        fake_server("vanilla"),
        fake_server("pumpkin", description="different"),
        workdir=tmp_path / "run",
    )
    cases = {name for verdict in result.verdicts for name in verdict.test_cases}
    assert cases
    assert not cases - TITLES.keys(), f"Test cases without titles: {sorted(cases - TITLES.keys())}"


def test_every_status_test_case_in_the_stored_live_run_has_a_title() -> None:
    sample = Path(__file__).resolve().parents[1] / "docs/samples/run-pumpkin.json"
    report = report_from_sample(sample)
    cases = {
        name
        for group in report.results
        for verdict in group.verdicts
        for name in verdict.test_cases
    }
    assert not cases - TITLES.keys(), f"Test cases without titles: {sorted(cases - TITLES.keys())}"
