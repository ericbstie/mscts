"""The hunger Groups: what Control sets up, what each window holds, and what is undone after.

Every test plays a Group against a fake server once and reads the Transcript for what each Bot
sent (Control's commands) and the Marks (the Observation windows). What a server answers is
never asserted: the fake answers Control's markers, the barrier and a respawn request, and
sends just what each Group waits for: the end of a hunger effect, the health after a `/damage`
or a meal, the husks summoned, the answer to `/data get`, and `set_time` every 10 ticks
(vanilla sends it every 20).
"""

import asyncio
import functools
import json
import uuid
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass, field

from mscts.bot import SYNC_REQUESTS
from mscts.codec.packets import Direction, Packet
from mscts.compare import OBSERVE_CLOSE, OBSERVE_OPEN
from mscts.group import GROUPS, GroupContext, GroupKind
from mscts.groups import player_hunger
from mscts.spec import Difficulty, ServerSpec
from mscts.transcript import Transcript
from tests.group.test_combat import HUSK
from tests.group.test_control import CODEC, text, tree
from tests.group.test_movement import Play, read
from tests.net.fakes import (
    EMPTY_CHUNK,
    NO_STATISTICS,
    TICK_S,
    JoinScript,
    Peer,
    join_server,
    serve,
)
from tests.net.test_bot_move import LOGIN, RESPAWN

CONTROL = "control"
MARKER = "tellraw @s "
CHAT_COMMAND, CLIENT_COMMAND = "minecraft:chat_command", "minecraft:client_command"
SET_HEALTH, SET_TIME = "minecraft:set_health", "minecraft:set_time"
PERFORM_RESPAWN = 0
COMMANDS = tree(
    "gamerule",
    "tick",
    "effect",
    "damage",
    "kill",
    "tellraw",
    "difficulty",
    "give",
    "clear",
    "summon",
    "tp",
    "data",
)
PLAY_TIMEOUT_S = 120.0
"""How long a fake serves a Bot: a whole play."""
HUNGER = 17
"""The hunger effect's id in the `mob_effect` registry, which `remove_mob_effect` carries."""
DEATH = "minecraft:player_combat_kill"
EFFECT_TICKS = 5
"""How many ticks after it is given the fake ends a hunger effect: longer than a barrier, so a
window opened without waiting for the end would hold it."""
TIME_TICKS = 10
"""How many ticks apart the fake sends `set_time` (vanilla: 20): longer than a barrier, so a
window that closes on the barrier after its sixth holds no seventh."""

type Answer = tuple[tuple[str, Mapping[str, object] | bytes], ...]
"""Packets a fake sends after a command: each name with its fields, or its raw payload."""

ENDS = ("minecraft:remove_mob_effect", {"entity_id": 1, "effect": HUNGER})


def _login(peer: Peer) -> bytes:
    """The `login` that names the player's entity id, which a sprint command carries."""
    return peer.frame("minecraft:login", **LOGIN)


def health(value: float, food: int) -> tuple[str, Mapping[str, object]]:
    return (SET_HEALTH, {"health": value, "food": food, "saturation": 0.0})


