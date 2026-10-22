"""The player Groups: where each case puts its Bot, what it sends, and what is undone after.

Every test plays a Group against a fake server and reads the Transcript for what each Bot
sent (its moves, Control's commands) and the Marks (the Observation windows). What a server
answers is never asserted: the fake answers Control's markers, the barrier and a respawn
request, and nothing else.
"""

import asyncio
import functools
import json
from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass, field
from unittest import mock

import pytest
from support.bot_join import RESPAWN

from mscts.bot import HANDLED_REQUESTS, SYNC_REQUESTS
from mscts.codec.packets import Packet
from mscts.compare import OBSERVE_OPEN
from mscts.group import GROUPS, GroupContext, GroupKind
from mscts.groups import player
from mscts.net import ProtocolError
from mscts.spec import Difficulty, ServerSpec
from mscts.transcript import Transcript
from tests.group.test_control import CODEC, text, tree
from tests.group.test_mobs_pathfinding import gametime_answer
from tests.group.test_movement import MOVES, Play, _sent, read
from tests.group.test_ticks import barriers_before_steps
from tests.net.fakes import (
    EMPTY_CHUNK,
    NO_STATISTICS,
    TICK_S,
    JoinScript,
    Peer,
    join_server,
    serve,
)

CONTROL = "control"
MARKER = "tellraw @s "
CHAT_COMMAND, CLIENT_COMMAND = "minecraft:chat_command", "minecraft:client_command"
PERFORM_RESPAWN = 0
COMMANDS = tree(
    "gamerule", "tp", "tick", "setblock", "effect", "fill", "kill", "tellraw", "weather", "time"
)
TIME_QUERY = "time query gametime"
FADE_TICKS = 100
"""How far the fake's game time moves on between two reads: as far as a storm takes to fade."""
FADE_READS = (TIME_QUERY, TIME_QUERY)
"""Control reads the game time when the weather is cleared, and once the world has run on."""
PLAY_TIMEOUT_S = 300.0
"""How long a fake serves a Bot: a play takes about 30 s when the host is idle, and several
times that under load."""

GROUP_IDS = (
    "player/fall",
    "player/drowning",
    "player/suffocation",
    "player/void",
    "player/fire",
    "player/freezing",
)
KINDS = {
    "player/fall": GroupKind.TICK_EXACT,
    "player/drowning": GroupKind.EXACT,
    "player/suffocation": GroupKind.EXACT,
    "player/void": GroupKind.EXACT,
    "player/fire": GroupKind.EXACT,
    "player/freezing": GroupKind.EXACT,
}
BOTS = {
    "player/fall": ("faller",),
    "player/drowning": ("drowner",),
    "player/suffocation": ("suffocator",),
    "player/void": ("voider",),
    "player/fire": ("burner",),
    "player/freezing": ("freezer",),
}
IMMUNE_TICKS = 10
"""Ticks between two hits of damage that comes every tick: a player is immune for 10 after one."""
HURTS = {
    "player/drowning": {"tp drowner 3.5 -62.0 2.5": 20},  # the air runs out again
    "player/suffocation": {"tp suffocator 1.5 -60.0 2.5": IMMUNE_TICKS},
    "player/fire": {
        "tp burner 7.5 -60.0 2.5": IMMUNE_TICKS,  # in fire
        "tp burner 5.5 -61.0 2.5": IMMUNE_TICKS,  # in lava
        "tp burner 11.5 -60.0 2.5": 20,  # burning on the dry grass (Entity.baseTick)
    },
    "player/freezing": {"tp freezer 9.5 -60.0 2.5": 40},  # tickCount % 40 (LivingEntity.aiStep)
}
"""Each `tp` after which the fake hurts the Bot, and the ticks between two hits there, as on
vanilla, by Group: hits that come a tick apart would end a window before the Group's `tp`."""
KILLS_AFTER = {"player/void": "tp voider "}
DEATH = "minecraft:player_combat_kill"
HEAL = "effect give faller minecraft:instant_health 1 5 true"
ON_GROUND = 1
"""A move's `flags` when the Bot reports it is on the ground."""


