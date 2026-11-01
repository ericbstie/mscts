"""The world border: where it is, how it moves, what it blocks and what it does to a player.

The Groups run its commands as an operator Bot called `warden`, so that its own feedback is
compared with the border packets each command makes (facts: the fact sheet of #68, 26.3 javap).
The border is saved with the world (`WorldBorder extends SavedData`), so every Group puts each of
its settings back to vanilla's default (`WorldBorder$Settings.<clinit>`) on the way out: a command
that repeats the value it has fails (`commands.worldborder.*.failed`) and changes nothing, so the
undo of a setting the Group never changed is harmless.

Control is in creative while a Group plays, because a border leaves its spot outside it, and
border damage follows the wall clock, so a survival Control would die there.
"""

import contextlib
from collections.abc import AsyncIterator
from dataclasses import replace

from mscts.bot import Bot
from mscts.group import Control, GroupContext, group
from mscts.groups._world import join_at_spawn, normal, pin_joins
from mscts.spec import CONTROL_PLAYER, ServerSpec

_WARDEN = "warden"
"""The operator Bot that runs the border commands itself, so its own feedback is compared."""

_CHAT = "minecraft:system_chat"
_BORDER = (
    "minecraft:initialize_border",
    "minecraft:set_border_size",
    "minecraft:set_border_lerp_size",
    "minecraft:set_border_center",
    "minecraft:set_border_warning_distance",
    "minecraft:set_border_warning_delay",
)
"""Every packet that carries the border: the whole border a player is sent on a join, and one
packet for each setting a command changes. `damage amount` and `damage buffer` send none."""

_WAIT_S = 30.0
"""How long the warden waits for the feedback of a command: a Bot's bound."""

_UNDO_BORDER = (
    "worldborder set 59999968",
    "worldborder center 0.0 0.0",
    "worldborder warning distance 5",
    "worldborder warning time 300",
    "worldborder damage amount 0.2",
    "worldborder damage buffer 5",
)
"""Puts every border setting back to vanilla's default: the size 59999968, the centre 0.0 0.0
(not `0 0`: `Vec2Argument` adds 0.5 to an integer), a warning of 5 blocks and 300 ticks, and a
damage of 0.2 a block past a buffer of 5."""


def _operator(spec: ServerSpec) -> ServerSpec:
    """Normal difficulty, with the warden an operator."""
    return replace(normal(spec), operators=(*spec.operators, _WARDEN))


async def _set_up(control: Control, undo: contextlib.AsyncExitStack) -> None:
    """Pin the joins, turn regeneration off, put Control in creative and push the border's undo.

    Each undo goes onto `undo` before its command runs, because a command that timed out may
    still have run. The border settings are put back in the order of `_UNDO_BORDER`.
    """
    await pin_joins(control, undo)
    undo.push_async_callback(control.run, "gamerule natural_health_regeneration true")
    await control.run("gamerule natural_health_regeneration false")
    undo.push_async_callback(control.run, f"gamemode survival {CONTROL_PLAYER}")
    await control.run(f"gamemode creative {CONTROL_PLAYER}")
    for command in reversed(_UNDO_BORDER):
        undo.push_async_callback(control.run, command)


@contextlib.asynccontextmanager
async def _fixture(context: GroupContext) -> AsyncIterator[contextlib.AsyncExitStack]:
    """Set the world up for a border Group; yield the stack of undos, which run on the way out."""
    async with contextlib.AsyncExitStack() as undo:
        await _set_up(context.control, undo)
        yield undo


async def _command_window(context: GroupContext, warden: Bot, command: str) -> None:
    """The warden runs `command` in a window of its feedback and the border packets.

    The warden drains first, so that an earlier operator's feedback is not taken for its own,
    and waits for its feedback inside the window, which the barrier alone does not cover.
    """
    await warden.drain()
    async with context.observe(_CHAT, *_BORDER):
        await warden.command(command)
        await warden.expect(_CHAT, timeout_s=_WAIT_S)


# `world/border-commands`

_COMMANDS = (
    "worldborder set 20",
    "worldborder set 40 5",
    "worldborder center 10 10",
    "worldborder warning distance 3",
    "worldborder warning time 5",
    "worldborder damage amount 1",
    "worldborder damage buffer 2",
    "worldborder get",
)
"""The commands, in the order they run. A bare number of time is ticks (`TimeArgument`), so
`set 40 5` is a lerp of 5 ticks, and `warning time 5` is 5 ticks. `center 10 10` centres the
border on (10.5, 10.5), since `Vec2Argument` adds 0.5 to an integer. `get` runs in the frozen
world, in the middle of the lerp, and reads 20."""


@group("world/border-commands", spec=_operator)
async def border_commands(context: GroupContext) -> None:
    """The warden runs each border command in a window of its own, in a frozen world."""
    async with _fixture(context) as undo:
        warden = await join_at_spawn(context, undo, _WARDEN)
        await context.freeze()
        for command in _COMMANDS:
            await _command_window(context, warden, command)
