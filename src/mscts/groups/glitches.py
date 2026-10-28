"""Vanilla glitches: pistons that break bedrock, and duplicate TNT, rails and carpets.

Technical players use these on purpose, and some servers remove them on purpose (Paper turns
them off by default: docs/research/2026-09-30-gameplay-survey.md). Each Group builds one
machine a player would build, with `/setblock`, fires it, and compares what it does tick by tick.

Each Group first stops the weather cycle and lets a storm fade (`calm_weather`,
`until_the_weather_fades`): its windows compare every entity that appears, and a storm on one
Instance only could strike lightning in one. Then it sets up the redstone arena
(`redstone.arena`): the watcher at the spawn, random ticks off, the world frozen. Control builds
the machines in the air above chunks (0, 0), (1, 0) and (0, 1), from y -53 up, so that no
explosion reaches the grass, and steps the world a tick at a time in each window (facts:
the issue's fact sheet, #42).

When a Group ends, Control kills the items and TNT the machines made, then removes everything it
built without updating the blocks beside them, so that no tick is scheduled on the way out.
"""

import contextlib
from collections.abc import AsyncIterator

from mscts.compare import Mask
from mscts.group import GroupContext, GroupKind, group
from mscts.groups._world import calm_weather, fast_forward, until_the_weather_fades
from mscts.groups.blocks import DROP_MASKS
from mscts.groups.redstone import _PISTON_PITCH, At, arena, stepped_window

_PACKETS = (
    "minecraft:block_update",
    "minecraft:section_blocks_update",
    "minecraft:block_event",
    "minecraft:level_event",
    "minecraft:sound",
    "minecraft:explode",
    "minecraft:add_entity",
    "minecraft:remove_entities",
    "minecraft:set_entity_data",
)
"""What every window compares: the blocks that change, the pistons' block events and sounds,
world events, the explosions, and the entities that appear, change and go."""

_REQUIRES = ("redstone/piston-push", "redstone/sticky")
"""The Groups that show a server's pistons push and pull as vanilla's do: a glitch is how
they misbehave, so it is played on the Candidate only once they match."""

_CLEAR = "fill 3 -60 3 25 -43 29 minecraft:air"
"""Takes away every machine and what it made: from the grass up to y -43."""

_CLEAR_STRICT = f"{_CLEAR} strict"
"""Clears without updating the blocks beside each one cleared (`FillCommand`: flag 816), so that
no tick is scheduled; the plain fill after it clears the machines on a server without
`strict`."""

_KILLS = ("kill @e[type=minecraft:item]", "kill @e[type=minecraft:tnt]")
"""Takes away the items and the TNT the machines made, so that the next play has none."""


@contextlib.asynccontextmanager
async def _machines(context: GroupContext, build: tuple[str, ...]) -> AsyncIterator[None]:
    """Calm the weather, set up the redstone arena, then run `build`; undo it all on the way out.

    The undo of the machines is pushed before the arena is set up, so that it runs after the
    arena's undo, still in the frozen world: the TNT and items go, then the blocks.
    """
    control = context.control
    async with contextlib.AsyncExitStack() as undo:
        await calm_weather(control, undo)
        await until_the_weather_fades(control)
        undo.push_async_callback(control.run, _CLEAR)
        undo.push_async_callback(control.run, _CLEAR_STRICT)
        for kill in _KILLS:
            undo.push_async_callback(control.run, kill)
        await undo.enter_async_context(arena(context, build))
        yield


def _put(x: int, y: int, z: int, block: str) -> str:
    """The `/setblock` of `block` at x, y, z."""
    return f"setblock {x} {y} {z} minecraft:{block}"


# `glitches/bedrock-breaking`: the Minecraft Wiki's exploding-piston method (Tutorial:Breaking
# bedrock, revision 3861736), at z 12 under bedrock and at z 4 under an end portal frame. The
# Wiki's TNT, primed by the player, takes a random push and blows up in the open air; here it is
# summoned (no push) in a box of obsidian, so that every ray of its explosion ends there.

_TARGETS = {12: "bedrock", 4: "end_portal_frame"}
"""The z of each machine, in the order they fire, and the block it breaks, at x 12, -53."""