@dataclass
class PlayerServer:
    """A fake server that joins like vanilla and answers Control's markers and the barrier.

    It answers a respawn request as `PlayerList.respawn` does: the `respawn` packet, then one
    chunk batch. After a `tp` in `hurts`, it hurts the Bot a tick later, and then once in
    each of that place's periods, until the next `tp` or `kill`: as on vanilla, a Bot moved or
    made fresh (`kill`, then respawn) is out of what hurt it.
    """

    seen: list[Packet] = field(default_factory=list)
    hurts: Mapping[str, int] = field(default_factory=dict)
    """Each `tp` after which the fake sends `set_health` and `entity_event`, and the ticks
    between two of them."""
    hurting: asyncio.Task[None] | None = None
    """The task that hurts the Bot, while it is somewhere that hurts."""
    kills_after: str | None = None
    """A command after which the fake sends `player_combat_kill`, once."""
    players: dict[str, Peer] = field(default_factory=dict)
    """Each connected player's connection, by name."""
    late: frozenset[str] = frozenset()
    """The players whose statistics requests are each answered a tick later still."""
    game_time: int = 0
    """The game time the next `time query gametime` answers: each answer moves it on by
    `FADE_TICKS`."""

    async def __call__(self, peer: Peer) -> None:
        """Serve one connection: a Handler."""
        with suppress(ConnectionError):
            await join_server(self.seen, JoinScript(commands=COMMANDS, then=self._play))(peer)

    async def _play(self, peer: Peer) -> None:
        requests = 0
        hellos = [p for p in self.seen if p.name == "minecraft:hello"]
        name = str((hellos[-1].fields or {})["name"])
        self.players[name] = peer
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
                    if name in self.late:
                        await asyncio.sleep(TICK_S)
                    await peer.write(peer.raw_frame("minecraft:award_stats", NO_STATISTICS))
                elif packet.name == CHAT_COMMAND:
                    command = str((packet.fields or {})["command"])
                    await self._command(peer, command)
        finally:
            self._stop_hurting()

    async def _command(self, peer: Peer, command: str) -> None:
        """Answer `command` from `peer`."""
        if command.startswith(MARKER):
            token = json.loads(command.removeprefix(MARKER))
            await peer.write(
                peer.frame("minecraft:system_chat", content=text(token), overlay=False)
            )
        elif command == TIME_QUERY:
            answer = gametime_answer(self.game_time)
            self.game_time += FADE_TICKS
            await peer.write(peer.frame("minecraft:system_chat", content=answer, overlay=False))
        elif self.kills_after and command.startswith(self.kills_after):
            victim = self.players[command.split()[1]]
            await victim.write(victim.raw_frame(DEATH, b"\x02" + text("dead")))
        elif command.startswith(("tp ", "kill ")):
            self._stop_hurting()  # moved or respawned, the Bot is out of what hurt it
            if command in self.hurts:
                self.hurting = asyncio.create_task(self._hurt(self.hurts[command]))

    def _stop_hurting(self) -> None:
        if self.hurting is not None:
            self.hurting.cancel()
            self.hurting = None

    async def _hurt(self, period_ticks: int) -> None:
        """Hurt every player but Control a tick from now, then every `period_ticks` ticks."""
        delay_s = TICK_S
        with suppress(ConnectionError):
            while True:
                await asyncio.sleep(delay_s)
                delay_s = period_ticks * TICK_S
                for name, peer in list(self.players.items()):
                    if name != CONTROL:
                        await peer.send(
                            "minecraft:set_health", health=19.0, food=20, saturation=5.0
                        )
                        await peer.send("minecraft:entity_event", entity_id=2, event_id=67)


def always_on_time() -> float:
    """A clock that never moves: no hit is ever older than its period allows."""
    return 0.0


async def _play(
    group_id: str,
    clock: Callable[[], float] = always_on_time,
    *,
    late: frozenset[str] = frozenset(),
) -> tuple[Transcript, Play]:
    transcript = Transcript(group_id=group_id, server="fake")
    async with serve(
        CODEC,
        PlayerServer(
            hurts=HURTS.get(group_id, {}),
            kills_after=KILLS_AFTER.get(group_id),
            late=late,
        ),
        timeout_s=PLAY_TIMEOUT_S,
    ) as endpoint:
        context = GroupContext(endpoint, transcript, timeout_s=10.0)
        try:
            with mock.patch.object(player, "clock", clock):
                await GROUPS[group_id].run(context)
        finally:
            await context.close()
    return transcript, read(transcript)


