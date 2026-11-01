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
from dataclasses import dataclass, replace

from mscts.bot import Bot
from mscts.group import Control, GroupContext, GroupKind, group
from mscts.groups._world import SPAWN_AT, join_at_spawn, normal, pin_joins
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


# `world/border-lerp`

_GROW_TICKS = 10
"""How many ticks the border takes to grow from 20 to 40: 2 blocks a tick."""

_SHRINK_TICKS = 10

_EXTRA_STEPS = 2
"""Steps past the end of a lerp: the border has stopped, and nothing more is sent."""

_LATE_JOIN_AFTER = 4
"""After how many steps of the growth the latecomer joins."""

_LATECOMER = "latecomer"

_GET = "worldborder get"


async def _join_late(context: GroupContext, undo: contextlib.AsyncExitStack) -> None:
    """A second Bot joins in a window of the border packets, in the middle of the lerp.

    It is told where the lerp is: `initialize_border` has the size now as its old size and the
    ticks left as its lerp time.
    """
    latecomer = await context.bot(_LATECOMER)
    undo.push_async_callback(context.control.run, f"tp {_LATECOMER} {SPAWN_AT}")
    async with context.observe(*_BORDER):
        await latecomer.join()


async def _read_each_step(
    context: GroupContext, undo: contextlib.AsyncExitStack, warden: Bot
) -> None:
    """Step the lerp's ticks and two more, one at a time; the warden reads the size after each.

    Control's `tick step` stays outside every window: an operator hears it as admin chat.
    """
    for step in range(1, _GROW_TICKS + _EXTRA_STEPS + 1):
        await context.step()
        await _command_window(context, warden, _GET)
        if step == _LATE_JOIN_AFTER:
            await _join_late(context, undo)


async def _shrink(context: GroupContext, warden: Bot) -> None:
    """Start a shrinking lerp, step it in one window of the border packets, and read the size.

    A server that sends the border on each tick of a lerp differs in the window.
    """
    await _command_window(context, warden, f"worldborder set 10 {_SHRINK_TICKS}")
    async with context.observe(*_BORDER):
        await context.step(_SHRINK_TICKS + _EXTRA_STEPS)
    await _command_window(context, warden, _GET)


@group("world/border-lerp", kind=GroupKind.TICK_EXACT, spec=_operator)
async def border_lerp(context: GroupContext) -> None:
    """A border of 20 grows to 40 over 10 ticks, read after each step; then shrinks to 10.

    Vanilla moves the border on the world's clock: `ServerLevel.tick` ticks it only when the
    world runs normally, and each tick takes one off the ticks left (`MovingBorderExtent.update`).
    So the border reads 22, 24 ... 40 after each step of a frozen world. No packet comes on any
    tick of the lerp, or when it ends.
    """
    async with _fixture(context) as undo:
        warden = await join_at_spawn(context, undo, _WARDEN)
        await context.freeze()
        await context.control.run("worldborder set 20")
        await _command_window(context, warden, f"worldborder set 40 {_GROW_TICKS}")
        await _read_each_step(context, undo, warden)
        await _shrink(context, warden)


# `world/border-collision`

_WALKER = "walker"
_Y = -60.0
_Z = 0.5
_COLLISION_PACKETS = ("minecraft:player_position", "minecraft:disconnect", *_BORDER)
"""What a window compares: the server sending the player back, kicking it, or changing the
border."""


@dataclass(frozen=True)
class _Walk:
    """One window: where the Bot is put, then the x it moves to in each tick."""

    start: float
    xs: tuple[float, ...]


def _along(start: float, step: float, count: int) -> tuple[float, ...]:
    """The `count` x a Bot reaches by moving `step` along x from `start`, one move each."""
    return tuple(round(start + step * k, 6) for k in range(1, count + 1))


_WALKS = (
    _Walk(6.5, _along(6.5, 0.2, 13)),
    _Walk(6.5, _along(6.5, 0.3, 9)),
    _Walk(6.5, _along(6.5, 0.5, 5)),
    _Walk(7.5, (8.5,)),
    _Walk(9.5, _along(9.5, -0.2, 8)),
)
"""Moves along x toward the border of a 16-wide border around 0, 0, whose plane is at x 8: 0.2, 0.3
and 0.5 a tick from 6.5, a jump of a block from 7.5, and last 0.2 a tick from outside, back in.
The player is 0.6 wide, so its box touches the plane at x 7.7.

Vanilla clips a move at the plane and sends the player back only if the clipped move is off by
more than 0.25 (`ServerGamePacketListenerImpl.handleMovePlayer`): at 0.2 a tick it sends nothing,
and at 0.3 or more it sends the player back to x 7.7 or 7.5 on each move from the plane on."""


async def _walk(context: GroupContext, walker: Bot, walk: _Walk) -> None:
    """Put the Bot at the start, then in a window move it a tick at a time, as `walk` says."""
    await context.control.run(f"tp {_WALKER} {walk.start} {_Y} {_Z}")
    async with context.observe(*_COLLISION_PACKETS):
        for x in walk.xs:
            await walker.move(x, _Y, _Z)
            await context.step_after(walker)


@group("world/border-collision", kind=GroupKind.TICK_EXACT, spec=normal)
async def border_collision(context: GroupContext) -> None:
    """A survival Bot walks into a border of 16 wide, one move a stepped tick, at several speeds."""
    async with _fixture(context) as undo:
        walker = await join_at_spawn(context, undo, _WALKER)
        await context.control.run("gamerule player_movement_check true")
        await context.freeze()
        await context.control.run("worldborder set 16")
        for walk in _WALKS:
            await _walk(context, walker, walk)
