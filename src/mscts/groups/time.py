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
carries the game time a step reaches shows the step has ended.

The time commands need an operator, so each Group's Bot `clock` is one. An operator hears every
other operator's commands as admin chat, so Control runs nothing inside a window that compares
chat, and the clock drains what it heard before each. Every rule a Group sets is put back
afterwards, because every Group is played on the same two Instances.

Kinds: `time/advance` is tick-exact, as each window reads the time after an exact number of
stepped ticks.
"""

import contextlib
from collections.abc import Callable
from dataclasses import replace

from mscts.bot import Bot
from mscts.codec.packets import Packet
from mscts.group import GroupContext, GroupKind, group
from mscts.groups._world import join_at_spawn, pin_joins
from mscts.spec import ServerSpec

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
    """Pin the joins, clear the weather and stop it and mob spawning; push each undo."""
    control = context.control
    await pin_joins(control, undo)
    for rule in ("spawn_mobs", "advance_weather"):
        await control.run(f"gamerule {rule} false")
        undo.push_async_callback(control.run, f"gamerule {rule} true")
    await control.run("weather clear")


async def _ask(bot: Bot, command: str) -> None:
    """Run `command` as `bot`, and wait for its answer."""
    await bot.command(command)
    await bot.expect(_CHAT, timeout_s=_WAIT_S)


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


def _heartbeat(packet: Packet) -> bool:
    """Whether a `set_time` is the 20-tick one, which carries no clock."""
    return (packet.fields or {}).get("clocks") == []


async def _now(bot: Bot) -> int:
    """The game time of a frozen world: what the next 20-tick `set_time` carries.

    The barrier first, so that a `set_time` stamped before the freeze is not the one read.
    """
    await bot.sync()
    return _game_time(await bot.expect(_TIME, timeout_s=_WAIT_S, where=_heartbeat))


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
        game_time = await _now(clock)
        for advancing in ("true", "false"):
            await control.run(f"gamerule advance_time {advancing}")
            await control.run(f"time set {_START}")
            for ticks in _STEPS:
                await control.run(f"tick step {ticks}")
                game_time += ticks
                await clock.expect(_TIME, timeout_s=_WAIT_S, where=_reached(game_time))
                await clock.drain()
                async with context.observe(_CHAT):
                    await _ask(clock, "time query day")
