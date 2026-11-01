"""Weather Groups: the commands that start and stop rain and thunder, and a frozen world.

In 26.3 `weather rain|thunder|clear <duration>` only sets the weather's target and its
duration (`WeatherData`) and answers; the sky changes in `ServerLevel.advanceWeatherCycle`,
which moves the rain and thunder levels 0.01 a tick toward the target and sends `game_event`
RAIN_LEVEL_CHANGE (7) and THUNDER_LEVEL_CHANGE (8) on each tick a level moves. When rain passes
a level of 0.2 (`isRaining`) it also sends START_RAINING (1) or STOP_RAINING (2), followed by 7
and 8 again. A frozen world never runs the cycle, and each stepped tick does (the issue's fact
sheet, #64).

A window that holds a command compares `system_chat` and `game_event`; a window that steps
compares `game_event` only, because an operator hears every `tick step` Control runs as admin
chat (`TickCommand.step` calls `sendSuccess(..., true)`). The watcher, an operator, runs each
weather command itself, because Control's feedback is never compared.

Before the watcher joins, Control stops the weather cycle and lets a storm fade (`calm_weather`,
`until_the_weather_fades`): a storm one Instance started during an earlier Group would reach the
windows on that Instance only. When a Group ends, the weather is cleared and every rule it set is
put back; the clear's fade is left to the next play, which starts by waiting for it.
"""

import contextlib
from collections.abc import AsyncIterator
from dataclasses import replace

from mscts.bot import Bot
from mscts.group import GroupContext, GroupKind, group
from mscts.groups._world import calm_weather, join_at_spawn, pin_joins, until_the_weather_fades
from mscts.spec import ServerSpec

WATCHER = "watcher"
"""The Bot that runs the weather commands and hears the sky change, an operator."""

_CHAT = "minecraft:system_chat"
_EVENT = "minecraft:game_event"

_WAIT_S = 30.0
"""How long the watcher waits for the feedback of its command."""


def _operator(spec: ServerSpec) -> ServerSpec:
    """The default spec, with the watcher an operator, so that it can run `/weather`."""
    return replace(spec, operators=(*spec.operators, WATCHER))


@contextlib.asynccontextmanager
async def _frozen_calm(context: GroupContext) -> AsyncIterator[Bot]:
    """Calm the weather and let it fade, join the watcher, stop random ticks and freeze.

    Yields the watcher. On the way out every rule is put back and the weather is cleared. Not
    `spawn_mobs`: the Fixture world has it off (ADR-0013), and an undo to vanilla's default would
    let animals spawn, and walk into the windows of every later play.
    """
    control = context.control
    async with contextlib.AsyncExitStack() as undo:
        await pin_joins(control, undo)
        await calm_weather(control, undo)
        await until_the_weather_fades(control)
        undo.push_async_callback(control.run, "weather clear")
        watcher = await join_at_spawn(context, undo, WATCHER)
        await control.run("gamerule random_tick_speed 0")
        undo.push_async_callback(control.run, "gamerule random_tick_speed 3")
        await context.freeze()
        yield watcher


async def _command_window(context: GroupContext, watcher: Bot, command: str) -> None:
    """The watcher runs `command` in a window of its feedback and the game events; no step.

    The watcher drains first, and waits for its own feedback inside the window: an operator is
    also told every other operator's commands.
    """
    await watcher.drain()
    async with context.observe(_CHAT, _EVENT):
        await watcher.command(command)
        await watcher.expect(_CHAT, timeout_s=_WAIT_S)


async def _step_window(context: GroupContext, ticks: int) -> None:
    """Step the world `ticks` ticks, one at a time, in a window of the game events."""
    async with context.observe(_EVENT):
        await context.step(ticks)


# `weather/commands`: rain, thunder and clear, each followed by stepped ticks.

_COMMANDS = (
    ("weather rain 600", 30),
    ("weather thunder 600", 30),
    ("weather clear", 62),
)
"""Each weather command and the ticks stepped after it. Every command but `clear` gives a
duration, because one without draws it at random. Rain passes 0.2 on its 20th tick, and thunder
reaches 0.3 after its 30. `clear` takes 62: thunder is 0 on the 30th, rain stops at the 41st
and is 0 on the 61st (the fact sheet; 30 is too few to see rain stop)."""


@group("weather/commands", spec=_operator, kind=GroupKind.TICK_EXACT)
async def commands(context: GroupContext) -> None:
    """The watcher starts rain and thunder and clears them, each with stepped ticks after it.

    The world is frozen, so the cycle runs only on the ticks Control steps. Each command has a
    window of its own, and so does each run of steps.
    """
    async with _frozen_calm(context) as watcher:
        for command, ticks in _COMMANDS:
            await _command_window(context, watcher, command)
            await _step_window(context, ticks)
