"""The potion effect Groups: what Control gives, what each window waits for, and what is undone.

Every test reads one play of a Group against a fake server: Control's commands, what each Bot
sent and read in each window, and the Marks (the Observation windows). What a server answers is
never asserted: the fake answers Control's markers, the barrier and a respawn request, and
sends just what a Group waits for. It ends each effect `EFFECT_TICKS` ticks after the give, and
sends every player `set_time` every `TIME_TICKS` ticks (vanilla: 20).
"""

import asyncio
import uuid
from contextlib import suppress
from dataclasses import dataclass, field
from typing import override

import pytest
from support.bot_join import ENTITY_ID, LOGIN
from support.control import CLIENT_COMMAND, CONTROL, playing, tree
from support.control_play import Play, read
from support.mobs import PLAYER, ZOMBIE
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
WATCHER, SEEN = "watcher", "seen"
REMOVED = "minecraft:remove_mob_effect"
SET_TIME = "minecraft:set_time"
RESPAWN_ASKED = {"action": PERFORM_RESPAWN}
COMMANDS = tree("gamerule", "tp", "tick", "effect", "kill", "tellraw", "damage", "summon")
EFFECT_TICKS = 5
"""How many ticks after it is given the fake ends an effect: longer than a barrier, so a window
that closed without waiting for the end would not hold it."""
TIME_TICKS = 10
"""How many ticks apart the fake sends `set_time`."""
HEALTH_LATE_TICKS = 6
"""How many ticks after it ends an instant effect the fake sends the health: more than two
barriers, so a window that closed at the barrier after the end alone would not hold it."""
ZOMBIE_LATE_TICKS = 4
"""How many ticks after the summon the fake tells the players of the zombie: more than a window's
opening barrier, so a window that opened without waiting to be told of it would hold the news."""
ZOMBIE_TAG = "mscts_effected"
ZOMBIE_ID = 500
CORPSE_TICKS = 20
"""How many ticks after a kill the fake removes the zombie, as vanilla removes a corpse."""


def _login(peer: Peer) -> bytes:
    return peer.frame("minecraft:login", **LOGIN)


def _entity(type_id: int, x: float, y: float, z: float) -> dict[str, object]:
    """The fields of an `add_entity` for an entity of type `type_id` at x, y, z.

    The entity gets the id of the zombie, or of the player that vanilla's `login` names.
    """
    entity_id = ENTITY_ID if type_id == PLAYER else ZOMBIE_ID
    return {
        "entity_id": entity_id,
        "entity_uuid": uuid.UUID(int=entity_id),
        "type": type_id,
        "x": x,
        "y": y,
        "z": z,
        "velocity": {"scale": 0, "x": 0, "y": 0, "z": 0},
        "pitch": 0,
        "yaw": 0,
        "head_yaw": 0,
        "data": 0,
    }


@dataclass
class EffectServer(PlayerServer):
    """A fake player server that ends every effect it is given, `EFFECT_TICKS` ticks later."""

    later: set[asyncio.Task[None]] = field(default_factory=set)
    """The ends of the effects still to be sent."""
    shows: bool = False
    """Whether the watcher is told of the player `seen` as it joins."""

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
            if self.shows and self._joined() == SEEN and WATCHER in self.players:
                await self.players[WATCHER].send(
                    "minecraft:add_entity", **_entity(PLAYER, 0.5, -60.0, 0.5)
                )
            await super()._play(peer)
        finally:
            clock.cancel()

    def _joined(self) -> str:
        """The name of the player that has just said hello."""
        hellos = [p for p in self.seen if p.name == "minecraft:hello"]
        return str((hellos[-1].fields or {})["name"])

    async def _tick(self, peer: Peer) -> None:
        with suppress(ConnectionError):
            while True:
                await asyncio.sleep(TIME_TICKS * TICK_S)
                await peer.write(peer.raw_frame(SET_TIME, bytes(9)))

    @override
    async def _command(self, peer: Peer, command: str) -> None:
        words = command.split()
        if words[:2] == ["effect", "give"] and words[2] in self.players:
            self.later.add(asyncio.create_task(self._end(words[2], words[3])))
        elif words[0] == "summon":
            where = (float(word) for word in words[2:5])
            self.later.add(asyncio.create_task(self._summon(*where)))
        elif command.startswith(f"kill @e[tag={ZOMBIE_TAG}"):
            self.later.add(asyncio.create_task(self._remove_zombie()))
        else:
            await super()._command(peer, command)

    async def _end(self, name: str, effect: str) -> None:
        """Tell the player `name` its effect has ended, `EFFECT_TICKS` ticks after the give.

        An instant effect also changes the health, `HEALTH_LATE_TICKS` later.
        """
        await asyncio.sleep(EFFECT_TICKS * TICK_S)
        with suppress(ConnectionError):
            await self.players[name].send(REMOVED, entity_id=ENTITY_ID, effect=0)
            if effect.startswith("minecraft:instant_"):
                await asyncio.sleep(HEALTH_LATE_TICKS * TICK_S)
                await self.players[name].send(
                    "minecraft:set_health", health=14.0, food=20, saturation=5.0
                )

    async def _summon(self, x: float, y: float, z: float) -> None:
        """Tell every player but Control of the zombie at `x`, `y`, `z`, `ZOMBIE_LATE_TICKS` on."""
        await asyncio.sleep(ZOMBIE_LATE_TICKS * TICK_S)
        for name, player in self.players.items():
            if name != CONTROL:
                await player.send("minecraft:add_entity", **_entity(ZOMBIE, x, y, z))

    async def _remove_zombie(self) -> None:
        """Tell every player but Control the zombie is gone, `CORPSE_TICKS` after the kill."""
        await asyncio.sleep(CORPSE_TICKS * TICK_S)
        with suppress(ConnectionError):
            for name, player in self.players.items():
                if name != CONTROL:
                    await player.send("minecraft:remove_entities", entity_ids=[ZOMBIE_ID])


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


