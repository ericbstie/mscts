"""Player Groups: game modes, death and respawn.

`player/game-modes` switches a Bot through every game mode while a second Bot watches.
`player/death` kills a Bot that holds items and experience under each setting of `keep_inventory`
and `immediate_respawn`.
`player/respawn` kills it and has it respawn, at the world spawn and at a spawn point.

The Bots are put back at the spawn, in survival, when the Group ends, and every rule is set back,
because every Group is played on the same two Instances. Control stands far from the Bots: it is a
player too, and it joins where the last Group left it, which may be in their view
(docs/roles/player-actions.md, #300).
A dead Bot's drops are taken away, so that Control and the Bot do not pick them up.
"""

import contextlib
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, replace

from mscts.bot import Bot
from mscts.compare import Mask
from mscts.group import GroupContext, GroupKind, group
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
    "minecraft:add_entity",
    "minecraft:remove_entities",
)
"""The packets a window compares: the abilities, the game mode event, the tab list, and the
entity data, attributes and waypoint the mode changes. Vanilla sends the watcher no entity added
or removed: a spectator stays tracked (`ServerPlayer.broadcastToPlayer`)."""

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


# `player/death` and `player/respawn`

type _Place = tuple[float, float]
"""An x and a z, at y -60."""

_SPAWN: _Place = (0.5, 0.5)

_MORTAL = "mortal"

DEATH_PACKETS = (
    "minecraft:game_event",
    "minecraft:player_combat_kill",
    "minecraft:set_health",
    "minecraft:set_experience",
    "minecraft:container_set_content",
    "minecraft:set_player_inventory",
    "minecraft:container_set_slot",
    "minecraft:add_entity",
    "minecraft:set_entity_data",
    "minecraft:respawn",
)
"""The packets a window compares for a death."""

_DIAMONDS = "give {bot} minecraft:diamond 5"
_ONE_LEVEL = "xp set {bot} 1 levels"
"""A level of experience drops as one orb of 7 points (`Player.getBaseExperienceReward`)."""

_REACH = 20
"""How far from a Bot's death its drops are taken away: they lie within a few blocks of it."""


@dataclass(frozen=True, slots=True)
class _Death:
    """One death: the game rules it happens under, and what the Bot holds when it dies.

    Attributes:
        keep_inventory: The value of the rule.
        immediate_respawn: The value of the rule.
        items: Whether the Bot holds a stack of diamonds.
        level: Whether the Bot has a level of experience.
    """

    keep_inventory: bool
    immediate_respawn: bool
    items: bool
    level: bool


_DEATHS = (
    _Death(keep_inventory=False, immediate_respawn=False, items=True, level=False),
    _Death(keep_inventory=False, immediate_respawn=False, items=False, level=True),
    _Death(keep_inventory=True, immediate_respawn=False, items=True, level=True),
    _Death(keep_inventory=False, immediate_respawn=True, items=True, level=False),
    _Death(keep_inventory=True, immediate_respawn=True, items=True, level=True),
)
"""The deaths. What drops is one entity a death: vanilla resends the entities a tick made in an
order that follows their raw ids, which differ per Instance."""

_ITEM_THROW = (
    "LivingEntity.createItemStackToDrop gives a dropped item the motion "
    "(-sin(a) * f, 0.2, cos(a) * f) with a = nextFloat() * 2 pi and f = nextFloat() * 0.5, and "
    "the ItemEntity constructor sets its yaw to nextFloat() * 360"
)
_ORB_THROW = (
    "the ExperienceOrb constructor sets its yaw to nextFloat() * 360 and its motion to "
    "((nextDouble() * 0.2 - 0.1) * 2, nextDouble() * 0.2 * 2, (nextDouble() * 0.2 - 0.1) * 2)"
)
_DRAWN = {
    "velocity.x": f"{_ITEM_THROW}; {_ORB_THROW}",
    "velocity.y": f"The item's is fixed at 0.2, but {_ORB_THROW}",
    "velocity.z": f"{_ITEM_THROW}; {_ORB_THROW}",
    "yaw": f"{_ITEM_THROW}; {_ORB_THROW}",
}

DROP_MASKS = tuple(
    Mask(
        "minecraft:add_entity",
        path,
        f"Vanilla draws it at random for what a dead player drops: {draw} (26.3 javap). Where "
        "the drop appears is compared (the player's place), and so are its type and count in "
        "`set_entity_data`; how it moves belongs to `entities/motion`.",
    )
    for path, draw in _DRAWN.items()
)
"""How a dropped item and an experience orb move and face, drawn at random by vanilla.

The one `add_entity` a death window compares is the item or the orb the Bot dropped.
"""


async def _rules(context: GroupContext, death: _Death) -> None:
    """Set the two game rules to the values of `death`."""
    rules = (
        ("keep_inventory", death.keep_inventory),
        ("immediate_respawn", death.immediate_respawn),
    )
    for rule, value in rules:
        await context.control.run(f"gamerule {rule} {str(value).lower()}")


