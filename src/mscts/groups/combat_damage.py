"""Combat damage Groups: how much each kind of damage hurts a player, and what it is sent about it.

A Bot called `victim` is hurt by Control's `/damage`, one kind of damage at a time, and the window
compares what the server sends it: the damage (`damage_event`, `hurt_animation`,
`entity_event`), its health (`set_health` and the health in `set_entity_data`), the push the
hit gives it (`set_entity_motion`), the stacks it holds (`container_set_slot`, which shows an
armor piece wearing down), the death (`player_combat_kill`, `system_chat`) and the sounds.

A player is immune for 10 ticks after a hit, and a second hit inside that gap hurts only by the
excess, with no `damage_event` (docs/roles/player-actions.md, #56). The immunity counts the
player's own ticks, which run in real time in a frozen world, so stepping the world does not clear
it. So the Bot is made fresh (`kill`, then `respawn`) before each hit: it has full health and
food and no immunity. A server saves a player's health and place across plays, so a Bot is also put
back at the spawn when the Group ends, and every setting is put back, because every Group is
played on the same two Instances. Natural regeneration is off, so health stays what the hit left
it. (Mobs do not spawn: the Fixture world has `spawn_mobs` off, ADR-0013, and no Group turns it
on.)

The kinds of damage that need an attacker (`player_attack`, `mob_attack`, `arrow`) are given a
marker as the one who hurts: an entity no client is told of, so it adds no packet, and one that
vanishes without a death animation when the Group removes it.
"""

import contextlib
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, replace

from mscts.bot import Bot
from mscts.group import GroupContext, GroupKind, group
from mscts.groups._world import CONTROL_AT, fresh, join_at_spawn, pin_joins
from mscts.spec import CONTROL_PLAYER, Difficulty, ServerSpec

VICTIM = "victim"
"""The Bot that is hurt."""

PACKETS = (
    "minecraft:damage_event",
    "minecraft:hurt_animation",
    "minecraft:entity_event",
    "minecraft:set_entity_data",
    "minecraft:set_entity_motion",
    "minecraft:set_health",
    "minecraft:container_set_slot",
    "minecraft:sound",
    "minecraft:system_chat",
    "minecraft:player_combat_kill",
)
"""The packets a window compares: the hit, what it does to the player, and its death.

`set_equipment` is not among them: a server tells it to the players who see the victim, never to
the victim, and the Bot is alone with Control, who is far away."""

_DAMAGE = 4
"""How much each hit hurts before armor, in half hearts: a fifth of a player's health."""

_DAMAGER_TAG = "mscts_damager"
_DAMAGER = f"@e[type=minecraft:marker,tag={_DAMAGER_TAG},limit=1]"
_DAMAGER_AT = "3.5 -60 0.5"
"""Where the marker stands: 3 blocks from the spawn, so that a hit it deals pushes the Bot along a
fixed line."""


@dataclass(frozen=True, slots=True)
class Source:
    """One kind of damage: the id of its damage type, and whether the marker deals it.

    Attributes:
        type: The damage type without `minecraft:`, as `/damage` takes it.
        by_marker: Whether `/damage` names the marker as the attacker (`by`).
    """

    type: str
    by_marker: bool = False


SOURCES = (
    Source("generic"),
    Source("player_attack", by_marker=True),
    Source("mob_attack", by_marker=True),
    Source("arrow", by_marker=True),
    Source("fall"),
    Source("in_fire"),
    Source("lava"),
    Source("magic"),
    Source("wither"),
    Source("explosion"),
    Source("out_of_world"),
    Source("starve"),
)
"""The kinds of damage the Groups compare, in the issue's order. The damage type tags in the
26.3 server jar put `generic`, `fall`, `magic`, `wither`, `out_of_world` and `starve` in
`bypasses_armor`; armor reduces the other six. Only `out_of_world` is in `bypasses_resistance` and
only `starve` in `bypasses_effects`."""


