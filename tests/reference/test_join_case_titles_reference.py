"""Every test case a live join/basic Comparison compares has a title (#175)."""

import logging
from pathlib import Path

import pytest
from support.reference import own_reference

from mscts.case_titles import TITLES
from mscts.compare import Outcome
from mscts.group import GROUPS
from mscts.run import run

LOG = logging.getLogger(__name__)
pytestmark = [pytest.mark.reference, pytest.mark.asyncio, pytest.mark.timeout(300)]


async def test_every_case_a_vanilla_pair_compares_at_join_has_a_title(
    cache_dir: Path, tmp_path: Path
) -> None:
    with own_reference(cache_dir) as server:
        (verdict,) = await run((GROUPS["join/basic"],), server, server, workdir=tmp_path)
    assert verdict.outcome in (Outcome.MATCH, Outcome.MISMATCH), verdict.detail
    assert {"login.dimension_name", "set_health.health"} <= set(verdict.test_cases), verdict
    assert any(name.startswith("level_chunk_with_light.") for name in verdict.test_cases), verdict
    missing = sorted(set(verdict.test_cases) - TITLES.keys())
    LOG.info("Compared %d test cases; %d without a title", len(verdict.test_cases), len(missing))
    LOG.info("Untitled cases: %s", missing)
    assert missing == [], missing
