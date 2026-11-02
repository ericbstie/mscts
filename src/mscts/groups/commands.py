"""Command Groups: what a command says back, and the effects it sends around its answer.

An operator Bot, `commander`, runs each command itself in a window of its own, so that its own
feedback is compared (Control's answers never are, `compare.py`). Control sets each case up before
the window, and the Bots drain what they heard of that: an operator is told every other operator's
feedback. The world is frozen, random ticks are off, the weather cycle is off, and joins are
pinned to the spawn (facts: the issue's fact sheet, #66).

Each window waits, in its body, for the chat packets vanilla sends for the command: one for a
success or an execution error, two for a parse error. Where vanilla says nothing, the Bot runs
`tellraw @s "mscts-end"` after the command and waits for that marker, which vanilla answers once
the command has run (one FIFO for a player's chat commands). The close barrier then takes what the
next tick sends: a block change, the player's own tick.

Each window compares the chat and the effect packets its command sends inside itself, on the same
tick or the first after it. A packet vanilla draws at random (a give's fake drop and its pickup
sound, a kill's loot) or sends on a schedule of its own (`move_entity_pos`, `update_attributes`)
is left out, so is `tick query`, whose tick times come from the wall clock.
"""

import contextlib
from collections.abc import AsyncIterator
from dataclasses import dataclass, replace

from mscts.bot import Bot
from mscts.group import Control, GroupContext, group
from mscts.groups._world import CONTROL_AT, calm_weather, join_at_spawn, normal, pin_joins
from mscts.spec import CONTROL_PLAYER, ServerSpec

COMMANDER = "commander"
"""The operator Bot that runs each command itself, so that its feedback is compared."""

WITNESS = "witness"
"""A second operator, in `commands/success`: vanilla tells it each command's feedback."""

ANSWER_TIMEOUT_S = 10.0
"""How long a Bot waits for what a command answers: a Bot's bound. Vanilla answered 1 to 13 ms
after the command (a clone 78 ms, a first fill on a fresh Instance 425 ms)."""

_SYSTEM_CHAT = "minecraft:system_chat"
_CHAT = (_SYSTEM_CHAT, "minecraft:player_chat", "minecraft:disguised_chat")
"""The chat every window compares: a command answers with `system_chat`, `say` with `player_chat`
(a server that sends `disguised_chat` instead has the Report show the difference)."""

_END = "mscts-end"
"""The marker's text: the same in every window and play, as it is compared (a counter made every
play differ)."""

_PLACES = {COMMANDER: "0.5 -60 14.5", WITNESS: "-3.5 -60 14.5"}
"""Where Control puts each Bot: in chunk (0, 0), clear of every block the Groups set."""


@dataclass(frozen=True, slots=True)
class _Case:
    """One window: Control's setup, the command, and what the window waits for and compares.

    Attributes:
        command: What the first Bot runs.
        setup: What Control runs before the window opens.
        answers: How many chat packets vanilla sends for `command` and `then`, one for a success
            or an execution error, two for a parse error.
        effects: The packets besides the chat that the window compares: what the command sends
            inside itself, on the same tick or the first after it.
        signed: Whether the Bot sends `command` as the vanilla client sends a message command.
        marker: Whether the window ends with the marker, where vanilla sends no chat (`answers`
            0) or its feedback is off.
        then: What the Bot sends right after `command`, without waiting.
    """

    command: str
    setup: tuple[str, ...] = ()
    answers: int = 1
    effects: tuple[str, ...] = ()
    signed: bool = False
    marker: bool = False
    then: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _Outline:
    """A Group's script: who joins, what the first Bot runs, and what is set and undone around it.

    Attributes:
        names: The Bots that join; the first runs the commands.
        cases: The windows, in order.
        undo: What Control runs after the last window, in order, before the fixture's own undo.
        start: What Control runs once, after the fixture, before the first window.
    """

    names: tuple[str, ...]
    cases: tuple[_Case, ...]
    undo: tuple[str, ...]
    start: tuple[str, ...] = ()


def _with_operators(spec: ServerSpec) -> ServerSpec:
    """Make the commander and the witness operators, besides whoever the spec names; play normal."""
    return normal(replace(spec, operators=(*spec.operators, COMMANDER, WITNESS)))


async def _play(context: GroupContext, outline: _Outline) -> None:
    """Set the world up, run `outline.start`, play each case in a window, and undo it all."""
    control = context.control
    async with contextlib.AsyncExitStack() as undo:
        bots = await undo.enter_async_context(_fixture(context, *outline.names))
        for command in reversed(outline.undo):
            undo.push_async_callback(control.run, command)
        for command in outline.start:
            await control.run(command)
        for case in outline.cases:
            await _play_case(context, bots, case)


@contextlib.asynccontextmanager
async def _fixture(context: GroupContext, *names: str) -> AsyncIterator[list[Bot]]:
    """Pin the joins, calm the weather, join and place `names`, freeze the world; undo it on exit.

    Not `spawn_mobs`: the Fixture world has it off already (ADR-0013).
    """
    control = context.control
    async with contextlib.AsyncExitStack() as undo:
        await pin_joins(control, undo)
        await calm_weather(control, undo)
        bots = await _joined_in_place(context, undo, names)
        await _freeze(control, undo)
        yield bots


