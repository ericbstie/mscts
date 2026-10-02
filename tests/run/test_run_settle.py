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

import pytest

import mscts.run as run_module
from mscts.codec.packets import Codec
from mscts.compare import Outcome
from mscts.group import Group, GroupContext
from mscts.groups import status
from mscts.run import Attached, run
from mscts.spec import ServerSpec
from mscts.target import TARGET
from tests.net.fakes import Handler, Peer, serve

_ID = "00000000-0000-0000-0000-000000000001"


@dataclasses.dataclass
class Occupancy:
    """A fake server's players online, as its status answers: one count per status request.

    The count for the n-th request is `online[n - 1]`, and the last one goes on for every
    request after it. Each answer's `players.sample` names `names`, if there are any.
    `polls` counts the status requests answered so far.
    """

    online: Sequence[int]
    names: Sequence[str] = ()
    polls: int = 0

    def handler(self) -> Handler:
        """Answer a status request from the script of counts, and a ping with its pong."""

        async def handle(peer: Peer) -> None:
            async for packet in peer.packets():
                if packet.name == "minecraft:status_request":
                    count = self.online[min(self.polls, len(self.online) - 1)]
                    self.polls += 1
                    players: dict[str, object] = {"max": 20, "online": count}
                    if self.names:
                        players["sample"] = [{"name": name, "id": _ID} for name in self.names]
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


@contextlib.asynccontextmanager
async def attached(name: str, occupancy: Occupancy) -> AsyncIterator[Attached]:
    """An Attached side that answers status as `occupancy` says."""
    async with serve(Codec.for_target(TARGET), occupancy.handler()) as endpoint:
        yield Attached(name, ServerSpec(host=endpoint.host, port=endpoint.port))


@pytest.mark.asyncio
async def test_a_group_plays_after_the_poll_that_finds_no_players_online(tmp_path: Path) -> None:
    reference, candidate = Occupancy(online=(1, 1, 0)), Occupancy(online=(0,))
    polls_at_start: dict[int, int] = {}
    async with attached("one", reference) as one, attached("two", candidate) as two:
        by_port = {one.endpoint.port: reference, two.endpoint.port: candidate}

        async def script(context: GroupContext) -> None:
            polls_at_start[context.endpoint.port] = by_port[context.endpoint.port].polls
            await status.basic(context)

        [verdict] = await run(
            [Group(id="test/settle", run=script)], one, two, workdir=tmp_path / "run"
        )

    assert verdict.outcome is Outcome.MATCH
    assert polls_at_start == {one.endpoint.port: 3, two.endpoint.port: 1}


DEADLINE_S = 0.3
BUSY = "{} still had 2 players online after waiting 0.3 s: watcher, control"


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
        role: Occupancy(online=(2,), names=("watcher", "control"))
        if role in stuck
        else Occupancy(online=(0,))
        for role in ("Reference", "Candidate")
    }
    played: list[int] = []

    async def script(context: GroupContext) -> None:
        played.append(context.endpoint.port)

    async with (
        attached("one", sides["Reference"]) as one,
        attached("two", sides["Candidate"]) as two,
    ):
        [verdict] = await run(
            [Group(id="test/settle", run=script)], one, two, workdir=tmp_path / "run"
        )

    assert verdict.outcome is Outcome.ERROR
    assert verdict.detail == "; ".join(BUSY.format(f"the {role}") for role in stuck)
    assert played == []
