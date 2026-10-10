"""Combat Groups: what a hit does to the player or mob it lands on.

A Bot called `fighter` hits a husk that cannot think (`NoAI`) with the item in its hand, and the
window compares what the server sends about the hit: the damage (`damage_event`, the husk's
health in `set_entity_data`), the knockback (`set_entity_motion`), the sounds and the
particles. The husk's position packets are left out: vanilla resends a still husk's position
about every 3 s of wall time, which lands in a window one play in four.

What the window leaves out is read back in a window of its own: the fighter is an operator and
copies each husk's `Health`, `Motion` and `Pos` to storage and reads them back, and the
answers are compared. The frozen husk keeps all three until the world steps, so they are exact.

A husk stands in for the zombie: it has the same health, speed and knockback but does not
burn in daylight. A zombie burns when it ticks in the sun, drawn at random each tick
(`Monster.isSunBurnTick`), and a stepped world ticks it. The husk is silent (`Silent:1b`): its
hurt sound has a random pitch (`LivingEntity.getVoicePitch`), and the sounds the Player makes
when it hits have a fixed one (`Player.playServerSideSound` passes pitch 1), so the windows
compare every pitch they hold.

The world is frozen (`tick freeze`), so the husk stands where it is put and the fight moves
only when a Group steps it. A player is never frozen (`TickRateManager.isEntityFrozen`), so
the fighter's attack charge counts every server tick, stepped or not. A hit is therefore
always at full charge, never at part of it: the Groups wait out the charge with steps first.
"""

import contextlib
import dataclasses
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass

from mscts.bot import Bot
from mscts.compare import Mask
from mscts.entities import Entity
from mscts.group import Control, GroupContext, GroupKind, group
from mscts.groups._world import find_when_tracked, normal, pin_joins, remove_tagged
from mscts.spec import CONTROL_PLAYER, ServerSpec

FIGHTER = "fighter"
"""The Bot that hits."""

PACKETS = (
    "minecraft:damage_event",
    "minecraft:hurt_animation",
    "minecraft:entity_event",
    "minecraft:set_entity_motion",
    "minecraft:set_entity_data",
    "minecraft:sound",
    "minecraft:animate",
    "minecraft:level_particles",
)
"""The packets a window compares: the hit, the husk's reaction, and the swing."""

PITCH_MASK = Mask(
    "minecraft:sound",
    "pitch",
    "Vanilla draws a hurt Player's voice pitch at random: LivingEntity.getVoicePitch is "
    "(nextFloat - nextFloat) * 0.2 + 1 (26.3 javap). The sound itself is still compared. "
    "The pitch of the attack sounds, which is fixed, is left out with it: only combat/pvp "
    "has a Player's voice in its window, and the other Groups compare those pitches.",
)

_TAG = "mscts_combat"
"""What every husk a Group summons is tagged with, so that it removes only those."""

_CHARGE_STEPS = 15
"""How many steps a Bot waits so that its attack charge is full: each is at least 2 server ticks
(a step and the barrier after it), and the slowest weapon here, an axe, needs 20 (26.3 javap).
15 steps are at least 30, so a barrier that ends a pass early still leaves a margin."""

_CONTROL_AT = "5.5 -60 44.5"
_HUSKS_AT = "5.5 -60 24.5"
"""Where `combat/immunity` sends a husk it is done with: 20 blocks from Control."""

_FEEDBACK_TIMEOUT_S = 10.0
"""How long the fighter waits for the answer to a `data get`."""

_SYSTEM_CHAT = "minecraft:system_chat"

_FIGHTER_X = 4.5
_REACH = 1.5
_FACING_EAST = -90.0
"""The yaw of a player facing +x."""

type _Weapon = str | None


def _fighting(spec: ServerSpec) -> ServerSpec:
    """Play on normal difficulty, with the fighter an operator: it reads the husks back."""
    return dataclasses.replace(normal(spec), operators=(*spec.operators, FIGHTER))


