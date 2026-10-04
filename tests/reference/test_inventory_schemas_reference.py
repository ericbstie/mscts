"""The container schemas against a live vanilla 26.3: what a join, a give and a chest send.

Boots a Reference of its own, since Control gives items and places a chest. Every container
packet the player receives decodes with the Codec's schema and encodes back to the same bytes.
"""

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from typing import cast

import pytest

from mscts.bot import Face
from mscts.codec.packets import Codec, Direction, State
from mscts.group import GroupContext
from mscts.runner import Instance
from mscts.transcript import Transcript

pytestmark = pytest.mark.reference

CODEC = Codec.load("26.3")
_TIMEOUT_S = 10.0
OPENER = "opener"
CHEST = (2, -60, 0)
"""On the flat world's grass, two blocks east of where the opener stands, in reach."""
GENERIC_9X3 = 2
"""A single chest's menu type: `minecraft:generic_9x3`, id 2 in `minecraft:menu` (registries)."""

SETUP = (
    "tp opener 0.5 -60 0.5 0 0",
    "give opener minecraft:stone 64",
    "give opener minecraft:diamond_sword",
    "setblock 2 -60 0 minecraft:chest",
)

CONTAINER_PACKETS = frozenset(
    {
        "minecraft:open_screen",
        "minecraft:container_set_content",
        "minecraft:container_set_slot",
        "minecraft:container_set_data",
        "minecraft:container_close",
        "minecraft:set_cursor_item",
        "minecraft:set_player_inventory",
    }
)


@pytest.mark.timeout(180)  # its own boot and stop, a join, four commands and a barrier
@pytest.mark.asyncio
async def test_every_container_packet_vanilla_sends_decodes_and_encodes_to_the_same_bytes(
    boot_reference: Callable[..., AbstractAsyncContextManager[Instance]],
) -> None:
    transcript = Transcript(group_id="reference/inventory-schemas", server="vanilla")
    async with boot_reference() as reference:
        context = GroupContext(reference.endpoint, transcript, timeout_s=_TIMEOUT_S)
        try:
            opener = await context.bot(OPENER)
            await opener.join()
            for command in SETUP:
                await context.control.run(command)
            await opener.place(*CHEST, Face.UP)  # the use opens the chest
            await opener.expect("minecraft:open_screen", timeout_s=_TIMEOUT_S)
            await opener.sync()
        finally:
            await context.close()

    packets = [
        event.packet
        for event in transcript.events
        if event.bot == OPENER
        and event.packet.direction is Direction.CLIENTBOUND
        and event.packet.name in CONTAINER_PACKETS
    ]
    for packet in packets:
        assert packet.fields is not None, (packet.name, packet.decode_error)
        encoded = CODEC.encode(State.PLAY, packet.direction, packet.name, packet.fields)
        assert encoded == bytes([packet.packet_id]) + packet.payload, packet.name
    names = {packet.name for packet in packets}
    assert {"minecraft:container_set_content", "minecraft:container_set_slot"} <= names
    (screen,) = [packet.fields for packet in packets if packet.name == "minecraft:open_screen"]
    assert screen is not None
    assert screen["window_type"] == GENERIC_9X3
    contents = [
        packet.fields
        for packet in packets
        if packet.name == "minecraft:container_set_content"
        and packet.fields is not None
        and packet.fields["window_id"] == screen["window_id"]
    ]
    # A single chest's menu: its 27 slots, then the player's 27 and its hotbar's 9.
    assert [len(cast("list[object]", fields["slot_data"])) for fields in contents] == [63]
