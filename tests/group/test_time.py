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
import time
import uuid
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, field

from support.control import CODEC, text, tree
from support.moves import Play, opened, read

from mscts.bot import SYNC_REQUESTS, offline_uuid
from mscts.case_titles import TITLES
from mscts.codec.packets import Direction, Packet
from mscts.codec.registry_names import registry_names
from mscts.compare import OBSERVE_CLOSE, OBSERVE_OPEN
from mscts.group import GROUPS, GroupContext, GroupKind
from mscts.spec import ServerSpec
from mscts.target import TARGET
from mscts.transcript import Transcript
from tests.net.fakes import NO_STATISTICS, TICK_S, JoinScript, Peer, join_server, serve

CONTROL, CLOCK, SLEEPER = "control", "clock", "sleeper"
MARKER = "tellraw @s "
CHAT_COMMAND, CLIENT_COMMAND = "minecraft:chat_command", "minecraft:client_command"
SYSTEM_CHAT, SET_TIME = "minecraft:system_chat", "minecraft:set_time"
COMMANDS = tree(
    "gamerule",
    "tick",
    "tellraw",
    "time",
    "weather",
    "tp",
    "setblock",
    "fill",
    "advancement",
    "spawnpoint",
    "op",
    "deop",
)
PLAY_TIMEOUT_S = 120.0
"""How long a fake serves a Bot: a whole play."""
TIME_TICKS = 4
"""How many ticks apart the fake sends `set_time` (vanilla: 20)."""
START_GAME_TIME = 500
RUNNING_PACE = 10_000
"""How far the fake's game time moves a second before the freeze: far, so that a Group that read
the game time from a `set_time` sent before the freeze would wait for far too little."""
USE_ITEM_ON = "minecraft:use_item_on"
ANIMATE, INFO_REMOVE = "minecraft:animate", "minecraft:player_info_remove"
PERCENTAGE = "gamerule players_sleeping_percentage "
SKIP_TICKS = 40
"""How many ticks after a player lies down the fake skips the night with 50% needed: longer
than 3 `set_time` and a read, so the read comes before the skip, as on vanilla (100 ticks)."""
DAWN_TICK = 18
"""On which tick of a step the fake gets a sleeper up with 100% needed."""
PLAYER = registry_names(TARGET.minecraft_version, "minecraft:entity_type").index("minecraft:player")
ENTITY_IDS = {"clock": 1, "sleeper": 2}
"""The entity id the fake gives each player but Control."""
STRAYS = ({"entity_id": 99, "action": 0}, {"entity_id": ENTITY_IDS["sleeper"], "action": 1})
"""The `animate`s the fake sends `STRAY_TICKS` before the night is skipped: another entity's
wake, and the sleeper's critical hit (action 1), neither of which is the sleeper getting up."""
STRAY_TICKS = 10
"""Longer than a barrier, so a window that ended on the stray `animate` would miss the skip."""
LATE_TICKS = 5
"""How many ticks the fake takes to answer a player's command, and to tell the others that
Control has left: longer than a barrier, so a window that did not wait for it would miss it."""
ANSWER_LAG_S = TICK_S / 2
"""How much later the sleeper gets each barrier answer than the clock, with
`time_behind_answers`."""


