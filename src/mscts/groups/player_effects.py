"""Player Groups: potion effects apply, tick and end the same way.

A player's effects tick on the player's own tick, and a frozen world does not freeze a player
(26.3 javap: `TickRateManager.isEntityFrozen` is false for a `Player`, and
`ServerGamePacketListenerImpl.tick` runs `ServerPlayer.doTick` every server tick, which reaches
`LivingEntity.tickEffects`). So an effect on a Bot lasts its time in wall-clock seconds, whatever
`tick step` does (measured on #58: Regeneration for 5 s ended 5.0 s after the give, stepped or not).
Each window therefore gives the effect, waits in its body for the packet that ends it, and closes
at the barrier. It compares what the effect sends and in what order, not the tick each packet
comes on; the rhythm still shows in how many hits come and the health they leave.

Every Group plays on normal difficulty with the world frozen and natural regeneration off, the
Bot at the spawn and Control far away (`quiet_arena`). The effects are cleared when the Group
ends, because a player keeps them across plays.
"""

import contextlib

from mscts.bot import Bot
from mscts.group import GroupContext, GroupKind, group
from mscts.groups._world import (
    find_when_tracked,
    fresh,
    join_at_spawn,
    normal,
    remove_tagged_until_gone,
)
from mscts.groups.combat_damage import Effect, Source, damage_command, effect_command, quiet_arena

PACKETS = (
    "minecraft:update_mob_effect",
    "minecraft:remove_mob_effect",
    "minecraft:update_attributes",
    "minecraft:set_entity_data",
    "minecraft:set_health",
    "minecraft:damage_event",
)
"""The packets a window compares: the effect given and taken, the attributes it changes, the
entity data it sets (particles, flags, health) and the health it gives or takes."""

_REMOVED = "minecraft:remove_mob_effect"
_SET_HEALTH = "minecraft:set_health"
_SET_TIME = "minecraft:set_time"

_END_TIMEOUT_S = 30.0
"""How long a Bot waits for an effect to end: the longest here lasts 5 s."""


async def _effected(context: GroupContext, undo: contextlib.AsyncExitStack, name: str) -> Bot:
    """Join a Bot at the spawn, and have its effects cleared when the Group ends."""
    bot = await join_at_spawn(context, undo, name)
    undo.push_async_callback(context.control.run, f"effect clear {name}")
    return bot


async def _until_it_ends(
    context: GroupContext, bot: Bot, give: str, *, end: str = _REMOVED
) -> None:
    """A window that runs `give` and closes at the barrier after the Bot reads `end`.

    `end` is the packet that ends the effect: its removal. A hidden effect's end changes no
    entity data, so vanilla sends its attributes on the player's next sync interval, 2 ticks
    after the removal: one answer before a closing barrier ends. One more barrier first keeps
    that packet inside the window.
    """
    async with context.observe(*PACKETS) as opened:
        await context.control.run(give)
        await bot.expect(end, timeout_s=_END_TIMEOUT_S, since_ns=opened)
        await bot.sync()


# `player/effect-attributes`: Speed, Slowness, Strength, Haste and Jump Boost, hidden and shown.

_ATTRIBUTE_SECONDS = 1

_ATTRIBUTE_EFFECTS = (
    Effect("speed", 0),
    Effect("speed", 1),
    Effect("slowness", 0),
    Effect("strength", 0),
    Effect("haste", 0),
    Effect("jump_boost", 0),
)
"""Speed I and II, Slowness I, Strength I, Haste I and Jump Boost I: the effects that change an
attribute the client reads (Strength changes none that is sent)."""


@group("player/effect-attributes", spec=normal)
async def effect_attributes(context: GroupContext) -> None:
    """A Bot is given each effect that changes an attribute for 1 s, then waits for it to end.

    Each effect is given twice over, with its particles hidden and shown, a window each.
    """
    async with quiet_arena(context) as undo:
        bot = await _effected(context, undo, "effected")
        await context.freeze()
        for hide in (True, False):
            for effect in _ATTRIBUTE_EFFECTS:
                give = effect_command(bot.name, effect, seconds=_ATTRIBUTE_SECONDS, hide=hide)
                await _until_it_ends(context, bot, give)


# `player/effect-ticking`: Regeneration, Poison and Wither hurt or heal on a rhythm.

_TICKING_SECONDS = 5
"""100 ticks, the length the issue names: Regeneration I heals twice in it, Poison II five times."""

_TICKING_HEALTH = 6.0
"""The health a Bot is hurt to: room to heal 4, and to be hurt 5 by Poison II and Wither I."""

_TICKING_EFFECTS = (
    Effect("regeneration", 0),
    Effect("regeneration", 1),
    Effect("poison", 0),
    Effect("poison", 1),
    Effect("wither", 0),
)
"""Regeneration I and II, Poison I and II and Wither I. Poison hurts only above 1.0 health, so
Poison II's fifth hit leaves 1 and the sixth does not come; the other effects take no more than 4
of the 6."""

_GENERIC = Source("generic")

_IMMUNITY_TIMES = 2
"""How many `set_time` a Bot waits for after a hit: vanilla sends one every 20 ticks, frozen or
not, so the second is at least 20 ticks on, after the hit's 10 ticks of immunity."""


async def _hurt_to(context: GroupContext, bot: Bot, health: float) -> None:
    """Make the Bot fresh, then hurt it to `health` and wait out the hit's immunity.

    A respawned player ignores damage until the server has read its `player_loaded`
    (`ServerPlayer.isInvulnerableTo`, #57), which `wait_until_handled` waits for.
    """
    await fresh(context, bot)
    await bot.wait_until_handled()
    await context.control.run(damage_command(bot.name, _GENERIC, 20.0 - health))
    for _ in range(_IMMUNITY_TIMES):
        await bot.expect(_SET_TIME, timeout_s=_END_TIMEOUT_S)


