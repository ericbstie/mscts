"""The game mode, death and respawn Groups: who is switched or killed, and what is undone after.

Every test plays a Group against a fake server and reads the Transcript for what each Bot sent
(Control's commands, the respawn requests) and the Marks (the Observation windows). What a server
answers is never asserted: the fake answers Control's markers, the barrier and a respawn request.
"""

import asyncio
import functools
from contextlib import suppress
from dataclasses import dataclass
from typing import override

import pytest

from mscts.codec.packets import Direction
from mscts.compare import OBSERVE_CLOSE, OBSERVE_OPEN, Mask
from mscts.group import GROUPS, GroupContext, GroupKind
from mscts.groups import player_modes
from mscts.spec import Difficulty, ServerSpec
from mscts.transcript import Transcript
from tests.group.test_control import CODEC, tree
from tests.group.test_movement import Play, read
from tests.group.test_player import PERFORM_RESPAWN, PlayerServer
from tests.net.fakes import JoinScript, Peer, join_server, serve

CONTROL = "control"
CLIENT_COMMAND = "minecraft:client_command"
COMMANDS = tree(
    "gamerule", "tp", "tick", "gamemode", "give", "clear", "xp", "kill", "spawnpoint", "tellraw"
)
PLAY_TIMEOUT_S = 300.0

GAME_MODES = "player/game-modes"
DEATH = "player/death"
RESPAWN = "player/respawn"
GROUP_IDS = (GAME_MODES, DEATH, RESPAWN)
KINDS = {
    GAME_MODES: GroupKind.EXACT,
    DEATH: GroupKind.TICK_EXACT,
    RESPAWN: GroupKind.TICK_EXACT,
}
BOTS = {
    GAME_MODES: ("changer", "watcher"),
    DEATH: ("mortal",),
    RESPAWN: ("mortal", "pointer"),
}
MASKS = {GAME_MODES: (), DEATH: player_modes.DROP_MASKS, RESPAWN: ()}
SPAWN = "0.5 -60 0.5"


def clear_drops(x: str, z: str) -> tuple[str, str]:
    """The commands that remove the items and orbs within 20 blocks of (x, z)."""
    where = f"x={x},y=-60,z={z},distance=..20"
    return (
        f"kill @e[type=minecraft:item,{where}]",
        f"kill @e[type=minecraft:experience_orb,{where}]",
    )


CLEAR_SPAWN = clear_drops("0.5", "0.5")
CLEAR_FAR = clear_drops("-95.5", "95.5")


@dataclass
class ModesServer(PlayerServer):
    """The player fake with the commands these Groups run in its command tree."""

    @override
    async def __call__(self, peer: Peer) -> None:
        """Serve one connection: a Handler."""
        with suppress(ConnectionError):
            await join_server(self.seen, JoinScript(commands=COMMANDS, then=self._play))(peer)


async def _play(group_id: str) -> tuple[Transcript, Play]:
    transcript = Transcript(group_id=group_id, server="fake")
    async with serve(CODEC, ModesServer(), timeout_s=PLAY_TIMEOUT_S) as endpoint:
        context = GroupContext(endpoint, transcript, timeout_s=10.0)
        try:
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


def opened(*names: str) -> str:
    return f"{OBSERVE_OPEN} {' '.join(names)}"


def respawn_requests(group_id: str, bot: str) -> list[int]:
    """When (in ns) `bot` asked to respawn."""
    transcript, _ = play(group_id)
    return [
        e.t_ns
        for e in transcript.events
        if e.bot == bot
        and e.packet.direction is Direction.SERVERBOUND
        and e.packet.name == CLIENT_COMMAND
        and e.packet.fields == {"action": PERFORM_RESPAWN}
    ]


def window_spans(group_id: str) -> list[tuple[int, int]]:
    """When each window opened and closed."""
    transcript, _ = play(group_id)
    opens = [m.t_ns for m in transcript.marks if m.label.startswith(OBSERVE_OPEN)]
    closes = [m.t_ns for m in transcript.marks if m.label == OBSERVE_CLOSE]
    return list(zip(opens, closes, strict=True))


def joined(group_id: str) -> list[str]:
    """The Bots that joined, in order, but Control."""
    transcript, _ = play(group_id)
    names = [
        str((e.packet.fields or {})["name"])
        for e in transcript.events
        if e.packet.name == "minecraft:hello"
    ]
    return [name for name in names if name != CONTROL]


# Registration


@pytest.mark.parametrize("group_id", GROUP_IDS)
def test_each_group_is_registered_on_normal_difficulty_and_requires_nothing(group_id: str) -> None:
    group = GROUPS[group_id]
    default = ServerSpec(host="127.0.0.1", port=25566)

    assert group.kind is KINDS[group_id]
    assert group.requires == ()
    assert group.masks == MASKS[group_id]
    assert group.spec(default) == ServerSpec(
        host="127.0.0.1", port=25566, difficulty=Difficulty.NORMAL
    )


