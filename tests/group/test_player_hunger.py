"""The hunger Groups: what Control sets up, what each window holds, and what is undone after.

Every test plays a Group against a fake server once and reads the Transcript for what each Bot
sent (Control's commands) and the Marks (the Observation windows). What a server answers is
never asserted: the fake answers Control's markers, the barrier and a respawn request, ends a
hunger effect a tick after it is given, sends the health the Group waits for after a
`/damage`, and sends `set_time` every tick (vanilla sends it every 20).
"""

import asyncio
import functools
import json
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
from tests.net.test_bot_move import RESPAWN

CONTROL = "control"
MARKER = "tellraw @s "
CHAT_COMMAND, CLIENT_COMMAND = "minecraft:chat_command", "minecraft:client_command"
SET_HEALTH, SET_TIME = "minecraft:set_health", "minecraft:set_time"
PERFORM_RESPAWN = 0
COMMANDS = tree("gamerule", "tick", "effect", "damage", "kill", "tp", "tellraw", "difficulty")
PLAY_TIMEOUT_S = 120.0
"""How long a fake serves a Bot: a whole play."""
HUNGER = 17
"""The hunger effect's id in the `mob_effect` registry, which `remove_mob_effect` carries."""
DEATH = "minecraft:player_combat_kill"

type Answer = tuple[tuple[str, Mapping[str, object] | bytes], ...]
"""Packets a fake sends after a command: each name with its fields, or its raw payload."""

ENDS = ("minecraft:remove_mob_effect", {"entity_id": 1, "effect": HUNGER})


def health(value: float, food: int) -> tuple[str, Mapping[str, object]]:
    return (SET_HEALTH, {"health": value, "food": food, "saturation": 0.0})


@dataclass
class HungerServer:
    """A fake server that joins like vanilla and answers what the hunger Groups wait for.

    It answers Control's markers, the barrier (a tick apart) and a respawn request (`respawn`,
    then one chunk batch). A command whose first word is in `answers` is answered, a tick
    later, with its packets, sent to the player the command names. Every player but Control
    is sent `set_time` every tick.
    """

    answers: Mapping[str, Answer] = field(default_factory=dict)
    """The packets sent after a command, by the command's first word."""
    seen: list[Packet] = field(default_factory=list)
    players: dict[str, Peer] = field(default_factory=dict)

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
        elif words[0] in self.answers:
            await asyncio.sleep(TICK_S)
            player = next(self.players[word] for word in words if word in self.players)
            for name, body in self.answers[words[0]]:
                if isinstance(body, bytes):
                    await player.write(player.raw_frame(name, body))
                else:
                    await player.send(name, **body)

    async def _tick(self, peer: Peer) -> None:
        with suppress(ConnectionError):
            while True:
                await asyncio.sleep(TICK_S)
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
        assert names[last_health + 1 :].count(SET_TIME) >= 6


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
        assert names[at + 1 :].count(SET_TIME) >= 6
    assert DEATH in [p.name for p in hard]


def test_starvation_respawns_the_bot_it_starved_to_death() -> None:
    transcript, _ = play("player/starvation")

    closes = [m.t_ns for m in transcript.marks if m.label == OBSERVE_CLOSE]
    asked = respawns(transcript, STARVER)
    assert len(asked) == 4
    assert asked[-1] > closes[-1]