@functools.cache
def play(group_id: str) -> tuple[Transcript, Play]:
    """Play `group_id` against a fake server once; its Transcript and what was read from it.

    A play takes seconds (the fake's ticks are real), so every test of a Group reads one.
    """
    return asyncio.run(_play(group_id))


def played(group_id: str) -> Play:
    return play(group_id)[1]


def tp(at: tuple[float, float, float], bot: str = "faller") -> str:
    return "tp {} {} {} {}".format(bot, *at)


def lane(index: int, y: float) -> tuple[float, float, float]:
    """A point over the landing lane `index`: lanes are 2 blocks apart along x, at z 2.5."""
    return (2 * index + 1.5, y, 2.5)


# Registration


@pytest.mark.parametrize("group_id", GROUP_IDS)
def test_each_group_is_registered_with_only_the_masks_it_needs_and_plays_on_normal_difficulty(
    group_id: str,
) -> None:
    group = GROUPS[group_id]
    default = ServerSpec(host="127.0.0.1", port=25566)

    assert group.kind is KINDS[group_id]
    assert group.requires == ()
    assert group.masks == (player.FIRE_MASKS if group_id == "player/fire" else ())
    assert group.spec(default) == ServerSpec(
        host="127.0.0.1", port=25566, difficulty=Difficulty.NORMAL
    )


def test_the_windows_compare_the_damage_the_health_and_the_death() -> None:
    assert player.PACKETS == (
        "minecraft:set_health",
        "minecraft:damage_event",
        "minecraft:hurt_animation",
        "minecraft:entity_event",
        "minecraft:set_entity_data",
        "minecraft:sound",
        "minecraft:player_position",
        "minecraft:player_combat_kill",
        "minecraft:respawn",
    )


def test_the_windows_after_a_first_hit_compare_only_what_a_hit_sends() -> None:
    assert player.HIT_PACKETS == (
        "minecraft:damage_event",
        "minecraft:hurt_animation",
        "minecraft:entity_event",
        "minecraft:set_health",
        "minecraft:sound",
    )


def opened(*names: str) -> str:
    return f"{OBSERVE_OPEN} {' '.join(names)}"


def test_every_fall_window_is_narrowed_to_the_packets() -> None:
    result = played("player/fall")

    assert {window.label for window in result.windows} == {opened(*player.PACKETS)}


@pytest.mark.parametrize("group_id", GROUP_IDS)
def test_the_rules_are_set_before_the_bots_join_and_put_back_after_the_blocks(
    group_id: str,
) -> None:
    transcript, result = play(group_id)

    assert result.first[:9] == (
        "gamerule player_movement_check false",
        "gamerule respawn_radius 0",
        "gamerule advance_weather false",
        "weather clear",
        *FADE_READS,
        "gamerule natural_health_regeneration false",
        "gamerule random_tick_speed 0",
        "tp control 96.5 -60 96.5",
    )
    hello = next(
        e.t_ns for e in transcript.events if e.packet.name == "minecraft:hello" and e.bot != CONTROL
    )
    commands = [(t, what) for t, who, what in _sent(transcript) if who == CONTROL]
    first_tp = next(t for t, what in commands if str(what).startswith("tp control"))
    assert first_tp < hello
    assert result.after[-6:] == (
        "gamerule random_tick_speed 3",
        "gamerule natural_health_regeneration true",
        "gamerule advance_weather true",
        "gamerule respawn_radius 10",
        "gamerule player_movement_check true",
        "tick unfreeze",
    )


@pytest.mark.parametrize("group_id", GROUP_IDS)
def test_no_group_touches_mob_spawning_or_removes_what_it_did_not_make(group_id: str) -> None:
    # The Fixture world has `spawn_mobs` off (ADR-0013); turning it back on after a Group would
    # leave it on for every Group that plays after.
    result = played(group_id)

    commands = (*result.first, *result.after, *(c for w in result.windows for c in w.before))
    assert not [c for c in commands if "spawn_mobs" in c or c.startswith("kill @e[type=!")]


