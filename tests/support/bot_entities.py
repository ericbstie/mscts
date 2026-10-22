"""A fake server that tells a joined Bot about entities, and the packets it tells it with."""

import uuid
from collections.abc import Mapping, Sequence

from mscts.codec.packets import Packet
from support.bot_join import LOGIN
from tests.net.fakes import Handler, JoinScript, Peer, answer_each_tick, join_server

UUID = uuid.UUID(int=7)


def added(entity_id: int, kind: int, x: float, y: float, z: float) -> tuple[str, dict[str, object]]:
    """An `add_entity` at `x, y, z` facing nowhere in particular, not moving."""
    return (
        "minecraft:add_entity",
        {
            "entity_id": entity_id,
            "entity_uuid": UUID,
            "type": kind,
            "x": x,
            "y": y,
            "z": z,
            "velocity": {"scale": 0, "x": 0, "y": 0, "z": 0},
            "pitch": 0,
            "yaw": 0,
            "head_yaw": 0,
            "data": 0,
        },
    )


def entity_server(
    seen: list[Packet], packets: Sequence[tuple[str, Mapping[str, object]]]
) -> Handler:
    """Join like vanilla, send `packets` after the Bot's first tick, and answer `sync`."""

    async def then(peer: Peer) -> None:
        requests = 0
        sent = False
        async for packet in peer.packets():
            seen.append(packet)
            if packet.name == "minecraft:client_command":
                requests += 1
                await answer_each_tick(peer, requests)
            elif not sent and packet.name == "minecraft:client_tick_end":
                sent = True
                for name, fields in packets:
                    await peer.send(name, **fields)

    def login_frame(peer: Peer) -> bytes:
        return peer.frame("minecraft:login", **LOGIN)

    return join_server(seen, JoinScript(after_batch=login_frame, then=then))
