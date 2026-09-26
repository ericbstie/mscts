"""A Run over Attached sides: Instances someone else launched, played but never started."""

import dataclasses
from collections.abc import Callable
from pathlib import Path

import pytest

from mscts.compare import Outcome
from mscts.run import Attached, Server, run, selfcheck
from mscts.scenario import Scenario, identity
from mscts.scenarios import status
from mscts.spec import ServerSpec
from tests.run.fakes import FakeAdapter, attached

BASIC = Scenario(id="status/basic", run=status.basic)
PING = Scenario(id="status/ping", run=status.ping, requires=("status/basic",))

type MakeServer = Callable[..., Server]


def _other_motd(spec: ServerSpec) -> ServerSpec:
    return dataclasses.replace(spec, motd="other")


def _prepared(server: Server) -> list[ServerSpec]:
    assert isinstance(server.adapter, FakeAdapter)
    return server.adapter.prepared


@pytest.mark.asyncio
async def test_an_attached_reference_is_played_and_only_the_candidate_is_launched(
    fake_server: MakeServer, run_token: str, tmp_path: Path
) -> None:
    candidate = fake_server("two")
    async with attached(FakeAdapter("one", run_token), tmp_path / "one") as reference:
        verdicts = await run(
            [BASIC, PING], reference, candidate, workdir=tmp_path / "run", repeat=2
        )

    assert [(v.scenario_id, v.outcome) for v in verdicts] == [
        ("status/basic", Outcome.MATCH),
        ("status/ping", Outcome.MATCH),
    ] * 2
    assert len(_prepared(candidate)) == 1


@pytest.mark.asyncio
async def test_an_attached_candidate_that_differs_is_a_mismatch(
    fake_server: MakeServer, run_token: str, tmp_path: Path
) -> None:
    other = FakeAdapter("two", run_token, description="not vanilla")
    async with attached(other, tmp_path / "two") as candidate:
        [verdict] = await run([BASIC], fake_server("one"), candidate, workdir=tmp_path / "run")

    assert verdict.outcome is Outcome.MISMATCH
    assert [d.candidate for d in verdict.divergences] == ["not vanilla"]


@dataclasses.dataclass(frozen=True)
class Mismatch:
    attached: Callable[[ServerSpec], ServerSpec]
    scenario: Scenario


MISMATCHES = {
    "default instance, custom scenario": Mismatch(
        identity, Scenario(id="test/custom", run=status.basic, spec=_other_motd)
    ),
    "custom instance, default scenario": Mismatch(_other_motd, BASIC),
}


@pytest.mark.asyncio
@pytest.mark.parametrize("case", MISMATCHES.values(), ids=MISMATCHES.keys())
@pytest.mark.parametrize("side", ["reference", "candidate"])
async def test_a_scenario_whose_spec_the_attached_instance_lacks_is_refused_before_anything_starts(
    case: Mismatch, side: str, fake_server: MakeServer, tmp_path: Path
) -> None:
    spec = case.attached(ServerSpec(host="127.0.0.2", port=1))
    other = fake_server("launched")
    given = Attached("vanilla", spec)
    reference, candidate = (given, other) if side == "reference" else (other, given)

    with pytest.raises(ValueError, match=rf"{case.scenario.id} needs another ServerSpec"):
        await run([case.scenario], reference, candidate, workdir=tmp_path)

    assert _prepared(other) == []


@pytest.mark.asyncio
async def test_an_attached_instance_plays_scenarios_of_its_own_spec(
    fake_server: MakeServer, tmp_path: Path
) -> None:
    custom = Scenario(id="test/custom", run=status.basic, spec=_other_motd)
    reference = Attached("vanilla", _other_motd(ServerSpec(host="127.0.0.2", port=1)))

    [verdict] = await run([custom], reference, fake_server("two"), workdir=tmp_path)

    # Accepted: played, against nothing listening at the Attached Endpoint.
    assert verdict.outcome is Outcome.ERROR
    assert verdict.detail.startswith("the Reference failed: ConnectionRefusedError")


def test_an_attached_side_is_reached_at_its_specs_endpoint() -> None:
    side = Attached("vanilla", ServerSpec(host="127.0.0.9", port=4242))

    assert (side.endpoint.host, side.endpoint.port) == ("127.0.0.9", 4242)


@pytest.mark.asyncio
async def test_a_selfcheck_against_an_attached_reference_launches_one_instance(
    fake_server: MakeServer, run_token: str, tmp_path: Path
) -> None:
    reference = fake_server("vanilla")
    async with attached(FakeAdapter("vanilla", run_token), tmp_path / "attached") as running:
        verdicts = await selfcheck(
            ["status/ping"],
            reference=reference,
            workdir=tmp_path / "selfcheck",
            repeat=2,
            attached=running,
        )

    assert {v.outcome for v in verdicts} == {Outcome.MATCH}
    assert len(verdicts) == 4
    [launched] = _prepared(reference)
    assert launched.host != running.endpoint.host


@pytest.mark.asyncio
async def test_a_selfcheck_against_an_instance_of_another_adapter_is_refused(
    fake_server: MakeServer, tmp_path: Path
) -> None:
    reference = fake_server("vanilla")
    other = Attached("pumpkin", ServerSpec(host="127.0.0.2", port=1))

    with pytest.raises(ValueError, match="pumpkin"):
        await selfcheck(
            ["status/basic"], reference=reference, workdir=tmp_path, repeat=1, attached=other
        )

    assert _prepared(reference) == []
