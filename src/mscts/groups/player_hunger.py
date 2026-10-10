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
import math
from collections.abc import Callable
from dataclasses import dataclass, replace

from mscts.bot import Bot
from mscts.codec.packets import Packet
from mscts.compare import Mask
from mscts.group import GroupContext, group
from mscts.groups._world import (
    find_when_tracked,
    fresh,
    join_at_spawn,
    normal,
    pin_joins,
    remove_tagged,
)
from mscts.spec import ServerSpec

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


@group("player/regeneration", spec=normal)
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


@group("player/starvation", spec=normal)
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


@group("player/eating", spec=normal, masks=EATING_MASKS)
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


# `player/exhaustion`: a Bot sprints and attacks, and reads back what each cost.

EXERCISER = "exerciser"
"""The Bot that sprints and attacks, and as an operator reads its own food back."""

_LANE_Z = -20.5
_START_X = -49.5
_RUN = 100
"""How many blocks the Bot sprints, one a move."""

_HUSKS = 20
_RING = 1.5
"""How far from the Bot the husks stand, in a ring: within reach, each in a place of its own."""

_TAG = "mscts_hunger"
_HUSK = "minecraft:husk"

_GONE_SYNCS = 60
"""How many barriers the Bot waits for the husks to go: each is at least a tick, and a corpse
goes 20 ticks after its death."""

_FOOD_PATHS = ("foodLevel", "foodSaturationLevel", "foodExhaustionLevel")
"""What the Bot reads back after each part: its food, saturation and exhaustion (`FoodData`)."""

_SYSTEM_CHAT = "minecraft:system_chat"


def _operator(spec: ServerSpec) -> ServerSpec:
    """Normal difficulty, with the exerciser an operator, so that it can run `/data get`."""
    return replace(normal(spec), operators=(*spec.operators, EXERCISER))


async def _read_back(context: GroupContext, bot: Bot) -> None:
    """Have the Bot read its food, saturation and exhaustion back, in a window of its own."""
    await bot.drain()
    async with context.observe(_SYSTEM_CHAT, _SET_HEALTH):
        for path in _FOOD_PATHS:
            await bot.command(f"data get entity {bot.name} {path}")
            await bot.expect(_SYSTEM_CHAT, timeout_s=_WAIT_S)


async def _sprint(bot: Bot) -> None:
    """Sprint `_RUN` blocks east, one block a move, each move followed by a barrier."""
    await bot.sprint(True)  # noqa: FBT003
    for step in range(1, _RUN + 1):
        await bot.move(_START_X + step, -60.0, _LANE_Z)
        await bot.sync()
    await bot.sprint(False)  # noqa: FBT003


def _ring(x: float) -> list[tuple[float, float]]:
    """Where the husks stand: `_HUSKS` places on a circle of radius `_RING` around (x, _LANE_Z)."""
    return [
        (
            round(x + _RING * math.cos(math.tau * k / _HUSKS), 2),
            round(_LANE_Z + _RING * math.sin(math.tau * k / _HUSKS), 2),
        )
        for k in range(_HUSKS)
    ]


async def _attack_each(context: GroupContext, bot: Bot, ring: list[tuple[float, float]]) -> None:
    """Summon a still, silent husk at each place in `ring`, then hit each once."""
    for x, z in ring:
        await context.control.run(
            f"summon minecraft:husk {x} -60 {z} "
            f'{{NoAI:1b,Silent:1b,PersistenceRequired:1b,Tags:["{_TAG}"]}}'
        )
    husks = [await find_when_tracked(bot, "husk", (x, -60.0, z)) for x, z in ring]
    async with context.observe(_SET_HEALTH):
        for husk in husks:
            await bot.attack(husk)
            await bot.sync()


async def _remove_husks(context: GroupContext, bot: Bot) -> None:
    """Kill the husks, and wait until the Bot, still beside them, is told the last is gone.

    The Bot stays, so that the husks' chunk stays loaded: once it unloads, `kill @e` no longer
    finds them, and the next play meets them in the ring (measured: 4 Self-check plays of 5
    failed so, when the Bot left first). A killed husk stays as a corpse for 20 ticks.

    Raises:
        TimeoutError: The Bot still tracked a husk after `_GONE_SYNCS` barriers.
    """
    await remove_tagged(context.control, _TAG)
    for _ in range(_GONE_SYNCS):
        if not any(bot.entities[i].type == _HUSK for i in bot.entities):
            return
        await bot.sync()
    msg = f"the Bot still tracked a husk after {_GONE_SYNCS} barriers"
    raise TimeoutError(msg)


@group("player/exhaustion", spec=_operator)
async def exhaustion(context: GroupContext) -> None:
    """A Bot sprints 100 blocks and hits 20 husks, reading its food back after each.

    The Bot keeps its full health, so it never heals, and the only exhaustion is what it does.
    Each move and hit is followed by a barrier, so the Bot's player ticks between two of them, as
    it does for a vanilla client, and its exhaustion adds up the same way on every server. It
    does not jump: in 1 Self-check play of 15 the two servers counted a different number of
    jumps (#57; follow-up #354).

    The windows compare only `set_health`, which on vanilla neither the sprint nor the hits
    send, so the readback carries the comparison. They leave out `sound` and `entity_event`:
    the attack sound and what a hit does follow the attack charge, which grows in real time.
    """
    control = context.control
    async with contextlib.AsyncExitStack() as undo:
        await pin_joins(control, undo)
        bot = await join_at_spawn(context, undo, EXERCISER)
        undo.push_async_callback(_remove_husks, context, bot)
        await context.freeze()
        await fresh(context, bot)
        await control.run(f"tp {bot.name} {_START_X} -60 {_LANE_Z} -90 0")
        async with context.observe(_SET_HEALTH):
            await _sprint(bot)
        await _read_back(context, bot)
        await _attack_each(context, bot, _ring(_START_X + _RUN))
        await _read_back(context, bot)
