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

from mscts.compare import OBSERVE_OPEN
from mscts.group import GROUPS, GroupContext, GroupKind
from mscts.groups import player_modes
from mscts.spec import Difficulty, ServerSpec
from mscts.transcript import Transcript
from tests.group.test_control import CODEC, tree
from tests.group.test_movement import Play, read
from tests.group.test_player import PlayerServer
from tests.net.fakes import JoinScript, Peer, join_server, serve

CONTROL = "control"
COMMANDS = tree("gamerule", "tp", "tick", "gamemode", "tellraw")
PLAY_TIMEOUT_S = 300.0

GAME_MODES = "player/game-modes"
GROUP_IDS = (GAME_MODES,)
KINDS = {GAME_MODES: GroupKind.EXACT}
BOTS = {GAME_MODES: ("changer", "watcher")}
MASKS = {GAME_MODES: ()}
SPAWN = "0.5 -60 0.5"


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
