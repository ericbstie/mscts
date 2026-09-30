"""Synthetic Packets, Transcripts and Divergences for Comparison tests."""

import time
from collections.abc import Mapping
from dataclasses import replace

from mscts.codec.packets import Direction, Packet, State
from mscts.compare import ABSENT, Divergence, DivergenceKind
from mscts.transcript import Mark, Transcript

CLIENTBOUND, SERVERBOUND = Direction.CLIENTBOUND, Direction.SERVERBOUND
GROUP = "test/group"
_MS = 1_000_000

_BLANK = Divergence(
    bot="alice",
    index=0,
    kind="field",
    packet="",
    path=None,
    reference=ABSENT,
    candidate=ABSENT,
    test_case="",
)
"""What `divergence` fills in for every field it is not given."""


def divergence(kind: DivergenceKind, /, **fields: object) -> Divergence:
    """A Divergence of `kind` with `fields`, and every other field as `_BLANK` has it.

    Every test builds its Divergences here, so a new Divergence field is one edit.
    """
    return replace(_BLANK, kind=kind, **fields)


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
    *items: tuple[str, Packet] | str, server: str = "vanilla", group_id: str = GROUP
) -> Transcript:
    """A Transcript of `items`, recorded 1 ms apart.

    A (bot, packet) pair is an Event, and a string is the label of a Mark.
    """
    result = Transcript(
        group_id=group_id, server=server, start_ns=time.monotonic_ns() - 1_000_000 * _MS
    )
    for position, item in enumerate(items):
        if isinstance(item, str):
            result.marks.append(Mark(t_ns=position * _MS, label=item))
        else:
            bot, recorded = item
            result.record(bot, recorded, t_ns=position * _MS)
    return result