async def _joined_in_place(
    context: GroupContext, undo: contextlib.AsyncExitStack, names: tuple[str, ...]
) -> list[Bot]:
    """Join a Bot for each of `names`, then have Control put each in its place and itself away.

    Each Bot passes the barrier first: Pumpkin kicked a Bot ("Wrong teleport id") whose join
    teleport it had not handled when Control's `tp` ran, and the barrier proves it handled it.
    """
    bots = [await join_at_spawn(context, undo, name) for name in names]
    for bot in bots:
        await bot.sync()
    for bot in bots:
        await context.control.run(f"tp {bot.name} {_PLACES[bot.name]}")
    await context.control.run(f"tp {CONTROL_PLAYER} {CONTROL_AT}")
    return bots


async def _freeze(control: Control, undo: contextlib.AsyncExitStack) -> None:
    """Freeze the world and stop random ticks, so that only a command changes it; push the undos."""
    await control.run("tick freeze")
    undo.push_async_callback(control.run, "tick unfreeze")
    await control.run("gamerule random_tick_speed 0")
    undo.push_async_callback(control.run, "gamerule random_tick_speed 3")


async def _play_case(context: GroupContext, bots: list[Bot], case: _Case) -> None:
    """Set `case` up, then, in a window, have the first of `bots` run it and wait for its answer."""
    runner = bots[0]
    for command in case.setup:
        await context.control.run(command)
    # What Control said meanwhile reached every operator too: take it now, so that it is not
    # taken for the answer.
    for bot in bots:
        await bot.drain()
    async with context.observe(*_CHAT, *case.effects) as opened:
        await _run(runner, case)
        await _wait_for_answer(runner, case, opened)


async def _run(bot: Bot, case: _Case) -> None:
    """Send the case's command, then each command that follows it, one right after the other."""
    if case.signed:
        await bot.signed_command(case.command)
    else:
        await bot.command(case.command)
    for command in case.then:
        await bot.command(command)


async def _wait_for_answer(bot: Bot, case: _Case, opened: int) -> None:
    """Wait for the chat packets vanilla sends for the case, then for a marker if it has one.

    Only a packet that arrived at the window's open Mark (`opened`) or later counts.
    """
    for _ in range(case.answers):
        await bot.expect(*_CHAT, timeout_s=ANSWER_TIMEOUT_S, since_ns=opened)
    if case.marker:
        await _wait_for_marker(bot, opened)


async def _wait_for_marker(bot: Bot, opened: int) -> None:
    """Run `tellraw @s` with the marker, and wait for it: the command before it has run."""
    await bot.command(f'tellraw @s "{_END}"')
    await bot.expect(
        _SYSTEM_CHAT,
        timeout_s=ANSWER_TIMEOUT_S,
        since_ns=opened,
        where=lambda packet: _END.encode() in packet.payload,
    )


# `commands/success`: one valid form of each of about 20 common commands.

_AREA_CLEAR = "fill 2 -60 2 14 -58 10 minecraft:air"
_BIG_BOX = "0 -50 0 15 61 15"
"""16 x 112 x 16 = 28 672 blocks, under the 32 768 `max_block_modifications`, in the air of one
chunk column, (0, 0); the commander's head is at y -58.2. Vanilla sends a tick's block changes
chunk by chunk in the identity-hash order of `ServerChunkCache.chunkHoldersToBroadcast`, so a
fill over several chunks sends its `section_blocks_update` in an order per boot (20 plays: 19 of
20 differed on a 31 x 30 x 31 box over four chunks)."""
_PIG = "minecraft:pig"
_KILLS = ("kill @e[type=minecraft:pig,tag=mscts]", "kill @e[type=minecraft:item]")

_BLOCK = ("minecraft:block_update",)
_SECTION = ("minecraft:section_blocks_update",)
_SLOT = ("minecraft:container_set_slot",)

