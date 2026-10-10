"""Join Groups: what a player receives when it joins a world.

`join/basic` compares one player's join alone, from the login to the end of its first chunk
batch. The window ends where that batch's `chunk_batch_finished` arrives (`observe(until=)`,
#105): later batches, and the animals that walk into view, depend on timing (#30's
measurement).
"""

import contextlib

from mscts.group import GroupContext, group
from mscts.groups._world import pin_joins
from mscts.groups.crafting import RECIPE_ID_MASKS
from mscts.settle import until_no_player_online

_PLAYER = "alice"
"""The Bot that joins."""

_FIRST_BATCH = "minecraft:chunk_batch_finished"
"""The packet whose arrival ends the window: the end of the first chunk batch."""

_REGENERATION = "gamerule natural_health_regeneration"
"""In peaceful, while it is on, a player's saturation goes up by 1 every 20 of its ticks
online (`ServerPlayer.tickRegeneration`). The player's data is saved, so how long one play's
player stayed would change what the next play's `set_health` sends
(docs/research/2026-10-03-peaceful-saturation.md)."""


@group("join/basic", masks=RECIPE_ID_MASKS)
async def basic(context: GroupContext) -> None:
    """One player joins alone and receives the first chunk batch."""
    async with contextlib.AsyncExitStack() as undo:
        await pin_joins(context.control, undo)
        await context.control.run(f"{_REGENERATION} false")
        undo.push_async_callback(context.control.run, f"{_REGENERATION} true")
        # The player joins alone: Control rejoins to undo the rules once the window is over.
        await context.control.leave()
        await until_no_player_online(context.endpoint)
        bot = await context.bot(_PLAYER)
        # alice has left before regeneration is on again, so it never feeds her.
        undo.push_async_callback(until_no_player_online, context.endpoint)
        undo.push_async_callback(bot.close)
        async with context.observe(until=_FIRST_BATCH), context.span("join.to_first_chunk"):
            await bot.join()
