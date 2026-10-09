"""Blocks Groups for a player: breaking blocks with a tool, and placing blocks onto a face.

A Bot called `digger` breaks and places blocks, and a second Bot, `watcher`, stands nearby
and receives what the server tells the other players about it: the cracks (`block_destruction`)
and the break particles (`level_event`), which vanilla does not send to the player who causes
them. Control sets each case up before its window, with commands, and undoes everything after
the last (a Group leaves the Instance as it found it, because every Group is played on the
same two Instances).

The world is frozen, so a dropped item stays where it appears and nothing but a Bot changes a
block (random ticks are off). `blocks/dig-creative` and `blocks/place` step it a tick at a time
(`GroupContext.step`). `blocks/dig-survival` cannot: a frozen world still runs its players'
ticks, so that Group waits by the clock (see `_dig_survival`).
Every block these Groups change is in chunk (0, 0), the one a Bot is sent when it joins
(docs/guide/writing-a-group.md).
"""

import asyncio
import contextlib
import struct
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace

from mscts.bot import Bot, Face
from mscts.group import GroupContext, GroupKind, group
from mscts.groups.blocks import DROP_MASKS
from mscts.spec import CONTROL_PLAYER, GameMode, ServerSpec

DIGGER = "digger"
"""The Bot that digs and places."""

WATCHER = "watcher"
"""The Bot that watches: vanilla tells the other players about a crack and a break, not the one
who digs."""

DIGGER_AT = "8.5 -60 4.5"
"""Where the digger stands for every case, facing south (yaw 0), on the flat world's grass,
in chunk (0, 0). The blocks of every case are 1.5 to 4 blocks south of it."""

WATCHER_AT = "12.5 -60 4.5"
CONTROL_AT = "4.5 -60 4.5"
"""Where the watcher and Control stand, clear of every block the Groups set (#300: Control is
a player too, and a block set where a player stands makes it crawl and choke on one Instance
only)."""

PACKETS = (
    "minecraft:block_update",
    "minecraft:block_changed_ack",
    "minecraft:block_destruction",
    "minecraft:level_event",
    "minecraft:add_entity",
    "minecraft:set_entity_data",
    "minecraft:container_set_slot",
)
"""The packets a window compares: the block as it changes or is sent back, the cracks and
particles, the item a block drops, and the slot a tool wears or a block is taken from."""

SURVIVAL_PACKETS = tuple(
    name for name in PACKETS if name not in {"minecraft:block_destruction", "minecraft:level_event"}
)
"""What `blocks/dig-survival` compares: the cracks and the particles of a dig are sent on the
server's clock (a `level_event` 2019 or 2020 each tick, a `block_destruction` each time the
stage changes), so how many a window holds depends on how long it lasts."""

_HOTBAR_0 = "hotbar.0"
_TAG = "mscts_blocks_player"
_KILL_ITEMS = "kill @e[type=minecraft:item]"

type _Cell = tuple[int, int, int]


def _creative(spec: ServerSpec) -> ServerSpec:
    return replace(spec, game_mode=GameMode.CREATIVE)


async def _stage(context: GroupContext, undo: contextlib.AsyncExitStack) -> Bot:
    """Join the digger and the watcher, put the two Bots and Control in place, and freeze the world.

    The digger reports where it stands, on the ground: the server divides dig speed by 5 for a
    player that is not on the ground, and a Bot teleported by a command has not said so yet.
    """
    control = context.control
    digger = await context.bot(DIGGER)
    await digger.join()
    watcher = await context.bot(WATCHER)
    await watcher.join()
    for player, at in ((DIGGER, DIGGER_AT), (WATCHER, WATCHER_AT), (CONTROL_PLAYER, CONTROL_AT)):
        await control.run(f"tp {player} {at} 0 0")
    await digger.sync()
    position = digger.position
    await digger.move(position.x, position.y, position.z, on_ground=True)
    undo.push_async_callback(control.run, "gamerule random_tick_speed 3")
    await control.run("gamerule random_tick_speed 0")
    await context.freeze()
    return digger


async def _give(context: GroupContext, item: str) -> None:
    """Put `item` (an id and a count, or `minecraft:air`) in the digger's first hotbar slot."""
    await context.control.run(f"item replace entity {DIGGER} {_HOTBAR_0} with {item}")


# Breaking: the stone, dirt and obsidian are one block south-east of the digger's feet.

_BLOCK: _Cell = (8, -60, 6)
_FACE = Face.NORTH
"""The face the digger hits: the one it faces."""


