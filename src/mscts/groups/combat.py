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
from collections.abc import AsyncIterator

from mscts.compare import Mask
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


@group("combat/melee-mob", spec=_normal, masks=(PITCH_MASK,), kind=GroupKind.TICK_EXACT)
async def melee_mob(context: GroupContext) -> None:
    """The fighter hits a husk with a hand, a wooden sword, a diamond sword and an axe."""
    async with _arena(context):
        fighter = await context.bot(FIGHTER)
        await fighter.join()
        for lane, weapon in enumerate(_WEAPONS):
            lane_z = 2.5 + 4 * lane
            await _stand(context, lane_z, weapon)
            await context.step(_CHARGE_STEPS)
            async with context.observe(*PACKETS):
                target = fighter.entities.find("husk", near=(_FIGHTER_X + _REACH, -60.0, lane_z))
                await fighter.attack(target)
                await context.step(2)
