"""Time Groups: the time of day advancing, the time commands, and sleeping through the night.

In 26.3 the time of day is a world clock, `minecraft:overworld`, that moves one tick a tick
while the game rule `advance_time` is true and the world runs
(docs/research/2026-10-15-day-cycle.md). `time query day` answers how far into the day it is,
`time query day repetition` how many days have passed, and `time query time` the clock's total
ticks.

Every case reads the time from `time query` feedback, which a window compares as
`system_chat`. The client also learns it from `set_time`, but that is a heartbeat packet
(`compare.HEARTBEAT`): vanilla sends it every 20 ticks, frozen or not, so no window compares
it. A Group only waits on `set_time`: the 20-tick one carries the game time, so the first that
carries the game time a step reaches shows the step has ended. This assumes the game time stands
still while the world is frozen, as it does on vanilla. On a server whose game time runs on, the
wait ends early and the clock reads the day too soon: still a difference, but one that shows in
`time query day`.

The time commands need an operator, so each Group's Bot `clock` is one. An operator hears every
other operator's commands as admin chat, so Control runs nothing inside a window that compares
chat, and the clock drains what it heard before each. Every rule a Group sets is put back
afterwards, because every Group is played on the same two Instances.

Kinds: `time/advance` is tick-exact, as each window reads the time after an exact number of
stepped ticks. It steps with `tick step` itself rather than `GroupContext.step`, which costs
about 300 ms a tick (242 ticks a play), and its windows hold only answers to queries, so it
makes no `tick:` Marks. `time/commands` is exact: the world never steps, and only the commands
move the time. `time/sleep` is exact, not tick-exact: a sleeping player falls into a deep sleep
on its own ticks, which run while the world is frozen, so the night skip follows the wall
clock. Its windows compare the order of what comes, and the clock reads the time back after
each. When the night is skipped is read the same way: the clock reads the day at most 60 ticks
after the player lies down, before the skip at 100, so a server that skips at once shows
another day.
"""

import contextlib
from collections.abc import Callable
from dataclasses import replace

from mscts.bot import Bot, Face, offline_uuid
from mscts.codec.packets import Packet
from mscts.group import Control, GroupContext, GroupKind, group
from mscts.groups._world import calm_weather, join_at_spawn, pin_joins
from mscts.spec import CONTROL_PLAYER, ServerSpec

CLOCK = "clock"
"""The Bot that reads the time back, an operator."""

_CHAT = "minecraft:system_chat"
_TIME = "minecraft:set_time"

_WAIT_S = 30.0
"""How long a Bot waits for what a Group waits for: the longest, a step of 100 ticks, takes 5 s
at 20 ticks a second, and the `set_time` that shows it ended up to 1 s more."""


def _operator(spec: ServerSpec) -> ServerSpec:
    """The default spec, with the clock an operator, so that it can run `/time`."""
    return replace(spec, operators=(*spec.operators, CLOCK))


async def _calm(context: GroupContext, undo: contextlib.AsyncExitStack) -> None:
    """Pin the joins, clear the weather and stop it; push each undo.

    Not `spawn_mobs`: the Fixture world has it off already (ADR-0013), and an undo to vanilla's
    default would let animals spawn, and walk into the windows of every later play.
    """
    await pin_joins(context.control, undo)
    await calm_weather(context.control, undo)


async def _command_then_chat(bot: Bot, command: str) -> None:
    """Run `command` as `bot`, and wait for the first `system_chat` that comes after it.

    That is the command's answer when nothing else is said meanwhile, as in every window here:
    Control runs nothing in them, and the clock drains what it heard before each.
    """
    await bot.command(command)
    await bot.expect(_CHAT, timeout_s=_WAIT_S)


async def _read(context: GroupContext, clock: Bot, *queries: str) -> None:
    """The clock runs each of `queries`, in one window of its own."""
    await clock.drain()
    async with context.observe(_CHAT):
        for query in queries:
            await _command_then_chat(clock, query)


def _game_time(packet: Packet) -> int:
    """The game time a `set_time` carries.

    Raises:
        TypeError: The packet did not decode to a game time.
    """
    game_time = (packet.fields or {}).get("game_time")
    if not isinstance(game_time, int):
        msg = f"a set_time with no game time: {packet.fields}"
        raise TypeError(msg)
    return game_time


def _reached(game_time: int) -> Callable[[Packet], bool]:
    """Whether a `set_time` carries `game_time` or later."""

    def holds(packet: Packet) -> bool:
        return _game_time(packet) >= game_time

    return holds


async def _frozen_game_time(bot: Bot) -> int:
    """The game time of a frozen world: what the next `set_time` carries.

    The barrier first, so that a `set_time` stamped before the freeze is not the one read. Any
    `set_time` will do, with a clock or without: no command that sends one is pending.
    """
    await bot.sync()
    return _game_time(await bot.expect(_TIME, timeout_s=_WAIT_S))


async def _step(control: Control, clock: Bot, ticks: int, game_time: int) -> int:
    """Step the frozen world `ticks` ticks from `game_time`, and return the game time reached.

    Returns once a `set_time` to the clock carries it, so the step has ended.
    """
    await control.run(f"tick step {ticks}")
    reached = game_time + ticks
    await clock.expect(_TIME, timeout_s=_WAIT_S, where=_reached(reached))
    return reached


