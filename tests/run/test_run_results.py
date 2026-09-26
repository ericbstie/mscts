"""A Run's full result: Verdicts per repetition, Measurements, and what each side is."""

from collections.abc import Callable
from pathlib import Path

import pytest

from mscts.codec.packets import Direction, Packet, State
from mscts.compare import Outcome
from mscts.run import Server, run_results, status_version
from mscts.scenario import Scenario
from mscts.scenarios import status
from mscts.transcript import Transcript
from tests.run.fakes import FakeAdapter, attached

BASIC = Scenario(id="status/basic", run=status.basic)
PING = Scenario(id="status/ping", run=status.ping, requires=("status/basic",))

type MakeServer = Callable[..., Server]


@pytest.mark.asyncio
async def test_each_scenario_has_a_verdict_and_measurements_per_repetition(
    fake_server: MakeServer, tmp_path: Path
) -> None:
    result = await run_results(
        [BASIC, PING], fake_server("one"), fake_server("two"), workdir=tmp_path / "run", repeat=2
    )

    basic, ping = result.results
    assert basic.scenario_id == "status/basic"
    assert [v.outcome for v in basic.verdicts] == [Outcome.MATCH] * 2
    assert basic.reference == basic.candidate == ((), ())
    for side in (ping.reference, ping.candidate):
        assert len(side) == 2
        for repetition in side:
            [rtt] = repetition
            assert (rtt.name, rtt.unit) == ("status.rtt", "ms")
            assert rtt.value > 0


@pytest.mark.asyncio
async def test_the_verdicts_read_repetition_after_repetition(
    fake_server: MakeServer, tmp_path: Path
) -> None:
    result = await run_results(
        [BASIC, PING], fake_server("one"), fake_server("two"), workdir=tmp_path / "run", repeat=2
    )

    assert [v.scenario_id for v in result.verdicts] == ["status/basic", "status/ping"] * 2


@pytest.mark.asyncio
async def test_each_launched_instance_has_a_startup_measurement_and_a_version(
    fake_server: MakeServer, tmp_path: Path
) -> None:
    result = await run_results(
        [BASIC], fake_server("one"), fake_server("two"), workdir=tmp_path / "run"
    )

    for side, name in ((result.reference, "one"), (result.candidate, "two")):
        assert side.name == name
        assert side.version == "26.3"
        [startup] = side.startup
        assert (startup.name, startup.unit) == ("instance.startup", "ms")
        assert startup.value > 0


@pytest.mark.asyncio
async def test_an_attached_side_has_no_startup_measurement(
    fake_server: MakeServer, run_token: str, tmp_path: Path
) -> None:
    async with attached(FakeAdapter("one", run_token), tmp_path / "one") as reference:
        result = await run_results([BASIC], reference, fake_server("two"), workdir=tmp_path / "run")

    assert result.reference.startup == ()
    assert len(result.candidate.startup) == 1
    assert result.reference.version == "26.3"


@pytest.mark.asyncio
async def test_a_blocked_scenario_has_no_measurements(
    fake_server: MakeServer, tmp_path: Path
) -> None:
    result = await run_results(
        [BASIC, PING],
        fake_server("one"),
        fake_server("two", description="not vanilla"),
        workdir=tmp_path / "run",
    )

    ping = result.results[1]
    assert ping.verdicts[0].outcome is Outcome.BLOCKED
    assert ping.reference == ping.candidate == ((),)


def _status(json_response: object) -> Transcript:
    transcript = Transcript(scenario_id="status/basic", server="x")
    packet = Packet(
        state=State.STATUS,
        direction=Direction.CLIENTBOUND,
        name="minecraft:status_response",
        packet_id=0,
        payload=b"",
        fields={"json_response": json_response},
    )
    transcript.record("status", packet, t_ns=0)
    return transcript


@pytest.mark.parametrize(
    ("json_response", "expected"),
    [
        ('{"version": {"name": "26.3", "protocol": 777}}', "26.3"),
        ('{"version": {"protocol": 777}}', None),
        ('{"version": {"name": 5}}', None),
        ('["version"]', None),
        ("not json", None),
        ("[" * 100_000, None),
        (7, None),
    ],
    ids=["named", "no-name", "not-a-string", "not-an-object", "not-json", "deep", "not-text"],
)
def test_the_status_version_is_read_leniently(json_response: object, expected: str | None) -> None:
    assert status_version(_status(json_response)) == expected


def test_a_transcript_without_a_status_response_has_no_version() -> None:
    assert status_version(Transcript(scenario_id="status/basic", server="x")) is None
