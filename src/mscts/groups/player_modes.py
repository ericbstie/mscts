"""Player Groups: game modes, death and respawn.

`player/game-modes` switches a Bot through every game mode while a second Bot watches.

The Bots are put back at the spawn, in survival, when the Group ends, and every rule is set back,
because every Group is played on the same two Instances. Control stands far from the Bots: it is a
player too, and it joins where the last Group left it, which may be in their view
(docs/roles/player-actions.md, #300).
"""

import contextlib
from collections.abc import AsyncIterator
from dataclasses import replace

from mscts.bot import Bot
from mscts.group import GroupContext, group
from mscts.groups._world import pin_joins
from mscts.spec import CONTROL_PLAYER, Difficulty, ServerSpec

_SPAWN_AT = "0.5 -60 0.5"
"""Where a Bot is put when the Group ends: the world spawn."""

_CONTROL_AT = "96.5 -60 96.5"
"""Where Control stands: 6 chunks from the spawn, out of every Bot's view."""

_WATCHER_AT = "4.5 -60 0.5"
"""Where the watcher stands: in view of the Bot, and clear of its place."""


def _normal(spec: ServerSpec) -> ServerSpec:
    """Play on normal difficulty."""
    return replace(spec, difficulty=Difficulty.NORMAL)


@contextlib.asynccontextmanager
async def _arena(context: GroupContext) -> AsyncIterator[contextlib.AsyncExitStack]:
    """Pin the joins and move Control away; undo it all on exit.

    Yields the stack of undos, for what the body sets: they run first, each even if another
    fails.
    """
    control = context.control
    async with contextlib.AsyncExitStack() as undo:
        await pin_joins(control, undo)
        await control.run(f"tp {CONTROL_PLAYER} {_CONTROL_AT}")
        yield undo


async def _join(context: GroupContext, undo: contextlib.AsyncExitStack, name: str) -> Bot:
    """Join a Bot, and have it put back at the spawn, in survival, when the Group ends."""
    bot = await context.bot(name)
    await bot.join()
    undo.push_async_callback(context.control.run, f"tp {name} {_SPAWN_AT}")
    undo.push_async_callback(context.control.run, f"gamemode survival {name}")
    await context.control.run(f"gamemode survival {name}")
    return bot


# `player/game-modes`

_CHANGER = "changer"
_WATCHER = "watcher"

MODE_PACKETS = (
    "minecraft:player_abilities",
    "minecraft:game_event",
    "minecraft:player_info_update",
    "minecraft:set_entity_data",
    "minecraft:update_attributes",
    "minecraft:waypoint",
)
"""The packets a window compares: the abilities, the game mode event, the tab list, and the
entity data, attributes and waypoint the mode changes."""

_MODES = ("creative", "adventure", "spectator", "survival")


@group("player/game-modes", spec=_normal)
async def game_modes(context: GroupContext) -> None:
    """A Bot is switched from survival to creative, adventure, spectator and survival again.

    A second Bot watches it, in a window for each switch.
    """
    async with _arena(context) as undo:
        await _join(context, undo, _CHANGER)
        await _join(context, undo, _WATCHER)
        await context.control.run(f"tp {_WATCHER} {_WATCHER_AT}")
        for mode in _MODES:
            async with context.observe(*MODE_PACKETS):
                await context.control.run(f"gamemode {mode} {_CHANGER}")
