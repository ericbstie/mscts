"""Blocks Groups: what `/setblock`, `/fill` and `/clone` do to the world.

A Bot called `builder`, an operator, runs each command itself inside an Observation window, so
that what the server tells it (the command's feedback) is compared along with what the command
changes: the blocks, the block entities, the break particles and the items a block drops.
Control sets each case up before its window, and undoes everything after the last (a Group
leaves the Instance as it found it, because every Group is played on the same two Instances).

The world is frozen (`tick freeze`) and random ticks are off, so nothing but the command
changes a block. Every block the Groups change is in chunk (0, 0), the one the builder is
sent when it joins (docs/guide/writing-a-group.md).
"""

import contextlib
from collections.abc import AsyncIterator
from dataclasses import dataclass, replace

from mscts.compare import Mask
from mscts.group import Control, GroupContext, group
from mscts.spec import CONTROL_PLAYER, ServerSpec

BUILDER = "builder"
"""The Bot that runs each command itself, as an operator, so its feedback is compared."""

FEEDBACK_TIMEOUT_S = 10.0
"""How long the builder waits for a command's feedback: `run.GROUP_TIMEOUT_S`, a Bot's bound."""

BUILDER_AT = "0.5 -60 14.5"
"""Where the builder stands for every case: on the flat world, in chunk (0, 0), and clear of
every block the Groups set.

Vanilla joins a player at a random place within `respawn_radius` (10) of the world spawn, once
per world. A block set where the builder stands makes it crawl (pose) and choke (health), on
one Instance only (docs/research/2026-10-03-builder-pose.md).

This holds only while PACKETS leaves out `player_position` (which the teleport sends,
before the first window) and `set_health`.
"""

CONTROL_AT = "3.5 -60 14.5"
"""Where Control stands: like BUILDER_AT, clear of every block the Groups set (#300).

Control joins at a random place of its own, saved per Instance, so a block set there makes it
crawl and choke on one Instance only, and the builder hears of it (a `set_entity_data` for
Control's entity, inside a window). It stands 3 blocks from the builder: the clone's blocks
end at z 11 and the player at z 14.2.
"""

PACKETS = (
    "minecraft:block_update",
    "minecraft:section_blocks_update",
    "minecraft:block_entity_data",
    "minecraft:level_event",
    "minecraft:add_entity",
    "minecraft:set_entity_data",
    "minecraft:system_chat",
)
"""The packets a window compares: what a command changes, breaks, drops and says."""

_SYSTEM_CHAT = "minecraft:system_chat"

_POP = "Block.popResource adds Mth.nextDouble(random, -0.25, 0.25) to the block's centre"
_MOTION = "the ItemEntity constructor sets nextDouble() * 0.2 - 0.1"
_DROPPED_ITEM = {
    "x": _POP,
    "y": _POP,
    "z": _POP,
    "velocity.x": _MOTION,
    "velocity.z": _MOTION,
    "yaw": "the ItemEntity constructor sets nextFloat() * 360",
}

DROP_MASKS = tuple(
    Mask(
        "minecraft:add_entity",
        path,
        f"Vanilla draws it at random for each item a block drops: {draw} (26.3 javap). Where "
        "an item moves is the subject of `entities/motion`, and which item drops, and how many, "
        "is compared in its `set_entity_data`.",
    )
    for path, draw in _DROPPED_ITEM.items()
)
"""Where a dropped item appears and how it moves and faces, drawn at random by vanilla.

Every `add_entity` these Groups' windows compare is a dropped item: a `destroy` mode, or a
block entity's contents, drops them.
"""


@dataclass(frozen=True, slots=True)
class _Case:
    """One window: what Control sets up before it opens, and the command the builder runs."""

    command: str
    setup: tuple[str, ...] = ()


def _with_builder(spec: ServerSpec) -> ServerSpec:
    """Make the builder an operator, besides Control and whoever the spec already names."""
    return replace(spec, operators=(*spec.operators, BUILDER))


