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

from mscts.group import GroupContext, GroupKind, group
from mscts.groups._world import calm_weather, until_the_weather_fades
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
