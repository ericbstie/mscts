"""Combat Groups: what a hit does to the player or mob it lands on.

A Bot called `fighter` hits a husk that cannot think (`NoAI`) with the item in its hand, and the
window compares what the server sends about the hit: the damage (`damage_event`, the husk's
health in `set_entity_data`), the knockback (`set_entity_motion`), the sounds and the
particles. The husk's position packets are left out: vanilla resends a still husk's position
about every 3 s of wall time, which lands in a window one play in four.

A husk stands in for the zombie: it has the same health, speed and knockback but does not
burn in daylight. A zombie burns when it ticks in the sun, drawn at random each tick
(`Monster.isSunBurnTick`), and a stepped world ticks it.

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
from mscts.groups._world import pin_joins
from mscts.spec import CONTROL_PLAYER, Difficulty, ServerSpec

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
    "Vanilla draws a hurt mob's voice pitch at random: LivingEntity.getVoicePitch is "
    "(nextFloat - nextFloat) * 0.2 + 1 (26.3 javap). The sound itself is still compared.",
)

_TAG = "mscts_combat"
"""What every husk a Group summons is tagged with, so that it removes only those."""

_CHARGE_STEPS = 10
"""How many steps a Bot waits so that its attack charge is full: each is at least 2 server ticks
(a step and the barrier after it), and the slowest weapon here, an axe, needs 20 (26.3 javap)."""

_CORPSE_POLLS = 20
"""How often Control asks whether a husk is left: a corpse goes in about 1 s, a poll takes about
0.3 s."""

_NONE_LEFT = b"conditional.fail"
"""What vanilla's `execute if entity` answers, as a translation key, when nothing matched."""

_CONTROL_AT = "5.5 -60 44.5"

_FIGHTER_X = 4.5
_REACH = 1.5
_FACING_EAST = -90.0
"""The yaw of a player facing +x."""

type _Weapon = str | None


def _normal(spec: ServerSpec) -> ServerSpec:
    """Play on normal difficulty: peaceful removes a hostile mob."""
    return dataclasses.replace(spec, difficulty=Difficulty.NORMAL)


async def _remove_husks(control: Control) -> None:
    """Kill every husk the Group summoned, leaving no loot and no experience, and wait for them.

    A husk a player hit drops experience, and loot, where it dies. Experience needs a player
    to have hurt it in the last 100 ticks (`lastHurtByPlayerMemoryTime`), which the first
    command clears; loot and experience both need `mob_drops`, which the rest turn off while
    the husks die. A corpse stays for 20 ticks of its own (`LivingEntity.tickDeath`), so the
    world runs again until none is left: the next play puts new husks where these stood, and
    would be told apart from them only by the order they were heard in.
    """
    await control.run(f"data merge entity @e[tag={_TAG}] {{last_hurt_by_player_memory_time:0}}")
    try:
        await control.run("gamerule mob_drops false")
        await control.run(f"kill @e[tag={_TAG}]")
    finally:
        await control.run("gamerule mob_drops true")
    await control.run("tick unfreeze")
    for _ in range(_CORPSE_POLLS):
        said = await control.run(f"execute if entity @e[tag={_TAG}]")
        if any(_NONE_LEFT in packet.payload for packet in said):
            return


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
        undo.push_async_callback(_remove_husks, control)
        await control.run(f"tp {CONTROL_PLAYER} {_CONTROL_AT}")
        yield


async def _summon(context: GroupContext, x: float, z: float) -> None:
    await context.control.run(
        f'summon minecraft:husk {x} -60 {z} {{NoAI:1b,OnGround:1b,Health:20f,Tags:["{_TAG}"]}}'
    )


async def _stand(context: GroupContext, lane_z: float, weapon: _Weapon) -> None:
    """Put the fighter in lane `lane_z` facing +x with `weapon` in hand, and a husk in front."""
    control = context.control
    await control.run(f"tp {FIGHTER} {_FIGHTER_X} -60 {lane_z} {_FACING_EAST} 0")
    held = weapon or "minecraft:air"
    await control.run(f"item replace entity {FIGHTER} hotbar.0 with {held}")
    await _summon(context, _FIGHTER_X + _REACH, lane_z)


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
    closed.
    """

    weapon: _Weapon
    act: _Act = _hit
    before: _Step = _nothing
    after: _Step = _nothing


async def _fight(context: GroupContext, cases: tuple[_Case, ...]) -> None:
    """Play each case in a lane of its own, in a window narrowed to `PACKETS`.

    The fighter joins, then for each case it is put in its lane with a husk in front, waits for
    a full charge, and hits inside the window, which the world then steps two ticks.
    """
    async with _arena(context):
        fighter = await context.bot(FIGHTER)
        await fighter.join()
        for lane, case in enumerate(cases):
            lane_z = 2.5 + 4 * lane
            await _stand(context, lane_z, case.weapon)
            await context.step(_CHARGE_STEPS)
            await case.before(fighter)
            async with context.observe(*PACKETS):
                target = fighter.entities.find("husk", near=(_FIGHTER_X + _REACH, -60.0, lane_z))
                await case.act(fighter, target)
                await context.step(2)
            await case.after(fighter)


@group("combat/melee-mob", spec=_normal, masks=(PITCH_MASK,), kind=GroupKind.TICK_EXACT)
async def melee_mob(context: GroupContext) -> None:
    """The fighter hits a husk with a hand, a wooden sword, a diamond sword and an axe."""
    await _fight(context, tuple(_Case(weapon) for weapon in _WEAPONS))


# `combat/critical`: a hit while falling, and one while sprinting.

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
    _Case(_SWORD, before=_start_sprinting, after=_stop_sprinting),
)
"""A hit while falling, which is critical, and one while sprinting, which is not."""


@group("combat/critical", spec=_normal, masks=(PITCH_MASK,), kind=GroupKind.TICK_EXACT)
async def critical(context: GroupContext) -> None:
    """The fighter hits a husk with a sword while falling, then while sprinting."""
    await _fight(context, _CRITICAL_CASES)