@dataclass
class HungerServer:
    """A fake server that joins like vanilla and answers what the hunger Groups wait for.

    It answers Control's markers, the barrier (a tick apart) and a respawn request (`respawn`,
    then one chunk batch), and tells every player but Control of each husk summoned
    (`add_entity`). A command whose first word is in `answers` is answered, a tick later
    (`EFFECT_TICKS` for an effect), with its packets, sent to the player the command names; a
    packet whose name is in `answers` is answered a tick later, to the player that sent it.
    Every player but Control is sent `set_time` every `TIME_TICKS` ticks.
    """

    answers: Mapping[str, Answer] = field(default_factory=dict)
    """The packets sent after a command, by the command's first word."""
    seen: list[Packet] = field(default_factory=list)
    players: dict[str, Peer] = field(default_factory=dict)
    summoned: int = 0
    later: set[asyncio.Task[None]] = field(default_factory=set)
    """The answers to commands still to be sent."""

    async def __call__(self, peer: Peer) -> None:
        """Serve one connection: a Handler."""
        with suppress(ConnectionError):
            script = JoinScript(commands=COMMANDS, after_batch=_login, then=self._play)
            await join_server(self.seen, script)(peer)

    async def _play(self, peer: Peer) -> None:
        self.players[peer.name] = peer
        clock = None if peer.name == CONTROL else asyncio.create_task(self._tick(peer))
        requests = 0
        try:
            async for packet in peer.packets():
                self.seen.append(packet)
                if packet.name == CLIENT_COMMAND and packet.fields == {"action": PERFORM_RESPAWN}:
                    await peer.send("minecraft:respawn", **RESPAWN, data_kept=0)
                    await peer.send("minecraft:chunk_batch_start")
                    await peer.send("minecraft:level_chunk_with_light", **EMPTY_CHUNK)
                    await peer.send("minecraft:chunk_batch_finished", batch_size=1)
                elif packet.name == CLIENT_COMMAND:
                    requests += 1
                    if (requests - 1) % SYNC_REQUESTS != 0:
                        await asyncio.sleep(TICK_S)  # a barrier's answers come a tick apart
                    await peer.write(peer.raw_frame("minecraft:award_stats", NO_STATISTICS))
                elif packet.name == CHAT_COMMAND:
                    await self._command(peer, str((packet.fields or {})["command"]))
                elif packet.name in self.answers:
                    await self._answer(peer, self.answers[packet.name])
        finally:
            if clock is not None:
                clock.cancel()

    async def _command(self, peer: Peer, command: str) -> None:
        words = command.split()
        if command.startswith(MARKER):
            token = json.loads(command.removeprefix(MARKER))
            await peer.write(
                peer.frame("minecraft:system_chat", content=text(token), overlay=False)
            )
        elif words[0] == "summon":
            await self._summon(*(float(word) for word in words[2:5]))
        elif words[0] in self.answers:
            player = next(self.players[word] for word in words if word in self.players)
            ticks = EFFECT_TICKS if words[0] == "effect" else 1
            self.later.add(asyncio.create_task(self._answer(player, self.answers[words[0]], ticks)))

    async def _summon(self, x: float, y: float, z: float) -> None:
        """Tell every player but Control of a husk at `x`, `y`, `z` (ids from 100)."""
        self.summoned += 1
        for name, player in self.players.items():
            if name != CONTROL:
                await player.send(
                    "minecraft:add_entity",
                    entity_id=99 + self.summoned,
                    entity_uuid=uuid.UUID(int=self.summoned),
                    type=HUSK,
                    x=x,
                    y=y,
                    z=z,
                    velocity={"scale": 0, "x": 0, "y": 0, "z": 0},
                    pitch=0,
                    yaw=0,
                    head_yaw=0,
                    data=0,
                )

    async def _answer(self, player: Peer, answer: Answer, ticks: int = 1) -> None:
        await asyncio.sleep(ticks * TICK_S)
        with suppress(ConnectionError):
            for name, body in answer:
                if isinstance(body, bytes):
                    await player.write(player.raw_frame(name, body))
                else:
                    await player.send(name, **body)

    async def _tick(self, peer: Peer) -> None:
        with suppress(ConnectionError):
            while True:
                await asyncio.sleep(TIME_TICKS * TICK_S)
                await peer.write(peer.raw_frame(SET_TIME, bytes(9)))


async def _play(group_id: str, server: HungerServer) -> Transcript:
    transcript = Transcript(group_id=group_id, server="fake")
    async with serve(CODEC, server, timeout_s=PLAY_TIMEOUT_S) as endpoint:
        context = GroupContext(endpoint, transcript, timeout_s=10.0)
        try:
            await GROUPS[group_id].run(context)
        finally:
            await context.close()
    return transcript


ANSWERS: Mapping[str, Mapping[str, Answer]] = {
    "player/regeneration": {"effect": (ENDS,), "damage": (health(10.0, 17),)},
    "player/starvation": {
        "effect": (ENDS, health(10.0, 0), health(1.0, 0), (DEATH, b"\x02" + text("dead")))
    },
    "player/eating": {"effect": (ENDS,), "minecraft:use_item": (health(20.0, 7),)},
    "player/exhaustion": {
        "data": (("minecraft:system_chat", {"content": text("data"), "overlay": False}),)
    },
}
"""What the fake answers in each Group: just what the Group waits for."""


@functools.cache
def play(group_id: str) -> tuple[Transcript, Play]:
    """Play `group_id` against a fake server once; its Transcript and what was read from it."""
    transcript = asyncio.run(_play(group_id, HungerServer(answers=ANSWERS[group_id])))
    return transcript, read(transcript)


def played(group_id: str) -> Play:
    return play(group_id)[1]


def opened(*names: str) -> str:
    return f"{OBSERVE_OPEN} {' '.join(names)}"


