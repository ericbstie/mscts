from collections.abc import Callable
from pathlib import Path

import pytest

from mscts.compare import Outcome
from mscts.run import Server, selfcheck
from tests.run.fakes import FakeAdapter


@pytest.mark.asyncio
async def test_a_selfcheck_plays_the_scenarios_and_their_prerequisites_reference_against_reference(
    fake_server: Callable[..., Server], tmp_path: Path
) -> None:
    reference = fake_server("vanilla")

    verdicts = await selfcheck(
        ["status/ping"], reference=reference, workdir=tmp_path / "selfcheck", repeat=2
    )

    assert [(v.scenario_id, v.outcome) for v in verdicts] == [
        ("status/basic", Outcome.MATCH),
        ("status/ping", Outcome.MATCH),
    ] * 2
    adapter = reference.adapter
    assert isinstance(adapter, FakeAdapter)
    assert len(adapter.prepared) == 2  # two Instances of the Reference, one per side
    assert adapter.prepared[0].host != adapter.prepared[1].host


@pytest.mark.asyncio
async def test_a_selfcheck_of_an_unknown_scenario_starts_nothing(
    fake_server: Callable[..., Server], tmp_path: Path
) -> None:
    reference = fake_server("vanilla")

    with pytest.raises(KeyError, match="status/nowhere"):
        await selfcheck(["status/nowhere"], reference=reference, workdir=tmp_path, repeat=1)

    assert isinstance(reference.adapter, FakeAdapter)
    assert reference.adapter.prepared == []