def assert_each_window_waits_for_the_end_and_one_barrier(
    windows: list[list[Event]], end: str
) -> None:
    """Check that the Bot sent two barriers' requests after it read `end` in every window.

    A hidden effect's last `update_attributes` comes 2 ticks after the end: one barrier of its
    own, then the window's, so that it is never between the closing barrier's answers.
    """
    for events in windows:
        names = [event.packet.name for event in events]
        assert names[names.index(end) + 1 :].count(CLIENT_COMMAND) == 2 * SYNC_REQUESTS


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
KINDS = {
    "player/effect-attributes": GroupKind.EXACT,
    "player/effect-ticking": GroupKind.EXACT,
    "player/effect-instant": GroupKind.TICK_EXACT,
    "player/effect-visibility": GroupKind.EXACT,
}
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

    windows = in_windows(transcript, EFFECTED)
    assert len(windows) == 12
    assert_each_window_waits_for_the_end_and_one_barrier(windows, REMOVED)


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

    windows = in_windows(transcript, TICKED)
    assert len(windows) == 5
    assert_each_window_waits_for_the_end_and_one_barrier(windows, REMOVED)


# `player/effect-instant`

INSTANT = "player/effect-instant"
INSTANT_BOT = "instant"
SET_HEALTH = "minecraft:set_health"
ZOMBIES = "@e[type=minecraft:zombie,tag=mscts_effected,limit=1]"
SUMMON = (
    "summon minecraft:zombie 3.5 -60 3.5 {NoAI:1b,PersistenceRequired:1b,Silent:1b,"
    'Rotation:[0f,0f],Tags:["mscts_effected"],'
    'equipment:{head:{id:"minecraft:carved_pumpkin",count:1}}}'
)
"""A zombie that stands still, makes no sound and does not burn in daylight."""
STEP = "tick step 1"
HURT_TO_10 = f"damage {INSTANT_BOT} 10.0 minecraft:generic"
BOT_GIVES = [
    f"effect give {INSTANT_BOT} minecraft:{name} 1 {amplifier} {hide}"
    for name, amplifier, hide in (
        ("instant_health", 0, "true"),
        ("instant_health", 1, "false"),
        ("instant_damage", 0, "true"),
        ("instant_damage", 0, "false"),
    )
]
ZOMBIE_GIVES = [
    f"effect give {ZOMBIES} minecraft:{name} 1 0 {hide}"
    for name, hide in (
        ("instant_health", "true"),
        ("instant_damage", "true"),
        ("instant_damage", "false"),
    )
]


def test_instant_hurts_a_fresh_bot_to_10_before_the_window_and_removes_the_zombie_after() -> None:
    result = play(INSTANT)[1]

    assert result.first == (*SET_UP, "tick freeze", f"kill {INSTANT_BOT}", HURT_TO_10)
    assert result.after == (
        "gamerule mob_drops false",
        "kill @e[tag=mscts_effected]",
        "gamerule mob_drops true",
        "tick unfreeze",
        f"effect clear {INSTANT_BOT}",
        f"tp {INSTANT_BOT} 0.5 -60 0.5",
        *UNDO,
    )


