"""Bot block actions against a live vanilla 26.3: creative dig and place, an early finish.

Boots a Reference of its own, since Control changes the player's game mode and the world.
Each action is one Observation window, read by time as Compare reads it: the Transcript is
kept in arrival order, so a packet another Bot takes later lands inside an earlier stretch
of `events`, and a window taken by index would shift.
"""

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

import pytest

from mscts.bot import Face
from mscts.codec.packets import Direction
from mscts.compare import OBSERVE_CLOSE, OBSERVE_OPEN
from mscts.group import GroupContext
from mscts.runner import Instance
from mscts.transcript import Transcript

pytestmark = pytest.mark.reference

_TIMEOUT_S = 10.0
DIGGER = "digger"
AIR, STONE = 0, 1
"""Block state ids: air's, and stone's only state (the data generator's blocks.json)."""

DUG = (2, -61, 0)
"""The flat world's top block (grass), two blocks east of where the digger stands, in reach."""
BELOW_DUG = (2, -62, 0)
HARD = (-2, -61, 0)
"""Where Control puts stone for the survival dig, two blocks west."""

SETUP = (
    "tp digger 0.5 -60 0.5 0 0",
    "gamemode creative digger",
    "item replace entity digger hotbar.0 with minecraft:stone",
    "setblock -2 -61 0 minecraft:stone",
)

Window = tuple[int, int]
"""When an Observation window opened, and when it closed for the digger (Transcript time)."""


def windows(transcript: Transcript) -> list[Window]:
    """The digger's Observation windows, in order."""
    opened = [mark.t_ns for mark in transcript.marks if mark.label == OBSERVE_OPEN]
    closed = [mark.t_ns for mark in transcript.marks if mark.label == f"{OBSERVE_CLOSE} {DIGGER}"]
    return list(zip(opened, closed, strict=True))


def received(transcript: Transcript, window: Window, name: str) -> list[dict[str, object]]:
    """The fields of each packet called `name` the digger received inside `window`."""
    opened, closed = window
    return [
        dict(event.packet.fields or {})
        for event in transcript.events
        if event.bot == DIGGER
        and event.packet.direction is Direction.CLIENTBOUND
        and event.packet.name == name
        and opened <= event.t_ns < closed
    ]


def states_at(updates: list[dict[str, object]], block: tuple[int, int, int]) -> list[object]:
    """The block states `updates` set at `block`, in order."""
    x, y, z = block
    return [
        update["block_state"] for update in updates if update["pos"] == {"x": x, "y": y, "z": z}
    ]


@pytest.mark.timeout(180)  # its own boot and stop, a join, six commands and the barriers
@pytest.mark.asyncio
async def test_dig_and_place_in_creative_and_an_early_finish_in_survival(
    boot_reference: Callable[..., AbstractAsyncContextManager[Instance]],
) -> None:
    transcript = Transcript(group_id="reference/bot-blocks", server="vanilla")
    async with boot_reference() as reference:
        context = GroupContext(reference.endpoint, transcript, timeout_s=_TIMEOUT_S)
        try:
            digger = await context.bot(DIGGER)
            await digger.join()
            for command in SETUP:
                await context.control.run(command)
            async with context.observe():
                await digger.dig(*DUG, Face.UP)
            async with context.observe():
                await digger.place(*BELOW_DUG, Face.UP)
            await context.control.run("gamemode survival digger")
            async with context.observe():
                await digger.dig(*HARD, Face.UP)
                await digger.stop_digging(*HARD, Face.UP)  # no tick of breaking between them
        finally:
            await context.close()

    dig, place, survival = windows(transcript)
    # Creative breaks the block at the start; the tick's end sends the change and
    # acknowledges sequence 1.
    assert states_at(received(transcript, dig, "minecraft:block_update"), DUG) == [AIR]
    assert received(transcript, dig, "minecraft:block_changed_ack") == [{"sequence": 1}]
    # The stone used on the block below takes its place. The server sends the block at once
    # (handleUseItemOn), then again with the tick's changes, and acknowledges sequence 2.
    assert states_at(received(transcript, place, "minecraft:block_update"), DUG) == [STONE, STONE]
    assert received(transcript, place, "minecraft:block_changed_ack") == [{"sequence": 2}]
    # Survival does not break the stone on a finish with no breaking time, and sends nothing
    # back for it (ServerPlayerGameMode keeps it as a delayed break, which would end seconds
    # later). It acknowledges up to the finish's sequence, 4 (the start's 3 too, if the two
    # arrived in different ticks).
    assert states_at(received(transcript, survival, "minecraft:block_update"), HARD) == []
    survival_acks = received(transcript, survival, "minecraft:block_changed_ack")
    assert survival_acks in ([{"sequence": 4}], [{"sequence": 3}, {"sequence": 4}])
