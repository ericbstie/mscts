"""Container packets as a Bot's inventory sees them, and a joined Bot that is sent some."""

from collections.abc import Awaitable, Callable, Mapping
from typing import TYPE_CHECKING

from mscts.bot import Bot
from mscts.inventory import Inventory
from mscts.transcript import Transcript
from support.bot_entities import entity_server
from support.bot_join import CODEC
from tests.net.fakes import with_bot

if TYPE_CHECKING:
    from mscts.codec.packets import Packet

GENERIC_9X3, FURNACE = 2, 14
"""`minecraft:generic_9x3` and `minecraft:furnace` in `minecraft:menu`."""


CHEST = 3
"""The window id the server gave the open chest."""


CHEST_TITLE = bytes([0x08, 0x00, 0x05]) + b"Chest"  # a network NBT String tag


type Received = tuple[str, Mapping[str, object]]


def open_screen(window_id: int, window_type: int) -> Received:
    fields = {"window_id": window_id, "window_type": window_type, "window_title": CHEST_TITLE}
    return ("minecraft:open_screen", fields)


def inventory_after(
    packets: list[Received],
    script: Callable[[Bot], Awaitable[None]] | None = None,
) -> tuple[Inventory, list[tuple[str, Mapping[str, object] | None]]]:
    """A joined Bot's inventory once `packets` came after its first tick and `script` ran.

    Also returns what the Bot sent after that tick, but statistics requests.
    """
    found: list[Inventory] = []
    seen: list[Packet] = []

    async def use(bot: Bot) -> None:
        await bot.join()
        await bot.tick()
        await bot.sync()
        if script is not None:
            await script(bot)
            await bot.sync()
        found.append(bot.inventory)

    transcript = Transcript(group_id="test/inventory", server="fake")
    with_bot(CODEC, transcript, entity_server(seen, packets), use)
    ends = [
        index for index, packet in enumerate(seen) if packet.name == "minecraft:client_tick_end"
    ]
    after = seen[ends[0] + 1 :]
    sent = [
        (packet.name, packet.fields)
        for packet in after
        if packet.name != "minecraft:client_command"
    ]
    return found[0], sent
