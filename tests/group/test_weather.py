"""The weather Groups: what Control and the watcher send, in which windows, and what is undone.

Every test plays a Group against a fake server once and reads the Transcript for what each Bot
sent (the commands) and the Marks (the Observation windows and the ticks stepped). What a server
answers is never asserted: the fake answers Control's markers, the game time, the barrier (a
tick apart) and the watcher's commands, five ticks late.
"""

import asyncio
import functools
import json
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, field

import pytest
from support.control import (
    AWARD_STATS,
    CHAT_COMMAND,
    CLIENT_COMMAND,
    CODEC,
    CONTROL,
    MARKER,
    SYSTEM_CHAT,
    chat,
    tree,
)
from support.gametime import gametime_answer
from support.moves import Play, opened, read

from mscts.bot import SYNC_REQUESTS, TICK_GAP_S
from mscts.codec.packets import Direction, Packet
from mscts.compare import OBSERVE_CLOSE, OBSERVE_OPEN, TICK_MARK
from mscts.group import GROUPS, GroupContext, GroupKind
from mscts.groups import weather
from mscts.spec import ServerSpec
from mscts.transcript import Transcript
from tests.net.fakes import NO_STATISTICS, JoinScript, Peer, join_server, serve

WATCHER = "watcher"
GAME_EVENT = "minecraft:game_event"
COMMANDS = tree("gamerule", "tick", "tellraw", "time", "weather", "tp")
TIME_QUERY = "time query gametime"
FADE_TICKS = 100
"""How far the fake's game time moves on between two reads: as far as a storm takes to fade."""
TICK_S = 2 * TICK_GAP_S
"""The fake's tick: just over what a barrier needs to see one pass, so a play is quick."""
LATE_TICKS = 5
"""How many ticks the fake takes to answer the watcher: longer than a barrier, so a window that
did not wait for the answer would miss it."""
SET_TIME = "minecraft:set_time"
SET_TIME_EVERY_S = 10 * TICK_S
"""How often the fake sends `set_time` to the watcher: far apart next to a barrier (two ticks), so
a Group that stops waiting for one too soon closes its window before the next comes."""
PLAY_TIMEOUT_S = 120.0
"""How long a fake serves a Bot: a whole play."""
STEP = (CONTROL, "tick step 1")
GROUP_IDS = ("weather/commands", "weather/frozen")

CALM = (
    "gamerule player_movement_check false",
    "gamerule respawn_radius 0",
    "gamerule advance_weather false",
    "weather clear",
    TIME_QUERY,
    TIME_QUERY,
    "gamerule random_tick_speed 0",
    "tick freeze",
)
"""What Control sets up before the first window: the joins pinned, the weather stopped, cleared
and let to fade (two reads of the game time), random ticks off, and the world frozen."""
UNDO = (
    "gamerule random_tick_speed 3",
    "tp watcher 0.5 -60 0.5",
    "weather clear",
    "gamerule advance_weather true",
    "gamerule respawn_radius 10",
    "gamerule player_movement_check true",
    "tick unfreeze",
)
"""What Control undoes after the last window, in order. Not `spawn_mobs`: the Fixture world has
it off (ADR-0013), and an undo to vanilla's default would let animals spawn in later plays."""