def _normal(spec: ServerSpec) -> ServerSpec:
    """Play on normal difficulty: peaceful heals the player and stops most damage."""
    return replace(spec, difficulty=Difficulty.NORMAL)


def damage_command(victim: str, source: Source, amount: float = _DAMAGE) -> str:
    """The command that hurts `victim` by `amount` with `source`."""
    command = f"damage {victim} {amount} minecraft:{source.type}"
    return f"{command} by {_DAMAGER}" if source.by_marker else command


@contextlib.asynccontextmanager
async def _arena(context: GroupContext) -> AsyncIterator[contextlib.AsyncExitStack]:
    """Pin the join, stop natural healing, move Control away and put the marker down; undo it all.

    Yields the stack of undos, for what the body sets: they run first, then these. Each undo runs
    even if another fails, and after the body however it ended.
    """
    control = context.control
    async with contextlib.AsyncExitStack() as undo:
        await pin_joins(control, undo)
        undo.push_async_callback(control.run, "gamerule natural_health_regeneration true")
        await control.run("gamerule natural_health_regeneration false")
        await control.run(f"tp {CONTROL_PLAYER} {CONTROL_AT}")
        undo.push_async_callback(control.run, f"kill {_DAMAGER}")
        await control.run(f'summon minecraft:marker {_DAMAGER_AT} {{Tags:["{_DAMAGER_TAG}"]}}')
        yield undo


async def _hurt(
    context: GroupContext,
    bot: Bot,
    source: Source,
    before: Sequence[str] = (),
    amount: float = _DAMAGE,
) -> None:
    """Make the Bot fresh, run the `before` commands, then hurt it with `source` in a window.

    A fresh Bot has lost its effects, so a Group that tests one gives it in `before`.
    """
    await fresh(context, bot)
    for command in before:
        await context.control.run(command)
    async with context.observe(*PACKETS):
        await context.control.run(damage_command(bot.name, source, amount))


async def _sweep(context: GroupContext, bot: Bot, before: Sequence[str] = ()) -> None:
    """Hurt the Bot with each kind of damage in turn, each in a window of its own."""
    for source in SOURCES:
        await _hurt(context, bot, source, before)


@group("combat/damage-types", kind=GroupKind.TICK_EXACT, spec=_normal)
async def damage_types(context: GroupContext) -> None:
    """A Bot with no armor is hurt by 4 points of each kind of damage."""
    async with _arena(context) as undo:
        bot = await join_at_spawn(context, undo, VICTIM)
        await context.freeze()
        await _sweep(context, bot)


# `combat/armor`: the same damage through each set of armor.


@dataclass(frozen=True, slots=True)
class Armor:
    """A set of armor: the material of its four pieces, and the enchantment on each, if any.

    Attributes:
        material: The item prefix: `iron` for `iron_helmet`.
        enchantment: The enchantment on every piece, at level IV, without `minecraft:`.
    """

    material: str
    enchantment: str | None = None


ARMORS = (
    Armor("iron"),
    Armor("diamond"),
    Armor("netherite"),
    Armor("diamond", "protection"),
    Armor("diamond", "fire_protection"),
    Armor("diamond", "blast_protection"),
)
"""The sets, in order: iron, diamond, netherite (which adds toughness), then diamond with
Protection, Fire Protection and Blast Protection."""

_PIECES = (("head", "helmet"), ("chest", "chestplate"), ("legs", "leggings"), ("feet", "boots"))
"""Each piece's equipment slot and its item suffix."""

_ENCHANTMENT_LEVEL = 4


def wear_commands(victim: str, worn: Armor) -> tuple[str, ...]:
    """The commands that put the set `worn` on `victim`, one per piece."""
    components = ""
    if worn.enchantment is not None:
        components = f"[enchantments={{{worn.enchantment}:{_ENCHANTMENT_LEVEL}}}]"
    return tuple(
        f"item replace entity {victim} armor.{slot} with "
        f"minecraft:{worn.material}_{piece}{components}"
        for slot, piece in _PIECES
    )