@contextlib.asynccontextmanager
async def _arena(context: GroupContext) -> AsyncIterator[None]:
    """Freeze the world, stop natural healing and take Control out of the way; undo it all.

    Control is a player too: it joins where the fighter does, and would hear every sound and
    see every hit (#300), so it goes 40 blocks away. Each undo runs even if another fails.
    The husks go before the world unfreezes.
    """
    control = context.control
    async with contextlib.AsyncExitStack() as undo:
        await pin_joins(control, undo)
        undo.push_async_callback(control.run, "gamerule natural_health_regeneration true")
        await control.run("gamerule natural_health_regeneration false")
        await context.freeze()
        undo.push_async_callback(remove_tagged, control, _TAG)
        await control.run(f"tp {CONTROL_PLAYER} {_CONTROL_AT}")
        yield


def _husk_tag(lane: int, number: int) -> str:
    """The tag of husk `number` in `lane`, for reading it back; the first is the one hit."""
    return f"{_TAG}_{lane}_{number}"


async def _summon(context: GroupContext, x: float, z: float, tag: str = _TAG) -> None:
    await context.control.run(
        f"summon minecraft:husk {x} -60 {z} "
        f'{{NoAI:1b,Silent:1b,OnGround:1b,Health:20f,Tags:["{_TAG}","{tag}"]}}'
    )


def _lane_z(lane: int) -> float:
    """The z of lane `lane`: lanes are 4 blocks apart, so a hit never reaches the next."""
    return 2.5 + 4 * lane


async def _stand(context: GroupContext, lane: int, case: "_Case") -> None:
    """Put the fighter in lane `lane_z` facing +x with its weapon in hand, and a husk in front.

    The husk it hits is summoned first; the case's `around` husks follow, each that far from it.
    Each is tagged for `_husk_tag`.
    """
    control = context.control
    lane_z = _lane_z(lane)
    await _refill(control, FIGHTER)
    await control.run(f"tp {FIGHTER} {_FIGHTER_X} -60 {lane_z} {_FACING_EAST} 0")
    held = case.weapon or "minecraft:air"
    await control.run(f"item replace entity {FIGHTER} hotbar.0 with {held}")
    x = _FIGHTER_X + _REACH
    await _summon(context, x, lane_z, _husk_tag(lane, 0))
    for number, (dx, dz) in enumerate(case.around, start=1):
        await _summon(context, x + dx, lane_z + dz, _husk_tag(lane, number))


_WEAPONS: tuple[_Weapon, ...] = (
    None,
    "minecraft:wooden_sword",
    "minecraft:diamond_sword",
    "minecraft:diamond_axe",
)
"""A bare hand, then a weapon of each kind: damage 1, 4, 7 and 9."""


type _Step = Callable[[Bot], Awaitable[None]]
"""What the fighter does on its own: no entity needed."""

type _Act = Callable[[Bot, Entity], Awaitable[None]]
"""What the fighter does inside a window, to the husk in front of it."""


async def _hit(bot: Bot, target: Entity) -> None:
    await bot.attack(target)


async def _nothing(_: Bot) -> None:
    pass


@dataclass(frozen=True, slots=True)
class _Case:
    """One window: the weapon, what the fighter does before it, in it, and after it.

    `before` runs after the fighter has waited out its charge, `after` once the window has
    closed. `around` puts a husk at each (x, z) offset from the one the fighter hits. `packets`
    is what the case's window compares.
    """

    weapon: _Weapon
    act: _Act = _hit
    before: _Step = _nothing
    after: _Step = _nothing
    around: tuple[tuple[float, float], ...] = ()
    packets: tuple[str, ...] = PACKETS


_STORAGE = "mscts:combat"
"""Where `_read_back` copies a husk's values to: `data get entity` names the husk in its answer,
with a hover event that holds its UUID, and the Instances' UUIDs differ. Storage names nothing."""

_READ = ("Health", "Motion", "Pos")


@contextlib.asynccontextmanager
async def _scratch(control: Control) -> AsyncIterator[None]:
    """Make the storage `_read_back` writes to, and remove it on the way out."""
    await control.run(f"data modify storage {_STORAGE} r set value {{}}")
    try:
        yield
    finally:
        await control.run(f"data remove storage {_STORAGE} r")


async def _ask(fighter: Bot, command: str) -> None:
    await fighter.command(command)
    await fighter.expect(_SYSTEM_CHAT, timeout_s=_FEEDBACK_TIMEOUT_S)


