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
from mscts.group import GroupContext, group
from mscts.groups._world import fresh, join_at_spawn, normal
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
_SET_TIME = "minecraft:set_time"

_END_TIMEOUT_S = 30.0
"""How long a Bot waits for an effect to end: the longest here lasts 5 s."""


async def _effected(context: GroupContext, undo: contextlib.AsyncExitStack, name: str) -> Bot:
    """Join a Bot at the spawn, and have its effects cleared when the Group ends."""
    bot = await join_at_spawn(context, undo, name)
    undo.push_async_callback(context.control.run, f"effect clear {name}")
    return bot


async def _until_it_ends(context: GroupContext, bot: Bot, give: str) -> None:
    """A window that runs `give` and closes at the barrier after the Bot reads the effect's end.

    A hidden effect's end changes no entity data, so vanilla sends its attributes on the player's
    next sync interval, 2 ticks after the removal: one answer before a closing barrier ends. One
    more barrier first keeps that packet inside the window.
    """
    async with context.observe(*PACKETS) as opened:
        await context.control.run(give)
        await bot.expect(_REMOVED, timeout_s=_END_TIMEOUT_S, since_ns=opened)
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