@pytest.mark.parametrize("group_id", GROUP_IDS)
def test_each_bot_is_put_back_at_the_spawn_before_the_blocks_are_restored(group_id: str) -> None:
    result = played(group_id)

    (bot,) = BOTS[group_id]
    back = f"tp {bot} 0.5 -60 0.5"
    assert back in result.after
    blocks = [i for i, c in enumerate(result.after) if c.startswith("setblock")]
    assert not blocks or result.after.index(back) < blocks[0]


# player/fall

STONE, WATER, HAY, SLIME, BED = range(5)
HEIGHTS = (3, 4, 10, 23)
LANDS_AT = {STONE: -59.0, WATER: -61.0, HAY: -59.0, SLIME: -59.0, BED: -59.4375}


def fall_cases() -> list[tuple[int, int]]:
    """The `(lane, height)` of each fall window, in order: the lethal fall is not among them."""
    ordinary = [
        (lane_index, height)
        for lane_index in range(5)
        for height in HEIGHTS
        if (lane_index, height) != (STONE, 23)
    ]
    return [*ordinary, (STONE, 10)]


def test_fall_builds_every_surface_once_the_world_is_frozen() -> None:
    result = played("player/fall")

    frozen = result.first.index("tick freeze")
    assert result.first[frozen + 1 : frozen + 8] == (
        "setblock 1 -60 2 minecraft:stone",
        "setblock 3 -62 2 minecraft:water",
        "setblock 3 -61 2 minecraft:water",
        "setblock 5 -60 2 minecraft:hay_block",
        "setblock 7 -60 2 minecraft:slime_block",
        "setblock 9 -60 3 minecraft:red_bed[facing=south,part=head]",
        "setblock 9 -60 2 minecraft:red_bed[facing=south,part=foot]",
    )
    # The Bot is not put in the block that becomes stone: it stays where it joined.
    assert not [c for c in result.first[:frozen] if c.startswith("tp faller")]


def test_fall_gives_each_surface_each_height_in_a_window_of_its_own() -> None:
    result = played("player/fall")

    starts = [window.before[-1] for window in result.windows[: len(fall_cases())]]
    assert starts == [tp(lane(i, LANDS_AT[i] + height)) for i, height in fall_cases()]


def test_fall_heals_the_bot_before_it_is_put_up_in_the_air() -> None:
    result = played("player/fall")

    for window in result.windows[:-1]:
        assert window.before[-2] == HEAL


def test_fall_drops_at_most_8_blocks_a_move_then_stops_above_the_surface_and_lands() -> None:
    result = played("player/fall")

    stone_3, stone_4, stone_10 = result.windows[:3]
    assert stone_3.moves("faller") == [lane(STONE, -58.0), lane(STONE, -59.0)]
    assert stone_4.moves("faller") == [lane(STONE, -58.0), lane(STONE, -59.0)]
    assert stone_10.moves("faller") == [
        lane(STONE, -57.0),
        lane(STONE, -58.0),
        lane(STONE, -59.0),
    ]


def test_fall_into_water_stops_in_the_water_with_its_head_out_before_it_lands() -> None:
    # A move from the air into the water that lands is a fall onto the water's floor to vanilla,
    # which learns that a player is in water on its tick; and under water a player loses air in
    # real time, which a stepped window cannot place.
    result = played("player/fall")

    water_23 = result.windows[6]
    assert water_23.moves("faller") == [
        lane(WATER, -46.0),
        lane(WATER, -54.0),
        lane(WATER, -60.5),
        lane(WATER, -61.0),
    ]


def test_fall_steps_the_world_after_every_move() -> None:
    result = played("player/fall")

    for window in result.windows[: len(fall_cases())]:
        moves = len(window.moves("faller"))
        assert [who for who, _ in window.sent] == ["faller", CONTROL] * moves
        assert [what for who, what in window.sent if who == CONTROL] == ["tick step 1"] * moves


def test_each_move_of_a_fall_reaches_the_server_before_the_step_after_it() -> None:
    transcript, result = play("player/fall")
    moves = sum(len(window.moves("faller")) for window in result.windows)

    barriers = barriers_before_steps(transcript, "faller", set(MOVES))

    assert len(barriers) == moves > 0
    assert set(barriers) == {HANDLED_REQUESTS}


