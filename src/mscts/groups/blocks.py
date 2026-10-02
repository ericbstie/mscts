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
from mscts.spec import ServerSpec

BUILDER = "builder"
"""The Bot that runs each command itself, as an operator, so its feedback is compared."""

FEEDBACK_TIMEOUT_S = 10.0
"""How long the builder waits for a command's feedback: `run.GROUP_TIMEOUT_S`, a Bot's bound."""

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
    states = "minecraft:oak_stairs[facing=east,half=top]"
    sign = 'minecraft:oak_sign[rotation=4]{front_text:{messages:["Hello","mscts","",""]}}'
    chest = 'minecraft:chest[facing=north]{Items:[{Slot:0b,id:"minecraft:diamond",count:3}]}'
    for block in (states, sign, chest):
        at = _ROW.format(x=x)
        cases.append(
            _Case(command=f"setblock {at} {block}", setup=(f"setblock {at} minecraft:air",))
        )
        x += 1
    at = _ROW.format(x=x)
    cases.append(
        _Case(command=f"setblock {at} minecraft:stone", setup=(f"setblock {at} minecraft:stone",))
    )
    return tuple(cases)


_SETBLOCK_CASES = _setblock_cases()
_SETBLOCK_CLEAR = "fill 1 -60 2 12 -60 2 minecraft:air"


@group("blocks/setblock", spec=_with_builder, masks=DROP_MASKS)
async def setblock(context: GroupContext) -> None:
    """The builder sets blocks in each mode, on air and on a block, with states and block data."""
    await _play(context, _SETBLOCK_CASES, _SETBLOCK_CLEAR)
