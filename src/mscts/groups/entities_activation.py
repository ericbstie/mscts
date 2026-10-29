"""Entity Groups: entities move on every tick at any distance inside the simulation distance.

The server's simulation distance is 4 chunks and its view distance 10, so a player is told about
entities it does not tick. Vanilla ticks an entity only if its chunk is at most 4 chunks from a
player's chunk, counted the longer way, east-west or north-south: the player's simulation ticket
has level 31 - 4 and spreads one level a chunk to the 8 chunks around, and an entity ticks at
level 31 or less (`ServerLevel.tick`, `DistanceManager.inEntityTickingRange`,
`DistanceManager.getPlayerTicketLevel`, `ChunkTracker`, 26.3 javap). Every player counts, Control
too, so Control stands 6 chunks east and south (`CONTROL_AT`), and everything the Groups summon
lies west of the spawn in chunk z 0, from chunk x -1 to -5.

A Bot called `watcher` joins at the spawn, in chunk (0, 0), and waits until it holds the chunks
from there to chunk x -5 (`_until_held`): a server tells a player about an entity only once it
has sent the entity's chunk. Then the world is frozen (`tick freeze`), and Control summons
inside a window and steps the world a tick at a time, so the window compares, step by step, what
the watcher is told about each entity.

The windows leave out `move_entity_pos` and the rotation packets. Vanilla resends an entity's
position, unchanged, once every 60 calls of `ServerEntity.sendChanges`, and the server calls it
every tick, frozen ones too, so that resend comes on a step that depends on the wall clock
(`FORCED_POS_UPDATE_PERIOD`). The velocity (`set_entity_motion`) and the sync on landing
(`entity_position_sync`) show the movement. Armor stands fall, not pigs: a pig without AI
(`NoAI`) does not fall at all (`LivingEntity.aiStep` moves it only if `Mob.isEffectiveAi`), and a
pig with AI looks around and strolls at random. Pigs fall only where the window compares their
fall damage, which comes on the tick they land.

Every entity is tagged, so that the Group removes only its own. Before it kills them, Control
brings them into the watcher's simulation distance: a mob killed where the world does not tick
it never finishes dying.
"""

import contextlib
from collections.abc import AsyncIterator, Iterable
from dataclasses import replace

from mscts.bot import Bot
from mscts.group import GroupContext, GroupKind, group
from mscts.groups._world import CONTROL_AT, fast_forward, pin_joins, remove_tagged_until_gone
from mscts.spec import CONTROL_PLAYER, ServerSpec

_WATCHER = "watcher"
_TAG = "mscts_activation"

MOVES = (
    "minecraft:bundle_delimiter",
    "minecraft:add_entity",
    "minecraft:set_entity_data",
    "minecraft:set_entity_motion",
    "minecraft:entity_position_sync",
    "minecraft:remove_entities",
)
"""What a window that watches entities move compares: each entity's spawn bundle, its velocity
and the sync when it lands or stops, and its removal."""

HURTS = (
    "minecraft:bundle_delimiter",
    "minecraft:add_entity",
    "minecraft:set_entity_data",
    "minecraft:damage_event",
    "minecraft:entity_event",
    "minecraft:hurt_animation",
)
"""What the fall-damage window compares: each pig's spawn bundle, its damage and its health."""

_STEPS = 20
"""How many ticks each window steps."""

_HELD = frozenset((x, 0) for x in range(-5, 1))
"""The chunks the watcher holds before anything is summoned: the spawn's and five west."""

_CHUNK_SYNCS = 200
"""How many barriers the watcher waits for its chunks: vanilla sent them within 540 ms of the
join, over 200 sides (#45)."""

_GATHER = "0.5 -60 12.5"
"""Where the tagged entities are brought before they are killed: in the watcher's chunk."""

DISTANCES = (8, 24, 40, 56)
"""How far west of the spawn the entities stand, in blocks: in chunk x -1, -2, -3 and -4, all
inside the simulation distance."""