def received_in_windows(transcript: Transcript, bot: str) -> list[list[Packet]]:
    """What `bot` received in each window, in order."""
    opens = [m.t_ns for m in transcript.marks if m.label.startswith(OBSERVE_OPEN)]
    closes = [m.t_ns for m in transcript.marks if m.label == OBSERVE_CLOSE]
    return [
        [
            e.packet
            for e in transcript.events
            if e.bot == bot
            and e.packet.direction is Direction.CLIENTBOUND
            and opened_at <= e.t_ns <= closed_at
        ]
        for opened_at, closed_at in zip(opens, closes, strict=True)
    ]


def respawns(transcript: Transcript, bot: str) -> list[int]:
    """When `bot` asked to respawn."""
    return [
        e.t_ns
        for e in transcript.events
        if e.bot == bot
        and e.packet.name == CLIENT_COMMAND
        and e.packet.fields == {"action": PERFORM_RESPAWN}
    ]


# Registration


def test_the_windows_compare_the_health_the_effects_the_eating_and_the_damage() -> None:
    assert player_hunger.PACKETS == (
        "minecraft:set_health",
        "minecraft:update_mob_effect",
        "minecraft:remove_mob_effect",
        "minecraft:entity_event",
        "minecraft:damage_event",
        "minecraft:sound",
        "minecraft:player_combat_kill",
    )


def test_regeneration_is_registered_exact_on_normal_difficulty_with_no_mask() -> None:
    group = GROUPS["player/regeneration"]
    default = ServerSpec(host="127.0.0.1", port=25566)

    assert group.kind is GroupKind.EXACT
    assert group.requires == ()
    assert group.masks == ()
    assert group.spec(default) == ServerSpec(
        host="127.0.0.1", port=25566, difficulty=Difficulty.NORMAL
    )


# player/regeneration

REGENERATOR = "regenerator"
DAMAGE = "damage regenerator 10 minecraft:generic"


def test_regeneration_pins_the_join_freezes_the_world_and_puts_both_back() -> None:
    result = played("player/regeneration")

    assert result.first == (
        "gamerule player_movement_check false",
        "gamerule respawn_radius 0",
        "tick freeze",
        "kill regenerator",
    )
    assert result.after == (
        "tp regenerator 0.5 -60 0.5",
        "gamerule respawn_radius 10",
        "gamerule player_movement_check true",
        "tick unfreeze",
    )


def test_regeneration_damages_a_fresh_bot_in_each_window_from_food_20_18_and_17() -> None:
    transcript, result = play("player/regeneration")

    assert [window.label for window in result.windows] == [opened(*player_hunger.PACKETS)] * 3
    assert [window.sent for window in result.windows] == [((CONTROL, DAMAGE),)] * 3
    assert [window.before for window in result.windows] == [
        result.first,
        ("kill regenerator", "effect give regenerator minecraft:hunger 4 74 true"),
        ("kill regenerator", "effect give regenerator minecraft:hunger 4 84 true"),
    ]
    opens = [m.t_ns for m in transcript.marks if m.label.startswith(OBSERVE_OPEN)]
    asked = respawns(transcript, REGENERATOR)
    assert len(asked) == 3
    assert all(a < o for a, o in zip(asked, opens, strict=True))


def test_regeneration_waits_for_food_17_then_100_ticks_before_a_window_ends() -> None:
    transcript, _ = play("player/regeneration")

    for packets in received_in_windows(transcript, REGENERATOR):
        names = [p.name for p in packets]
        last_health = max(i for i, name in enumerate(names) if name == SET_HEALTH)
        assert (packets[last_health].fields or {})["food"] == 17
        assert names[last_health + 1 :].count(SET_TIME) == 6


def test_regeneration_waits_for_each_hunger_effect_to_end_before_its_window() -> None:
    transcript, _ = play("player/regeneration")

    windows = received_in_windows(transcript, REGENERATOR)
    assert all("minecraft:remove_mob_effect" not in [p.name for p in w] for w in windows)
    ended = [
        e.t_ns
        for e in transcript.events
        if e.bot == REGENERATOR and e.packet.name == "minecraft:remove_mob_effect"
    ]
    opens = [m.t_ns for m in transcript.marks if m.label.startswith(OBSERVE_OPEN)]
    assert len(ended) == 2
    assert all(end < opened for end, opened in zip(ended, opens[1:], strict=True))


# player/starvation

STARVER = "starver"
EMPTY = "effect give starver minecraft:hunger 5 255 true"


def test_starvation_is_registered_exact_on_normal_difficulty_with_no_mask() -> None:
    group = GROUPS["player/starvation"]
    default = ServerSpec(host="127.0.0.1", port=25566)

    assert group.kind is GroupKind.EXACT
    assert group.requires == ()
    assert group.masks == ()
    assert group.spec(default) == ServerSpec(
        host="127.0.0.1", port=25566, difficulty=Difficulty.NORMAL
    )


