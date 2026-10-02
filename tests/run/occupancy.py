"""Fake servers for the tests of waiting until no player is online (#97).

Each answers the status request from a script of counts, so a test says how many players a
server shows at each poll, and what the server was asked.
"""

import contextlib
import dataclasses
import json
from collections.abc import AsyncIterator, Sequence

from mscts.codec.packets import Codec
from mscts.net import Endpoint
from mscts.run import Attached
from mscts.spec import ServerSpec
from mscts.target import TARGET
from tests.net.fakes import Handler, Peer, serve

_ID = "00000000-0000-0000-0000-000000000001"


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
async def listening(handler: Handler) -> AsyncIterator[Endpoint]:
    """A fake server running `handler` for each connection, at the Endpoint it yields."""
    async with serve(Codec.for_target(TARGET), handler) as endpoint:
        yield endpoint


@contextlib.asynccontextmanager
async def attached(name: str, handler: Handler) -> AsyncIterator[Attached]:
    """An Attached side, a fake server running `handler`."""
    async with listening(handler) as endpoint:
        yield Attached(name, ServerSpec(host=endpoint.host, port=endpoint.port))