type _Position = tuple[float, float, float]


def activation_spec(spec: ServerSpec) -> ServerSpec:
    """View distance 10 and simulation distance 4: entities 5 to 10 chunks away are not ticked."""
    return replace(spec, view_distance=10, simulation_distance=4)


def _west(distance: float) -> float:
    """The x of the block centre `distance` blocks west of the spawn's (x 0.5)."""
    return 0.5 - distance


def _summon(entity: str, at: _Position, *nbt: str) -> str:
    """The `/summon` of `entity` (without `minecraft:`) at `at`, with `nbt`, facing west, tagged.

    Each of `nbt` is one field of the compound, e.g. `PersistenceRequired:1b`.
    """
    x, y, z = at
    fields = ",".join((*nbt, "Rotation:[90f,0f]", f'Tags:["{_TAG}"]'))
    return f"summon minecraft:{entity} {x} {y} {z} {{{fields}}}"


async def _until_held(bot: Bot, chunks: frozenset[tuple[int, int]]) -> None:
    """Pass barriers until `bot` holds every chunk in `chunks`.

    Raises:
        TimeoutError: It still lacked one after `_CHUNK_SYNCS` barriers; the error names those.
    """
    for _ in range(_CHUNK_SYNCS):
        if chunks <= bot.chunks:
            return
        await bot.sync()
    missing = sorted(chunks - bot.chunks)
    msg = f"{bot.name} still lacked chunks {missing} after {_CHUNK_SYNCS} barriers"
    raise TimeoutError(msg)


async def _clear(context: GroupContext, watcher: Bot) -> None:
    """Kill the tagged entities and what they dropped; return once the watcher is told they went.

    First they come into the watcher's simulation distance (`_GATHER`). A server may drop loot
    from a killed mob whatever the game rule says (Pumpkin does), so the items go too.
    """
    control = context.control
    await control.run(f"tp @e[tag={_TAG}] {_GATHER}")
    await control.run(f"kill @e[tag={_TAG}]")
    await control.run("kill @e[type=minecraft:item]")
    await remove_tagged_until_gone(control, _TAG, watcher)


@contextlib.asynccontextmanager
async def _arena(context: GroupContext) -> AsyncIterator[contextlib.AsyncExitStack]:
    """Pin the join, send Control away, join the watcher and wait for its chunks; undo it all.

    Yields the stack of undos, for what the body sets: they run first, then the tagged
    entities go, then the rules come back.
    """
    control = context.control
    async with contextlib.AsyncExitStack() as undo:
        await pin_joins(control, undo)
        await control.run(f"tp {CONTROL_PLAYER} {CONTROL_AT}")
        watcher = await context.bot(_WATCHER)
        await watcher.join()
        undo.push_async_callback(_clear, context, watcher)
        await _until_held(watcher, _HELD)
        yield undo


async def _watch(context: GroupContext, packets: Iterable[str], summons: Iterable[str]) -> None:
    """In a window narrowed to `packets`, Control runs `summons`, then the world steps `_STEPS`."""
    async with context.observe(*packets):
        for command in summons:
            await context.control.run(command)
        await context.step(_STEPS)


# `entities/activation-falling`

STANDS = tuple(_summon("armor_stand", (_west(d), -58.0, 0.5)) for d in DISTANCES)
"""Armor stands 2 blocks over the ground at each of `DISTANCES`: vanilla lands each on the 8th
tick."""

PIGS = tuple(_summon("pig", (_west(d), -55.0, 2.5), "PersistenceRequired:1b") for d in DISTANCES)
"""Pigs 5 blocks over the ground at each of `DISTANCES`, 2 blocks south of the stands: vanilla
hurts each as it lands, on the 13th tick."""


