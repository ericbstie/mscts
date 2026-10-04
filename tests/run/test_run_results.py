"""A Run's full result: Verdicts per repetition, Measurements, and what each side is."""

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import pytest

from mscts import run as runs
from mscts.adapters.base import Source
from mscts.codec.packets import Direction, Packet, State
from mscts.compare import Outcome
from mscts.group import Group
from mscts.groups import status
from mscts.run import Server, run_results, status_version
from mscts.transcript import Transcript
from tests.run.fakes import FakeAdapter, attached

BASIC = Group(id="status/basic", run=status.basic)
PING = Group(id="status/ping", run=status.ping, requires=("status/basic",))

type MakeServer = Callable[..., Server]


@pytest.mark.asyncio
async def test_each_group_has_a_verdict_and_measurements_per_repetition(
    fake_server: MakeServer, tmp_path: Path
) -> None:
    result = await run_results(
        [BASIC, PING], fake_server("one"), fake_server("two"), workdir=tmp_path / "run", repeat=2
    )

    basic, ping = result.results
    assert basic.group_id == "status/basic"
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

    assert [v.group_id for v in result.verdicts] == ["status/basic", "status/ping"] * 2


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
async def test_a_group_blocked_by_the_candidate_measures_the_reference_alone(
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
    [[rtt]] = ping.reference
    assert rtt.name == "status.rtt"
    assert ping.candidate == ((),)
    [elapsed_s] = ping.elapsed_s
    assert elapsed_s > 0


@pytest.mark.asyncio
async def test_a_play_that_does_not_match_keeps_both_sides_transcripts(
    fake_server: MakeServer, tmp_path: Path
) -> None:
    # #162: a flaky play can only be diagnosed from what each side sent, and when.
    result = await run_results(
        [BASIC, PING],
        fake_server("one"),
        fake_server("two", description="not vanilla"),
        workdir=tmp_path / "run",
        keep_transcripts=True,
    )

    basic, ping = result.results
    [kept] = basic.transcripts
    assert kept is not None
    reference, candidate = kept
    assert (reference.server, candidate.server) == ("one", "two")
    assert reference.events
    assert ping.transcripts == (None,), "a blocked play did not play the Candidate"


@pytest.mark.asyncio
async def test_a_run_keeps_no_transcripts_unless_asked(
    fake_server: MakeServer, tmp_path: Path
) -> None:
    # Review of #226: a long Run against a Candidate that differs everywhere would hold
    # every play's Transcripts to its end, and the CLI never reads them.
    result = await run_results(
        [BASIC],
        fake_server("one"),
        fake_server("two", description="not vanilla"),
        workdir=tmp_path / "run",
        repeat=2,
    )

    assert result.results[0].transcripts == (None, None)


@pytest.mark.asyncio
async def test_a_play_that_matches_keeps_no_transcripts(
    fake_server: MakeServer, tmp_path: Path
) -> None:
    result = await run_results(
        [BASIC],
        fake_server("one"),
        fake_server("two"),
        workdir=tmp_path / "run",
        repeat=2,
        keep_transcripts=True,
    )

    assert result.results[0].transcripts == (None, None)


def _status(json_response: object) -> Transcript:
    transcript = Transcript(group_id="status/basic", server="x")
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
    assert status_version(Transcript(group_id="status/basic", server="x")) is None


@pytest.mark.asyncio
async def test_group_time_covers_both_plays_and_comparison_per_repetition(
    fake_server: MakeServer, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    times = iter((10.0, 10.4, 20.0, 20.6, 30.0, 30.8, 40.0, 40.9))
    monkeypatch.setattr(runs, "perf_counter", lambda: next(times))
    result = await run_results(
        [BASIC, PING], fake_server("one"), fake_server("two"), workdir=tmp_path / "run", repeat=2
    )
    assert result.results[0].elapsed_s == pytest.approx((0.4, 0.8))
    assert result.results[1].elapsed_s == pytest.approx((0.6, 0.9))


@pytest.mark.asyncio
@pytest.mark.parametrize("version", ["nightly", None], ids=["build", "no-build"])
async def test_installed_version_comes_from_source_instead_of_status(
    version: str | None, fake_server: MakeServer, tmp_path: Path
) -> None:
    candidate = fake_server("two")
    source = Source(sha256="a" * 64, size=1, version=version, commit="abcdef12" * 5)
    candidate = replace(candidate, installation=replace(candidate.installation, source=source))
    result = await run_results([BASIC], fake_server("one"), candidate, workdir=tmp_path / "run")
    assert result.candidate.version == "26.3"
    expected = f"nightly abcdef1 (sha256 {'a' * 8}…)" if version else f"sha256 {'a' * 64}"
    assert result.candidate.installed_version == expected
    assert result.reference.installed_version is None