@dataclass
class TimeServer:
    """A fake server that joins like vanilla and keeps a game time.

    The game time moves on `RUNNING_PACE` a second from `START_GAME_TIME` until
    `tick freeze`, and then only by the ticks of each `tick step`, one at a time. Every player
    but Control is sent `set_time` with the game time, and no clock, every `TIME_TICKS` ticks.
    It answers Control's markers, the barrier (a tick apart), and each command of a player but
    Control with a `system_chat`, `LATE_TICKS` later.

    A `use_item_on` lies the player down: every player but Control is told so a tick later.
    With `players_sleeping_percentage` 50 the sleeper gets up `SKIP_TICKS` later, and with 100
    on the 18th tick of a step (`animate`). When Control leaves, the others are told
    (`player_info_remove`), `LATE_TICKS` later.
    """

    seen: list[Packet] = field(default_factory=list)
    players: dict[str, Peer] = field(default_factory=dict)
    started: float = field(default_factory=time.monotonic)
    frozen_at: int | None = None
    """The game time when the world froze, or None while it runs."""
    stepped: int = 0
    percentage: int = 100
    sleeping: bool = False
    clocks: tuple[dict[str, object], ...] = ()
    """The clocks each 20-tick `set_time` carries: none, like vanilla 26.3."""
    time_behind_answers: bool = False
    """Whether the clock reads a `set_time` right behind each barrier answer, before the
    sleeper's answer: so when a window opens, after the later answer, the clock has one queued
    that it read before the open (#454)."""
    time_after_answers: bool = False
    """Whether the clock reads a `set_time` right after each of the sleeper's barrier answers,
    which come `ANSWER_LAG_S` behind the clock's: so when a window opens, after the sleeper's
    answer, the clock reads one inside it before the Group's body runs (#469)."""
    later: set[asyncio.Task[None]] = field(default_factory=set)

    @property
    def game_time(self) -> int:
        if self.frozen_at is None:
            return START_GAME_TIME + int((time.monotonic() - self.started) * RUNNING_PACE)
        return self.frozen_at + self.stepped

    async def __call__(self, peer: Peer) -> None:
        """Serve one connection: a Handler."""
        with suppress(ConnectionError):
            await join_server(self.seen, JoinScript(commands=COMMANDS, then=self._play))(peer)

    async def _play(self, peer: Peer) -> None:
        await self._show(peer.name)
        self.players[peer.name] = peer
        clock = None if peer.name == CONTROL else asyncio.create_task(self._tick(peer))
        requests = 0
        try:
            async for packet in peer.packets():
                self.seen.append(packet)
                if packet.name == CLIENT_COMMAND:
                    requests += 1
                    await self._award_stats(peer, first=(requests - 1) % SYNC_REQUESTS == 0)
                elif packet.name == CHAT_COMMAND:
                    await self._command(peer, str((packet.fields or {})["command"]))
                elif packet.name == USE_ITEM_ON:
                    self.later.add(asyncio.create_task(self._lie_down()))
        finally:
            if clock is not None:
                clock.cancel()
            if peer.name == CONTROL:
                del self.players[CONTROL]
                self.later.add(asyncio.create_task(self._left()))

    async def _award_stats(self, peer: Peer, *, first: bool) -> None:
        """Answer a statistics request: the first of a barrier at once, the others a tick later.

        With `time_behind_answers`, the clock's answer comes in one write with a `set_time`
        behind it, and the sleeper's `ANSWER_LAG_S` later. With `time_after_answers`, the
        sleeper's answer comes `ANSWER_LAG_S` later, and the clock is sent a `set_time` a loop
        turn after it: the clock's socket has it only once the sleeper's reader is due to run,
        so the clock's reader stamps it after the sleeper's answer.
        """
        if not first:
            await asyncio.sleep(TICK_S)  # a barrier's answers come a tick apart
        answer = peer.raw_frame("minecraft:award_stats", NO_STATISTICS)
        lags = self.time_behind_answers or self.time_after_answers
        if lags and peer.name == SLEEPER:
            await asyncio.sleep(ANSWER_LAG_S)
        if self.time_behind_answers and peer.name == CLOCK:
            answer += peer.frame(SET_TIME, game_time=self.game_time, clocks=list(self.clocks))
        await peer.write(answer)
        if self.time_after_answers and peer.name == SLEEPER:
            await asyncio.sleep(0)
            await self._time(self.players[CLOCK])

    async def _time(self, peer: Peer) -> None:
        """Send `peer` a `set_time` with the game time and `clocks`."""
        await peer.send(SET_TIME, game_time=self.game_time, clocks=list(self.clocks))

    async def _show(self, name: str) -> None:
        """Tell every player but Control that player `name` is there (`add_entity`)."""
        if name in ENTITY_IDS:
            await self._everyone(
                "minecraft:add_entity",
                entity_id=ENTITY_IDS[name],
                entity_uuid=offline_uuid(name),
                type=PLAYER,
                x=0.5,
                y=-60.0,
                z=0.5,
                velocity={"scale": 0, "x": 0, "y": 0, "z": 0},
                pitch=0,
                yaw=0,
                head_yaw=0,
                data=0,
            )

    async def _left(self) -> None:
        """Tell the others another player has gone at once, and Control `LATE_TICKS` later."""
        await self._everyone(INFO_REMOVE, uuids=[uuid.UUID(int=99)])
        await asyncio.sleep(LATE_TICKS * TICK_S)
        await self._everyone(INFO_REMOVE, uuids=[offline_uuid(CONTROL)])

    async def _command(self, peer: Peer, command: str) -> None:
        if command.startswith(MARKER):
            token = json.loads(command.removeprefix(MARKER))
            await peer.send(SYSTEM_CHAT, content=text(token), overlay=False)
        elif command == "tick freeze":
            self.frozen_at = self.game_time
        elif command.startswith("tick step "):
            self.later.add(asyncio.create_task(self._step(int(command.rsplit(maxsplit=1)[-1]))))
        elif command.startswith(PERCENTAGE):
            self.percentage = int(command.removeprefix(PERCENTAGE))
        elif peer.name != CONTROL:
            self.later.add(asyncio.create_task(self._answer(peer, command)))

    async def _everyone(self, name: str, /, **fields: object) -> None:
        """Send packet `name` to every player but Control."""
        with suppress(ConnectionError):
            for player, peer in tuple(self.players.items()):
                if player != CONTROL:
                    await peer.send(name, **fields)

    async def _lie_down(self) -> None:
        await asyncio.sleep(TICK_S)
        self.sleeping = True
        await self._everyone(SYSTEM_CHAT, content=text("sleeping"), overlay=True)
        if self.percentage == 50:
            await asyncio.sleep((SKIP_TICKS - STRAY_TICKS) * TICK_S)
            for stray in STRAYS:
                await self._everyone(ANIMATE, **stray)
            await asyncio.sleep(STRAY_TICKS * TICK_S)
            await self._get_up()

    async def _get_up(self) -> None:
        self.sleeping = False
        await self._everyone(ANIMATE, entity_id=ENTITY_IDS[SLEEPER], action=0)

    async def _step(self, ticks: int) -> None:
        for tick in range(1, ticks + 1):
            await asyncio.sleep(TICK_S)
            self.stepped += 1
            if self.sleeping and tick == DAWN_TICK:
                await self._get_up()

    async def _answer(self, peer: Peer, command: str) -> None:
        await asyncio.sleep(LATE_TICKS * TICK_S)
        with suppress(ConnectionError):
            await peer.send(SYSTEM_CHAT, content=text(command), overlay=False)

    async def _tick(self, peer: Peer) -> None:
        with suppress(ConnectionError):
            while True:  # the first as the player enters play, before any freeze
                await self._time(peer)
                await asyncio.sleep(TIME_TICKS * TICK_S)