@group("entities/activation-falling", spec=activation_spec, kind=GroupKind.TICK_EXACT)
async def activation_falling(context: GroupContext) -> None:
    """Armor stands fall 2 blocks at 8, 24, 40 and 56 blocks away; then pigs fall 5 blocks there."""
    async with _arena(context):
        await context.freeze()
        await _watch(context, MOVES, STANDS)
        await _watch(context, HURTS, PIGS)


# `entities/activation-items`

_ICE_ROW = "fill -70 -61 4 -1 -61 4"
"""The ground of the ice row, east-west along z 4, past the farthest item and its slide."""


def _trench(distance: int) -> str:
    """The ground the stream of the item at `distance` runs in: 9 blocks west from under it."""
    return f"fill {-distance - 8} -61 8 {-distance} -61 8"


_FLOW_TICKS = 60
"""How long the water runs before the window: it spreads a block every 5 ticks, 7 blocks from its
source, so it has stopped after 35."""


def _item(item: str, at: _Position, motion_x: float) -> str:
    """The `/summon` of one `item` (without `minecraft:`) at `at`, moving `motion_x` east a tick."""
    stack = f'Item:{{id:"minecraft:{item}",count:1}}'
    return _summon("item", at, stack, f"Motion:[{motion_x}d,0.0d,0.0d]")


ITEMS = (
    *(
        _item(item, (_west(d), -60.0, 4.5), -0.4)
        for d, item in zip(DISTANCES, ("stone", "dirt", "cobblestone", "oak_planks"), strict=True)
    ),
    *(
        _item(item, (_west(d), -61.0, 8.5), 0.0)
        for d, item in zip(DISTANCES, ("sand", "gravel", "glass", "bricks"), strict=True)
    ),
)
"""An item sliding west on the ice at each of `DISTANCES`, then an item lying still at the east
end of each stream. Vanilla sends the velocity of an item in water every tick, since the water
pushes it (`ItemEntity.tick` sets `needsSync`), and that of an item on ice every 20 calls of
`ServerEntity.sendChanges`."""


async def _build(context: GroupContext, undo: contextlib.AsyncExitStack) -> None:
    """Lay the ice row and dig a stream for each distance; push the undo of each onto `undo`."""
    control = context.control
    await control.run(f"{_ICE_ROW} minecraft:ice")
    undo.push_async_callback(control.run, f"{_ICE_ROW} minecraft:grass_block")
    for distance in DISTANCES:
        await control.run(f"{_trench(distance)} minecraft:air")
        undo.push_async_callback(control.run, f"{_trench(distance)} minecraft:grass_block")
        await control.run(f"setblock {-distance} -61 8 minecraft:water")


@group("entities/activation-items", spec=activation_spec, kind=GroupKind.TICK_EXACT)
async def activation_items(context: GroupContext) -> None:
    """Items slide west on ice and are carried by water at 8, 24, 40 and 56 blocks away.

    The world is frozen before the water has run, and steps on until it has, so that every
    stream is the same when the items come.
    """
    async with _arena(context) as undo:
        await _build(context, undo)
        await context.freeze()
        await fast_forward(context.control, _FLOW_TICKS)
        await _watch(context, MOVES, ITEMS)


# `entities/activation-edge`

EDGE = (
    _summon("armor_stand", (-63.5, -58.0, 4.5)),
    _summon("armor_stand", (-64.5, -58.0, 6.5)),
)
"""An armor stand 2 blocks up in chunk x -4, the last chunk inside the simulation distance, and
one a block further west, in chunk x -5, the first outside it. Vanilla lands the first on the 8th
tick and tells the watcher nothing more of the second after its spawn: it does not tick it, and
sends its changes only in ticking range, unless it must (`ChunkMap.tick`)."""


@group("entities/activation-edge", spec=activation_spec, kind=GroupKind.TICK_EXACT)
async def activation_edge(context: GroupContext) -> None:
    """An armor stand falls just inside the simulation distance; one just outside stays up."""
    async with _arena(context):
        await context.freeze()
        await _watch(context, MOVES, EDGE)