@dataclass
class WeatherServer:
    """A fake server that joins like vanilla and answers like one run by operators.

    A marker (`tellraw @s "<token>"`) gets its token back at once, and `time query gametime`
    the game time, `FADE_TICKS` further on each time. The watcher's commands are answered
    `LATE_TICKS` later, while the server goes on answering the barrier. A barrier's answers
    come a tick apart.
    """

    seen: list[Packet] = field(default_factory=list)
    game_time: int = 0

    async def __call__(self, peer: Peer) -> None:
        """Serve one connection: a Handler."""
        with suppress(ConnectionError):
            await join_server(self.seen, JoinScript(commands=COMMANDS, then=self._play))(peer)

    async def _play(self, peer: Peer) -> None:
        ticker = None if peer.name == CONTROL else asyncio.create_task(self._set_times(peer))
        try:
            await self._serve(peer)
        finally:
            if ticker is not None:
                ticker.cancel()

    async def _set_times(self, peer: Peer) -> None:
        """Send `peer` a `set_time` as it enters play, and one every `SET_TIME_EVERY_S`."""
        with suppress(ConnectionError):
            while True:
                await peer.send(SET_TIME, game_time=self.game_time, clocks=[])
                await asyncio.sleep(SET_TIME_EVERY_S)

    async def _serve(self, peer: Peer) -> None:
        requests = 0
        async with asyncio.TaskGroup() as later:
            try:
                async for packet in peer.packets():
                    self.seen.append(packet)
                    if packet.name == CLIENT_COMMAND:
                        requests += 1
                        if (requests - 1) % SYNC_REQUESTS != 0:
                            await asyncio.sleep(TICK_S)  # a barrier's answers come a tick apart
                        await peer.write(peer.raw_frame(AWARD_STATS, NO_STATISTICS))
                    elif packet.name == CHAT_COMMAND:
                        command = str((packet.fields or {})["command"])
                        await self._command(peer, command, later)
            except ConnectionError:
                pass  # the Bot left with something unread (a reset)

    async def _command(self, peer: Peer, command: str, later: asyncio.TaskGroup) -> None:
        if command.startswith(MARKER):
            await peer.write(chat(peer, json.loads(command.removeprefix(MARKER))))
        elif command == TIME_QUERY:
            self.game_time += FADE_TICKS
            frame = peer.frame(SYSTEM_CHAT, content=gametime_answer(self.game_time), overlay=False)
            await peer.write(frame)
        elif peer.name != CONTROL:
            later.create_task(self._say(peer, command))

    async def _say(self, peer: Peer, command: str) -> None:
        await asyncio.sleep(LATE_TICKS * TICK_S)
        with suppress(ConnectionError):  # the Bot may have left first
            await peer.write(chat(peer, f"done: {command}"))


async def _play(group_id: str, server: WeatherServer) -> Transcript:
    transcript = Transcript(group_id=group_id, server="fake")
    async with serve(CODEC, server, timeout_s=PLAY_TIMEOUT_S) as endpoint:
        context = GroupContext(endpoint, transcript, timeout_s=10.0)
        try:
            await GROUPS[group_id].run(context)
        finally:
            await context.close()
    return transcript


@functools.cache
def play(group_id: str) -> tuple[Transcript, Play]:
    """Play `group_id` against a fake server once; its Transcript and what was read from it."""
    transcript = asyncio.run(_play(group_id, WeatherServer()))
    return transcript, read(transcript)


def played(group_id: str) -> Play:
    return play(group_id)[1]


def marks(transcript: Transcript, test: Callable[[str], bool]) -> list[int]:
    return [m.t_ns for m in transcript.marks if test(m.label)]


def windows(transcript: Transcript) -> list[tuple[int, int]]:
    """Each window's open and close Marks."""
    opens = marks(transcript, lambda label: label.startswith(OBSERVE_OPEN))
    closes = marks(transcript, lambda label: label == OBSERVE_CLOSE)
    return list(zip(opens, closes, strict=True))


def received(transcript: Transcript, bot: str, name: str) -> list[int]:
    """When `bot` received each packet called `name`."""
    return [
        e.t_ns
        for e in transcript.events
        if e.bot == bot and e.packet.direction is Direction.CLIENTBOUND and e.packet.name == name
    ]


def operator_spec() -> ServerSpec:
    return ServerSpec(host="127.0.0.1", port=25566, operators=(WATCHER,))


# Every Group


@pytest.mark.parametrize("group_id", GROUP_IDS)
def test_each_group_is_registered_tick_exact_with_the_watcher_an_operator(group_id: str) -> None:
    group = GROUPS[group_id]

    assert group.kind is GroupKind.TICK_EXACT
    assert group.requires == ()
    assert group.masks == ()
    assert group.spec(ServerSpec(host="127.0.0.1", port=25566)) == operator_spec()
    assert weather.WATCHER == WATCHER