def test_fall_reports_every_move_in_the_air_but_the_last() -> None:
    transcript, result = play("player/fall")

    opens = [m.t_ns for m in transcript.marks if m.label.startswith(OBSERVE_OPEN)]
    closes = [m.t_ns for m in transcript.marks if m.label == "observe:close"]
    for opened, closed in zip(opens[: len(fall_cases())], closes, strict=False):
        flags = [
            int(str((e.packet.fields or {})["flags"])) & ON_GROUND
            for e in transcript.events
            if e.bot == "faller" and e.packet.name in MOVES and opened <= e.t_ns <= closed
        ]
        assert flags[-1] == ON_GROUND
        assert not any(flags[:-1])
    assert len(result.windows) == len(fall_cases()) + 2


def test_fall_turns_fall_damage_off_for_one_fall_and_on_again_for_the_last() -> None:
    result = played("player/fall")

    off_fall = len(fall_cases()) - 1
    assert result.windows[off_fall].before[0] == "gamerule fall_damage false"
    assert result.windows[off_fall].moves("faller")[-1] == lane(STONE, -59.0)
    lethal = result.windows[off_fall + 1]
    assert lethal.before[0] == "gamerule fall_damage true"
    assert lethal.before[-1] == tp(lane(STONE, -59.0 + 23))
    assert result.after.count("gamerule fall_damage true") == 1


def test_fall_ends_with_the_deadly_fall_and_the_respawn_in_a_window_of_its_own() -> None:
    transcript, result = play("player/fall")

    *_, lethal, respawn = result.windows
    assert lethal.moves("faller")[-1] == lane(STONE, -59.0)
    assert respawn.sent == ()
    asked = [
        e
        for e in transcript.events
        if e.bot == "faller"
        and e.packet.name == CLIENT_COMMAND
        and e.packet.fields == {"action": PERFORM_RESPAWN}
    ]
    opens = [m.t_ns for m in transcript.marks if m.label.startswith(OBSERVE_OPEN)]
    closes = [m.t_ns for m in transcript.marks if m.label == "observe:close"]
    [ask] = asked
    assert opens[-1] < ask.t_ns < closes[-1]


def test_fall_restores_the_flat_world_and_unfreezes_it_last() -> None:
    result = played("player/fall")

    assert result.after[:10] == (
        "gamerule fall_damage true",
        "tp faller 0.5 -60 0.5",
        "setblock 9 -60 2 minecraft:air",
        "setblock 9 -60 3 minecraft:air",
        "setblock 7 -60 2 minecraft:air",
        "setblock 5 -60 2 minecraft:air",
        "setblock 3 -61 2 minecraft:grass_block",
        "setblock 3 -62 2 minecraft:dirt",
        "setblock 1 -60 2 minecraft:air",
        "kill @e[type=minecraft:item]",  # the bed's other half drops as an item when it goes
    )
    assert result.after[-1] == "tick unfreeze"


# player/drowning


def test_drowning_starts_from_a_fresh_player_and_puts_it_in_the_water_inside_the_window() -> None:
    transcript, result = play("player/drowning")

    first, *_ = result.windows
    assert first.label == opened(*player.PACKETS)
    assert first.before[-1] == "kill drowner"
    assert first.sent == ((CONTROL, "tp drowner 3.5 -62.0 2.5"),)
    asked = [
        e
        for e in transcript.events
        if e.bot == "drowner"
        and e.packet.name == CLIENT_COMMAND
        and e.packet.fields == {"action": PERFORM_RESPAWN}
    ]
    opens = [m.t_ns for m in transcript.marks if m.label.startswith(OBSERVE_OPEN)]
    assert len(asked) == 1
    assert asked[0].t_ns < opens[0]


def test_drowning_builds_its_pool_once_the_world_is_frozen_and_restores_it() -> None:
    result = played("player/drowning")

    frozen = result.first.index("tick freeze")
    assert result.first[frozen + 1 : frozen + 3] == (
        "setblock 3 -62 2 minecraft:water",
        "setblock 3 -61 2 minecraft:water",
    )
    assert result.after[:4] == (
        "gamerule drowning_damage true",
        "tp drowner 0.5 -60 0.5",
        "setblock 3 -61 2 minecraft:grass_block",
        "setblock 3 -62 2 minecraft:dirt",
    )


