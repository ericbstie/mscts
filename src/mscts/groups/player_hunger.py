"""Player Groups: hunger, and the health it gives back and takes away.

A player's food, saturation and exhaustion change on its own tick: `ServerPlayer.doTick` runs
`FoodData.tick` once a server tick, and a player is not frozen by `tick freeze` (26.3 javap:
the connection's tick runs it, whatever the world does). So regeneration, starvation and the
end of eating take real time. Each window waits for the `set_health` that ends what it tests,
then for at least 100 more server ticks in which nothing else may come (`_quiet`), and ends on
the barrier. The values are compared in their order, never by the tick they come on.

Vanilla sends `set_health` (health, food, saturation) only when the health or the food changed,
or the saturation reached 0 or left it (`ServerPlayer.doTick`).

Every part starts from a fresh player: a respawn gives health 20, food 20, saturation 5 and no
exhaustion (`ServerPlayer.restoreFrom` keeps the food only when the player keeps everything).
No command sets the food, so a Group lowers it with the hunger effect, which adds
0.005 * (amplifier + 1) exhaustion a tick (`HungerMobEffect`). Each 4 exhaustion past 4 takes
one point of saturation, or of food when the saturation is 0 (`FoodData.tick`). The effect lasts
an exact number of ticks, so the total is exact, and each total here lies between two multiples
of 4, where the order of the effect's ticks and the food's makes no difference. The health is
set with `/damage` of type `generic`, which costs no exhaustion. Every rule the Group sets is put
back afterwards, because every Group is played on the same two Instances.
"""

import contextlib
from collections.abc import Callable
from dataclasses import dataclass

from mscts.bot import Bot
from mscts.codec.packets import Packet
from mscts.group import GroupContext, group
from mscts.groups._world import _normal, fresh, join_at_spawn, pin_joins

PACKETS = (
    "minecraft:set_health",
    "minecraft:update_mob_effect",
    "minecraft:remove_mob_effect",
    "minecraft:entity_event",
    "minecraft:damage_event",
    "minecraft:sound",
    "minecraft:player_combat_kill",
)
"""The packets a window compares: the health, food and saturation, the effects given and
taken, the eating and the damage, the sounds the player hears, and a death."""

_SET_HEALTH = "minecraft:set_health"
_EFFECT_ENDS = "minecraft:remove_mob_effect"
_TIME = "minecraft:set_time"

_WAIT_S = 60.0
"""How long a Bot waits for what a Group waits for: the longest, regeneration from food 20 to
17, takes 252 ticks, 12.6 s at 20 ticks a second."""

_QUIET_TIMES = 6
"""How many `set_time` packets a window waits for after the last change: vanilla sends one every
20 server ticks, frozen or not (`MinecraftServer.tickChildren`), so 6 span at least 100 ticks,
more than the 80 between two heals or two hits of starvation."""


@dataclass(frozen=True, slots=True)
class _Hunger:
    """The hunger effect a Group gives a fresh player to lower its food.

    Attributes:
        amplifier: The effect's amplifier: 0.005 * (amplifier + 1) exhaustion a tick.
        seconds: How long it lasts, 20 ticks a second.
    """

    amplifier: int
    seconds: int


async def _quiet(bot: Bot) -> None:
    """Wait until at least 100 server ticks have passed (`_QUIET_TIMES`)."""
    for _ in range(_QUIET_TIMES):
        await bot.expect(_TIME, timeout_s=_WAIT_S)


async def _lower(context: GroupContext, bot: Bot, hunger: _Hunger) -> None:
    """Give the Bot `hunger`, hiding its particles, and wait until it has worn off."""
    await context.control.run(
        f"effect give {bot.name} minecraft:hunger {hunger.seconds} {hunger.amplifier} true"
    )
    await bot.expect(_EFFECT_ENDS, timeout_s=_WAIT_S)


async def _damage(context: GroupContext, bot: Bot, amount: int) -> None:
    """Take `amount` health from the Bot, at no cost in exhaustion (type `generic`)."""
    await context.control.run(f"damage {bot.name} {amount} minecraft:generic")


def _food_is(food: int) -> Callable[[Packet], bool]:
    """Whether a `set_health` says the food is `food`."""

    def holds(packet: Packet) -> bool:
        return (packet.fields or {}).get("food") == food

    return holds


# `player/regeneration`: a Bot at 10 health heals while its food is 18 or more.

_REGENERATOR = "regenerator"

_STARTS = (None, _Hunger(74, 4), _Hunger(84, 4))
"""Food 20 and saturation 5 (a fresh player); food 18 and saturation 0 (30 exhaustion: 7
points); food 17 and saturation 0 (34 exhaustion: 8 points)."""

_STOPS_AT = 17
"""The food at which regeneration stops: it needs 18 (`FoodData.tick`)."""


@group("player/regeneration", spec=_normal)
async def regeneration(context: GroupContext) -> None:
    """A Bot at 10 health heals from food 20 and saturation 5, from food 18, and from food 17.

    Each heal costs exhaustion, so the food falls; at 17 the healing stops. Each window holds the
    damage and every heal until then, and 100 ticks with nothing more.
    """
    control = context.control
    async with contextlib.AsyncExitStack() as undo:
        await pin_joins(control, undo)
        bot = await join_at_spawn(context, undo, _REGENERATOR)
        await context.freeze()
        for start in _STARTS:
            await fresh(context, bot)
            if start is not None:
                await _lower(context, bot, start)
            async with context.observe(*PACKETS):
                await _damage(context, bot, 10)
                await bot.expect(_SET_HEALTH, timeout_s=_WAIT_S, where=_food_is(_STOPS_AT))
                await _quiet(bot)
