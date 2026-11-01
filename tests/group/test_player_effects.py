"""The potion effect Groups: what Control gives, what each window waits for, and what is undone.

Every test reads one play of a Group against a fake server: Control's commands, what each Bot
sent and read in each window, and the Marks (the Observation windows). What a server answers is
never asserted: the fake answers Control's markers, the barrier and a respawn request, and
sends just what a Group waits for. It ends each effect `EFFECT_TICKS` ticks after the give, and
sends every player `set_time` every `TIME_TICKS` ticks (vanilla: 20).
"""

import asyncio
from contextlib import suppress
from dataclasses import dataclass, field
from typing import override

import pytest
from support.bot_join import ENTITY_ID, LOGIN
from support.control import CLIENT_COMMAND, CONTROL, playing, tree
from support.control_play import Play, read
from support.player_server import PERFORM_RESPAWN, PlayerServer
from support.window import window_since

from mscts.bot import SYNC_REQUESTS
from mscts.codec.packets import Direction
from mscts.compare import OBSERVE_OPEN
from mscts.group import GROUPS, GroupKind
from mscts.groups import player_effects
from mscts.spec import Difficulty, ServerSpec
from mscts.transcript import Event, Transcript
from tests.net.fakes import TICK_S, JoinScript, Peer, join_server

EFFECTED = "effected"
REMOVED = "minecraft:remove_mob_effect"
SET_TIME = "minecraft:set_time"
RESPAWN_ASKED = {"action": PERFORM_RESPAWN}
COMMANDS = tree("gamerule", "tp", "tick", "effect", "kill", "tellraw", "damage", "summon")
EFFECT_TICKS = 5
"""How many ticks after it is given the fake ends an effect: longer than a barrier, so a window
that closed without waiting for the end would not hold it."""
TIME_TICKS = 10
"""How many ticks apart the fake sends `set_time`."""


def _login(peer: Peer) -> bytes:
    return peer.frame("minecraft:login", **LOGIN)


@dataclass
class EffectServer(PlayerServer):
    """A fake player server that ends every effect it is given, `EFFECT_TICKS` ticks later."""

    later: set[asyncio.Task[None]] = field(default_factory=set)
    """The ends of the effects still to be sent."""

    @override
    async def __call__(self, peer: Peer) -> None:
        """Serve one connection: a Handler, with the command tree of these Groups."""
        script = JoinScript(commands=COMMANDS, after_batch=_login, then=self._play)
        with suppress(ConnectionError):
            await join_server(self.seen, script)(peer)

    @override
    async def _play(self, peer: Peer) -> None:
        clock = asyncio.create_task(self._tick(peer))
        try:
            await super()._play(peer)
        finally:
            clock.cancel()

    async def _tick(self, peer: Peer) -> None:
        with suppress(ConnectionError):
            while True:
                await asyncio.sleep(TIME_TICKS * TICK_S)
                await peer.write(peer.raw_frame(SET_TIME, bytes(9)))

    @override
    async def _command(self, peer: Peer, command: str) -> None:
        words = command.split()
        if words[:2] == ["effect", "give"]:
            self.later.add(asyncio.create_task(self._end(words[2])))
        else:
            await super()._command(peer, command)

    async def _end(self, name: str) -> None:
        """Tell the player `name` its effect has ended, `EFFECT_TICKS` ticks after the give."""
        await asyncio.sleep(EFFECT_TICKS * TICK_S)
        with suppress(ConnectionError):
            await self.players[name].send(REMOVED, entity_id=ENTITY_ID, effect=0)


async def _play(group_id: str, server: EffectServer) -> tuple[Transcript, Play]:
    transcript = Transcript(group_id=group_id, server="fake")
    async with playing(server, transcript, timeout_s=10.0) as context:
        await GROUPS[group_id].run(context)
    return transcript, read(transcript)


_PLAYS: dict[str, tuple[Transcript, Play]] = {}
"""Each Group's play against a default fake server; no test changes it."""


def replay(group_id: str, server: EffectServer) -> tuple[Transcript, Play]:
    """Play `group_id` against `server`, which a test that needs its own fake supplies."""
    return asyncio.run(_play(group_id, server))


def play(group_id: str) -> tuple[Transcript, Play]:
    """The play of `group_id` against a default fake server, played the first time it is asked."""
    if group_id not in _PLAYS:
        _PLAYS[group_id] = replay(group_id, EffectServer())
    return _PLAYS[group_id]


