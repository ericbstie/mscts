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
from mscts.compare import Mask
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


async def _give(context: GroupContext, bot: Bot, hunger: _Hunger) -> None:
    """Give the Bot `hunger`, hiding its particles."""
    await context.control.run(
        f"effect give {bot.name} minecraft:hunger {hunger.seconds} {hunger.amplifier} true"
    )


async def _lower(context: GroupContext, bot: Bot, hunger: _Hunger) -> None:
    """Give the Bot `hunger` and wait until it has worn off."""
    await _give(context, bot, hunger)
    await bot.expect(_EFFECT_ENDS, timeout_s=_WAIT_S)


async def _damage(context: GroupContext, bot: Bot, amount: int) -> None:
    """Take `amount` health from the Bot, at no cost in exhaustion (type `generic`)."""
    await context.control.run(f"damage {bot.name} {amount} minecraft:generic")


def _says(field: str, value: float) -> Callable[[Packet], bool]:
    """Whether a `set_health` says `field` (`food`, `health`) is `value`."""

    def holds(packet: Packet) -> bool:
        return (packet.fields or {}).get(field) == value

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
                await bot.expect(_SET_HEALTH, timeout_s=_WAIT_S, where=_says("food", _STOPS_AT))
                await _quiet(bot)


# `player/starvation`: a Bot at food 0 starves down to a floor that depends on the difficulty.

_STARVER = "starver"
_DEATH = "minecraft:player_combat_kill"

_EMPTY = _Hunger(255, 5)
"""Food 0 and saturation 0 from a fresh player: 128 exhaustion, more than the 100 of food 20
and saturation 5. The food reaches 0 about 20 ticks before the effect ends."""


@dataclass(frozen=True, slots=True)
class _Starving:
    """One part of `player/starvation`.

    Attributes:
        difficulty: The difficulty the part is played on.
        health: The Bot's health when its food runs out.
        floor: The health starvation stops at, or None if it kills the Bot.
    """

    difficulty: str
    health: int
    floor: int | None


_STARVINGS = (_Starving("easy", 12, 10), _Starving("normal", 3, 1), _Starving("hard", 2, None))
"""Starvation hurts a player 1 every 80 ticks while its health is over 10 on easy, over 1 on
normal, and always on hard (`FoodData.tick`): two hits each."""


async def _starve(context: GroupContext, bot: Bot, part: _Starving) -> None:
    """Hurt a fresh Bot to `part.health`, take all its food, and wait for its health to settle."""
    await _damage(context, bot, 20 - part.health)
    await _give(context, bot, _EMPTY)
    if part.floor is None:
        await bot.expect(_DEATH, timeout_s=_WAIT_S)
    else:
        await bot.expect(_SET_HEALTH, timeout_s=_WAIT_S, where=_says("health", part.floor))
        await _quiet(bot)


@group("player/starvation", spec=_normal)
async def starvation(context: GroupContext) -> None:
    """A Bot with no food starves on easy, normal and hard, from just above each floor.

    On easy it stops at 10 health, on normal at 1, and on hard it dies. Natural regeneration
    is off, so nothing heals it between hits. Each window holds the damage, the food running
    out, every hit, and on easy and normal 100 ticks with nothing more.
    """
    control = context.control
    async with contextlib.AsyncExitStack() as undo:
        await pin_joins(control, undo)
        undo.push_async_callback(control.run, "gamerule natural_health_regeneration true")
        await control.run("gamerule natural_health_regeneration false")
        undo.push_async_callback(control.run, "difficulty normal")
        bot = await join_at_spawn(context, undo, _STARVER)
        await context.freeze()
        for part in _STARVINGS:
            await control.run(f"difficulty {part.difficulty}")
            await fresh(context, bot)
            async with context.observe(*PACKETS):
                await _starve(context, bot, part)
        await bot.respawn()


# `player/eating`: a hungry Bot eats four foods, one window each.

_EATER = "eater"

_HUNGRY = _Hunger(234, 4)
"""Food 2 and saturation 0 from a fresh player (94 exhaustion: 23 points), so that every food
the Bot eats raises its food."""

_FOODS = (
    "minecraft:bread",
    "minecraft:cooked_beef",
    "minecraft:golden_apple",
    "minecraft:rotten_flesh",
)
"""Bread 5 food and 0.6 saturation a point, cooked beef 8 and 0.8, a golden apple 4 and 1.2 with
its regeneration and absorption, rotten flesh 4 and 0.1 (`Foods`)."""

_EATING_PACKETS = (
    _SET_HEALTH,
    "minecraft:update_mob_effect",
    "minecraft:entity_event",
    "minecraft:sound",
)
"""What an eating window compares: the food, the golden apple's effects, the end of eating and
its sounds."""

_FLESH_PACKETS = (_SET_HEALTH, "minecraft:entity_event", "minecraft:sound")
"""What the rotten flesh's window compares: not its effects, since it gives hunger only 4 times
in 5, at random (`Foods.ROTTEN_FLESH`'s consume effect, probability 0.8)."""

EATING_MASKS = (
    Mask(
        "minecraft:sound",
        "pitch",
        "Vanilla draws it at random for the sounds of eating (26.3 javap): "
        "`FoodProperties.onConsume` plays the food's eat sound with pitch "
        "random.triangle(1.0, 0.4) and PLAYER_BURP with pitch randomBetween(0.9, 1.0). Which "
        "sound plays, and at what volume, is still compared.",
    ),
)
"""The Mask on the eating sounds' pitch."""


@group("player/eating", spec=_normal, masks=EATING_MASKS)
async def eating(context: GroupContext) -> None:
    """A Bot at food 2 eats bread, cooked beef, a golden apple and rotten flesh, in turn.

    The Bot has full health, so nothing heals it. Each window opens before the Bot starts to
    eat and ends on the `set_health` that eating sends.
    """
    control = context.control
    async with contextlib.AsyncExitStack() as undo:
        await pin_joins(control, undo)
        bot = await join_at_spawn(context, undo, _EATER)
        await context.freeze()
        await control.run(f"clear {bot.name}")
        await fresh(context, bot)
        await _lower(context, bot, _HUNGRY)
        for food in _FOODS:
            await control.run(f"give {bot.name} {food}")
        for slot, food in enumerate(_FOODS):
            await bot.hold(slot)
            names = _FLESH_PACKETS if food == "minecraft:rotten_flesh" else _EATING_PACKETS
            async with context.observe(*names, until=_SET_HEALTH, bot=bot):
                await bot.use_item()
                await bot.expect(_SET_HEALTH, timeout_s=_WAIT_S)
