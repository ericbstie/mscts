"""Movement Groups: what the server does with the moves a player reports.

A vanilla client says where its player is, and the server checks each move against its own
copy of the player: a move too far for one tick, a move into a block, a player floating in
the air for too long, a move sent while the server waits for the client to accept a
teleport. When it refuses a move, it sends the player back (`player_position`); when it
refuses a player, it kicks them (`disconnect`). Those two packets are all a window compares:
what a Bot sends is never compared.

Each Group's Bots join with the movement check off (`gamerule player_movement_check false`)
and turn it on once they have joined: a join can repeat its first `player_position` while the
check is on, a race with the server's first tick (docs/research/2026-09-26-join.md). Every
correction carries the next teleport id, so one repeat would shift every id after it. Control
then puts the Bot where each case starts with `/tp`, before its window.

The speed check runs only while the world runs normally
(`ServerGamePacketListenerImpl.handlePlayerPositionChange`, 26.3 javap: `runsNormally()`), so
`movement/too-fast` and `movement/flying` play in a running world. The speed check measures a
move from where the player was when the tick began (`firstGood*`, reset by `tickPlayer`) and
counts the moves since then, the Bot's accept of the `/tp` among them; the window's opening
barrier (`Bot.sync`) puts a server tick between that accept and the first move, so each case is
measured from its start, with no move counted before it. The collision checks run in
a frozen world too, so `movement/into-blocks` and `movement/before-teleport` freeze it and step
it one tick after each move (tick-exact). Every block they set is in chunk (0, 0), the one a
Bot is sent when it joins (docs/guide/writing-a-group.md).
"""

import contextlib
from dataclasses import dataclass

from mscts.bot import Bot
from mscts.group import GroupContext, GroupKind, group

PACKETS = ("minecraft:player_position", "minecraft:disconnect")
"""The packets a window compares: the server sending the player back, and kicking it."""

KICK_TIMEOUT_S = 10.0
"""How long a floating Bot waits to be kicked: `run.GROUP_TIMEOUT_S`, a Bot's bound. Vanilla
kicks it after 80 of its ticks in the air, 4 seconds at 20 ticks a second."""

_MOVEMENT_CHECK = "gamerule player_movement_check"

type _Point = tuple[float, float, float]


@dataclass(frozen=True, slots=True)
class _Case:
    """One window: where the Bot starts, then the moves it sends in each server tick.

    The moves of one tick go back to back, each its own client tick (`Bot.move`), so the
    server takes them in one packet pass.
    """

    start: _Point
    ticks: tuple[tuple[_Point, ...], ...]


async def _join(context: GroupContext, undo: contextlib.AsyncExitStack, *names: str) -> list[Bot]:
    """Join a Bot for each name with the movement check off, then turn the check on again.

    The check is on by default, so turning it on is also the undo, pushed on `undo` before
    the check is turned off: a command that timed out may still have run.
    """
    undo.push_async_callback(context.control.run, f"{_MOVEMENT_CHECK} true")
    await context.control.run(f"{_MOVEMENT_CHECK} false")
    bots = []
    for name in names:
        bot = await context.bot(name)
        await bot.join()
        bots.append(bot)
    await context.control.run(f"{_MOVEMENT_CHECK} true")
    return bots


async def _tp(context: GroupContext, bot: Bot, at: _Point) -> None:
    x, y, z = at
    await context.control.run(f"tp {bot.name} {x} {y} {z}")


async def _play(context: GroupContext, bot: Bot, cases: tuple[_Case, ...], *, frozen: bool) -> None:
    """Play each case in a window of its own: the Bot is put at its start, then moves.

    In a frozen world, the world steps one tick after each tick's moves. In a running one,
    every case has one tick, which the window's barrier ends.
    """
    for case in cases:
        await _tp(context, bot, case.start)
        async with context.observe(*PACKETS):
            for moves in case.ticks:
                for move in moves:
                    await bot.move(*move)
                if frozen:
                    await context.step(1)


# `movement/too-fast`: moves along x from (8.5, -60, 8.5), on the flat world's grass.

_RUNNER = "runner"
_TOO_FAST_START = (8.5, -60.0, 8.5)


def _along_x(*distances: float) -> tuple[_Point, ...]:
    x, y, z = _TOO_FAST_START
    return tuple((x + distance, y, z) for distance in distances)


_TOO_FAST_CASES = (
    *(_Case(_TOO_FAST_START, (_along_x(distance),)) for distance in (1, 5, 9, 11, 20)),
    _Case(_TOO_FAST_START, (_along_x(8, 16),)),
    _Case(_TOO_FAST_START, (_along_x(2, 4, 6, 8, 10, 12),)),
)
"""One move each of 1, 5, 9, 11 and 20 blocks; then two moves of 8 blocks in one tick, and six
of 2 blocks in one tick.

Vanilla refuses a move whose squared length from where the tick began is above 100 times the
moves since the tick began, counting from 1 again past 5 (26.3 javap).
"""


@group("movement/too-fast")
async def too_fast(context: GroupContext) -> None:
    """A Bot moves 1, 5, 9, 11 and 20 blocks in one move each, then several moves in one tick."""
    async with contextlib.AsyncExitStack() as undo:
        [runner] = await _join(context, undo, _RUNNER)
        await _play(context, runner, _TOO_FAST_CASES, frozen=False)