@pytest.mark.parametrize("group_id", GROUP_IDS)
def test_the_bots_join_in_order(group_id: str) -> None:
    assert joined(group_id) == list(BOTS[group_id])


@pytest.mark.parametrize("group_id", GROUP_IDS)
def test_the_joins_are_pinned_and_control_moves_away_before_any_bot_joins(group_id: str) -> None:
    transcript, result = play(group_id)

    assert result.first[:3] == (
        "gamerule player_movement_check false",
        "gamerule respawn_radius 0",
        "tp control 96.5 -60 96.5",
    )
    hello = next(
        e.t_ns for e in transcript.events if e.packet.name == "minecraft:hello" and e.bot != CONTROL
    )
    moved = next(
        e.t_ns
        for e in transcript.events
        if e.bot == CONTROL and (e.packet.fields or {}).get("command") == "tp control 96.5 -60 96.5"
    )
    assert moved < hello
    undone = [command for command in result.after if command != "tick unfreeze"]
    assert undone[-2:] == ["gamerule respawn_radius 10", "gamerule player_movement_check true"]


@pytest.mark.parametrize("group_id", GROUP_IDS)
def test_each_bot_is_back_in_survival_at_the_spawn_when_the_group_ends(group_id: str) -> None:
    result = played(group_id)

    for bot in BOTS[group_id]:
        assert result.after.index(f"gamemode survival {bot}") < result.after.index(
            f"tp {bot} {SPAWN}"
        )
        assert result.first.count(f"gamemode survival {bot}") == 1


@pytest.mark.parametrize("group_id", GROUP_IDS)
def test_no_group_touches_mob_spawning_or_kills_what_it_did_not_make(group_id: str) -> None:
    result = played(group_id)

    commands = (*result.first, *result.after, *(c for w in result.windows for c in w.before))
    assert not [c for c in commands if "spawn_mobs" in c or c.startswith("kill @e[type=!")]


# player/game-modes

MODES = ("creative", "adventure", "spectator", "survival")


def test_game_modes_compares_the_abilities_the_event_the_tab_list_and_what_a_watcher_sees() -> None:
    assert player_modes.MODE_PACKETS == (
        "minecraft:player_abilities",
        "minecraft:game_event",
        "minecraft:player_info_update",
        "minecraft:set_entity_data",
        "minecraft:update_attributes",
        "minecraft:waypoint",
        "minecraft:add_entity",
        "minecraft:remove_entities",
    )


def test_game_modes_switches_the_changer_through_every_mode_in_a_window_each() -> None:
    result = played(GAME_MODES)

    assert [w.label for w in result.windows] == [opened(*player_modes.MODE_PACKETS)] * 4
    assert [w.sent for w in result.windows] == [
        ((CONTROL, f"gamemode {mode} changer"),) for mode in MODES
    ]


def test_game_modes_puts_the_watcher_beside_the_changer_before_the_first_window() -> None:
    result = played(GAME_MODES)

    assert result.first[-1] == "tp watcher 4.5 -60 0.5"
    assert [w.before for w in result.windows[1:]] == [()] * 3


# player/death

RULES = (
    ("false", "false"),
    ("false", "false"),
    ("true", "false"),
    ("false", "true"),
    ("true", "true"),
)
"""The values of `keep_inventory` and `immediate_respawn` each death runs under."""
DIAMONDS, LEVEL = "give mortal minecraft:diamond 5", "xp set mortal 1 levels"
KITS = ((DIAMONDS,), (LEVEL,), (DIAMONDS, LEVEL), (DIAMONDS,), (DIAMONDS, LEVEL))
"""What the Bot holds each death, after `clear` and `xp set 0 levels`."""


def test_death_compares_the_death_the_health_the_drops_and_the_respawn_screen() -> None:
    assert player_modes.DEATH_PACKETS == (
        "minecraft:game_event",
        "minecraft:player_combat_kill",
        "minecraft:set_health",
        "minecraft:set_experience",
        "minecraft:container_set_content",
        "minecraft:set_player_inventory",
        "minecraft:container_set_slot",
        "minecraft:add_entity",
        "minecraft:set_entity_data",
        "minecraft:respawn",
    )


def test_death_sets_the_rules_inside_the_window_and_kills_the_bot_last() -> None:
    result = played(DEATH)

    assert [w.label for w in result.windows] == [opened(*player_modes.DEATH_PACKETS)] * 5
    assert [w.sent for w in result.windows] == [
        (
            (CONTROL, f"gamerule keep_inventory {keep}"),
            (CONTROL, f"gamerule immediate_respawn {immediate}"),
            (CONTROL, "kill mortal"),
        )
        for keep, immediate in RULES
    ]