@contextlib.asynccontextmanager
async def _frozen(control: Control, clear: str) -> AsyncIterator[None]:
    """Freeze the world and stop random ticks; on the way out, `clear` the blocks and undo both.

    Each undo runs even if another fails, and after the body however it ended: the Self-check
    and `mscts run` play every Group on the same two Instances.
    """
    async with contextlib.AsyncExitStack() as undo:
        await control.run("tick freeze")
        undo.push_async_callback(control.run, "tick unfreeze")
        await control.run("gamerule random_tick_speed 0")
        undo.push_async_callback(control.run, "gamerule random_tick_speed 3")
        undo.push_async_callback(control.run, "kill @e[type=minecraft:item]")
        undo.push_async_callback(control.run, clear)
        yield


async def _play(context: GroupContext, cases: tuple[_Case, ...], clear: str) -> None:
    """Join the builder and play each case in a window of its own: setup, then the command.

    The builder waits for its command's feedback inside the window. The window's barrier
    (`Bot.sync`) alone does not cover a chat command on a server that is behind schedule
    (docs/research/2026-10-01-control.md), and the feedback is sent when the command runs.
    """
    builder = await context.bot(BUILDER)
    await builder.join()
    await context.control.run(f"tp {BUILDER} {BUILDER_AT}")
    await context.control.run(f"tp {CONTROL_PLAYER} {CONTROL_AT}")
    async with _frozen(context.control, clear):
        for case in cases:
            for command in case.setup:
                await context.control.run(command)
            # What Control said meanwhile reached the builder too (an operator hears every
            # other operator's feedback): take it now, so it is not taken for the answer.
            await builder.drain()
            async with context.observe(*PACKETS):
                await builder.command(case.command)
                await builder.expect(_SYSTEM_CHAT, timeout_s=FEEDBACK_TIMEOUT_S)


# `blocks/setblock`: a row of cells at y = -60, the first air above the flat world's grass.

_ROW = "{x} -60 2"

_STAIRS = "minecraft:oak_stairs[facing=east,half=top]"
_SIGN = 'minecraft:oak_sign[rotation=4]{front_text:{messages:["Hello","mscts","",""]}}'
_CHEST = 'minecraft:chest[facing=north]{Items:[{Slot:0b,id:"minecraft:diamond",count:3}]}'


def _setblock_cases() -> tuple[_Case, ...]:
    cases = []
    x = 1
    for mode in ("destroy", "keep", "replace", "strict"):
        for before in ("minecraft:air", "minecraft:dirt"):
            at = _ROW.format(x=x)
            cases.append(
                _Case(
                    command=f"setblock {at} minecraft:stone {mode}",
                    setup=(f"setblock {at} {before}",),
                )
            )
            x += 1
    for block in (_STAIRS, _SIGN, _CHEST):
        at = _ROW.format(x=x)
        cases.append(
            _Case(command=f"setblock {at} {block}", setup=(f"setblock {at} minecraft:air",))
        )
        x += 1
    at = _ROW.format(x=x)
    cases.append(
        _Case(command=f"setblock {at} minecraft:stone", setup=(f"setblock {at} minecraft:stone",))
    )
    at = _ROW.format(x=x + 1)
    cases.append(_Case(command=f"data get block {at} Items", setup=(f"setblock {at} {_CHEST}",)))
    return tuple(cases)


_SETBLOCK_CASES = _setblock_cases()
_SETBLOCK_CLEAR = "fill 1 -60 2 13 -60 2 minecraft:air"


@group("blocks/setblock", spec=_with_builder, masks=DROP_MASKS)
async def setblock(context: GroupContext) -> None:
    """The builder sets blocks in each mode, on air and on a block, with states and block data."""
    await _play(context, _SETBLOCK_CASES, _SETBLOCK_CLEAR)


# `blocks/fill`: a 5 x 5 x 5 region whose y runs from -50 to -46, so that it crosses the border
# between chunk sections -4 (y -64 to -49) and -3 (y -48 to -33). The flat world is air there.