async def _read_back(context: GroupContext, fighter: Bot, tags: list[str]) -> None:
    """Read each husk's health, velocity and position back, in a window of its own.

    The packets of a hit do not tell all of it: the health is in an entity's data, which the
    sprint flag shares (see `SPRINT_PACKETS`), and the position is not compared at all. A
    frozen husk keeps what the hit left until the world steps, so the answers are exact. Per
    husk the fighter copies the three values to storage, then reads them in one answer.
    """
    await fighter.drain()  # what Control said meanwhile reached the operator too
    async with context.observe(_SYSTEM_CHAT):
        for tag in tags:
            for path in _READ:
                copy = f"data modify storage {_STORAGE} r.{tag}.{path} set from entity"
                await _ask(fighter, f"{copy} @e[tag={tag},limit=1] {path}")
            await _ask(fighter, f"data get storage {_STORAGE} r.{tag}")


async def _fight(context: GroupContext, cases: tuple[_Case, ...]) -> None:
    """Play each case in a lane of its own: a window for the hit, then one for the readback.

    The fighter joins, then for each case it is put in its lane with a husk in front, waits for
    a full charge, and hits inside the window, which the world then steps two ticks.
    """
    async with _arena(context), _scratch(context.control):
        fighter = await context.bot(FIGHTER)
        await fighter.join()
        for lane, case in enumerate(cases):
            await _stand(context, lane, case)
            await context.step(_CHARGE_STEPS)
            await case.before(fighter)
            near = (_FIGHTER_X + _REACH, -60.0, _lane_z(lane))
            target = await find_when_tracked(fighter, "husk", near)
            async with context.observe(*case.packets):
                await case.act(fighter, target)
                await context.step(2)
            await case.after(fighter)
            tags = [_husk_tag(lane, number) for number in range(len(case.around) + 1)]
            await _read_back(context, fighter, tags)


@group("combat/melee-mob", spec=_fighting, kind=GroupKind.TICK_EXACT)
async def melee_mob(context: GroupContext) -> None:
    """The fighter hits a husk with a hand, a wooden sword, a diamond sword and an axe."""
    await _fight(context, tuple(_Case(weapon) for weapon in _WEAPONS))


# `combat/critical`: a hit while falling, and one while sprinting.

SPRINT_PACKETS = tuple(name for name in PACKETS if name != "minecraft:set_entity_data")
"""What a sprinting hit's window compares: `PACKETS` without the entity data.

A sprinting hit changes the data of two entities at the end of its tick: the husk's health and
the fighter's sprint flag, which the hit clears. Vanilla sends them in the order of a hash of
the entity ids (`ServerEntity` per tracked entity), and the two Instances' ids differ: 2 plays
in 6 differed only in that order. So the window leaves out both: the husk's health is read back
(`_read_back`), and whether the sprint stops is not compared. A rule that ignores the order of
the tick-end resends of several entities (#320) would let it be.
"""

_SWORD = "minecraft:diamond_sword"
_GROUND = -60.0
_HOP = 1.0
"""How high the fighter hops before a falling hit: it comes down half of that."""


async def _hop(bot: Bot) -> None:
    """Go up a block in the air, as a jump does, without coming down yet."""
    x, z = bot.position.x, bot.position.z
    await bot.move(x, _GROUND + _HOP, z, on_ground=False)


async def _fall_and_hit(bot: Bot, target: Entity) -> None:
    """Come down half a block in the air, then hit.

    Vanilla counts a hit as critical when the player has fallen (`fallDistance`, which a move
    down in the air adds to) and is not on the ground, climbing, in water or sprinting.
    """
    x, z = bot.position.x, bot.position.z
    await bot.move(x, _GROUND + _HOP / 2, z, on_ground=False)
    await bot.attack(target)


async def _land(bot: Bot) -> None:
    await bot.move(bot.position.x, _GROUND, bot.position.z)


async def _start_sprinting(bot: Bot) -> None:
    await bot.sprint(True)  # noqa: FBT003 - the Bot's own spelling


async def _stop_sprinting(bot: Bot) -> None:
    await bot.sprint(False)  # noqa: FBT003 - the Bot's own spelling