# `time/advance`: a frozen world steps 1, 20 and 100 ticks, with `advance_time` true and false.

_START = 1000
_STEPS = (1, 20, 100)


@group("time/advance", spec=_operator, kind=GroupKind.TICK_EXACT)
async def advance(context: GroupContext) -> None:
    """The world steps 1, 20 and 100 ticks from day 1000; the clock reads the day after each.

    With `advance_time` true the day moves with every tick stepped; with it false it stays.
    Control steps the world (`tick step`) outside the windows. The clock waits until a
    `set_time` carries the game time the step reaches, so the step has ended, and then reads
    `time query day` in a window of its own.
    """
    control = context.control
    async with contextlib.AsyncExitStack() as undo:
        await _calm(context, undo)
        clock = await join_at_spawn(context, undo, CLOCK)
        undo.push_async_callback(control.run, "gamerule advance_time true")
        await context.freeze()
        game_time = await _frozen_game_time(clock)
        for advancing in ("true", "false"):
            await control.run(f"gamerule advance_time {advancing}")
            await control.run(f"time set {_START}")
            for ticks in _STEPS:
                game_time = await _step(control, clock, ticks, game_time)
                await _read(context, clock, "time query day")


# `time/commands`: the clock sets, adds to and reads the time.

_COMMANDS = (
    "time set day",
    "time query time",
    "time set noon",
    "time query time",
    "time set night",
    "time query time",
    "time set midnight",
    "time query time",
    "time set 1000",
    "time add 100",
    "time query day",
    "time add 24000",
    "time query day",
    "time query day repetition",
    "time query time",
    "time query daytime",
)
"""From total ticks 0: each named time of the day, read back; an absolute time; two adds; and
each query. `time query daytime` is the query 26.3 removed, so vanilla refuses it. `time query
gametime` is left out: the game time counts every tick since the world was made, so it differs
between two Instances (#399)."""


@group("time/commands", spec=_operator)
async def commands(context: GroupContext) -> None:
    """The clock runs each time command in a frozen world, in a window of its own.

    The world is frozen, so only the commands move the time. Control sets the clock to 0 first,
    and each window holds the command's answer.
    """
    async with contextlib.AsyncExitStack() as undo:
        await _calm(context, undo)
        clock = await join_at_spawn(context, undo, CLOCK)
        await context.freeze()
        await context.control.run("time set 0")
        await clock.drain()
        for command in _COMMANDS:
            async with context.observe(_CHAT):
                await _command_then_chat(clock, command)


# `time/sleep`: a player lies down at midnight, with 100% and then 50% of players needed.

SLEEPER = "sleeper"
"""The Bot that sleeps; not an operator."""

_FOOT = (2, -60, 0)
"""The block of the bed's foot. The bed faces east (+x), so its head is the block east of it."""

_STAND = (_FOOT[0] - 2, _FOOT[1], _FOOT[2])
"""The block the sleeper stands on to lie down, west of the bed, and its spawn point before."""

_MIDNIGHT = 18000
_BEFORE_DAWN = 23460
"""A time at which a sleeping player is still in bed: vanilla gets one up at 23478."""

_DAWN_STEPS = 40

_QUIET_TIMES = 7
"""How many `set_time` the clock waits for while a player sleeps and the night goes on (any
`set_time`: vanilla sends one every 20 ticks, and no command runs meanwhile). The first may be
sent before the player lies down; the other 6 span at least 100 ticks after it, the time a
player takes to fall into a deep sleep."""

_BEFORE_DEEP_SLEEP = 3
"""How many `set_time` the clock waits for after a player lies down with 50% needed, before it
reads the day: the first may come before, so 3 come 20 to 60 ticks after, and the night
is skipped at 100."""

SLEEP_PACKETS = (
    _CHAT,
    "minecraft:animate",
    "minecraft:set_entity_data",
    "minecraft:game_event",
)
"""What a sleep window compares: the sleep messages, leaving the bed, the sleeping pose and the
game events."""

_WAKE_UP = 0
"""`ClientboundAnimatePacket.WAKE_UP` in 26.3."""


def _at(block: tuple[int, int, int]) -> str:
    """A block's position, as a command takes it."""
    return " ".join(map(str, block))


async def _place_bed(control: Control, undo: contextlib.AsyncExitStack) -> None:
    """Set the bed at `_FOOT`, facing east, and push its removal."""
    x, y, z = _FOOT
    head = (x + 1, y, z)
    for block, part in ((_FOOT, "foot"), (head, "head")):
        await control.run(f"setblock {_at(block)} minecraft:red_bed[part={part},facing=east]")
    undo.push_async_callback(control.run, f"fill {_at(_FOOT)} {_at(head)} minecraft:air strict")