_SUCCESS = (
    _Case(
        "setblock 4 -60 4 minecraft:stone",
        setup=("setblock 4 -60 4 minecraft:air",),
        effects=_BLOCK,
    ),
    _Case("fill 4 -60 6 6 -58 8 minecraft:stone", setup=(_AREA_CLEAR,), effects=_SECTION),
    _Case(
        "clone 4 -60 6 6 -58 8 8 -60 6",
        setup=("fill 8 -60 6 10 -58 8 minecraft:air",),
        effects=_SECTION,
    ),
    _Case(
        f'summon {_PIG} 12.5 -60 12.5 {{NoAI:1b,Tags:["mscts"],UUID:[I;1,2,3,4]}}',
        effects=("minecraft:add_entity",),
    ),
    _Case("kill @e[type=minecraft:pig,tag=mscts]", effects=("minecraft:entity_event",)),
    _Case(
        "kill @e[type=minecraft:pig,tag=mscts2]",
        setup=(
            f'summon {_PIG} 12.5 -60 4.5 {{NoAI:1b,Tags:["mscts","mscts2"]}}',
            f'summon {_PIG} 12.5 -60 6.5 {{NoAI:1b,Tags:["mscts","mscts2"]}}',
        ),
    ),
    _Case("tp @s 1.5 -60 14.5", effects=("minecraft:player_position",)),
    _Case("give @s minecraft:diamond_sword", effects=_SLOT),
    _Case("enchant @s minecraft:sharpness 2", effects=_SLOT),
    _Case("clear @s minecraft:diamond_sword", effects=_SLOT),
    _Case("effect give @s minecraft:speed 100 1 true", effects=("minecraft:update_mob_effect",)),
    _Case("xp add @s 10 points", effects=("minecraft:set_experience",)),
    _Case("gamemode creative", effects=("minecraft:game_event", "minecraft:player_abilities")),
    _Case("difficulty easy", effects=("minecraft:change_difficulty",)),
    _Case("time set 1000"),
    _Case("weather clear"),
    _Case("gamerule keep_inventory true"),
    _Case("tick rate 20", effects=("minecraft:ticking_state",)),
    _Case("seed"),
    _Case("list"),
    _Case("execute if block 4 -60 4 minecraft:stone", setup=("setblock 4 -60 4 minecraft:stone",)),
    _Case("say Hello from the commander", signed=True),
    _Case(
        f"fill {_BIG_BOX} minecraft:stone",
        setup=(f"fill {_BIG_BOX} minecraft:air",),
        answers=2,
        then=('tellraw @s "after the fill"',),
    ),
)
"""The `give` is a sword: a diamond grants an advancement and 12 recipes on the first play only.
The pigs are summoned with a UUID of the Group's, since vanilla names an entity in a message with
a hover holding its UUID, drawn at random. The last case sends a slow command and a fast one at
once, and vanilla answers them in order."""

_SUCCESS_UNDO = (
    *reversed(_KILLS),
    "clear commander",
    "xp set commander 0 levels",
    "xp set commander 0 points",
    "effect clear commander",
    "gamerule keep_inventory false",
    "difficulty normal",
    "gamemode survival commander",
    _AREA_CLEAR,
    f"fill {_BIG_BOX} minecraft:air",
)
"""What Control runs after the last window, in order."""


@group("commands/success", spec=_with_operators)
async def success(context: GroupContext) -> None:
    """The commander runs a valid form of each common command; the witness hears the feedback."""
    await _play(context, _Outline((COMMANDER, WITNESS), _SUCCESS, _SUCCESS_UNDO))


# `commands/errors`: the same commands, run wrong.

_ERRORS = (
    _Case("setblock 4 -60 4 minecraft:not_a_block", answers=2),
    _Case("setblock 4 -60", answers=2),
    _Case("notacommand", answers=2),
    _Case("setblock 4 400 4 minecraft:stone"),
    _Case("setblock 4 -60 4 minecraft:stone", setup=("setblock 4 -60 4 minecraft:stone",)),
    _Case("fill 0 -60 0 100 -50 100 minecraft:stone"),
    _Case("clone 4 -60 6 6 -58 8 5 -60 6"),
    _Case("kill @e[tag=nothing]"),
    _Case("tp @s @e[tag=nothing]", answers=2),
    _Case("give @s minecraft:diamond 0", answers=2),
    _Case("give @s minecraft:not_an_item", answers=2),
    _Case("clear @s minecraft:diamond"),
    _Case("effect give @s minecraft:not_an_effect", answers=2),
    _Case("effect clear @s minecraft:speed"),
    _Case("enchant @s minecraft:sharpness"),
    _Case("xp add @s abc", answers=2),
    _Case("gamemode nonsense", answers=2),
    _Case("gamemode survival", answers=0, marker=True),
    _Case("difficulty normal"),
    _Case("time set abc"),
    _Case("weather rain abc", answers=2),
    _Case("gamerule not_a_rule true", answers=2),
    _Case("gamerule keep_inventory maybe", answers=2),
    _Case("tick rate 0", answers=2),
    _Case("seed extra", answers=2),
    _Case("list nonsense", answers=2),
    _Case("summon minecraft:not_an_entity", answers=2),
    _Case("say", answers=2),
)
"""A parse error answers two messages, the error and the command up to the cursor; an error
while the command runs answers one. A `gamemode survival` for a player in survival already
answers nothing in vanilla. `summon minecraft:pig 12.5 400 12.5` is left out: vanilla summons
it, with a random UUID (`setblock 4 400 4` is the position outside the world)."""

_ERRORS_UNDO = (*reversed(_KILLS), _AREA_CLEAR)
"""None of these changes anything in vanilla; a server that does one of them is put back."""


@group("commands/errors", spec=_with_operators)
async def errors(context: GroupContext) -> None:
    """The commander runs commands wrong: a bad or missing argument, or no match for a selector."""
    await _play(context, _Outline((COMMANDER,), _ERRORS, _ERRORS_UNDO))
