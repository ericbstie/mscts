"""A Run plays a Group only once the previous Group's Bots have left the server (#97).

`Bot.close()` only closes the socket, and a server removes the player later (vanilla on its
next tick). So before a Group plays on an Instance, the Run polls its status until
`players.online` is 0. The fakes here answer each status request from a script of counts.
"""

import contextlib
import dataclasses
import json
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from time import perf_counter

import pytest

import mscts.run as run_module
from mscts.codec.packets import Codec
from mscts.compare import Outcome
from mscts.group import Group, GroupContext
from mscts.groups import status
from mscts.run import Attached, run, run_results
from mscts.spec import ServerSpec
from mscts.target import TARGET
from tests.net.fakes import Handler, Peer, serve, status_server

_ID = "00000000-0000-0000-0000-000000000001"
DEADLINE_S = 0.3
"""The deadline the tests that wait for it give a Run: short, so they stay fast."""


def named(*names: str) -> list[object]:
    """A status `players.sample` listing `names`, as vanilla does."""
    return [{"name": name, "id": _ID} for name in names]


@dataclasses.dataclass
class Occupancy:
    """A fake server's players online, as its status answers: one count per status request.

    The count for the n-th request is `online[n - 1]`, and the last one goes on for every
    request after it. Each answer holds `sample` as its `players.sample`, if it is not None.
    `polls` counts the status requests answered so far.
    """

    online: Sequence[int]
    sample: object = None
    polls: int = 0

    def handler(self) -> Handler:
        """Answer a status request from the script of counts, and a ping with its pong."""

        async def handle(peer: Peer) -> None:
            async for packet in peer.packets():
                if packet.name == "minecraft:status_request":
                    count = self.online[min(self.polls, len(self.online) - 1)]
                    self.polls += 1
                    players: dict[str, object] = {"max": 20, "online": count}
                    if self.sample is not None:
                        players["sample"] = self.sample
                    reply = {
                        "description": "mscts",
                        "players": players,
                        "version": {"name": "26.3", "protocol": TARGET.protocol_version},
                    }
                    await peer.send("minecraft:status_response", json_response=json.dumps(reply))
                elif packet.name == "minecraft:ping_request":
                    assert packet.fields is not None
                    await peer.send("minecraft:pong_response", timestamp=packet.fields["timestamp"])
                    return

        return handle


async def never_answer(peer: Peer) -> None:
    """Read what the client sends and answer none of it, until it closes the connection."""
    async for _ in peer.packets():
        pass


@contextlib.asynccontextmanager
async def attached(name: str, handler: Handler) -> AsyncIterator[Attached]:
    """An Attached side, a fake server running `handler`."""
    async with serve(Codec.for_target(TARGET), handler) as endpoint:
        yield Attached(name, ServerSpec(host=endpoint.host, port=endpoint.port))


@pytest.mark.asyncio
async def test_a_group_plays_after_the_poll_that_finds_no_players_online(tmp_path: Path) -> None:
    reference, candidate = Occupancy(online=(1, 1, 0)), Occupancy(online=(0,))
    polls_at_start: dict[int, int] = {}
    async with (
        attached("one", reference.handler()) as one,
        attached("two", candidate.handler()) as two,
    ):
        by_port = {one.endpoint.port: reference, two.endpoint.port: candidate}

        async def script(context: GroupContext) -> None:
            polls_at_start[context.endpoint.port] = by_port[context.endpoint.port].polls
            await status.basic(context)

        [verdict] = await run(
            [Group(id="test/settle", run=script)], one, two, workdir=tmp_path / "run"
        )

    assert verdict.outcome is Outcome.MATCH
    assert polls_at_start == {one.endpoint.port: 3, two.endpoint.port: 1}