async def _keep_inventory(context: GroupContext, undo: contextlib.AsyncExitStack) -> None:
    """Keep the Bot's stacks through each death, so that the armor survives the `kill`.

    The Bot's stacks are cleared when the Group ends: the server saves them across plays.
    """
    control = context.control
    undo.push_async_callback(control.run, "gamerule keep_inventory false")
    await control.run("gamerule keep_inventory true")
    undo.push_async_callback(control.run, f"clear {VICTIM}")


@group("combat/armor", kind=GroupKind.TICK_EXACT, spec=_normal)
async def armor(context: GroupContext) -> None:
    """A Bot wears each set of armor in turn and is hurt by 4 points of each kind of damage."""
    async with _arena(context) as undo:
        bot = await join_at_spawn(context, undo, VICTIM)
        await _keep_inventory(context, undo)
        await context.freeze()
        for worn in ARMORS:
            for command in wear_commands(bot.name, worn):
                await context.control.run(command)
            await _sweep(context, bot)


# `combat/effects`: the same damage under Resistance and Absorption.


@dataclass(frozen=True, slots=True)
class Effect:
    """A status effect: its id without `minecraft:`, and its amplifier (0 is level I).

    Attributes:
        name: The effect, as `/effect give` takes it.
        amplifier: One less than the level.
    """

    name: str
    amplifier: int


EFFECTS = (
    Effect("resistance", 0),
    Effect("resistance", 1),
    Effect("resistance", 2),
    Effect("resistance", 3),
    Effect("absorption", 1),
)
"""Resistance I to IV, then Absorption II."""

_EFFECT_SECONDS = 1_000_000
"""How long an effect lasts: the most `/effect give` takes, so that it outlasts the window."""


def effect_command(victim: str, effect: Effect) -> str:
    """The command that gives `victim` the effect, with no particles."""
    return f"effect give {victim} minecraft:{effect.name} {_EFFECT_SECONDS} {effect.amplifier} true"


@group("combat/effects", kind=GroupKind.TICK_EXACT, spec=_normal)
async def effects(context: GroupContext) -> None:
    """A Bot with each effect is hurt by 4 points of each kind of damage, with no armor.

    A kill clears a player's effects, so the effect is given again after each respawn.
    """
    async with _arena(context) as undo:
        bot = await join_at_spawn(context, undo, VICTIM)
        await context.freeze()
        for effect in EFFECTS:
            await _sweep(context, bot, (effect_command(bot.name, effect),))


# `combat/death`: damage above the Bot's health, with the death message on and off.


@dataclass(frozen=True, slots=True)
class Death:
    """One death: what kills the Bot, and whether the server says so in chat.

    Attributes:
        source: The kind of damage.
        message: The value of the game rule `show_death_messages`.
    """

    source: Source
    message: bool


DEATHS = (
    Death(Source("generic"), message=True),
    Death(Source("fall"), message=True),
    Death(Source("magic"), message=True),
    Death(Source("generic"), message=False),
)
"""Three kinds of damage with the death message on, which have three messages, then one with it off.

Kinds that need an attacker are left out: the attacker's name goes in the message, with the UUID
of an entity that differs between servers."""

_LETHAL = 100
"""How much a lethal hit hurts: five times a player's health."""


@group("combat/death", kind=GroupKind.TICK_EXACT, spec=_normal)
async def death(context: GroupContext) -> None:
    """A Bot is hurt by 100 points of damage, and respawns in a window of its own.

    The game rule `immediate_respawn` is false, as in vanilla, so the server sends the death screen
    (`player_combat_kill`) and waits for the Bot to ask to respawn.
    """
    control = context.control
    async with _arena(context) as undo:
        bot = await join_at_spawn(context, undo, VICTIM)
        undo.push_async_callback(control.run, "gamerule show_death_messages true")
        await context.freeze()
        for case in DEATHS:
            await control.run(f"gamerule show_death_messages {str(case.message).lower()}")
            await _hurt(context, bot, case.source, amount=_LETHAL)
            async with context.observe(*PACKETS):
                await bot.respawn()