def test_starvation_turns_regeneration_off_and_puts_it_and_the_difficulty_back() -> None:
    result = played("player/starvation")

    assert result.first == (
        "gamerule player_movement_check false",
        "gamerule respawn_radius 0",
        "gamerule natural_health_regeneration false",
        "tick freeze",
        "difficulty easy",
        "kill starver",
    )
    assert result.after == (
        "tp starver 0.5 -60 0.5",
        "difficulty normal",
        "gamerule natural_health_regeneration true",
        "gamerule respawn_radius 10",
        "gamerule player_movement_check true",
        "tick unfreeze",
    )


def test_starvation_hurts_and_empties_a_fresh_bot_on_easy_normal_and_hard() -> None:
    result = played("player/starvation")

    assert [window.label for window in result.windows] == [opened(*player_hunger.PACKETS)] * 3
    assert [window.sent for window in result.windows] == [
        ((CONTROL, f"damage starver {amount} minecraft:generic"), (CONTROL, EMPTY))
        for amount in (8, 17, 18)
    ]
    assert [window.before for window in result.windows] == [
        result.first,
        ("difficulty normal", "kill starver"),
        ("difficulty hard", "kill starver"),
    ]


def test_starvation_waits_for_each_floor_then_100_ticks_and_on_hard_for_the_death() -> None:
    transcript, _ = play("player/starvation")

    easy, normal, hard = received_in_windows(transcript, STARVER)
    for packets, floor in ((easy, 10.0), (normal, 1.0)):
        names = [p.name for p in packets]
        at = next(i for i, p in enumerate(packets) if (p.fields or {}).get("health") == floor)
        assert names[at + 1 :].count(SET_TIME) == 6
    assert DEATH in [p.name for p in hard]


def test_starvation_respawns_the_bot_it_starved_to_death() -> None:
    transcript, _ = play("player/starvation")

    closes = [m.t_ns for m in transcript.marks if m.label == OBSERVE_CLOSE]
    asked = respawns(transcript, STARVER)
    assert len(asked) == 4
    assert asked[-1] > closes[-1]


# player/eating

EATER = "eater"
FOODS = (
    "minecraft:bread",
    "minecraft:cooked_beef",
    "minecraft:golden_apple",
    "minecraft:rotten_flesh",
)
EATING = (SET_HEALTH, "minecraft:update_mob_effect", "minecraft:entity_event", "minecraft:sound")
FLESH = (SET_HEALTH, "minecraft:entity_event", "minecraft:sound")


def sent_by(transcript: Transcript, bot: str, name: str) -> list[Packet]:
    return [
        e.packet
        for e in transcript.events
        if e.bot == bot and e.packet.direction is Direction.SERVERBOUND and e.packet.name == name
    ]


def sent_times(transcript: Transcript, bot: str, name: str) -> list[int]:
    return [
        e.t_ns
        for e in transcript.events
        if e.bot == bot and e.packet.direction is Direction.SERVERBOUND and e.packet.name == name
    ]


def test_eating_is_registered_exact_on_normal_difficulty_masking_the_sound_pitch() -> None:
    group = GROUPS["player/eating"]
    default = ServerSpec(host="127.0.0.1", port=25566)

    assert group.kind is GroupKind.EXACT
    assert group.requires == ()
    assert [(mask.packet, mask.path) for mask in group.masks] == [("minecraft:sound", "pitch")]
    assert group.spec(default) == ServerSpec(
        host="127.0.0.1", port=25566, difficulty=Difficulty.NORMAL
    )


def test_eating_empties_a_fresh_bot_to_food_2_and_gives_it_each_food() -> None:
    result = played("player/eating")

    assert result.first == (
        "gamerule player_movement_check false",
        "gamerule respawn_radius 0",
        "tick freeze",
        "clear eater",
        "kill eater",
        "effect give eater minecraft:hunger 4 234 true",
        *(f"give eater {food}" for food in FOODS),
    )
    assert result.after == (
        "tp eater 0.5 -60 0.5",
        "gamerule respawn_radius 10",
        "gamerule player_movement_check true",
        "tick unfreeze",
    )