@group("player/effect-ticking", spec=normal)
async def effect_ticking(context: GroupContext) -> None:
    """A Bot at 6 health is given Regeneration, Poison and Wither for 5 s, one at a time.

    The window holds every heal or hit and the health it leaves, in order. A kill clears a
    player's effects, so each effect starts from a fresh Bot.
    """
    async with quiet_arena(context) as undo:
        bot = await _effected(context, undo, "ticked")
        await context.freeze()
        for effect in _TICKING_EFFECTS:
            await _hurt_to(context, bot, _TICKING_HEALTH)
            give = effect_command(bot.name, effect, seconds=_TICKING_SECONDS, hide=True)
            await _until_it_ends(context, bot, give)


# `player/effect-instant`: Instant Health and Instant Damage on the Bot, and on a zombie.

_INSTANT_TICKS = 1
"""`/effect give` takes an instant effect's number as ticks, not seconds
(`EffectCommands.computeDurationInTicks`), so 1 is the one tick it takes."""

_INSTANT_HEALTH = 10.0
"""The health the Bot is hurt to: Instant Health I and II heal it 4 and 8, Instant Damage I hurts
it 6, and none of them is lethal or ends at full health."""

_BOT_INSTANTS = (
    (Effect("instant_health", 0), True),
    (Effect("instant_health", 1), False),
    (Effect("instant_damage", 0), True),
    (Effect("instant_damage", 0), False),
)
"""Each with its particles hidden or shown: Instant Health I and II, Instant Damage I twice."""

_ZOMBIE_INSTANTS = (
    (Effect("instant_health", 0), True),
    (Effect("instant_damage", 0), True),
    (Effect("instant_damage", 0), False),
)
"""On the undead the two swap: Instant Health hurts the zombie and Instant Damage heals it."""

_ZOMBIE_TAG = "mscts_effected"
_ZOMBIE = f"@e[type=minecraft:zombie,tag={_ZOMBIE_TAG},limit=1]"
_ZOMBIE_AT: tuple[float, float, float] = (3.5, -60, 3.5)
"""Where the zombie stands: 3 blocks from the Bot in x and z, on the grass."""

_SUMMON = (
    "summon minecraft:zombie {x} {y} {z} {{NoAI:1b,PersistenceRequired:1b,Silent:1b,"
    'Rotation:[0f,0f],Tags:["{tag}"],equipment:{{head:{{id:"minecraft:carved_pumpkin",count:1}}}}}}'
)
"""A zombie that stands still, is silent and keeps its place, and does not burn in daylight (a
pumpkin on its head, `Zombie.aiStep`). `NoAI` makes a frozen world freeze it, so its windows are
stepped; a player is never frozen."""

_ZOMBIE_STEPS = 2
"""How many ticks a zombie window steps: the effect's tick and the one after it."""

_ZOMBIE_IMMUNITY_STEPS = 10
"""How many ticks a zombie is immune after a hit, which the stepped world counts."""


async def _instants_on_the_bot(context: GroupContext, bot: Bot) -> None:
    """Hurt the Bot to `_INSTANT_HEALTH` and give it each of `_BOT_INSTANTS`, a window each.

    Pumpkin applies an instant effect inside the command and sends no `remove_mob_effect`, but
    both servers send the health it sets, so each window ends on that.
    """
    for effect, hide in _BOT_INSTANTS:
        await _hurt_to(context, bot, _INSTANT_HEALTH)
        give = effect_command(bot.name, effect, seconds=_INSTANT_TICKS, hide=hide)
        await _until_it_ends(context, bot, give, end=_SET_HEALTH)


async def _instants_on_the_zombie(context: GroupContext) -> None:
    """Give the zombie each of `_ZOMBIE_INSTANTS`, two steps a window.

    The steps between two windows wait out the zombie's immunity to the hit before.
    """
    for number, (effect, hide) in enumerate(_ZOMBIE_INSTANTS):
        if number:
            await context.step(_ZOMBIE_IMMUNITY_STEPS)
        give = effect_command(_ZOMBIE, effect, seconds=_INSTANT_TICKS, hide=hide)
        async with context.observe(*PACKETS):
            await context.control.run(give)
            await context.step(_ZOMBIE_STEPS)


@group("player/effect-instant", kind=GroupKind.TICK_EXACT, spec=normal)
async def effect_instant(context: GroupContext) -> None:
    """A Bot at 10 health and a zombie are given Instant Health and Instant Damage.

    The Bot's windows end at the barrier after the health the effect sets. The zombie is a mob,
    which a frozen world freezes, so its windows step the world two ticks. It is summoned after
    the Bot's last respawn, and the Bot waits to be told of it: after a respawn vanilla was once
    seen never to send the Bot the zombie again.
    """
    control = context.control
    async with quiet_arena(context) as undo:
        bot = await _effected(context, undo, "instant")
        undo.push_async_callback(remove_tagged_until_gone, control, _ZOMBIE_TAG, bot)
        await context.freeze()
        await _instants_on_the_bot(context, bot)
        x, y, z = _ZOMBIE_AT
        await control.run(_SUMMON.format(x=x, y=y, z=z, tag=_ZOMBIE_TAG))
        await find_when_tracked(bot, "minecraft:zombie", _ZOMBIE_AT)
        await _instants_on_the_zombie(context)