def _breaker(z: int, target: str) -> tuple[str, ...]:
    """The machine at z: `target`, obsidian above the piston's place and a lever in a box.

    The lever, on, sits on the east wall of a box of obsidian with one cell left for the TNT,
    at x 9, -52, z. The piston Control places at x 12, -52, z is beside the box's east wall,
    which the lever powers.
    """
    return (
        f"fill 8 -53 {z - 1} 11 -51 {z + 1} minecraft:obsidian",
        _put(9, -52, z, "air"),
        _put(12, -53, z, target),
        _put(12, -51, z, "obsidian"),
        _put(10, -52, z, "lever[face=wall,facing=west,powered=true]"),
    )


_BREAKERS_BUILD = tuple(
    command for z, target in _TARGETS.items() for command in _breaker(z, target)
)


def _breaking(z: int) -> tuple[At, ...]:
    """Fire the machine at z: place the piston, blow up its power, and turn it down."""
    return (
        At(0, _put(12, -52, z, "piston[facing=east]")),
        At(4, f"summon minecraft:tnt 9.5 -52 {z}.5 {{fuse:1s,NoGravity:1b}}"),
        At(5, _put(12, -52, z, "piston[facing=down]")),
    )


_BREAKING_TICKS = 9
"""The piston extends on tick 1 and is out on tick 3. The TNT, with a fuse of 1, explodes on
tick 5 and destroys the lever, so the piston has lost its power: its retraction is due on
tick 6. Between the two, Control replaces it with a piston facing down. A piston retracts the way
its block faces when the event runs (`PistonBaseBlock.triggerEvent` reads `FACING` first), and
removes the block in front of it whatever it is (`level.removeBlock`): the bedrock goes on tick
6. The piston lands on tick 8."""


@group(
    "glitches/bedrock-breaking",
    kind=GroupKind.TICK_EXACT,
    requires=_REQUIRES,
    masks=(_PISTON_PITCH, *DROP_MASKS),
)
async def bedrock_breaking(context: GroupContext) -> None:
    """A piston turned in the tick before it retracts breaks bedrock and an end portal frame."""
    async with _machines(context, _BREAKERS_BUILD):
        for z in _TARGETS:
            await stepped_window(context, _breaking(z), _BREAKING_TICKS, _PACKETS)


# `glitches/tnt-duplication`: a coral-fan TNT duplicator (Tutorial:Block and item duplication,
# "Piston-based TNT duplication", revision 3862182; random-j-farmer.github.io, "TNT Dupers"). A
# sticky piston at x 20 pushes a stone and a slime block east; a TNT stuck to the slime's north
# side, under a redstone block that never updated it, moves along. The coral fan on the stone's
# north side pops when the piston head takes the stone's place, and its update reaches the TNT.

_TNT_BUILD = (
    "fill 19 -60 5 25 -60 11 minecraft:glass",
    "fill 20 -60 6 24 -60 10 minecraft:water",
    _put(20, -45, 9, "sticky_piston[facing=east]"),
    _put(21, -45, 9, "stone"),
    _put(22, -45, 9, "slime_block"),
    _put(21, -45, 8, "dead_tube_coral_wall_fan[facing=north,waterlogged=false]"),
    _put(22, -45, 8, "tnt"),
    f"{_put(22, -44, 8, 'redstone_block')} strict",
)
"""A pool of water in glass on the grass, under the TNT, for the primed TNT to explode in, where
it breaks nothing. Then the duplicator. The first block pushed is stone, not slime, so that the
fan stays where it is. The redstone block is placed with `strict`, which updates no block beside
it: an update would prime the TNT now (`TntBlock.neighborChanged`)."""

_TNT_PUSH = (At(0, _put(19, -45, 9, "redstone_block")),)

_TNT_PUSH_TICKS = 6
"""On tick 1 the piston captures the blocks it moves (`PistonBaseBlock.moveBlocks`), sets moving
blocks where they go, then its head where the stone was. The fan loses its support and pops, and
its update reaches the TNT at its old place before that is set to air: the powered TNT primes
(`TntBlock.prime`, fuse 80), and its moving copy lands a block east on tick 3."""

_TNT_FAST_FORWARD = 70
"""The ticks stepped at once, outside a window, while the primed TNT falls into the pool."""