def test_eating_holds_each_food_then_eats_it_in_a_window_of_its_own() -> None:
    transcript, result = play("player/eating")

    assert [window.label for window in result.windows] == [opened(*EATING)] * 3 + [opened(*FLESH)]
    assert [window.before for window in result.windows][1:] == [()] * 3
    held = sent_by(transcript, EATER, "minecraft:set_carried_item")
    assert [(p.fields or {})["slot"] for p in held] == [1, 2, 3]  # the fake's player holds 0
    opens = [m.t_ns for m in transcript.marks if m.label.startswith(OBSERVE_OPEN)]
    closes = [m.t_ns for m in transcript.marks if m.label == OBSERVE_CLOSE]
    held_at = sent_times(transcript, EATER, "minecraft:set_carried_item")
    eaten_at = sent_times(transcript, EATER, "minecraft:use_item")
    assert all(h < o for h, o in zip(held_at, opens[1:], strict=True))
    assert all(o < e < c for o, e, c in zip(opens, eaten_at, closes, strict=True))


def test_eating_windows_end_on_the_health_that_eating_sends() -> None:
    transcript, _ = play("player/eating")

    for packets in received_in_windows(transcript, EATER):
        assert packets[-1].name == SET_HEALTH


# player/exhaustion

EXERCISER = "exerciser"
SYSTEM_CHAT = "minecraft:system_chat"
READ_BACK = tuple(
    (EXERCISER, f"data get entity exerciser {path}")
    for path in ("foodLevel", "foodSaturationLevel", "foodExhaustionLevel")
)


def test_exhaustion_is_registered_exact_on_normal_difficulty_with_the_bot_an_operator() -> None:
    group = GROUPS["player/exhaustion"]
    default = ServerSpec(host="127.0.0.1", port=25566)

    assert group.kind is GroupKind.EXACT
    assert group.requires == ()
    assert group.masks == ()
    assert group.spec(default) == ServerSpec(
        host="127.0.0.1", port=25566, difficulty=Difficulty.NORMAL, operators=(EXERCISER,)
    )


def test_exhaustion_puts_a_fresh_bot_at_the_lane_and_sends_the_husks_away_after() -> None:
    result = played("player/exhaustion")

    assert result.first == (
        "gamerule player_movement_check false",
        "gamerule respawn_radius 0",
        "tick freeze",
        "kill exerciser",
        "tp exerciser -49.5 -60 -20.5 -90 0",
    )
    assert result.after == (
        "tp exerciser 0.5 -60 0.5",
        "tp @e[tag=mscts_hunger] 0 -300 0",
        "gamerule respawn_radius 10",
        "gamerule player_movement_check true",
        "tick unfreeze",
    )


def test_exhaustion_sprints_jumps_and_attacks_reading_the_food_back_after_each() -> None:
    transcript, result = play("player/exhaustion")

    assert [window.label for window in result.windows] == [
        opened(SET_HEALTH),
        opened(SYSTEM_CHAT, SET_HEALTH),
    ] * 3
    sprint, _, jumps, _, attacks, _ = result.windows
    # the sprint's own tick reports where the Bot is first (the fake teleports no one)
    assert sprint.sent[1:] == tuple(
        (EXERCISER, (-49.5 + step, -60.0, -20.5)) for step in range(1, 101)
    )
    assert (
        jumps.sent == ((EXERCISER, (50.5, -59.58, -20.5)), (EXERCISER, (50.5, -60.0, -20.5))) * 50
    )
    assert [window.sent for window in result.windows[1::2]] == [READ_BACK] * 3
    assert set(attacks.sent) <= {(EXERCISER, (50.5, -60.0, -20.5))}  # a position reminder
    assert len(attacks.before) == 20
    assert all(c.startswith("summon minecraft:husk ") for c in attacks.before)
    hit = sent_by(transcript, EXERCISER, "minecraft:attack")
    assert [(p.fields or {})["entity_id"] for p in hit] == list(range(100, 120))


def test_exhaustion_follows_each_move_and_hit_with_a_barrier() -> None:
    transcript, _ = play("player/exhaustion")

    sent = [
        e.packet
        for e in transcript.events
        if e.bot == EXERCISER
        and e.packet.direction is Direction.SERVERBOUND
        and e.packet.name in {"minecraft:move_player_pos", "minecraft:attack", CLIENT_COMMAND}
    ]
    # An action is a hit or a move to a new place; a move to the same place is a reminder.
    steps: list[str] = []
    at = None
    for packet in sent:
        fields = packet.fields or {}
        if packet.name == "minecraft:move_player_pos":
            place = (fields["x"], fields["y"], fields["z"])
            if place != at:
                steps.append("act")
            at = place
        else:
            steps.append("act" if packet.name == "minecraft:attack" else "sync")
    acts = "".join("a" if step == "act" else "s" for step in steps)
    assert acts.count("a") >= 100 + 100 + 20
    # the first is the sprint's own tick, which reports where the Bot stands
    assert "aa" not in acts[acts.find("a") + 1 :]
