"""Synthetic Packets and Transcripts for Comparison tests."""

import time
from collections.abc import Mapping

from mscts.codec.packets import Direction, Packet, State
from mscts.transcript import Transcript

CLIENTBOUND, SERVERBOUND = Direction.CLIENTBOUND, Direction.SERVERBOUND
SCENARIO = "test/scenario"
_MS = 1_000_000


def packet(
    name: str,
    payload: bytes = b"",
    *,
    state: State = State.PLAY,
    direction: Direction = CLIENTBOUND,
    fields: Mapping[str, object] | None = None,
) -> Packet:
    """A Packet; clientbound in play and without fields, unless told otherwise."""
    return Packet(
        state=state, direction=direction, name=name, packet_id=0, payload=payload, fields=fields
    )


def transcript(
    *events: tuple[str, Packet], server: str = "vanilla", scenario_id: str = SCENARIO
) -> Transcript:
    """A Transcript of `events`, each a (bot, packet) pair, recorded 1 ms apart."""
    result = Transcript(
        scenario_id=scenario_id, server=server, start_ns=time.monotonic_ns() - 1_000_000 * _MS
    )
    for position, (bot, recorded) in enumerate(events):
        result.record(bot, recorded, t_ns=position * _MS)
    return result