pytestmark = [pytest.mark.timeout(300), pytest.mark.usefixtures("long_play")]


def in_windows(transcript: Transcript, bot: str) -> list[list[Event]]:
    """What `bot` sent and read in each window, in order."""
    opens = sorted(
        mark.t_ns for mark in transcript.marks if mark.label.split(" ", 1)[0] == OBSERVE_OPEN
    )
    return [window_since(transcript, bot, opened) for opened in opens]


def assert_each_window_waits_for_the_end_and_one_barrier(transcript: Transcript, bot: str) -> None:
    """Check that `bot` sent two barriers' requests after it read the end in every window.

    A hidden effect's last `update_attributes` comes 2 ticks after the end: one barrier of its
    own, then the window's, so that it is never between the closing barrier's answers.
    """
    for events in in_windows(transcript, bot):
        names = [event.packet.name for event in events]
        assert names[names.index(REMOVED) + 1 :].count(CLIENT_COMMAND) == 2 * SYNC_REQUESTS


def command_times(transcript: Transcript, command: str) -> list[int]:
    """When Control sent `command`."""
    return [
        e.t_ns
        for e in transcript.events
        if e.bot == CONTROL
        and e.packet.direction is Direction.SERVERBOUND
        and (e.packet.fields or {}).get("command") == command
    ]


def requests_times(transcript: Transcript, bot: str) -> list[int]:
    """When `bot` sent a `client_command` that is not a respawn request."""
    return [
        e.t_ns
        for e in transcript.events
        if e.bot == bot
        and e.packet.direction is Direction.SERVERBOUND
        and e.packet.name == CLIENT_COMMAND
        and e.packet.fields != RESPAWN_ASKED
    ]


def respawn_times(transcript: Transcript, bot: str) -> list[int]:
    """When `bot` asked to respawn."""
    return [
        e.t_ns
        for e in transcript.events
        if e.bot == bot
        and e.packet.direction is Direction.SERVERBOUND
        and e.packet.name == CLIENT_COMMAND
        and e.packet.fields == RESPAWN_ASKED
    ]


def read_times(transcript: Transcript, bot: str, name: str) -> list[int]:
    """When `bot` took a packet called `name`."""
    return [
        e.t_ns
        for e in transcript.events
        if e.bot == bot and e.packet.direction is Direction.CLIENTBOUND and e.packet.name == name
    ]


def opened(*names: str) -> str:
    """The label of the Mark that opens a window comparing `names`."""
    return " ".join((OBSERVE_OPEN, *names))


PACKETS = (
    "minecraft:update_mob_effect",
    "minecraft:remove_mob_effect",
    "minecraft:update_attributes",
    "minecraft:set_entity_data",
    "minecraft:set_health",
    "minecraft:damage_event",
)
KINDS = {"player/effect-attributes": GroupKind.EXACT, "player/effect-ticking": GroupKind.EXACT}
"""Each Group's kind: exact when every window is the Bot's, which a frozen world does not
freeze, and tick-exact when a window steps a mob."""
SET_UP = (
    "gamerule player_movement_check false",
    "gamerule respawn_radius 0",
    "gamerule natural_health_regeneration false",
    "tp control 96.5 -60 96.5",
)
"""What Control does before a Bot joins, in order: pin the join, stop healing, move away."""
UNDO = (
    "gamerule natural_health_regeneration true",
    "gamerule respawn_radius 10",
    "gamerule player_movement_check true",
    "tick unfreeze",
)
"""What Control undoes last, in order."""


# Registration


def test_the_windows_compare_the_effects_the_attributes_the_entity_data_and_the_health() -> None:
    assert player_effects.PACKETS == PACKETS


@pytest.mark.parametrize(("group_id", "kind"), list(KINDS.items()))
def test_each_group_is_registered_needs_nothing_masks_nothing_and_plays_on_normal_difficulty(
    group_id: str, kind: GroupKind
) -> None:
    group = GROUPS[group_id]
    default = ServerSpec(host="127.0.0.1", port=25566)

    assert group.kind is kind
    assert group.requires == ()
    assert group.masks == ()
    assert group.spec(default) == ServerSpec(
        host="127.0.0.1", port=25566, difficulty=Difficulty.NORMAL
    )


# `player/effect-attributes`