def _float32(value: float) -> float:
    return struct.unpack(">f", struct.pack(">f", value))[0]


@dataclass(frozen=True, slots=True)
class _Dig:
    """One dig: the block at `_BLOCK`, the tool in hand, and how long the digger waits to finish.

    `ticks` is how many server ticks the digger waits between the start and the finish. It is
    None where the dig has no finish: in creative the start breaks the block.
    """

    block: str
    tool: str
    ticks: int | None


TICK_S = 0.05
"""How long a server tick lasts at 20 ticks a second, which a Group waits to let ticks pass."""

_HAND = "minecraft:air"
_DIAMOND_PICKAXE = "minecraft:diamond_pickaxe"
_BREAK_FINISH = 0.7
"""The share of a block's progress that the server asks for at the finish
(`ServerPlayerGameMode.handleBlockBreakAction`, STOP_DESTROY_BLOCK)."""

SLACK_TICKS = 20
"""How many ticks an on-time finish waits beyond the least the server accepts, so that a server
that runs late cannot refuse it."""


def _progress(speed: float, hardness: float, divisor: int) -> float:
    return _float32(_float32(speed / hardness) / divisor)


def break_ticks(speed: float, hardness: float, divisor: int) -> int:
    """How many client ticks after the start a vanilla client finishes a block.

    The client adds `speed / hardness / divisor` (the divisor is 30 with the tool the block
    needs, or none is needed, and 100 without) to its progress each tick, in binary32, and
    sends the finish on the tick it reaches 1 (`MultiPlayerGameMode.continueDestroyBlock`).
    """
    per_tick = _progress(speed, hardness, divisor)
    progress, ticks = 0.0, 0
    while progress < 1.0:
        progress = _float32(progress + per_tick)
        ticks += 1
    return ticks


def accept_ticks(speed: float, hardness: float, divisor: int) -> int:
    """How many ticks of dig the server needs before it accepts a finish.

    It accepts when `progress * (ticks + 1)` reaches 0.7, in binary32
    (`ServerPlayerGameMode.handleBlockBreakAction`, STOP_DESTROY_BLOCK).
    """
    per_tick = _progress(speed, hardness, divisor)
    ticks = 0
    while _float32(per_tick * (ticks + 1)) < _float32(_BREAK_FINISH):
        ticks += 1
    return ticks


def finish_ticks(speed: float, hardness: float, divisor: int) -> int:
    """How many ticks an on-time finish waits: the client's, or `SLACK_TICKS` past the server's."""
    return max(
        break_ticks(speed, hardness, divisor),
        accept_ticks(speed, hardness, divisor) + SLACK_TICKS,
    )


async def _set_up(context: GroupContext, dig: _Dig) -> None:
    x, y, z = _BLOCK
    await context.control.run(f"setblock {x} {y} {z} {dig.block}")
    await _give(context, dig.tool)


async def _take_away(context: GroupContext) -> None:
    """Take the block and its drops away, so the next case is its own.

    The server keeps a finish it refused, and breaks the block once it should have broken
    (`ServerPlayerGameMode.tick`): air disarms that on the player's next tick, and a step
    guarantees one.
    """
    x, y, z = _BLOCK
    await context.control.run(f"setblock {x} {y} {z} minecraft:air")
    await context.control.run(_KILL_ITEMS)
    await context.step(1)


async def _dig_creative(context: GroupContext, digger: Bot, dig: _Dig) -> None:
    """Play one creative dig: the start breaks the block, in one window and one tick."""
    x, y, z = _BLOCK
    await _set_up(context, dig)
    await context.step(1)  # the block set reaches the Bots before the window opens
    async with context.observe(*PACKETS):
        await digger.dig(x, y, z, _FACE)
        await context.step(1)


async def _dig_survival(
    context: GroupContext,
    digger: Bot,
    dig: _Dig,
    sleep: Callable[[float], Awaitable[None]],
) -> None:
    """Play one survival dig: start in a window, wait on the clock, finish in another.

    Dig progress is counted in the server's ticks, and a frozen world still ticks its players
    (`ServerPlayerGameMode.tick` counts `gameTicks` in every tick), so a stepped world cannot
    time a dig: one step takes about 6 ticks of the clock. The wait is by the clock, outside
    every window, and the finish is in a window of its own.
    """
    if dig.ticks is None:
        msg = f"a survival dig of {dig.block} has no finish"
        raise ValueError(msg)
    x, y, z = _BLOCK
    await _set_up(context, dig)
    async with context.observe(*SURVIVAL_PACKETS):
        await digger.dig(x, y, z, _FACE)
    await sleep(dig.ticks * TICK_S)
    async with context.observe(*SURVIVAL_PACKETS):
        await digger.stop_digging(x, y, z, _FACE)
    await _take_away(context)