async def _first_night(control: Control) -> None:
    """Make the sleeper's first night in the bed like its first ever, every time it is played.

    The first time a player sleeps it gets the advancement `adventure/sleep_in_bed`, and the bed
    becomes its spawn point; vanilla announces both. Both are kept with the player, so the
    advancement is revoked, and the spawn point moved off the bed.
    """
    await control.run(f"advancement revoke {SLEEPER} only minecraft:adventure/sleep_in_bed")
    await control.run(f"spawnpoint {SLEEPER} {_at(_STAND)}")


def _woke(clock: Bot) -> Callable[[Packet], bool]:
    """Whether an `animate` is the sleeper getting up, as `clock`, which tracks it, is told.

    Any other entity's `animate`, or another action, does not end a wait for it.
    """
    sleeper = offline_uuid(SLEEPER)
    ids = {entity.id for entity in clock.entities.values() if entity.uuid == sleeper}

    def holds(packet: Packet) -> bool:
        fields = packet.fields or {}
        return fields.get("entity_id") in ids and fields.get("action") == _WAKE_UP

    return holds


async def _alone(context: GroupContext, clock: Bot) -> None:
    """Make Control leave, and wait until the clock is told it has.

    Control is a player too, and counts towards the players needed to sleep (`SleepStatus`).
    """
    await context.control.leave()
    await clock.expect("minecraft:player_info_remove", timeout_s=_WAIT_S, where=_control_gone)


def _control_gone(packet: Packet) -> bool:
    """Whether a `player_info_remove` names Control."""
    uuids = (packet.fields or {}).get("uuids")
    return isinstance(uuids, list) and offline_uuid(CONTROL_PLAYER) in uuids


async def _alone_at_midnight(context: GroupContext, clock: Bot, percentage: int) -> None:
    """Set the sleeping percentage, the time to midnight and the sleeper by the bed; then leave.

    Control leaves last (`_alone`), and the clock drains the admin chat it heard meanwhile.
    """
    control = context.control
    x, y, z = _STAND
    await control.run(f"gamerule players_sleeping_percentage {percentage}")
    await control.run(f"time set {_MIDNIGHT}")
    await control.run(f"tp {SLEEPER} {x + 0.5} {y} {z + 0.5} -90 0")
    await _alone(context, clock)
    await clock.drain()


async def _lie_down(sleeper: Bot) -> None:
    """Use the bed's foot from above, as a client does to sleep in it."""
    await sleeper.place(*_FOOT, Face.UP)


async def _count_set_time(clock: Bot, times: int) -> None:
    """Wait for `times` `set_time`: vanilla sends one every 20 ticks."""
    for _ in range(times):
        await clock.expect(_TIME, timeout_s=_WAIT_S)


async def _read_day(context: GroupContext, clock: Bot) -> None:
    """The clock reads the day and the days passed, in a window of its own."""
    await _read(context, clock, "time query day", "time query day repetition")


async def _to_dawn(context: GroupContext, clock: Bot, game_time: int) -> None:
    """Step the world from just before dawn until a sleeping player is up, in a window.

    `game_time` is the frozen game time. Control steps the world inside the window, and an
    operator hears that as admin chat, so the clock is no operator meanwhile: the window
    compares the chat too.
    """
    control = context.control
    await control.run(f"time set {_BEFORE_DAWN}")
    await control.run(f"deop {CLOCK}")
    try:
        await clock.drain()
        async with context.observe(*SLEEP_PACKETS):
            await _step(control, clock, _DAWN_STEPS, game_time)
    finally:
        await control.run(f"op {CLOCK}")


@group("time/sleep", spec=_operator)
async def sleep(context: GroupContext) -> None:
    """A player sleeps at midnight while another stays up: first all, then half, are needed.

    With `players_sleeping_percentage` 100, one sleeper of two is not enough: the night goes on,
    and the sleeper gets up when the world steps to dawn. With 50 it is enough: the night is
    skipped once the sleeper has slept 100 ticks, with the world frozen; the clock reads the day
    once before that too. Control leaves before each player lies down, so the two Bots are the
    only players then. The clock reads the day after each part.
    """
    control = context.control
    async with contextlib.AsyncExitStack() as undo:
        await _calm(context, undo)
        clock = await join_at_spawn(context, undo, CLOCK)
        sleeper = await join_at_spawn(context, undo, SLEEPER)
        await context.freeze()
        game_time = await _frozen_game_time(clock)
        await _place_bed(control, undo)
        await _first_night(control)
        undo.push_async_callback(control.run, "gamerule players_sleeping_percentage 100")
        await _alone_at_midnight(context, clock, 100)
        async with context.observe(*SLEEP_PACKETS):
            await _lie_down(sleeper)
            await _count_set_time(clock, _QUIET_TIMES)
        await _read_day(context, clock)
        await _to_dawn(context, clock, game_time)
        await _read_day(context, clock)
        await _alone_at_midnight(context, clock, 50)
        async with context.observe(*SLEEP_PACKETS):
            await _lie_down(sleeper)
            await _count_set_time(clock, _BEFORE_DEEP_SLEEP)
        await _read(context, clock, "time query day")
        async with context.observe(*SLEEP_PACKETS):
            await clock.expect("minecraft:animate", timeout_s=_WAIT_S, where=_woke(clock))
        await _read_day(context, clock)
