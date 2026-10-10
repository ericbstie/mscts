"""Entity Groups: what a client is told when an entity appears, changes and dies.

A Bot called `watcher` stands at the spawn and Control, far away, summons, changes and kills
entities a few blocks from it, each in a window of its own. The windows compare what the watcher
is told about each entity: its spawn (`add_entity`, in a bundle), its data (`set_entity_data`),
its attributes, its equipment and head, its damage and death events, and its removal.

The world is frozen (`tick freeze`), so nothing moves or ticks unless a Group steps it. Every
entity is summoned with NBT, which makes vanilla skip `Mob.finalizeSpawn`, where a summoned mob
gets its random equipment, baby chance and attribute bonuses (`SummonCommand.createEntity`, 26.3
javap). Mobs cannot think (`NoAI`), and other entities do not fall (`NoGravity`). Every entity is
tagged, so the Group removes only its own when it ends. (Mobs do not spawn on their own: the
Fixture world has `spawn_mobs` off, ADR-0013.)

Vanilla resends the data of every entity a tick changed at the end of that tick, in an order that
follows their entity ids, which differ between Instances (#320). So each window changes one entity.
"""

import contextlib
from collections.abc import AsyncIterator
from dataclasses import dataclass

from mscts.group import GroupContext, group
from mscts.groups._world import CONTROL_AT, normal, pin_joins, remove_tagged
from mscts.spec import CONTROL_PLAYER

WATCHER = "watcher"
"""The Bot that is told about the entities."""

PACKETS = (
    "minecraft:bundle_delimiter",
    "minecraft:add_entity",
    "minecraft:set_entity_data",
    "minecraft:update_attributes",
    "minecraft:set_equipment",
    "minecraft:rotate_head",
    "minecraft:entity_event",
    "minecraft:damage_event",
    "minecraft:hurt_animation",
    "minecraft:remove_entities",
)
"""The packets a window compares: what an entity looks like, how it is hurt, and its removal."""

_TAG = "mscts_entities"
"""What every entity a Group summons is tagged with, so that it removes only those."""

_MOB = "NoAI:1b,PersistenceRequired:1b"
_STILL = "NoGravity:1b"
_FACING = "Rotation:[90f,0f]"
"""Every entity faces west (yaw 90) and looks straight ahead."""

type _Position = tuple[float, float, float]


def summon_command(entity: str, at: _Position, nbt: str) -> str:
    """The command that summons `entity` (without `minecraft:`) at `at`, with `nbt` and the tag.

    `nbt` is the inside of a compound, without its braces. The entity faces west.
    """
    x, y, z = at
    return f'summon minecraft:{entity} {x} {y} {z} {{{nbt},{_FACING},Tags:["{_TAG}"]}}'


@contextlib.asynccontextmanager
async def _arena(context: GroupContext) -> AsyncIterator[contextlib.AsyncExitStack]:
    """Pin the join, take Control away, freeze the world and join the watcher; undo it all.

    Yields the stack of undos, for what the body sets: they run first, then these. The tagged
    entities go first, and `remove_tagged` waits for their bodies to go, in a running world.
    """
    control = context.control
    async with contextlib.AsyncExitStack() as undo:
        await pin_joins(control, undo)
        await control.run(f"tp {CONTROL_PLAYER} {CONTROL_AT}")
        await context.freeze()
        undo.push_async_callback(remove_tagged, control, _TAG)
        watcher = await context.bot(WATCHER)
        await watcher.join()
        yield undo


# `entities/summon`: one entity of each kind, in a row south of the spawn.


@dataclass(frozen=True, slots=True)
class Summon:
    """One entity to summon: its type without `minecraft:`, and its NBT.

    Attributes:
        entity: The entity type, as `/summon` takes it.
        nbt: The inside of the NBT compound, without braces.
    """

    entity: str
    nbt: str


SUMMONS = (
    Summon("pig", _MOB),
    Summon("cow", _MOB),
    Summon("sheep", f"{_MOB},Color:3b"),
    Summon("chicken", _MOB),
    Summon("zombie", _MOB),
    Summon("skeleton", f'{_MOB},equipment:{{mainhand:{{id:"minecraft:bow",count:1}}}}'),
    Summon("creeper", _MOB),
    Summon(
        "villager",
        f'{_MOB},VillagerData:{{type:"minecraft:plains",profession:"minecraft:farmer",level:1}}',
    ),
    Summon("armor_stand", _STILL),
    Summon("item_frame", 'Facing:1b,Item:{id:"minecraft:diamond",count:1}'),
    Summon("oak_boat", _STILL),
    Summon("minecart", _STILL),
    Summon("arrow", _STILL),
    Summon("snowball", _STILL),
    Summon("experience_orb", f"{_STILL},Value:5s"),
    Summon("falling_block", f'{_STILL},BlockState:{{Name:"minecraft:sand"}}'),
    Summon("tnt", f"{_STILL},fuse:40s"),
)
"""The issue's list, in its order. The sheep is light blue (colour 3), the skeleton holds a bow,
the villager is a plains farmer, the item frame lies on the ground holding a diamond, the orb is
worth 5 points, the falling block is sand, and the TNT has 40 ticks left of its fuse."""


def row_position(number: int) -> _Position:
    """Where the `number`th entity of `entities/summon` stands: 2 blocks apart, x -16.5 to 15.5."""
    return (-16.5 + 2 * number, -60.0, -6.5)


@group("entities/summon", spec=normal)
async def summon(context: GroupContext) -> None:
    """Control summons one entity of each kind in turn, each in a window of its own."""
    async with _arena(context):
        for number, entity in enumerate(SUMMONS):
            command = summon_command(entity.entity, row_position(number), entity.nbt)
            async with context.observe(*PACKETS):
                await context.control.run(command)


# `entities/data-changes`: one zombie, changed one way at a time.

ZOMBIE_AT: _Position = (-4.5, -60.0, -12.5)

ROOF = "-5 -57 -13"
"""A block above the zombie's head: a zombie the world ticks catches fire in daylight at random
(`Zombie.isSunBurnTick` draws `nextFloat`), unless it cannot see the sky."""

_ZOMBIE = f"@e[tag={_TAG},limit=1]"

CHANGES = (
    f'data merge entity {_ZOMBIE} {{CustomName:"Bob",CustomNameVisible:1b}}',
    f"data merge entity {_ZOMBIE} {{Glowing:1b}}",
    f"data merge entity {_ZOMBIE} {{Silent:1b}}",
    f"data merge entity {_ZOMBIE} {{NoGravity:1b}}",
    f"data merge entity {_ZOMBIE} {{Fire:95s}}",
    f"effect give {_ZOMBIE} minecraft:invisibility 1000 0 true",
    f"attribute {_ZOMBIE} minecraft:movement_speed base set 0.5",
)
"""The changes, in order, each kept in the next. The fire starts at 95 ticks and burns for the
last three steps; a fire hurts only on a multiple of 20 ticks left, so it never hurts the
zombie here."""


@group("entities/data-changes", spec=normal)
async def data_changes(context: GroupContext) -> None:
    """Control changes a zombie one way at a time; each window holds the change and one step.

    An entity shows some changes only when it ticks: it is on fire, or invisible, from its next
    tick on. So each window steps the world once.
    """
    control = context.control
    async with _arena(context) as undo:
        undo.push_async_callback(control.run, f"setblock {ROOF} minecraft:air")
        await control.run(f"setblock {ROOF} minecraft:stone")
        await control.run(summon_command("zombie", ZOMBIE_AT, _MOB))
        for change in CHANGES:
            async with context.observe(*PACKETS):
                await control.run(change)
                await context.step()