def test_drowning_waits_for_the_first_hit_and_three_more_then_for_the_bubbles() -> None:
    result = played("player/drowning")

    assert [window.label for window in result.windows] == [
        opened(*player.PACKETS),
        *[opened(*player.HIT_PACKETS)] * 4,
    ]
    assert [window.sent for window in result.windows[1:]] == [()] * 4


def test_drowning_turns_the_damage_off_before_its_last_window() -> None:
    result = played("player/drowning")

    assert result.windows[-1].before[0] == "gamerule drowning_damage false"
    assert result.after.count("gamerule drowning_damage true") == 1


# player/suffocation


def test_suffocation_puts_a_fresh_bot_into_the_stone_inside_the_first_window() -> None:
    result = played("player/suffocation")

    first, *hits = result.windows
    assert first.label == opened(*player.PACKETS)
    assert first.before[-1] == "kill suffocator"
    assert first.sent == ((CONTROL, "tp suffocator 1.5 -60.0 2.5"),)
    assert [window.label for window in hits] == [opened(*player.HIT_PACKETS)] * 2
    assert [window.sent for window in hits] == [(), ()]


def test_suffocation_builds_a_column_of_stone_after_the_freeze_and_removes_it() -> None:
    result = played("player/suffocation")

    frozen = result.first.index("tick freeze")
    assert result.first[frozen + 1 : frozen + 3] == (
        "setblock 1 -60 2 minecraft:stone",
        "setblock 1 -59 2 minecraft:stone",
    )
    assert result.after[:3] == (
        "tp suffocator 0.5 -60 0.5",
        "setblock 1 -59 2 minecraft:air",
        "setblock 1 -60 2 minecraft:air",
    )


# player/void


def test_void_puts_a_fresh_bot_below_the_world_and_waits_for_its_death() -> None:
    transcript, result = play("player/void")

    first, respawn = result.windows
    assert first.label == opened(*player.PACKETS)
    assert first.before[-1] == "kill voider"
    assert first.sent == ((CONTROL, "tp voider 0.5 -130.0 0.5"),)
    assert respawn.label == opened(*player.PACKETS)
    assert respawn.sent == ()
    asked = [
        e
        for e in transcript.events
        if e.bot == "voider"
        and e.packet.name == CLIENT_COMMAND
        and e.packet.fields == {"action": PERFORM_RESPAWN}
    ]
    opens = [m.t_ns for m in transcript.marks if m.label.startswith(OBSERVE_OPEN)]
    closes = [m.t_ns for m in transcript.marks if m.label == "observe:close"]
    assert len(asked) == 2  # the fresh start, and the respawn after the void
    assert opens[1] < asked[1].t_ns < closes[1]


def test_void_sets_no_block() -> None:
    result = played("player/void")

    assert not any(c.startswith(("setblock", "fill")) for c in (*result.first, *result.after))


# player/fire


def test_fire_visits_fire_lava_the_dry_grass_and_the_water_in_that_order() -> None:
    result = played("player/fire")

    assert [window.sent for window in result.windows] == [
        ((CONTROL, "tp burner 7.5 -60.0 2.5"),),
        ((CONTROL, "tp burner 5.5 -61.0 2.5"),),
        ((CONTROL, "tp burner 11.5 -60.0 2.5"),),
        ((CONTROL, "tp burner 3.5 -61.0 2.5"),),
    ]


def test_fire_waits_for_a_hit_in_each_place_but_the_water() -> None:
    result = played("player/fire")

    assert [window.label for window in result.windows] == [
        opened(*player.PACKETS),
        opened(*player.PACKETS),
        opened(*player.PACKETS),
        opened(*player.PACKETS),
    ]


def test_the_fire_windows_open_with_the_weather_cleared_and_its_cycle_stopped() -> None:
    # Rain puts out a burning player, so a storm the weather cycle started during an earlier
    # Group would end the burn on the dry grass on one Instance only (#426).
    result = played("player/fire")

    stopped = result.first.index("gamerule advance_weather false")
    cleared = result.first.index("weather clear")
    assert cleared > stopped
    # `weather clear` sets the weather, but the rain level falls 0.01 a running tick: the
    # Group waits until the world has run the 100 ticks a storm takes to fade, then freezes it.
    assert result.first[cleared + 1 : cleared + 3] == FADE_READS
    assert result.first.index("tick freeze") > cleared + 2
    assert result.after.count("gamerule advance_weather true") == 1


