import dataclasses
from collections.abc import Callable
from pathlib import Path

import pytest

from mscts.compare import Outcome
from mscts.run import Server, run
from mscts.scenario import Scenario, ScenarioKind
from mscts.scenarios import status
from mscts.spec import ServerSpec
from tests.run.fakes import FakeAdapter

BASIC = Scenario(id="status/basic", run=status.basic)
PING = Scenario(id="status/ping", run=status.ping, requires=("status/basic",))

type MakeServer = Callable[..., Server]


def _adapter(server: Server) -> FakeAdapter:
    assert isinstance(server.adapter, FakeAdapter)
    return server.adapter


@pytest.mark.asyncio
async def test_a_run_against_two_equal_servers_matches(
    fake_server: MakeServer, tmp_path: Path
) -> None:
    verdicts = await run(
        [BASIC, PING], fake_server("one"), fake_server("two"), workdir=tmp_path / "run"
    )

    assert [(v.scenario_id, v.outcome) for v in verdicts] == [
        ("status/basic", Outcome.MATCH),
        ("status/ping", Outcome.MATCH),
    ]


@pytest.mark.asyncio
async def test_each_side_runs_on_its_own_free_endpoint(
    fake_server: MakeServer, tmp_path: Path
) -> None:
    reference, candidate = fake_server("one"), fake_server("two")

    await run([BASIC], reference, candidate, workdir=tmp_path / "run")

    [one], [two] = _adapter(reference).prepared, _adapter(candidate).prepared
    assert one.host != two.host
    assert one == ServerSpec(host=one.host, port=one.port)


@pytest.mark.asyncio
async def test_a_candidate_that_differs_is_a_mismatch_and_blocks_what_requires_it(
    fake_server: MakeServer, tmp_path: Path
) -> None:
    candidate = fake_server("two", description="not vanilla")

    basic, ping = await run([BASIC, PING], fake_server("one"), candidate, workdir=tmp_path / "run")

    assert basic.outcome is Outcome.MISMATCH
    assert [d.candidate for d in basic.divergences] == ["not vanilla"]
    assert ping.outcome is Outcome.BLOCKED
    assert ping.detail == "prerequisite status/basic was mismatch"


@pytest.mark.asyncio
async def test_repetitions_reuse_the_instances(fake_server: MakeServer, tmp_path: Path) -> None:
    reference, candidate = fake_server("one"), fake_server("two")

    verdicts = await run([BASIC, PING], reference, candidate, workdir=tmp_path / "run", repeat=3)

    assert [v.scenario_id for v in verdicts] == ["status/basic", "status/ping"] * 3
    assert {v.outcome for v in verdicts} == {Outcome.MATCH}
    assert len(_adapter(reference).prepared) == len(_adapter(candidate).prepared) == 1


@pytest.mark.asyncio
async def test_a_scenario_with_its_own_spec_gets_instances_of_its_own(
    fake_server: MakeServer, tmp_path: Path
) -> None:
    reference, candidate = fake_server("one"), fake_server("two")

    def other_motd(spec: ServerSpec) -> ServerSpec:
        return dataclasses.replace(spec, motd="other")

    custom = Scenario(id="test/custom", run=status.basic, spec=other_motd)

    verdicts = await run([BASIC, custom, PING], reference, candidate, workdir=tmp_path / "run")

    assert {v.outcome for v in verdicts} == {Outcome.MATCH}
    assert [spec.motd for spec in _adapter(reference).prepared] == ["mscts", "other"]
    assert [spec.motd for spec in _adapter(candidate).prepared] == ["mscts", "other"]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", [ScenarioKind.TICK_EXACT, ScenarioKind.STATISTICAL])
async def test_only_exact_scenarios_can_run_yet(
    kind: ScenarioKind, fake_server: MakeServer, tmp_path: Path
) -> None:
    scenario = Scenario(id="test/kind", run=status.basic, kind=kind)
    reference = fake_server("one")

    with pytest.raises(NotImplementedError, match=str(kind)):
        await run([scenario], reference, fake_server("two"), workdir=tmp_path / "run")

    assert _adapter(reference).prepared == []


@pytest.mark.asyncio
async def test_a_scenario_listed_twice_is_refused(fake_server: MakeServer, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="status/basic"):
        await run([BASIC, BASIC], fake_server("one"), fake_server("two"), workdir=tmp_path)
