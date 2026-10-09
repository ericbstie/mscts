"""World setup that more than one Group uses."""

import contextlib

from mscts.bot import Bot
from mscts.group import Control, GroupContext

CONTROL_AT = "96.5 -60 96.5"
"""Where Control stands: 6 chunks from the spawn, clear of every block the Groups set (#300) and
out of the Bot's view, so that its entity is never sent to the Bot again when the Bot respawns:
vanilla sends it a tick or so later, which no window can place."""

SPAWN_AT = "0.5 -60 0.5"
"""Where a Bot is put when the Group ends: the world spawn, clear of every block a Group sets."""

_MOVEMENT_CHECK = "gamerule player_movement_check"
"""The check that can repeat a join's first `player_position`, a race with the first tick
(docs/research/2026-09-26-join.md; `ServerGamePacketListenerImpl.shouldCheckPlayerMovement`
returns false when the rule is off)."""

_RESPAWN_RADIUS = "gamerule respawn_radius"
"""How far from the world spawn a player may spawn: 10 by default in 26.3, at random. At 0
both Instances spawn the player at the same place, so they send the same chunks (measured on
#30: 20 of 20 plays, with no `setworldspawn`, which could not be undone)."""


async def pin_joins(control: Control, undo: contextlib.AsyncExitStack) -> None:
    """Make a joining player spawn at the world spawn and be placed there once.

    Sets `respawn_radius` to 0 and turns `player_movement_check` off, through `control`, and
    pushes onto `undo` the commands that set both back to vanilla's defaults.
    """
    await control.run(f"{_MOVEMENT_CHECK} false")
    undo.push_async_callback(control.run, f"{_MOVEMENT_CHECK} true")
    await control.run(f"{_RESPAWN_RADIUS} 0")
    undo.push_async_callback(control.run, f"{_RESPAWN_RADIUS} 10")


async def join_at_spawn(context: GroupContext, undo: contextlib.AsyncExitStack, name: str) -> Bot:
    """Join a Bot, and have it put back at the spawn when the Group ends.

    The server saves a player where it leaves, so a Bot left in the Group's pool or stone would
    rejoin inside that block, on the next play (#300).
    """
    bot = await context.bot(name)
    await bot.join()
    undo.push_async_callback(context.control.run, f"tp {name} {SPAWN_AT}")
    return bot


async def fresh(context: GroupContext, bot: Bot) -> None:
    """Kill the Bot and respawn it, so that it has full health, food and air and is not burning.

    The server saves a player when it leaves: its air, health and fire, and where it was.
    """
    await context.control.run(f"kill {bot.name}")
    await bot.respawn()