ATTRIBUTES = "player/effect-attributes"
EFFECTS = (
    ("speed", 0),
    ("speed", 1),
    ("slowness", 0),
    ("strength", 0),
    ("haste", 0),
    ("jump_boost", 0),
)
GIVES = [
    f"effect give {EFFECTED} minecraft:{name} 1 {amplifier} {hide}"
    for hide in ("true", "false")
    for name, amplifier in EFFECTS
]
"""Each effect for 1 s, with its particles hidden, then shown."""


def test_attributes_stops_healing_pins_the_join_and_freezes_the_world_after_the_bot_joins() -> None:
    transcript, result = play(ATTRIBUTES)

    assert result.first == (*SET_UP, "tick freeze")
    joined = next(
        e.t_ns
        for e in transcript.events
        if e.bot == EFFECTED and e.packet.name == "minecraft:hello"
    )
    freezes = [
        e.t_ns for e in transcript.events if (e.packet.fields or {}).get("command") == "tick freeze"
    ]
    assert joined < freezes[0]


def test_attributes_puts_the_bot_back_at_the_spawn_after_clearing_its_effects() -> None:
    result = play(ATTRIBUTES)[1]

    assert result.after == (f"effect clear {EFFECTED}", f"tp {EFFECTED} 0.5 -60 0.5", *UNDO)


def test_attributes_gives_six_effects_with_the_particles_hidden_then_shown_a_window_each() -> None:
    result = play(ATTRIBUTES)[1]

    assert [window.label for window in result.windows] == [opened(*PACKETS)] * 12
    assert [window.commands for window in result.windows] == [(give,) for give in GIVES]
    assert [window.before for window in result.windows][1:] == [()] * 11


def test_attributes_ends_each_window_one_barrier_after_the_bot_reads_the_effect_end() -> None:
    transcript = play(ATTRIBUTES)[0]

    assert len(in_windows(transcript, EFFECTED)) == 12
    assert_each_window_waits_for_the_end_and_one_barrier(transcript, EFFECTED)


# `player/effect-ticking`

TICKING = "player/effect-ticking"
TICKED = "ticked"
TICKING_EFFECTS = (
    ("regeneration", 0),
    ("regeneration", 1),
    ("poison", 0),
    ("poison", 1),
    ("wither", 0),
)
TICKING_GIVES = [
    f"effect give {TICKED} minecraft:{name} 5 {amplifier} true"
    for name, amplifier in TICKING_EFFECTS
]
"""Each effect for 5 s (100 ticks), with its particles hidden."""
HURT = f"damage {TICKED} 14.0 minecraft:generic"
"""What takes a fresh Bot from 20 health to 6."""


def test_ticking_hurts_a_fresh_bot_before_the_window_and_clears_its_effects_after() -> None:
    result = play(TICKING)[1]

    assert result.first == (*SET_UP, "tick freeze", f"kill {TICKED}", HURT)
    assert result.after == (f"effect clear {TICKED}", f"tp {TICKED} 0.5 -60 0.5", *UNDO)


def test_ticking_gives_five_effects_to_a_bot_at_6_health_a_window_each() -> None:
    result = play(TICKING)[1]

    assert [window.label for window in result.windows] == [opened(*PACKETS)] * 5
    assert [window.commands for window in result.windows] == [(give,) for give in TICKING_GIVES]
    assert [window.before for window in result.windows][1:] == [(f"kill {TICKED}", HURT)] * 4


def test_ticking_hurts_the_bot_once_it_is_loaded_and_gives_the_effect_after_two_set_times() -> None:
    transcript = play(TICKING)[0]

    respawns = respawn_times(transcript, TICKED)
    handled = requests_times(transcript, TICKED)
    hurts = command_times(transcript, HURT)
    times = read_times(transcript, TICKED, SET_TIME)
    gives = [t for give in TICKING_GIVES for t in command_times(transcript, give)]
    assert len(respawns) == len(hurts) == len(gives) == 5
    for respawn, hurt, give in zip(respawns, hurts, gives, strict=True):
        # a respawned player ignores damage until its player_loaded is read (#57)
        assert any(respawn < t < hurt for t in handled)
        # the hit's 10 ticks of immunity are over by the second `set_time`, 20 ticks or more on
        assert sum(hurt < t < give for t in times) == 2


def test_ticking_ends_each_window_one_barrier_after_the_bot_reads_the_effect_end() -> None:
    transcript = play(TICKING)[0]

    assert len(in_windows(transcript, TICKED)) == 5
    assert_each_window_waits_for_the_end_and_one_barrier(transcript, TICKED)