# `movement/into-blocks` and `movement/before-teleport`: blocks at x = 5, in four lanes of z.

_WALKER = "walker"
_WALL = "fill 5 -60 1 5 -58 3 minecraft:stone"
"""A wall 3 blocks high across the lane at z = 2."""

INTO_BLOCKS_WORLD = (
    _WALL,
    "fill 5 -60 5 5 -58 7 minecraft:stone",
    "fill 5 -60 6 5 -59 6 minecraft:air",
    "setblock 5 -60 10 minecraft:stone",
    "setblock 5 -60 13 minecraft:oak_slab[type=bottom]",
)
"""A wall at z = 2; a wall with a gap 1 block wide and 2 high at z = 6; a block at z = 10; a
bottom slab at z = 13."""

_INTO_BLOCKS_CLEAR = "fill 5 -60 1 5 -58 13 minecraft:air"

_INTO_BLOCKS_CASES = (
    _Case((4.5, -60.0, 2.5), (((5.5, -60.0, 2.5),),)),
    _Case(
        (4.5, -60.0, 6.5),
        (((5.0, -60.0, 6.5),), ((5.5, -60.0, 6.5),), ((6.0, -60.0, 6.5),), ((6.5, -60.0, 6.5),)),
    ),
    _Case((4.5, -60.0, 10.5), (((5.5, -59.0, 10.5),),)),
    _Case((4.5, -60.0, 13.5), (((5.5, -59.5, 13.5),),)),
)
"""Into the wall; through the gap, half a block a tick; up onto the block, without a jump; up
onto the slab."""


async def _frozen_world(
    context: GroupContext, undo: contextlib.AsyncExitStack, bot: Bot, world: tuple[str, ...]
) -> None:
    """Freeze the world and set `world`'s blocks, clearing them on the way out.

    The Bot is moved to where the first case starts first: it joined at a random place near
    the world spawn, which a block could fill.
    """
    await _tp(context, bot, _INTO_BLOCKS_CASES[0].start)
    await context.freeze()
    undo.push_async_callback(context.control.run, _INTO_BLOCKS_CLEAR)
    for command in world:
        await context.control.run(command)


@group("movement/into-blocks", kind=GroupKind.TICK_EXACT)
async def into_blocks(context: GroupContext) -> None:
    """A Bot walks into a wall, through a gap, up a full block and up onto a slab."""
    async with contextlib.AsyncExitStack() as undo:
        [walker] = await _join(context, undo, _WALKER)
        await _frozen_world(context, undo, walker, INTO_BLOCKS_WORLD)
        await _play(context, walker, _INTO_BLOCKS_CASES, frozen=True)


_BEFORE_TELEPORT_CASE = _Case(
    (4.5, -60.0, 2.5),
    (((5.5, -60.0, 2.5), (5.6, -60.0, 2.5), (5.7, -60.0, 2.5), (4.0, -60.0, 2.5)),),
)
"""Into the wall, which vanilla answers with a teleport back; then, before the Bot has had it,
two more moves into the wall and one back out.

Vanilla takes only the rotation of a move while it waits for the client to accept a teleport
(`updateAwaitingTeleport`). The Bot accepts it as soon as it arrives, so the moves after the
first must go out before it does: they go back to back, in one tick.
"""


@group("movement/before-teleport", kind=GroupKind.TICK_EXACT)
async def before_teleport(context: GroupContext) -> None:
    """A Bot sends moves after the server has sent it back, before it accepts the teleport."""
    async with contextlib.AsyncExitStack() as undo:
        [walker] = await _join(context, undo, _WALKER)
        await _frozen_world(context, undo, walker, (_WALL,))
        await _play(context, walker, (_BEFORE_TELEPORT_CASE,), frozen=True)


# `movement/flying`: two Bots hover 1.5 blocks above the grass, one in creative.

_FLYER = "flyer"
_CREATIVE_FLYER = "creative_flyer"
_HOVER = 1.5


async def _hover(bot: Bot, x: float, z: float) -> None:
    """Rise 1.5 blocks off the ground, then move once more in the air.

    Vanilla counts a player as floating from a move that starts in the air
    (`verticalCollisionBelow` is read before the move), so the first move alone is not enough.
    """
    await bot.move(x, -60.0 + _HOVER, z, on_ground=False)
    await bot.move(x, -60.0 + _HOVER + 0.1, z, on_ground=False)


@group("movement/flying")
async def flying(context: GroupContext) -> None:
    """A survival Bot and a creative Bot hover in the air until the survival one is kicked."""
    async with contextlib.AsyncExitStack() as undo:
        creative, flyer = await _join(context, undo, _CREATIVE_FLYER, _FLYER)
        await context.control.run(f"gamemode creative {_CREATIVE_FLYER}")
        undo.push_async_callback(context.control.run, f"gamemode survival {_CREATIVE_FLYER}")
        await _tp(context, creative, (2.5, -60.0, 2.5))
        await _tp(context, flyer, (6.5, -60.0, 2.5))
        # The creative Bot rises first, so it has floated longer than the survival one by
        # the time that one is kicked: past vanilla's limit, without a clock.
        async with context.observe(*PACKETS):
            await _hover(creative, 2.5, 2.5)
            await _hover(flyer, 6.5, 2.5)
            await flyer.expect("minecraft:disconnect", timeout_s=KICK_TIMEOUT_S)
