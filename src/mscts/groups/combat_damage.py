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
from collections.abc import AsyncIterator
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
"""Where the marker stands: 3 blocks from the spawn, so that the push is not toward a random side
(a hit from the same place pushes along a vector of length 0)."""


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
"""The kinds of damage the Groups compare, in order: those armor reduces, those it does not
(`bypasses_armor`: magic, wither, out_of_world, starve), and those an attacker deals."""


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


async def _hurt(context: GroupContext, bot: Bot, source: Source) -> None:
    """Make the Bot fresh, then hurt it with `source` in a window of its own."""
    await fresh(context, bot)
    async with context.observe(*PACKETS):
        await context.control.run(damage_command(bot.name, source))


@group("combat/damage-types", kind=GroupKind.TICK_EXACT, spec=_normal)
async def damage_types(context: GroupContext) -> None:
    """A Bot with no armor is hurt by 4 points of each kind of damage."""
    async with _arena(context) as undo:
        bot = await join_at_spawn(context, undo, VICTIM)
        await context.freeze()
        for source in SOURCES:
            await _hurt(context, bot, source)