_CRITICAL_CASES = (
    _Case(_SWORD, act=_fall_and_hit, before=_hop, after=_land),
    _Case(_SWORD, before=_start_sprinting, after=_stop_sprinting, packets=SPRINT_PACKETS),
)
"""A hit while falling, which is critical, and one while sprinting, which is not."""


@group("combat/critical", spec=_fighting, kind=GroupKind.TICK_EXACT)
async def critical(context: GroupContext) -> None:
    """The fighter hits a husk with a sword while falling, then while sprinting."""
    await _fight(context, _CRITICAL_CASES)


# `combat/knockback`: a standing hit and a sprinting hit.

_KNOCKBACK_CASES = (
    _Case(_SWORD),
    _Case(_SWORD, before=_start_sprinting, after=_stop_sprinting, packets=SPRINT_PACKETS),
)
"""A hit while standing, and one while sprinting, which adds knockback and stops the sprint."""


@group("combat/knockback", spec=_fighting, kind=GroupKind.TICK_EXACT)
async def knockback(context: GroupContext) -> None:
    """The fighter hits a husk with a sword while standing, then while sprinting."""
    await _fight(context, _KNOCKBACK_CASES)


# `combat/sweep`: a full-charge sword hit on the ground, with three husks beside the target.

_BESIDE = ((0.0, 0.9), (0.0, -0.9), (0.9, 0.0))
"""Three husks 0.9 blocks from the target, each inside the box a sweep covers around it (1 block
wide and long, a quarter of a block high; `Player.attack`, 26.3 javap)."""


SWEEP_PACKETS = (
    "minecraft:damage_event",
    "minecraft:sound",
    "minecraft:animate",
    "minecraft:level_particles",
)
"""What the sweep window compares: the damage each husk takes, the sounds and the particles.

It leaves out the husks' velocity and health. Vanilla sends them at the end of the tick, for
every husk the sweep hurt, in the order of a hash of the entity ids (`ServerEntity` per tracked
entity), and the two Instances' ids differ: 1 play in 6 differed only in that order. The
damage events come in the order the sweep finds the husks, which is the same on both. The health
and velocity of each husk are read back (`_read_back`).
"""


@group("combat/sweep", spec=_fighting, kind=GroupKind.TICK_EXACT)
async def sweep(context: GroupContext) -> None:
    """The fighter hits a husk with a sword on the ground, with three husks beside it."""
    await _fight(context, (_Case(_SWORD, around=_BESIDE, packets=SWEEP_PACKETS),))


# `combat/immunity`: two Bots hit one husk, a few ticks apart.

STRIKER = "striker"
"""The Bot that hits with a diamond sword (7 damage)."""

TAPPER = "tapper"
"""The Bot that hits with a bare hand (1 damage)."""

_LANE_Z = 2.5
_STRIKER_Z = -0.5
_TAPPER_Z = 0.5
_TAPPER_X = _FIGHTER_X - 1.0
"""Where the two Bots stand: either side of the husk's lane, the tapper a block further back.

The striker's sword sweeps: it hurts whoever stands within a block of the husk it hits, and the
tapper is a Player. A block back puts the tapper out of the sweep and still in reach.
"""


@dataclass(frozen=True, slots=True)
class _Pair:
    """Who hits first, who hits second, and how many steps the husk takes between the hits."""

    first: str
    second: str
    steps: int


_PAIRS = (
    _Pair(STRIKER, TAPPER, 5),
    _Pair(TAPPER, STRIKER, 5),
    _Pair(STRIKER, TAPPER, 11),
)
"""A weaker hit 5 ticks after a stronger one, a stronger one 5 ticks after a weaker one, and a
weaker one 11 ticks after a stronger one.

A hurt mob ignores a hit that is not stronger than the last, until its immunity (20 ticks, from
`invulnerableTime`) is down to 10 or less; then it takes the whole hit. The husk counts those
ticks only when the world steps (a frozen mob does not tick), so the gap is exact. Each Bot
has a charge of its own, so a Bot that hit in the last case is full again after the steps that
wait for the charge. A Bot hits once per case: the same Bot twice would hit at part of its
charge, which depends on how long it took.
"""