async def _kit(context: GroupContext, bot: Bot, death: _Death) -> None:
    """Give the Bot what it holds when it dies, and nothing else."""
    control = context.control
    await control.run(f"clear {bot.name}")
    await control.run(f"xp set {bot.name} 0 levels")
    if death.items:
        await control.run(_DIAMONDS.format(bot=bot.name))
    if death.level:
        await control.run(_ONE_LEVEL.format(bot=bot.name))


async def _clear_drops(context: GroupContext, place: _Place) -> None:
    """Remove the items and orbs within `_REACH` blocks of `place`.

    A dead Bot's drops would stay in the Instance, lie where the Bot respawns and be picked up
    by the next play.
    """
    x, z = place
    where = f"x={x},y=-60,z={z},distance=..{_REACH}"
    await context.control.run(f"kill @e[type=minecraft:item,{where}]")
    await context.control.run(f"kill @e[type=minecraft:experience_orb,{where}]")


@contextlib.asynccontextmanager
async def _dying(bot: Bot) -> AsyncIterator[Callable[[], Awaitable[None]]]:
    """Yield how to respawn the Bot; if the body ends without that, respawn it on exit.

    A dead Bot that a failed Group leaves is saved with no health and logs back in dead, so the
    next Group would fail for a reason that is not its own. When the body failed, an error of
    that respawn is dropped: the body's is the one to see.
    """
    pending = True

    async def respawn() -> None:
        nonlocal pending
        pending = False
        await bot.respawn()

    try:
        yield respawn
    except Exception:
        if pending:
            with contextlib.suppress(Exception):
                await bot.respawn()
        raise
    if pending:
        await bot.respawn()


@contextlib.asynccontextmanager
async def _mortal(context: GroupContext) -> AsyncIterator[contextlib.AsyncExitStack]:
    """Move Control away and freeze the world; undo the rules and the drops on exit."""
    async with _arena(context) as undo:
        undo.push_async_callback(_clear_drops, context, _SPAWN)
        for rule in ("keep_inventory", "immediate_respawn"):
            undo.push_async_callback(context.control.run, f"gamerule {rule} false")
        await context.freeze()
        yield undo


@group("player/death", kind=GroupKind.TICK_EXACT, spec=_normal, masks=DROP_MASKS)
async def death(context: GroupContext) -> None:
    """A Bot is killed holding items or experience, under each setting of two game rules."""
    async with _mortal(context) as undo:
        bot = await _join(context, undo, _MORTAL)
        for case in _DEATHS:
            await _kit(context, bot, case)
            async with _dying(bot) as respawn:
                async with context.observe(*DEATH_PACKETS):
                    await _rules(context, case)
                    await context.control.run(f"kill {bot.name}")
                await _clear_drops(context, _SPAWN)
                await respawn()


RESPAWN_PACKETS = (
    "minecraft:respawn",
    "minecraft:set_health",
    "minecraft:set_experience",
    "minecraft:container_set_content",
    "minecraft:set_player_inventory",
    "minecraft:container_set_slot",
    "minecraft:set_default_spawn_position",
    "minecraft:player_position",
    "minecraft:player_abilities",
    "minecraft:game_event",
    "minecraft:update_attributes",
    "minecraft:set_entity_data",
    "minecraft:change_difficulty",
    "minecraft:initialize_border",
)

_POINTER = "pointer"
_FAR: _Place = (-95.5, 95.5)
_POINTER_AT = "-95.5 -60 95.5"
_SPAWNPOINT = f"spawnpoint {_POINTER} -88 -60 88"
"""Where the second Bot stands, and where it respawns. A server keeps a player's spawn point for
good and a command cannot clear it, so only a Bot of its own has one: `_MORTAL` respawns at the
world spawn every play. The Bots are 6 chunks apart or more, because the view distance is 2: a
player who respawns is sent to the others in view a tick or two later, which no window can place."""


async def _die_and_respawn(context: GroupContext, bot: Bot, death: _Death, place: _Place) -> None:
    """Kill the Bot at `place` holding its kit, and take its drops away; respawn it in a window."""
    await _rules(context, death)
    await _kit(context, bot, death)
    async with _dying(bot) as respawn:
        await context.control.run(f"kill {bot.name}")
        await _clear_drops(context, place)
        async with context.observe(*RESPAWN_PACKETS):
            await respawn()


@group("player/respawn", kind=GroupKind.TICK_EXACT, spec=_normal)
async def respawn(context: GroupContext) -> None:
    """A Bot is killed and respawns at the world spawn, with and without `keep_inventory`.

    Then a second Bot with a spawn point is killed and respawns there.
    """
    both = _Death(keep_inventory=False, immediate_respawn=False, items=True, level=True)
    async with _mortal(context) as undo:
        mortal = await _join(context, undo, _MORTAL)
        pointer = await _join(context, undo, _POINTER)
        undo.push_async_callback(_clear_drops, context, _FAR)
        await context.control.run(f"tp {_POINTER} {_POINTER_AT}")
        await context.control.run(_SPAWNPOINT)
        await _die_and_respawn(context, mortal, both, _SPAWN)
        await _die_and_respawn(context, mortal, replace(both, keep_inventory=True), _SPAWN)
        await _die_and_respawn(context, pointer, both, _FAR)