_TNT_EXPLOSION_TICKS = 10
"""The TNT explodes 80 ticks after it was primed: on the 4th tick of this window."""

_PRIMED_PUSH = tuple(
    Mask(
        packet,
        path,
        "Vanilla draws it at random for TNT a block primes (26.3 javap): `PrimedTnt.<init>` "
        "turns it nextDouble() * 2 pi (offsets 17-30) and pushes it 0.02 a tick that way, "
        "velocity (-sin * 0.02, 0.2, -cos * 0.02), so where it explodes moves with it. How "
        "far primed TNT drifts is the subject of `entities/motion`; that it appears, its fuse, "
        "when it explodes, at what height, how strongly and how many blocks it breaks are "
        "compared.",
    )
    for packet, path in (
        ("minecraft:add_entity", "velocity.x"),
        ("minecraft:add_entity", "velocity.z"),
        ("minecraft:explode", "center.x"),
        ("minecraft:explode", "center.z"),
    )
)
"""Which way the primed TNT drifts, drawn at random by vanilla, and so where it explodes."""


@group(
    "glitches/tnt-duplication",
    kind=GroupKind.TICK_EXACT,
    requires=_REQUIRES,
    masks=_PRIMED_PUSH,
)
async def tnt_duplication(context: GroupContext) -> None:
    """A coral fan that pops as a piston pushes a TNT primes it, and the TNT block moves on."""
    async with _machines(context, _TNT_BUILD):
        await stepped_window(context, _TNT_PUSH, _TNT_PUSH_TICKS, _PACKETS)
        await fast_forward(context.control, _TNT_FAST_FORWARD)
        await stepped_window(context, (), _TNT_EXPLOSION_TICKS, _PACKETS)


# `glitches/rail-carpet-duplication`: two duplicators by the same coral-fan update, at z 22 a
# rail and at z 28 a carpet, each pushed east by a piston at x 4, which Control powers from x 3.

_RAIL_Z, _CARPET_Z = 22, 28

_RAIL_BUILD = (
    _put(4, -45, _RAIL_Z, "piston[facing=east]"),
    _put(5, -45, _RAIL_Z, "stone"),
    _put(6, -45, _RAIL_Z, "slime_block"),
    _put(6, -44, _RAIL_Z, "rail[shape=east_west]"),
    _put(5, -44, _RAIL_Z, "dead_tube_coral_fan[waterlogged=false]"),
)
"""A rail on a slime block, which the piston pushes behind a stone, and a fan on the stone. The
fan pops when the head takes the stone's place, and its update reaches the rail, which has lost
its support (`BaseRailBlock.neighborChanged`): it drops as an item."""

_CARPET_BUILD = (
    _put(4, -45, _CARPET_Z, "piston[facing=east]"),
    _put(5, -45, _CARPET_Z, "slime_block"),
    _put(5, -44, _CARPET_Z, "slime_block"),
    _put(5, -45, _CARPET_Z - 1, "dead_tube_coral_wall_fan[facing=north,waterlogged=false]"),
    _put(5, -44, _CARPET_Z - 1, "white_carpet"),
)
"""Two slime blocks, one on the other, and a carpet stuck to the upper one's north side, on a
fan on the lower one's: the fan pops when the head takes the lower slime's place, and the carpet,
left with air below, drops as an item."""

_DUPLICATING_TICKS = 5
"""The piston pushes on tick 1, when the rail or the carpet drops; its moving copy lands a block
east on tick 3 (`PistonMovingBlockEntity.tick`)."""


def _duplicating(z: int) -> tuple[At, ...]:
    """Power the piston at x 4, -45, z: a redstone block behind it."""
    return (At(0, _put(3, -45, z, "redstone_block")),)


@group(
    "glitches/rail-carpet-duplication",
    kind=GroupKind.TICK_EXACT,
    requires=_REQUIRES,
    masks=DROP_MASKS,
)
async def rail_carpet_duplication(context: GroupContext) -> None:
    """A coral fan that pops as a piston pushes a rail or a carpet drops it, and the block lands."""
    async with _machines(context, (*_RAIL_BUILD, *_CARPET_BUILD)):
        for z in (_RAIL_Z, _CARPET_Z):
            await stepped_window(context, _duplicating(z), _DUPLICATING_TICKS, _PACKETS)
