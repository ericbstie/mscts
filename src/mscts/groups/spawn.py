"""Spawn Groups: where a new player first appears, relative to the world spawn.

A joining player is placed in the configuration phase (`PrepareSpawnTask.start`): where its
saved data says, and only a player with none goes to `PlayerSpawnFinder.findSpawn`, which tries
the blocks within `respawn_radius` of the world spawn from a random start
(docs/research/2026-10-15-spawn-position.md). A play therefore needs a new player name, not a
new world: it joins `spawnpos<play>`, which no earlier play of the Run joined.
"""

import math

from mscts.group import GroupContext, GroupKind, group

_SPAWN_BLOCK_CENTRE = 0.5
"""The x and z of the middle of the world spawn block (`setworldspawn 0 -60 0`)."""


@group("spawn/join-position", kind=GroupKind.STATISTICAL)
async def join_position(context: GroupContext) -> None:
    """A new player joins with `respawn_radius` at its default; where it appears is sampled."""
    await context.control.run("setworldspawn 0 -60 0")
    await _join_and_sample(context, f"spawnpos{context.play}")


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
