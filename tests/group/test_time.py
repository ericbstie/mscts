"""The time Groups: what Control sets up, what each window holds, and what is undone after.

Every test plays a Group against a fake server once and reads the Transcript for what each Bot
sent (the commands) and the Marks (the Observation windows). What a server answers is never
asserted: the fake answers Control's markers, the barrier and the clock's commands, sends every
player but Control a `set_time` with the game time every `TIME_TICKS` ticks, and moves the game
time on by the ticks of each `tick step`.
"""

import asyncio
import functools
import json
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, field

from mscts.bot import SYNC_REQUESTS
from mscts.codec.packets import Direction, Packet
from mscts.compare import OBSERVE_OPEN
from mscts.group import GROUPS, GroupContext, GroupKind
from mscts.spec import ServerSpec
from mscts.transcript import Transcript
from tests.group.test_control import CODEC, text, tree
from tests.group.test_movement import Play, read
from tests.net.fakes import NO_STATISTICS, TICK_S, JoinScript, Peer, join_server, serve

CONTROL, CLOCK = "control", "clock"
MARKER = "tellraw @s "
CHAT_COMMAND, CLIENT_COMMAND = "minecraft:chat_command", "minecraft:client_command"
SYSTEM_CHAT, SET_TIME = "minecraft:system_chat", "minecraft:set_time"
COMMANDS = tree("gamerule", "tick", "tellraw", "time", "weather", "tp")
PLAY_TIMEOUT_S = 120.0
"""How long a fake serves a Bot: a whole play."""
TIME_TICKS = 4
"""How many ticks apart the fake sends `set_time` (vanilla: 20)."""
START_GAME_TIME = 500


@dataclass
class TimeServer:
    """A fake server that joins like vanilla and keeps a game time that only steps move.

    It answers Control's markers, the barrier (a tick apart), and each command of a player but
    Control with a `system_chat` a tick later. `tick step N` moves the game time on by N a tick
    at a time. Every player but Control is sent `set_time` with the game time, and no clock,
    every `TIME_TICKS` ticks.
    """

    seen: list[Packet] = field(default_factory=list)
    players: dict[str, Peer] = field(default_factory=dict)
    game_time: int = START_GAME_TIME
    sent_times: dict[str, list[int]] = field(default_factory=dict)
    """The game time of each `set_time` sent, by player."""
    later: set[asyncio.Task[None]] = field(default_factory=set)

    async def __call__(self, peer: Peer) -> None:
        """Serve one connection: a Handler."""
        with suppress(ConnectionError):
            await join_server(self.seen, JoinScript(commands=COMMANDS, then=self._play))(peer)

    async def _play(self, peer: Peer) -> None:
        self.players[peer.name] = peer
        clock = None if peer.name == CONTROL else asyncio.create_task(self._tick(peer))
        requests = 0
        try:
            async for packet in peer.packets():
                self.seen.append(packet)
                if packet.name == CLIENT_COMMAND:
                    requests += 1
                    if (requests - 1) % SYNC_REQUESTS != 0:
                        await asyncio.sleep(TICK_S)  # a barrier's answers come a tick apart
                    await peer.write(peer.raw_frame("minecraft:award_stats", NO_STATISTICS))
                elif packet.name == CHAT_COMMAND:
                    await self._command(peer, str((packet.fields or {})["command"]))
        finally:
            if clock is not None:
                clock.cancel()

    async def _command(self, peer: Peer, command: str) -> None:
        if command.startswith(MARKER):
            token = json.loads(command.removeprefix(MARKER))
            await peer.send(SYSTEM_CHAT, content=text(token), overlay=False)
        elif command.startswith("tick step "):
            self.later.add(asyncio.create_task(self._step(int(command.rsplit(maxsplit=1)[-1]))))
        elif peer.name != CONTROL:
            self.later.add(asyncio.create_task(self._answer(peer, command)))

    async def _step(self, ticks: int) -> None:
        for _ in range(ticks):
            await asyncio.sleep(TICK_S)
            self.game_time += 1

    async def _answer(self, peer: Peer, command: str) -> None:
        await asyncio.sleep(TICK_S)
        with suppress(ConnectionError):
            await peer.send(SYSTEM_CHAT, content=text(command), overlay=False)

    async def _tick(self, peer: Peer) -> None:
        with suppress(ConnectionError):
            while True:
                await asyncio.sleep(TIME_TICKS * TICK_S)
                self.sent_times.setdefault(peer.name, []).append(self.game_time)
                await peer.send(SET_TIME, game_time=self.game_time, clocks=[])