def test_instant_gives_four_effects_to_the_bot_and_three_to_a_zombie_a_window_each() -> None:
    result = play(INSTANT)[1]

    assert [window.label for window in result.windows] == [opened(*PACKETS)] * 7
    assert [window.commands for window in result.windows] == [
        *((give,) for give in BOT_GIVES),
        *((give, STEP, STEP) for give in ZOMBIE_GIVES),
    ]
    assert [window.before for window in result.windows][1:] == [
        *[(f"kill {INSTANT_BOT}", HURT_TO_10)] * 3,
        (SUMMON,),
        *[(STEP,) * 10] * 2,
    ]


def test_instant_steps_the_world_two_ticks_in_each_zombie_window_and_none_in_the_bots() -> None:
    result = play(INSTANT)[1]

    assert [window.ticks for window in result.windows] == [0, 0, 0, 0, 2, 2, 2]


def test_instant_ends_each_of_the_bots_windows_one_barrier_after_the_health_the_effect_sets() -> (
    None
):
    transcript = play(INSTANT)[0]

    # Pumpkin sends no remove_mob_effect for an instant effect, but it sends the health
    assert_each_window_waits_for_the_end_and_one_barrier(
        in_windows(transcript, INSTANT_BOT)[:4], SET_HEALTH
    )


def test_instant_summons_the_zombie_after_the_bots_last_respawn_and_waits_to_be_told_of_it() -> (
    None
):
    transcript = play(INSTANT)[0]

    [summoned] = command_times(transcript, SUMMON)
    opens = [m.t_ns for m in transcript.marks if m.label.startswith(OBSERVE_OPEN)]
    assert max(respawn_times(transcript, INSTANT_BOT)) < summoned
    told = read_times(transcript, INSTANT_BOT, "minecraft:add_entity")
    assert len(told) == 1
    assert summoned < told[0] < opens[4]
    # the news comes after the Bot's first look, so it passes a barrier of its own besides the
    # one that opens the window
    asked = sum(summoned < t < opens[4] for t in requests_times(transcript, INSTANT_BOT))
    assert asked > SYNC_REQUESTS


def test_instant_waits_until_the_bot_is_told_the_zombie_is_gone_before_it_leaves() -> None:
    transcript = play(INSTANT)[0]

    [gone] = read_times(transcript, INSTANT_BOT, "minecraft:remove_entities")
    [leaves] = command_times(transcript, f"tp {INSTANT_BOT} 0.5 -60 0.5")
    assert gone < leaves


# `player/effect-visibility`

VISIBILITY = "player/effect-visibility"
VISIBILITY_GIVES = [
    f"effect give {SEEN} minecraft:{name} 1000000 0 {hide}"
    for name, hide in (
        ("invisibility", "true"),
        ("invisibility", "false"),
        ("glowing", "true"),
        ("glowing", "false"),
    )
]
CLEAR = f"effect clear {SEEN}"


def test_visibility_joins_both_bots_before_the_world_is_frozen_and_undoes_for_both() -> None:
    result = play(VISIBILITY)[1]

    assert result.first == (*SET_UP, "tick freeze")
    assert result.after == (
        f"effect clear {SEEN}",
        f"tp {SEEN} 0.5 -60 0.5",
        f"effect clear {WATCHER}",
        f"tp {WATCHER} 0.5 -60 0.5",
        *UNDO,
    )


def test_visibility_gives_each_effect_then_clears_it_a_window_each() -> None:
    result = play(VISIBILITY)[1]

    assert [window.label for window in result.windows] == [opened(*PACKETS)] * 8
    assert [window.commands for window in result.windows] == [
        (command,) for give in VISIBILITY_GIVES for command in (give, CLEAR)
    ]
    assert [window.before for window in result.windows][1:] == [()] * 7


def barriers_before_the_first_window(transcript: Transcript, bot: str) -> int:
    """How many statistics requests `bot` sent between the freeze and the first window."""
    [frozen] = command_times(transcript, "tick freeze")
    first = min(m.t_ns for m in transcript.marks if m.label.startswith(OBSERVE_OPEN))
    return sum(frozen < t < first for t in requests_times(transcript, bot))


def test_visibility_waits_for_the_watcher_to_track_the_other_bot_for_up_to_four_barriers() -> None:
    never = barriers_before_the_first_window(play(VISIBILITY)[0], WATCHER)
    transcript, _ = replay(VISIBILITY, EffectServer(shows=True))
    shown = barriers_before_the_first_window(transcript, WATCHER)

    # the window's own barrier comes last
    assert shown == SYNC_REQUESTS
    assert never == 5 * SYNC_REQUESTS