def test_fire_builds_water_lava_and_fire_after_the_freeze_and_restores_the_world() -> None:
    result = played("player/fire")

    frozen = result.first.index("tick freeze")
    assert result.first[frozen + 1 : frozen + 6] == (
        "setblock 3 -62 2 minecraft:water",
        "setblock 3 -61 2 minecraft:water",
        "setblock 5 -62 2 minecraft:lava",
        "setblock 5 -61 2 minecraft:lava",
        "setblock 7 -60 2 minecraft:fire",
    )
    assert result.after[:7] == (
        "tp burner 0.5 -60 0.5",
        "setblock 7 -60 2 minecraft:air",
        "setblock 5 -61 2 minecraft:grass_block",
        "setblock 5 -62 2 minecraft:dirt",
        "setblock 3 -61 2 minecraft:grass_block",
        "setblock 3 -62 2 minecraft:dirt",
        "gamerule random_tick_speed 3",
    )


# player/freezing


def test_freezing_compares_the_teleport_into_the_snow_and_two_hits() -> None:
    result = played("player/freezing")

    first, second = result.windows
    assert first.label == opened(*player.FREEZING_PACKETS)
    assert second.label == opened(*player.HIT_PACKETS)
    assert first.sent == ((CONTROL, "tp freezer 9.5 -60.0 2.5"),)
    assert first.before[-1] == "kill freezer"
    assert second.sent == ()


def test_freezing_leaves_the_entity_data_out_because_the_first_hit_depends_on_the_tick_count() -> (
    None
):
    assert "minecraft:set_entity_data" not in player.FREEZING_PACKETS
    assert (*player.HIT_PACKETS, "minecraft:player_position") == player.FREEZING_PACKETS


def test_freezing_builds_one_block_of_powder_snow_after_the_freeze_and_removes_it() -> None:
    result = played("player/freezing")

    assert result.first[result.first.index("tick freeze") + 1] == (
        "setblock 9 -60 2 minecraft:powder_snow"
    )
    assert result.after[:2] == (
        "tp freezer 0.5 -60 0.5",
        "setblock 9 -60 2 minecraft:air",
    )


def test_fire_masks_only_the_random_pitch_of_its_sounds() -> None:
    masks = GROUPS["player/fire"].masks

    assert [(mask.packet, mask.path) for mask in masks] == [("minecraft:sound", "pitch")]


# A hit that comes between two windows

# Hits come a fixed number of ticks apart, and a player ticks in real time: a window that opens
# later than that lets a hit pass unseen, and every window after it holds another health. The
# Reference would differ from itself, so the Group fails (the Reference's `error`).


def jumping_clock() -> Callable[[], float]:
    """A clock that is 10 s later at every reading: far longer than any hit's period."""
    now = iter(range(0, 10_000, 10))
    return lambda: float(next(now))


@pytest.mark.parametrize(
    "group_id",
    ["player/drowning", "player/suffocation", "player/fire", "player/freezing"],
)
def test_a_window_that_opens_after_the_next_hit_fails_the_group_instead_of_comparing(
    group_id: str,
) -> None:
    with pytest.raises(ProtocolError, match="the next may have come between the windows"):
        asyncio.run(_play(group_id, clock=jumping_clock()))


@pytest.mark.parametrize("group_id", sorted(HURTS))
def test_each_window_still_holds_its_tp_when_controls_barrier_ends_after_the_bots(
    group_id: str,
) -> None:
    # A window opens at its Bot's own barrier (#356), and the Group sends the tp once Control's
    # has ended too. On vanilla no hit comes in between: hits come at least 10 ticks apart, and
    # the window before ended on one. A fake that hurt every tick put a hit there.
    _, slow = asyncio.run(_play(group_id, late=frozenset({CONTROL})))

    assert [window.sent for window in slow.windows] == [
        window.sent for window in played(group_id).windows
    ]


def test_fire_makes_the_bot_fresh_before_the_fire_and_again_before_the_lava() -> None:
    # A player is immune for 10 ticks after a hit, and a lava tick inside them hurts only by the
    # excess, so the lava's full hit would fall between two windows.
    result = played("player/fire")

    fire_window, lava_window, *_ = result.windows
    assert fire_window.before[-1] == "kill burner"
    assert lava_window.before[-1] == "kill burner"
