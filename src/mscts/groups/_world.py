"""World setup that more than one Group uses."""

import contextlib

from mscts.group import Control

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
