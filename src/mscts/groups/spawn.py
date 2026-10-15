"""Spawn Groups: where a new player first appears, relative to the world spawn.

A joining player is placed in the configuration phase (`PrepareSpawnTask.start`): where its
saved data says, and only a player with none goes to `PlayerSpawnFinder.findSpawn`, which tries
the blocks within `respawn_radius` of the world spawn from a random start
(docs/research/2026-10-15-spawn-position.md). A play therefore needs a new player name, not a
new world: it joins `spawnpos` or `spawnexact` with the Run's characters and its play after
it (`GroupContext.player_name`), a name no earlier play or Run joined.
"""

import contextlib
import math

from mscts.group import GroupContext, GroupKind, group
from mscts.groups._world import pin_joins

_SET_SPAWN = "setworldspawn 0 -60 0"
"""The Fixture: the world spawn is the block at (0, -60, 0)."""

_SPAWN_BLOCK_CENTRE = 0.5
"""The x and z of the middle of the world spawn block (`setworldspawn 0 -60 0`)."""


@group("spawn/join-position", kind=GroupKind.STATISTICAL)
async def join_position(context: GroupContext) -> None:
    """A new player joins with `respawn_radius` at its default; where it appears is sampled."""
    await context.control.run(_SET_SPAWN)
    await _join_and_sample(context, context.player_name("spawnpos"))


@group("spawn/join-position-exact", kind=GroupKind.STATISTICAL)
async def join_position_exact(context: GroupContext) -> None:
    """A new player joins with `respawn_radius` 0: every one appears on the spawn column."""
    async with contextlib.AsyncExitStack() as undo:
        await context.control.run(_SET_SPAWN)
        await pin_joins(context.control, undo)
        await _join_and_sample(context, context.player_name("spawnexact"))


async def _join_and_sample(context: GroupContext, name: str) -> None:
    """Join a Bot called `name` and record where the server puts it, from the spawn block."""
    player = await context.bot(name)
    await player.join()
    x = player.position.x - _SPAWN_BLOCK_CENTRE
    z = player.position.z - _SPAWN_BLOCK_CENTRE
    context.sample("spawn.x", x)
    context.sample("spawn.y", player.position.y)
    context.sample("spawn.z", z)
    context.sample("spawn.distance", math.hypot(x, z))