@pytest.mark.timeout(300)
@pytest.mark.parametrize("group_id", GROUP_IDS)
def test_each_group_calms_the_world_freezes_it_and_puts_every_rule_back(group_id: str) -> None:
    result = played(group_id)

    assert result.first == CALM
    assert result.after == UNDO


# weather/commands


@pytest.mark.timeout(300)
def test_commands_rain_thunder_and_clear_each_have_a_command_window_and_a_step_window() -> None:
    result = played("weather/commands")

    assert [w.label for w in result.windows] == [
        opened(SYSTEM_CHAT, GAME_EVENT),
        opened(GAME_EVENT),
    ] * 3


@pytest.mark.timeout(300)
def test_commands_steps_30_ticks_after_rain_30_after_thunder_and_62_after_clear() -> None:
    result = played("weather/commands")

    command_windows, step_windows = result.windows[::2], result.windows[1::2]
    assert [w.sent for w in command_windows] == [
        ((WATCHER, "weather rain 600"),),
        ((WATCHER, "weather thunder 600"),),
        ((WATCHER, "weather clear"),),
    ]
    assert [w.sent for w in step_windows] == [(STEP,) * 30, (STEP,) * 30, (STEP,) * 62]
    assert [w.before for w in result.windows[1:]] == [()] * 5


@pytest.mark.timeout(300)
def test_commands_marks_each_stepped_tick_in_its_own_step_window() -> None:
    transcript, _ = play("weather/commands")

    labels = [m.label for m in transcript.marks if m.label.startswith(TICK_MARK)]
    assert [label for label in labels if " " not in label] == [
        f"{TICK_MARK}{k}" for k in range(1, 123)
    ]
    ticks = marks(transcript, lambda label: label.startswith(TICK_MARK) and " " not in label)
    step_windows = windows(transcript)[1::2]
    assert [sum(o < t < c for t in ticks) for o, c in step_windows] == [30, 30, 62]


@pytest.mark.timeout(300)
def test_commands_wait_in_each_command_window_for_the_watchers_answer() -> None:
    transcript, _ = play("weather/commands")

    answers = received(transcript, WATCHER, SYSTEM_CHAT)
    held = [[t for t in answers if o < t < c] for o, c in windows(transcript)[::2]]
    assert [len(window) for window in held] == [1] * 3


# weather/frozen


@pytest.mark.timeout(300)
def test_frozen_runs_weather_rain_in_a_window_and_then_steps_one_tick_in_another() -> None:
    result = played("weather/frozen")

    assert [w.label for w in result.windows] == [
        opened(SYSTEM_CHAT, GAME_EVENT),
        opened(GAME_EVENT),
    ]
    assert [w.sent for w in result.windows] == [((WATCHER, "weather rain"),), (STEP,)]
    assert result.windows[1].before == ()


@pytest.mark.timeout(300)
def test_frozen_holds_the_window_open_for_the_answer_and_3_set_time_that_follow() -> None:
    transcript, _ = play("weather/frozen")

    (opened_at, closed_at), _ = windows(transcript)
    [said] = [t for t in received(transcript, WATCHER, SYSTEM_CHAT) if opened_at < t < closed_at]
    [command] = [
        e.t_ns
        for e in transcript.events
        if e.bot == WATCHER and (e.packet.fields or {}).get("command") == "weather rain"
    ]
    asks = [
        e.t_ns
        for e in transcript.events
        if e.bot == WATCHER and e.packet.name == CLIENT_COMMAND and e.t_ns > command
    ]
    times = [t for t in received(transcript, WATCHER, SET_TIME) if command < t < asks[0]]
    # a count, not ticks: the fake sends a set_time every 10 ticks, vanilla every 20, so 3 span at
    # least 40 of vanilla's ticks after the command
    assert said < asks[0]
    assert len(times) >= 3
    assert asks[0] < closed_at
