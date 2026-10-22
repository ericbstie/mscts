"""What a Bot's Replies answer through, and the packets they answer."""

import asyncio
from typing import TYPE_CHECKING, cast

from mscts.bot import Replies
from mscts.codec.packets import Direction, Packet, State

if TYPE_CHECKING:
    from mscts.net import Connection


class Sent:
    """A stand-in Connection that only records what is sent through it."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, dict[str, object]]] = []

    async def send(self, name: str, /, **fields: object) -> None:
        self.sent.append((name, fields))


def arrived(state: State, name: str, **fields: object) -> Packet:
    return Packet(
        state=state,
        direction=Direction.CLIENTBOUND,
        name=name,
        packet_id=0,
        payload=b"",
        fields=fields,
    )


def answers(replies: Replies, *packets: Packet) -> list[tuple[str, dict[str, object]]]:
    connection = Sent()

    async def feed() -> None:
        for packet in packets:
            await replies(cast("Connection", connection), packet)

    asyncio.run(feed())
    return connection.sent