async def _refill(control: Control, name: str) -> None:
    """Fill `name`'s health and food: a Player keeps both from play to play (saved player data).

    A hit costs the attacker exhaustion; after enough plays the food level drops, and the
    `set_health` that says so would land in a window on one Instance only.
    """
    await control.run(f"effect give {name} minecraft:instant_health 1 10 true")
    await control.run(f"effect give {name} minecraft:saturation 1 10 true")


async def _stand_pair(context: GroupContext) -> None:
    """Put the Bots either side of the lane, the striker with a sword and the tapper bare-handed."""
    control = context.control
    stands = (
        (STRIKER, _FIGHTER_X, _STRIKER_Z, _SWORD),
        (TAPPER, _TAPPER_X, _TAPPER_Z, "minecraft:air"),
    )
    for name, x, dz, held in stands:
        await _refill(control, name)
        await control.run(f"tp {name} {x} -60 {_LANE_Z + dz} {_FACING_EAST} 0")
        await control.run(f"item replace entity {name} hotbar.0 with {held}")


@group("combat/immunity", spec=normal, kind=GroupKind.TICK_EXACT)
async def immunity(context: GroupContext) -> None:
    """A weaker hit, a stronger one, and a weaker one, on a husk that was just hurt."""
    async with _arena(context):
        bots = {name: await context.bot(name) for name in (STRIKER, TAPPER)}
        for bot in bots.values():
            await bot.join()
        await _stand_pair(context)
        husk = (_FIGHTER_X + _REACH, -60.0, _LANE_Z)
        for number, pair in enumerate(_PAIRS):
            if number:
                await context.control.run(f"tp @e[type=minecraft:husk,tag={_TAG}] {_HUSKS_AT}")
            await _summon(context, husk[0], husk[2])
            await context.step(_CHARGE_STEPS)
            first, second = bots[pair.first], bots[pair.second]
            targets = [await find_when_tracked(bot, "husk", husk) for bot in (first, second)]
            async with context.observe(*PACKETS):
                await first.attack(targets[0])
                await context.step(pair.steps)
                await second.attack(targets[1])
                await context.step(2)


# `combat/pvp`: a Bot hits another Bot.

ATTACKER = "attacker"
VICTIM = "victim"

PVP_PACKETS = (*PACKETS, "minecraft:set_health")
PVP_SPRINT_PACKETS = (*SPRINT_PACKETS, "minecraft:set_health")
"""What the windows compare: `PACKETS` and the victim's health, and the same without the entity
data for a sprinting hit (`SPRINT_PACKETS`)."""

_VICTIM_X = _FIGHTER_X + _REACH


async def _pvp_hit(context: GroupContext, attacker: Bot, lane_z: float, *, sprint: bool) -> None:
    """Put the Bots in `lane_z` and hit once, sprinting or not, in a window of its own."""
    control = context.control
    await control.run(f"tp {ATTACKER} {_FIGHTER_X} -60 {lane_z} {_FACING_EAST} 0")
    await control.run(f"tp {VICTIM} {_VICTIM_X} -60 {lane_z} 90.0 0")
    await context.step(_CHARGE_STEPS)
    if sprint:
        await _start_sprinting(attacker)
    packets = PVP_SPRINT_PACKETS if sprint else PVP_PACKETS
    target = await find_when_tracked(attacker, "player", (_VICTIM_X, -60.0, lane_z))
    async with context.observe(*packets):
        await attacker.attack(target)
        await context.step(2)
    if sprint:
        await _stop_sprinting(attacker)


@group("combat/pvp", spec=normal, masks=(PITCH_MASK,), kind=GroupKind.TICK_EXACT)
async def pvp(context: GroupContext) -> None:
    """A Bot hits another Bot with a diamond sword while standing, then while sprinting."""
    async with _arena(context):
        attacker = await context.bot(ATTACKER)
        await attacker.join()
        victim = await context.bot(VICTIM)
        await victim.join()
        await _refill(context.control, ATTACKER)
        await context.control.run(f"item replace entity {ATTACKER} hotbar.0 with {_SWORD}")
        await _refill(context.control, VICTIM)
        for lane, sprint in enumerate((False, True)):
            await _pvp_hit(context, attacker, 2.5 + 4 * lane, sprint=sprint)