async def _respawn(context: GroupContext, digger: Bot) -> None:
    """Kill the digger and respawn it where it stood: the server counts its dig time anew."""
    await context.control.run(f"kill {DIGGER}")
    await digger.respawn()
    await context.control.run(f"tp {DIGGER} {DIGGER_AT} 0 0")
    await digger.sync()
    position = digger.position
    await digger.move(position.x, position.y, position.z, on_ground=True)


EARLY_CASES = (
    _Dig("minecraft:stone", _HAND, 1),
    _Dig("minecraft:obsidian", _DIAMOND_PICKAXE, 1),
)
"""Finishes sent as the start is sent, which the server refuses: a block that takes a hand
104 ticks, and obsidian that takes a diamond pickaxe 131 (the right tool, so that it is the
time that is wrong)."""

SURVIVAL_CASES = (
    _Dig("minecraft:stone", "minecraft:wooden_pickaxe", finish_ticks(2.0, 1.5, 30)),
    _Dig("minecraft:stone", "minecraft:iron_pickaxe", finish_ticks(6.0, 1.5, 30)),
    _Dig("minecraft:dirt", _HAND, finish_ticks(1.0, 0.5, 30)),
    _Dig("minecraft:stone", _HAND, finish_ticks(1.0, 1.5, 100)),
    _Dig("minecraft:obsidian", _DIAMOND_PICKAXE, finish_ticks(8.0, 50.0, 30)),
)
"""Finishes sent when the client would send them, which the server accepts: the block breaks and
drops. Obsidian and stone by hand take the longest, 188 and 151 ticks."""

UPTIME_S = 3.0
"""How long the digger waits after its last early finish, so that the first on-time finishes are
accepted: the cheapest need 15 ticks (0.75 s) of the digger's time or less, and the two that need
more (104 and 131 ticks, 5.2 s and 6.6 s) come after 15 s or more of it."""


@group("blocks/dig-survival", masks=DROP_MASKS)
async def dig_survival(context: GroupContext) -> None:
    """The digger finishes digs far too early (refused), then on time (accepted)."""
    async with contextlib.AsyncExitStack() as undo:
        digger = await _stage(context, undo)
        undo.push_async_callback(context.control.run, _KILL_ITEMS)
        for dig in EARLY_CASES:
            await _respawn(context, digger)  # an early finish is early only for a new player
            await _dig_survival(context, digger, dig, asyncio.sleep)
        await asyncio.sleep(UPTIME_S)
        for dig in SURVIVAL_CASES:
            await _dig_survival(context, digger, dig, asyncio.sleep)


_CREATIVE_CASES = (
    _Dig("minecraft:stone", _HAND, None),
    _Dig("minecraft:dirt", _HAND, None),
    _Dig("minecraft:obsidian", _HAND, None),
    _Dig("minecraft:stone", "minecraft:iron_sword", None),
)


@group("blocks/dig-creative", spec=_creative, masks=DROP_MASKS, kind=GroupKind.TICK_EXACT)
async def dig_creative(context: GroupContext) -> None:
    """The digger breaks stone, dirt and obsidian at once, and cannot with a sword."""
    async with contextlib.AsyncExitStack() as undo:
        digger = await _stage(context, undo)
        for dig in _CREATIVE_CASES:
            await _dig_creative(context, digger, dig)


# Placing: a stone block floats at `_TARGET`, and the digger places onto one of its faces.

_TARGET: _Cell = (8, -59, 7)
_CLEAR = (
    "fill 6 -56 5 10 -57 9 minecraft:air",
    "fill 6 -58 5 10 -58 9 minecraft:air",
    "fill 6 -60 5 10 -59 9 minecraft:air",
)
"""Empties the cells a case can set (the target, and what is placed against any face of it, a
bed or a door included), the top layers first: a torch or a door that loses its support drops an
item, which then appears in a later case's window."""

_CURSOR_MIDDLE = (0.5, 0.5, 0.5)
_NEIGHBOUR = {
    Face.DOWN: (0, -1, 0),
    Face.UP: (0, 1, 0),
    Face.NORTH: (0, 0, -1),
    Face.SOUTH: (0, 0, 1),
    Face.WEST: (-1, 0, 0),
    Face.EAST: (1, 0, 0),
}