_FILL_BOX = "2 -50 2 6 -46 6"
_FILL_CLEAR = f"fill {_FILL_BOX} minecraft:air"
_FILL_BEFORE = (
    _FILL_CLEAR,
    "setblock 3 -49 3 minecraft:dirt",
    "setblock 4 -48 4 minecraft:glass",
    "setblock 5 -47 5 minecraft:glass",
    "setblock 2 -50 4 minecraft:glass",
)
"""Blocks already in the region, in both sections. Only the dirt drops an item.

Vanilla resends each new item at the end of the tick, in the hash order of its entity id.
The two Instances number their entities differently, so a window with two drops can
send them in a different order on each side: this is no Divergence worth reporting, and
it makes a Group flaky (measured: 17 of 20 plays did not match with four drops).
"""

_FILL_OPTIONS = (
    "",
    "hollow",
    "keep",
    "outline",
    "replace",
    "replace minecraft:dirt",
    "strict",
    "destroy",
)
"""The modes, `destroy` last: a Candidate that hangs on it has answered the rest by then."""


def _fill_cases() -> tuple[_Case, ...]:
    return tuple(
        _Case(command=f"fill {_FILL_BOX} minecraft:stone {option}".rstrip(), setup=_FILL_BEFORE)
        for option in _FILL_OPTIONS
    )


_FILL_CASES = _fill_cases()


@group("blocks/fill", spec=_with_builder, masks=DROP_MASKS)
async def fill(context: GroupContext) -> None:
    """The builder fills a region that crosses a chunk section border, in each mode."""
    await _play(context, _FILL_CASES, _FILL_CLEAR)


# `blocks/clone`: copy a box of 3 x 3 x 3 blocks (x 2 to 4, z 8 to 10, above the flat world).
# A clone drops no item, so the Group has no Mask.

_CLONE_SOURCE = "2 -60 8 4 -58 10"
_CLONE_APART = "8 -60 8"
_CLONE_OVERLAPPING = "3 -60 9"
_CLONE_CLEAR = "fill 2 -60 8 10 -58 11 minecraft:air"
_CLONE_BEFORE = (
    _CLONE_CLEAR,
    "setblock 2 -60 8 minecraft:stone",
    "setblock 3 -60 9 minecraft:dirt",
    f"setblock 4 -60 8 {_SIGN}",
    f"setblock 4 -59 10 {_STAIRS}",
    f"setblock 3 -59 9 {_CHEST}",
    "setblock 10 -58 10 minecraft:gold_block",
)
"""The source holds a block of each kind and air; the gold block is where the source has air."""

_CLONE_CHEST_COPY = "9 -59 9"
"""Where the source's chest is copied to."""

_CLONE_BLOCKS = ("replace", "masked", "filtered minecraft:stone")
_CLONE_HOW = ("normal", "force", "move")


def _clone_cases() -> tuple[_Case, ...]:
    apart = (
        _Case(command=f"clone {_CLONE_SOURCE} {_CLONE_APART} {blocks} {how}", setup=_CLONE_BEFORE)
        for blocks in _CLONE_BLOCKS
        for how in _CLONE_HOW
    )
    overlapping = (
        _Case(
            command=f"clone {_CLONE_SOURCE} {_CLONE_OVERLAPPING} replace {how}",
            setup=_CLONE_BEFORE,
        )
        for how in _CLONE_HOW
    )
    chest = (
        _Case(
            command=f"data get block {_CLONE_CHEST_COPY} Items",
            setup=(*_CLONE_BEFORE, f"clone {_CLONE_SOURCE} {_CLONE_APART} replace {how}"),
        )
        for how in ("normal", "move")
    )
    return (*apart, *overlapping, *chest)


_CLONE_CASES = _clone_cases()


@group("blocks/clone", spec=_with_builder)
async def clone(context: GroupContext) -> None:
    """The builder clones blocks with each filter and each way to copy, and over themselves."""
    await _play(context, _CLONE_CASES, _CLONE_CLEAR)