@pytest.mark.asyncio
async def test_the_wait_honours_the_interval_and_is_no_part_of_the_time_a_group_took(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    interval_s = 0.2
    monkeypatch.setattr(run_module, "SETTLE_INTERVAL_S", interval_s)

    async with (
        attached("one", Occupancy(online=(1, 1, 0)).handler()) as one,
        attached("two", Occupancy(online=(0,)).handler()) as two,
    ):
        begun = perf_counter()
        result = await run_results(
            [Group(id="status/basic", run=status.basic)], one, two, workdir=tmp_path / "run"
        )
        waited_s = perf_counter() - begun

    assert waited_s >= 2 * interval_s * 0.9  # two waits between the three polls
    [elapsed_s] = result.results[0].elapsed_s
    assert elapsed_s < 2 * interval_s * 0.9, "the Group's time includes the wait"


def _busy(role: str, what: str) -> str:
    return f"the {role} still had {what} online after waiting {DEADLINE_S} s"


@pytest.mark.asyncio
@pytest.mark.timeout(10)  # the deadline is what ends the wait: a hang is the failure
@pytest.mark.parametrize(
    "stuck", [("Reference",), ("Candidate",), ("Reference", "Candidate")], ids="/".join
)
async def test_a_server_that_never_empties_gives_an_error_naming_the_deadline(
    stuck: tuple[str, ...], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(run_module, "SETTLE_TIMEOUT_S", DEADLINE_S)
    sides = {
        role: Occupancy(online=(2,), sample=named("watcher", "control"))
        if role in stuck
        else Occupancy(online=(0,))
        for role in ("Reference", "Candidate")
    }
    played: list[int] = []

    async def script(context: GroupContext) -> None:
        played.append(context.endpoint.port)

    async with (
        attached("one", sides["Reference"].handler()) as one,
        attached("two", sides["Candidate"].handler()) as two,
    ):
        [verdict] = await run(
            [Group(id="test/settle", run=script)], one, two, workdir=tmp_path / "run"
        )

    assert verdict.outcome is Outcome.ERROR
    expected = [_busy(role, "2 players") + ": watcher, control" for role in stuck]
    assert verdict.detail == "; ".join(expected)
    assert played == []


@dataclasses.dataclass(frozen=True)
class Wording:
    online: int
    sample: object
    detail: str


WORDINGS = {
    "one player, none named": Wording(1, None, _busy("Reference", "1 player")),
    "only the names it can read": Wording(
        3,
        [*named("a"), 5, {"name": 7, "id": _ID}, {"id": _ID}],
        _busy("Reference", "3 players") + ": a",
    ),
    "a sample that is no list": Wording(2, 7, _busy("Reference", "2 players")),
}


@pytest.mark.asyncio
@pytest.mark.timeout(10)
@pytest.mark.parametrize("case", WORDINGS.values(), ids=WORDINGS.keys())
async def test_the_error_says_how_many_players_and_names_those_it_can_read(
    case: Wording, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(run_module, "SETTLE_TIMEOUT_S", DEADLINE_S)
    busy = Occupancy(online=(case.online,), sample=case.sample)

    async with (
        attached("one", busy.handler()) as one,
        attached("two", Occupancy(online=(0,)).handler()) as two,
    ):
        [verdict] = await run(
            [Group(id="status/basic", run=status.basic)], one, two, workdir=tmp_path / "run"
        )

    assert (verdict.outcome, verdict.detail) == (Outcome.ERROR, case.detail)


UNREADABLE = {
    "no players": "{}",
    "players that is no object": '{"players": 5}',
    "no online count": '{"players": {"max": 20}}',
    "an online count that is text": '{"players": {"online": "2"}}',
    "an online count that is a bool": '{"players": {"online": true}}',
    "not JSON": "not json",
}


@pytest.mark.asyncio
@pytest.mark.timeout(10)
@pytest.mark.parametrize("reply", UNREADABLE.values(), ids=UNREADABLE.keys())
async def test_a_status_that_cannot_be_read_does_not_stop_the_group_playing(
    reply: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(run_module, "SETTLE_TIMEOUT_S", DEADLINE_S)
    played: list[int] = []

    async def script(context: GroupContext) -> None:
        played.append(context.endpoint.port)
        await status.basic(context)

    async with (
        attached("one", Occupancy(online=(0,)).handler()) as one,
        attached("two", status_server(reply, [])) as two,
    ):
        [verdict] = await run(
            [Group(id="test/settle", run=script)], one, two, workdir=tmp_path / "run"
        )

    # The Candidate's own answer is what the Group meets and the Verdict reports.
    assert verdict.outcome is Outcome.MISMATCH
    assert played == [one.endpoint.port, two.endpoint.port]


@pytest.mark.asyncio
@pytest.mark.timeout(5)  # a poll is bounded by a Bot's 10 s: only the deadline can cut it short
async def test_a_status_that_never_answers_is_cut_off_at_the_deadline(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(run_module, "SETTLE_TIMEOUT_S", DEADLINE_S)
    played: list[int] = []

    async def script(context: GroupContext) -> None:
        played.append(context.endpoint.port)

    async with (
        attached("one", never_answer) as one,
        attached("two", Occupancy(online=(0,)).handler()) as two,
    ):
        [verdict] = await run(
            [Group(id="test/settle", run=script)], one, two, workdir=tmp_path / "run"
        )

    assert verdict.outcome is Outcome.MATCH
    assert played == [one.endpoint.port, two.endpoint.port]