@dataclass(frozen=True, slots=True)
class _Place:
    """One window: what the digger holds, and which face of which block it places onto.

    `setup` is what Control sets besides the target, which is stone; `yaw` is the way the
    digger faces (0 south, 90 west, 180 north, 270 east).
    """

    item: str
    face: Face = Face.UP
    cursor: tuple[float, float, float] = _CURSOR_MIDDLE
    yaw: float = 0.0
    setup: tuple[str, ...] = ()
    on: _Cell = _TARGET
    count: int = 64


async def _clear(context: GroupContext) -> None:
    """Empty the cells, then kill the items that dropped: they merge, a tick at a time."""
    for command in _CLEAR:
        await context.control.run(command)
    await context.control.run(_KILL_ITEMS)


def _at(cell: _Cell) -> str:
    return " ".join(str(coordinate) for coordinate in cell)


async def _place(context: GroupContext, digger: Bot, place: _Place) -> None:
    """Play one placement: set the cell up, turn the digger, then place and step a tick."""
    control = context.control
    await _clear(context)
    await control.run(f"setblock {_at(_TARGET)} minecraft:stone")
    for command in place.setup:
        await control.run(command)
    await _give(context, f"{place.item} {place.count}")
    await context.step(1)  # the blocks set reach the Bots before the window opens
    await digger.look(place.yaw, 0.0)
    x, y, z = place.on
    async with context.observe(*PACKETS):
        await digger.place(x, y, z, place.face, place.cursor)
        await context.step(1)


_SIDES = (Face.DOWN, Face.UP, Face.NORTH, Face.SOUTH, Face.WEST, Face.EAST)
_ARMOR_STAND = (
    f"summon minecraft:armor_stand {_TARGET[0] + 0.5} {_TARGET[1] + 1} {_TARGET[2] + 0.5} "
    f'{{NoGravity:1b,Tags:["{_TAG}"]}}'
)
_ABOVE_CELL = (_TARGET[0], _TARGET[1] + 1, _TARGET[2])
_ABOVE = _at(_ABOVE_CELL)
PLACE_CASES = (
    *(_Place("minecraft:oak_stairs", face, (0.5, 0.75, 0.5)) for face in _SIDES),
    *(_Place("minecraft:oak_stairs", Face.UP, yaw=yaw) for yaw in (90.0, 180.0, 270.0)),
    *(_Place("minecraft:oak_log", face) for face in _SIDES),
    _Place("minecraft:oak_slab", Face.UP),
    _Place("minecraft:oak_slab", Face.NORTH, (0.5, 0.75, 0.5)),
    _Place(
        "minecraft:oak_slab",
        Face.UP,
        setup=(f"setblock {_ABOVE} minecraft:oak_slab[type=bottom]",),
        on=_ABOVE_CELL,
    ),
    _Place("minecraft:oak_door", Face.UP, (0.25, 1.0, 0.5)),
    _Place("minecraft:oak_door", Face.UP, (0.75, 1.0, 0.5), yaw=180.0),
    _Place("minecraft:torch", Face.UP),
    *(_Place("minecraft:torch", face) for face in (Face.NORTH, Face.SOUTH, Face.WEST, Face.EAST)),
    *(_Place("minecraft:red_bed", Face.UP, yaw=yaw, count=1) for yaw in (0.0, 90.0, 180.0, 270.0)),
    _Place(
        "minecraft:stone",
        Face.UP,
        setup=(f"setblock {_ABOVE} minecraft:short_grass",),
        on=_ABOVE_CELL,
    ),
    _Place(
        "minecraft:stone",
        Face.UP,
        setup=(f"setblock {_ABOVE} minecraft:snow[layers=1]",),
        on=_ABOVE_CELL,
    ),
    _Place(
        "minecraft:stone",
        Face.UP,
        setup=(_ARMOR_STAND,),
    ),
)


@group("blocks/place", masks=DROP_MASKS, kind=GroupKind.TICK_EXACT)
async def place(context: GroupContext) -> None:
    """The digger places stairs, logs, slabs, a door, torches and beds, and into other blocks."""
    async with contextlib.AsyncExitStack() as undo:
        digger = await _stage(context, undo)
        undo.push_async_callback(context.control.run, f"kill @e[tag={_TAG}]")
        undo.push_async_callback(_clear, context)
        for case in PLACE_CASES:
            await _place(context, digger, case)