async def _play(group_id: str, server: TimeServer) -> Transcript:
    transcript = Transcript(group_id=group_id, server="fake")
    async with serve(CODEC, server, timeout_s=PLAY_TIMEOUT_S) as endpoint:
        context = GroupContext(endpoint, transcript, timeout_s=10.0)
        try:
            await GROUPS[group_id].run(context)
        finally:
            await context.close()
    return transcript


FROZEN_AT: dict[str, int] = {}
"""The fake's game time when each Group played froze the world."""


OVERWORLD: dict[str, object] = {"clock": 0, "total_ticks": 0, "partial_tick": 0.0, "rate": 1.0}
"""A clock in a 20-tick `set_time`, as a server that also sends the time of day there would."""


@functools.cache
def play(group_id: str, *, clocked: bool = False) -> tuple[Transcript, Play]:
    """Play `group_id` against a fake server once; its Transcript and what was read from it.

    With `clocked`, each 20-tick `set_time` carries the overworld clock.
    """
    server = TimeServer(clocks=(OVERWORLD,) if clocked else ())
    transcript = asyncio.run(_play(group_id, server))
    assert server.frozen_at is not None
    if not clocked:
        FROZEN_AT[group_id] = server.frozen_at
    return transcript, read(transcript)


def played(group_id: str) -> Play:
    return play(group_id)[1]


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
    "gamerule advance_weather false",
    "weather clear",
)
"""Not `spawn_mobs`: the Fixture world has it off (ADR-0013), and setting it back to vanilla's
default after a play would let animals spawn in every later play."""
UNCALM = (
    "gamerule advance_weather true",
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
    targets = [FROZEN_AT["time/advance"] + sum((1, 20, 100, 1, 20, 100)[: k + 1]) for k in range(6)]
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


def test_commands_wait_in_each_window_for_the_answer() -> None:
    transcript, _ = play("time/commands")

    answers = [t for t, _ in received(transcript, CLOCK, SYSTEM_CHAT)]
    held = [[t for t in answers if o < t < c] for o, c in windows(transcript)]
    assert [len(window) for window in held] == [1] * 16


# time/sleep

SLEEP = (SYSTEM_CHAT, ANIMATE, "minecraft:set_entity_data", "minecraft:game_event")
READ_DAY = ((CLOCK, "time query day"), (CLOCK, "time query day repetition"))
AT_MIDNIGHT = ("time set 18000", "tp sleeper 0.5 -60 0.5 -90 0")


def sent(transcript: Transcript, bot: str, name: str) -> list[tuple[int, Packet]]:
    return [
        (e.t_ns, e.packet)
        for e in transcript.events
        if e.bot == bot and e.packet.direction is Direction.SERVERBOUND and e.packet.name == name
    ]


def windows(transcript: Transcript) -> list[tuple[int, int]]:
    """Each window's open and close Marks."""
    opens = marks(transcript, lambda label: label.startswith(OBSERVE_OPEN))
    closes = marks(transcript, lambda label: label == OBSERVE_CLOSE)
    return list(zip(opens, closes, strict=True))


def test_sleep_is_registered_exact_with_the_clock_an_operator() -> None:
    group = GROUPS["time/sleep"]

    assert group.kind is GroupKind.EXACT
    assert group.requires == ()
    assert group.masks == ()
    assert group.spec(ServerSpec(host="127.0.0.1", port=25566)) == operator_spec()


def test_sleep_sets_a_bed_and_takes_it_and_every_rule_back() -> None:
    result = played("time/sleep")

    assert result.first == (
        *CALM,
        "tick freeze",
        "setblock 2 -60 0 minecraft:red_bed[part=foot,facing=east]",
        "setblock 3 -60 0 minecraft:red_bed[part=head,facing=east]",
        "advancement revoke sleeper only minecraft:adventure/sleep_in_bed",
        "spawnpoint sleeper 0 -60 0",
        "gamerule players_sleeping_percentage 100",
        *AT_MIDNIGHT,
    )
    assert result.after == (
        "gamerule players_sleeping_percentage 100",
        "fill 2 -60 0 3 -60 0 minecraft:air strict",
        "tp sleeper 0.5 -60 0.5",
        "tp clock 0.5 -60 0.5",
        *UNCALM,
        "tick unfreeze",
    )


def test_sleep_lies_down_at_midnight_with_100_then_50_percent_needed() -> None:
    transcript, result = play("time/sleep")

    assert [window.label for window in result.windows] == [
        opened(*SLEEP),
        opened(SYSTEM_CHAT),
        opened(*SLEEP),
        opened(SYSTEM_CHAT),
        opened(*SLEEP),
        opened(SYSTEM_CHAT),
        opened(*SLEEP),
        opened(SYSTEM_CHAT),
    ]
    lie_100, read_100, dawn, read_dawn, lie_50, before_skip, skip, read_50 = result.windows
    # no command in the lie-down windows; a move is the sleeper's tick reporting where it is
    assert [what for _, what in lie_100.sent + lie_50.sent if isinstance(what, str)] == []
    assert [what for _, what in skip.sent if isinstance(what, str)] == []
    assert before_skip.sent == ((CLOCK, "time query day"),)
    assert (read_100.sent, read_dawn.sent, read_50.sent) == (READ_DAY,) * 3
    # the clock is no operator while Control steps, so it hears no admin chat in the window
    assert dawn.before == ("time set 23460", "deop clock")
    assert dawn.sent == ((CONTROL, "tick step 40"),)
    assert read_dawn.before == ("op clock",)
    assert lie_50.before == ("gamerule players_sleeping_percentage 50", *AT_MIDNIGHT)
    uses = sent(transcript, SLEEPER, "minecraft:use_item_on")
    foot_from_above = ({"x": 2, "y": -60, "z": 0}, 1)  # Face.UP
    assert [((p.fields or {})["pos"], (p.fields or {})["face"]) for _, p in uses] == [
        foot_from_above
    ] * 2
    lain = [t for t, _ in uses]
    lie_windows = [windows(transcript)[k] for k in (0, 4)]
    assert len(lain) == 2
    assert all(o < t < c for t, (o, c) in zip(lain, lie_windows, strict=True))


def test_sleep_leaves_the_two_bots_alone_in_the_world_for_each_lie_down() -> None:
    transcript, _ = play("time/sleep")

    control = offline_uuid(CONTROL)
    removed = [
        t
        for t, p in received(transcript, CLOCK, INFO_REMOVE)
        if (p.fields or {})["uuids"] == [control]
    ]
    by_control = [
        e.t_ns
        for e in transcript.events
        if e.bot == CONTROL and e.packet.direction is Direction.SERVERBOUND
    ]
    lie_windows = [windows(transcript)[k] for k in (0, 4)]
    assert len(removed) == 2
    for gone, (opened_at, closed_at) in zip(removed, lie_windows, strict=True):
        assert gone < opened_at
        assert not [t for t in by_control if gone < t < closed_at]


def test_sleep_with_100_percent_waits_for_7_set_time_inside_the_lie_down_window() -> None:
    transcript, _ = play("time/sleep")

    opened_at, closed_at = windows(transcript)[0]
    [said] = [t for t, _ in received(transcript, CLOCK, SYSTEM_CHAT) if opened_at < t < closed_at]
    lain = sent(transcript, SLEEPER, "minecraft:use_item_on")[0][0]
    times = [t for t, _ in received(transcript, CLOCK, SET_TIME) if opened_at <= t < closed_at]
    assert lain < said
    # a count, not ticks: the fake sends a set_time every TIME_TICKS ticks, vanilla every 20, so
    # 7 span 24 of the fake's ticks after the first, and 120 of vanilla's
    assert len(times) >= 7


def test_sleep_counts_only_the_set_time_the_clock_read_inside_each_lie_down_window() -> None:
    # the clock reads a set_time after its barrier's answer but before the window opens
    transcript = asyncio.run(_play("time/sleep", TimeServer(time_behind_answers=True)))

    asks = [t for t, _ in sent(transcript, CLOCK, CLIENT_COMMAND)]
    times = [t for t, _ in received(transcript, CLOCK, SET_TIME)]
    for k, count in ((0, 7), (4, 3)):
        opened_at, _ = windows(transcript)[k]
        closing = min(t for t in asks if t > opened_at)  # the clock's barrier at the close
        assert len([t for t in times if opened_at <= t < closing]) >= count


def test_sleep_counts_a_set_time_the_clock_read_after_the_open_before_the_lie_down() -> None:
    # the clock reads a set_time after the sleeper's barrier answer, before the body runs
    transcript = asyncio.run(_play("time/sleep", TimeServer(time_after_answers=True)))

    asks = [t for t, _ in sent(transcript, CLOCK, CLIENT_COMMAND)]
    lain = [t for t, _ in sent(transcript, SLEEPER, USE_ITEM_ON)]
    times = [t for t, _ in received(transcript, CLOCK, SET_TIME)]
    for k, at, count in ((0, lain[0], 7), (4, lain[1], 3)):
        opened_at, _ = windows(transcript)[k]
        closing = min(t for t in asks if t > opened_at)  # the clock's barrier at the close
        assert [t for t in times if opened_at <= t < at]  # the case the fake makes
        assert len([t for t in times if opened_at <= t < closing]) == count


def test_sleep_steps_to_dawn_until_a_set_time_shows_the_step_ended() -> None:
    transcript, _ = play("time/sleep")

    opened_at, closed_at = windows(transcript)[2]
    times = received(transcript, CLOCK, SET_TIME)
    assert any(
        opened_at < t < closed_at and game_time(p) >= FROZEN_AT["time/sleep"] + 40 for t, p in times
    )


def test_sleep_with_50_percent_reads_the_day_before_the_skip_then_waits_for_it() -> None:
    transcript, _ = play("time/sleep")

    lie_50, before_skip, skip = windows(transcript)[4:7]
    animates = [t for t, _ in received(transcript, CLOCK, ANIMATE)]
    lain = sent(transcript, SLEEPER, "minecraft:use_item_on")[1][0]
    in_lie = [t for t, _ in received(transcript, CLOCK, SET_TIME) if lain < t < lie_50[1]]
    assert len(in_lie) >= 3
    assert not [t for t in animates if lie_50[0] < t < before_skip[1]]
    woke = [
        t
        for t, p in received(transcript, CLOCK, ANIMATE)
        if p.fields == {"entity_id": ENTITY_IDS[SLEEPER], "action": 0}
    ]
    assert [t for t in woke if skip[0] < t < skip[1]]


def test_a_set_time_that_carries_a_clock_ends_each_wait_as_one_without() -> None:
    for group_id in ("time/advance", "time/sleep"):
        plain = [w.label for w in play(group_id)[1].windows]
        clocked = [w.label for w in play(group_id, clocked=True)[1].windows]
        assert clocked == plain


BED_AT = (
    "set_entity_data.entries[].value.x",
    "set_entity_data.entries[].value.y",
    "set_entity_data.entries[].value.z",
)
"""The test cases a sleeping player's bed adds to a Report (a Pumpkin run of time/sleep)."""


def test_each_test_case_of_a_sleeping_players_bed_has_a_title() -> None:
    assert all(name in TITLES for name in BED_AT)