def test_death_gives_the_bot_only_what_the_death_holds_before_each_window() -> None:
    result = played(DEATH)

    for window, kit in zip(result.windows, KITS, strict=True):
        assert window.before[-len(kit) - 2 :] == ("clear mortal", "xp set mortal 0 levels", *kit)


def test_death_drops_one_entity_a_death_so_that_no_two_are_resent_in_an_order_of_ids() -> None:
    # Vanilla resends the entities one tick made in the order of their raw ids, which differ per
    # Instance: a death that dropped an item and an orb would differ from itself.
    for (keep, _), kit in zip(RULES, KITS, strict=True):
        assert keep == "true" or len(kit) == 1


def test_death_takes_the_drops_away_and_then_respawns_the_bot_after_every_window() -> None:
    result = played(DEATH)

    asked = respawn_requests(DEATH, "mortal")
    spans = window_spans(DEATH)
    assert len(asked) == len(spans)
    for (_, closed), request in zip(spans, asked, strict=True):
        assert request > closed
    for window in result.windows[1:]:
        assert window.before[:2] == CLEAR_SPAWN


def test_death_freezes_the_world_and_puts_the_rules_and_the_drops_back_after() -> None:
    result = played(DEATH)

    assert "tick freeze" in result.first
    assert result.after[-1] == "tick unfreeze"
    assert "gamerule keep_inventory false" in result.after
    assert "gamerule immediate_respawn false" in result.after
    assert result.after[:2] == CLEAR_SPAWN


def test_death_masks_how_vanilla_moves_and_turns_what_a_dead_player_drops() -> None:
    assert [(m.packet, m.path) for m in player_modes.DROP_MASKS] == [
        ("minecraft:add_entity", "velocity.x"),
        ("minecraft:add_entity", "velocity.y"),
        ("minecraft:add_entity", "velocity.z"),
        ("minecraft:add_entity", "yaw"),
    ]
    assert all(isinstance(m, Mask) and "javap" in m.reason for m in player_modes.DROP_MASKS)


# player/respawn


def test_respawn_compares_what_the_new_player_is_sent() -> None:
    assert player_modes.RESPAWN_PACKETS == (
        "minecraft:respawn",
        "minecraft:set_health",
        "minecraft:set_experience",
        "minecraft:container_set_content",
        "minecraft:set_player_inventory",
        "minecraft:container_set_slot",
        "minecraft:set_default_spawn_position",
        "minecraft:player_position",
        "minecraft:player_abilities",
        "minecraft:game_event",
        "minecraft:update_attributes",
        "minecraft:set_entity_data",
    )


def test_respawn_asks_once_in_each_of_three_windows_that_send_no_command() -> None:
    result = played(RESPAWN)

    assert [w.label for w in result.windows] == [opened(*player_modes.RESPAWN_PACKETS)] * 3
    assert [w.sent for w in result.windows] == [()] * 3
    mortal, pointer = respawn_requests(RESPAWN, "mortal"), respawn_requests(RESPAWN, "pointer")
    assert [len(mortal), len(pointer)] == [2, 1]
    asked = sorted([*mortal, *pointer])
    for (opened_ns, closed_ns), request in zip(window_spans(RESPAWN), asked, strict=True):
        assert opened_ns < request < closed_ns


def test_respawn_kills_each_bot_holding_its_kit_and_removes_the_drops_before_its_window() -> None:
    result = played(RESPAWN)

    deaths = (("mortal", CLEAR_SPAWN), ("mortal", CLEAR_SPAWN), ("pointer", CLEAR_FAR))
    for window, (bot, clear) in zip(result.windows, deaths, strict=True):
        assert window.before[-7:] == (
            f"clear {bot}",
            f"xp set {bot} 0 levels",
            f"give {bot} minecraft:diamond 5",
            f"xp set {bot} 1 levels",
            f"kill {bot}",
            *clear,
        )
    assert result.after[:2] == CLEAR_FAR
    assert all(command in result.after for command in CLEAR_SPAWN)


def test_respawn_keeps_the_inventory_of_the_second_death_only() -> None:
    result = played(RESPAWN)

    rules = [
        next(c for c in window.before if c.startswith("gamerule keep_inventory"))
        for window in result.windows
    ]
    assert rules == [
        "gamerule keep_inventory false",
        "gamerule keep_inventory true",
        "gamerule keep_inventory false",
    ]


def test_respawn_puts_a_second_bot_far_from_the_first_and_gives_it_a_spawn_point() -> None:
    # A server keeps a spawn point for good and no command clears it, so the Bot that respawns at
    # the world spawn never has one. A player who respawns is sent to the others in view a tick or
    # two later, so the Bots are out of each other's view.
    result = played(RESPAWN)

    placed = [c for c in result.first if c.startswith(("tp pointer", "spawnpoint"))]
    assert placed == ["tp pointer -95.5 -60 95.5", "spawnpoint pointer -88 -60 88"]
    assert not [c for c in result.after if c.startswith("spawnpoint")]