async def _play(group_id: str, server: TimeServer) -> Transcript:
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
    transcript = asyncio.run(_play(group_id, TimeServer()))
    return transcript, read(transcript)


def played(group_id: str) -> Play:
    return play(group_id)[1]


def opened(*names: str) -> str:
    return f"{OBSERVE_OPEN} {' '.join(names)}"


def marks(transcript: Transcript, test: Callable[[str], bool]) -> list[int]:
    return [m.t_ns for m in transcript.marks if test(m.label)]


def received(transcript: Transcript, bot: str, name: str) -> list[tuple[int, Packet]]:
    return [
        (e.t_ns, e.packet)
        for e in transcript.events
        if e.bot == bot and e.packet.direction is Direction.CLIENTBOUND and e.packet.name == name
    ]


def game_time(packet: Packet) -> int:
    value = (packet.fields or {})["game_time"]
    assert isinstance(value, int)
    return value


def operator_spec() -> ServerSpec:
    return ServerSpec(host="127.0.0.1", port=25566, operators=(CLOCK,))


CALM = (
    "gamerule player_movement_check false",
    "gamerule respawn_radius 0",
    "gamerule spawn_mobs false",
    "gamerule advance_weather false",
    "weather clear",
)
UNCALM = (
    "gamerule advance_weather true",
    "gamerule spawn_mobs true",
    "gamerule respawn_radius 10",
    "gamerule player_movement_check true",
)


# time/advance


def test_advance_is_registered_tick_exact_with_the_clock_an_operator() -> None:
    group = GROUPS["time/advance"]

    assert group.kind is GroupKind.TICK_EXACT
    assert group.requires == ()
    assert group.masks == ()
    assert group.spec(ServerSpec(host="127.0.0.1", port=25566)) == operator_spec()


def test_advance_calms_the_world_freezes_it_and_puts_every_rule_back() -> None:
    result = played("time/advance")

    assert result.first == (
        *CALM,
        "tick freeze",
        "gamerule advance_time true",
        "time set 1000",
        "tick step 1",
    )
    assert result.after == (
        "gamerule advance_time true",
        "tp clock 0.5 -60 0.5",
        *UNCALM,
        "tick unfreeze",
    )


def test_advance_reads_the_day_after_each_step_with_advance_time_true_then_false() -> None:
    result = played("time/advance")

    assert [window.label for window in result.windows] == [opened(SYSTEM_CHAT)] * 6
    assert [window.sent for window in result.windows] == [((CLOCK, "time query day"),)] * 6
    befores = [window.before for window in result.windows]
    assert befores[1:] == [
        ("tick step 20",),
        ("tick step 100",),
        ("gamerule advance_time false", "time set 1000", "tick step 1"),
        ("tick step 20",),
        ("tick step 100",),
    ]


def test_advance_opens_each_window_once_a_set_time_shows_the_step_has_ended() -> None:
    transcript, _ = play("time/advance")

    opens = marks(transcript, lambda label: label.startswith(OBSERVE_OPEN))
    times = received(transcript, CLOCK, SET_TIME)
    targets = [START_GAME_TIME + sum((1, 20, 100, 1, 20, 100)[: k + 1]) for k in range(6)]
    for opened_at, target in zip(opens, targets, strict=True):
        assert any(t < opened_at and game_time(packet) >= target for t, packet in times)


# time/commands

TIME_COMMANDS = (
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


def test_commands_is_registered_exact_with_the_clock_an_operator() -> None:
    group = GROUPS["time/commands"]

    assert group.kind is GroupKind.EXACT
    assert group.requires == ()
    assert group.masks == ()
    assert group.spec(ServerSpec(host="127.0.0.1", port=25566)) == operator_spec()


def test_commands_start_from_a_frozen_clock_at_0_and_put_every_rule_back() -> None:
    result = played("time/commands")

    assert result.first == (*CALM, "tick freeze", "time set 0")
    assert result.after == ("tp clock 0.5 -60 0.5", *UNCALM, "tick unfreeze")


def test_commands_run_each_time_command_as_the_clock_in_a_window_of_its_own() -> None:
    result = played("time/commands")

    assert [window.label for window in result.windows] == [opened(SYSTEM_CHAT)] * 16
    assert [window.sent for window in result.windows] == [
        ((CLOCK, command),) for command in TIME_COMMANDS
    ]
    assert [window.before for window in result.windows][1:] == [()] * 15
