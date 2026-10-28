"""The crowding Groups: what Control sets up and summons, the windows, and what is undone after.

Every test plays a Group against a fake server and reads the Transcript for Control's commands
and the Marks (the Observation windows and the ticks stepped). What a server answers is never
asserted: the fake answers Control's markers, the barrier and the game time, and tells the
watcher about each pig Control summons.
"""

import asyncio
import json
import math
import re
import uuid
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass, field

import pytest
from support.control import playing, text, tree
from support.control_play import Window, control_commands, read
from support.gametime import gametime_answer

import mscts.groups
from mscts.bot import SYNC_REQUESTS
from mscts.codec.packets import Packet
from mscts.codec.registry_names import registry_names
from mscts.compare import OBSERVE_OPEN
from mscts.group import GROUPS, GroupKind
from mscts.spec import ServerSpec
from mscts.target import TARGET
from mscts.transcript import Transcript
from tests.net.fakes import NO_STATISTICS, TICK_S, JoinScript, Peer, join_server

CONTROL = "control"
WATCHER = "watcher"
MARKER = "tellraw @s "
CHAT_COMMAND, CLIENT_COMMAND = "minecraft:chat_command", "minecraft:client_command"
COMMANDS = tree("gamerule", "tp", "tick", "summon", "kill", "fill", "setblock", "time", "tellraw")
TAG = "mscts_crowding"
KILL_PIGS = f"kill @e[tag={TAG}]"
KILL_ITEMS = "kill @e[type=minecraft:item]"
TIME_QUERY = "time query gametime"
STEP = "tick step 1"
PIG = registry_names(TARGET.minecraft_version, "minecraft:entity_type").index("minecraft:pig")
FIRST_PIG_ID = 100

PUSHING = "entities/pushing"

_SUMMON = re.compile(r"summon minecraft:pig (\S+) (\S+) (\S+) ")


@dataclass
class CrowdServer:
    """A fake server that joins like vanilla and answers Control, the barrier and the game time.

    Each pig Control summons becomes an `add_entity` to the watcher, with ids from
    `FIRST_PIG_ID` on, and a kill of the tagged entities removes them all. The frozen world's
    game time moves on only with `tick step`.
    """

    seen: list[Packet] = field(default_factory=list)
    _watcher: Peer | None = None
    _pigs: list[int] = field(default_factory=list)
    _summoned: int = 0
    _game_time: int = 0

    async def __call__(self, peer: Peer) -> None:
        """Serve one connection: a Handler."""
        with suppress(ConnectionError):
            await join_server(self.seen, JoinScript(commands=COMMANDS, then=self._play))(peer)

    async def _play(self, peer: Peer) -> None:
        if peer.name != CONTROL:
            self._watcher = peer
        requests = 0
        async for packet in peer.packets():
            self.seen.append(packet)
            if packet.name == CLIENT_COMMAND:
                requests += 1
                if (requests - 1) % SYNC_REQUESTS != 0:
                    await asyncio.sleep(TICK_S)  # a barrier's answers come a tick apart
                await peer.write(peer.raw_frame("minecraft:award_stats", NO_STATISTICS))
            elif packet.name == CHAT_COMMAND:
                await self._command(peer, str((packet.fields or {})["command"]))

    async def _command(self, peer: Peer, command: str) -> None:
        if command.startswith(MARKER):
            token = json.loads(command.removeprefix(MARKER))
            await peer.send("minecraft:system_chat", content=text(token), overlay=False)
        elif command == TIME_QUERY:
            answer = gametime_answer(self._game_time)
            await peer.send("minecraft:system_chat", content=answer, overlay=False)
        elif command.startswith("tick step "):
            self._game_time += int(command.removeprefix("tick step "))
        elif (summon := _SUMMON.match(command)) is not None:
            await self._add(*(float(axis) for axis in summon.groups()))
        elif command == KILL_PIGS and self._pigs:
            await self._to_watcher("minecraft:remove_entities", entity_ids=list(self._pigs))
            self._pigs.clear()

    async def _add(self, x: float, y: float, z: float) -> None:
        entity_id = FIRST_PIG_ID + self._summoned
        self._summoned += 1
        self._pigs.append(entity_id)
        await self._to_watcher(
            "minecraft:add_entity",
            entity_id=entity_id,
            entity_uuid=uuid.UUID(int=entity_id),
            type=PIG,
            x=x,
            y=y,
            z=z,
            velocity={"scale": 0, "x": 0, "y": 0, "z": 0},
            pitch=0,
            yaw=64,
            head_yaw=64,
            data=0,
        )

    async def _to_watcher(self, name: str, **fields: object) -> None:
        if self._watcher is not None:
            await self._watcher.send(name, **fields)


@dataclass(frozen=True)
class Played:
    """A played Group: its windows, Control's commands around them, its samples, its Transcript."""

    windows: tuple[Window, ...]
    first: tuple[str, ...]
    after: tuple[str, ...]
    samples: Mapping[str, tuple[object, ...]]
    transcript: Transcript


async def replay(group_id: str, server: CrowdServer) -> Played:
    """Play `group_id` against `server`; read what the Transcript shows, and the samples."""
    transcript = Transcript(group_id=group_id, server="fake")
    async with playing(server, transcript) as context:
        await GROUPS[group_id].run(context)
        samples = {name: series.values for name, series in context.samples.items()}
    windows = read(transcript)
    return Played(windows.windows, windows.first, windows.after, samples, transcript)


_PLAYS: dict[str, Played] = {}
"""Each Group's play against a default fake server; no test changes it."""


async def play(group_id: str) -> Played:
    """The play of `group_id` against a default fake server, played the first time it is asked."""
    if group_id not in _PLAYS:
        _PLAYS[group_id] = await replay(group_id, CrowdServer())
    return _PLAYS[group_id]


def joined_at(transcript: Transcript) -> int:
    """When the watcher said hello."""
    return next(
        e.t_ns for e in transcript.events if e.bot != CONTROL and e.packet.name == "minecraft:hello"
    )


pytestmark = [pytest.mark.timeout(300), pytest.mark.usefixtures("long_play")]


def pig(x: float, z: float) -> str:
    """The summon of a still, tagged pig that drops nothing, facing west, at `x`, -60, `z`."""
    nbt = (
        'NoAI:1b,PersistenceRequired:1b,DeathLootTable:"minecraft:empty",Rotation:[90f,0f],'
        f'Tags:["{TAG}"]'
    )
    return f"summon minecraft:pig {x} -60 {z} {{{nbt}}}"


SETUP = (
    "gamerule player_movement_check false",
    "gamerule respawn_radius 0",
    "tp control 96.5 -60 96.5",
    "gamerule mob_griefing false",
    "gamerule mob_drops false",
    "tick freeze",
)
"""What Control runs before the watcher joins, in order."""

CLEAR = (KILL_PIGS, TIME_QUERY, "tick step 25", TIME_QUERY, KILL_ITEMS)
"""What Control runs after a crowd's window: the pigs die, the world steps until their bodies are
gone, and anything they dropped goes."""

TEARDOWN = (
    KILL_PIGS,
    KILL_ITEMS,
    "gamerule mob_drops false",
    KILL_PIGS,
    "gamerule mob_drops true",
    "tick unfreeze",
    "gamerule mob_drops true",
    "gamerule mob_griefing true",
    "gamerule respawn_radius 10",
    "gamerule player_movement_check true",
    "tick unfreeze",
)
"""What Control runs last: the pigs and items go, the watcher waits until it is told they are
gone, the rules come back, then the GroupContext unfreezes the world it froze."""


# Every Group


def test_the_groups_package_imports_the_module_so_that_every_run_has_its_groups() -> None:
    assert "entities_crowding" in mscts.groups.__all__


# `entities/pushing`

PEN = ("fill 3 -60 3 5 -60 5 minecraft:oak_fence", "setblock 4 -60 4 minecraft:air")
PUSH_WINDOW = (
    f"{OBSERVE_OPEN} minecraft:bundle_delimiter minecraft:add_entity minecraft:set_entity_data "
    "minecraft:set_entity_motion minecraft:update_attributes minecraft:damage_event "
    "minecraft:entity_event minecraft:remove_entities"
)
"""The open Mark of every window of `entities/pushing`: the pigs appearing, their data and
velocity, any hurt or death, and their removal; no movement packet."""


def ring(count: int, centre: tuple[float, float]) -> list[str]:
    """The summons of `count` pigs 0.2 blocks around `centre`, from the east, anticlockwise."""
    cx, cz = centre
    angles = [2 * math.pi * i / count for i in range(count)]
    return [
        pig(round(cx + 0.2 * math.cos(angle), 3), round(cz + 0.2 * math.sin(angle), 3))
        for angle in angles
    ]


def test_pushing_is_tick_exact_on_the_default_spec_and_needs_and_masks_nothing() -> None:
    group = GROUPS[PUSHING]
    default = ServerSpec(host="127.0.0.1", port=25566)

    assert group.kind is GroupKind.TICK_EXACT
    assert group.requires == ()
    assert group.masks == ()
    assert group.spec(default) == default


@pytest.mark.asyncio
async def test_pushing_freezes_the_world_with_no_griefing_or_drops_then_builds_the_pen() -> None:
    result = await play(PUSHING)
    joined = joined_at(result.transcript)
    before_join = [c for t, c in control_commands(result.transcript) if t < joined]

    assert before_join == list(SETUP)
    assert result.first == (*SETUP, *PEN)


@pytest.mark.asyncio
async def test_pushing_narrows_every_window_to_the_pigs_data_velocity_hurts_and_removal() -> None:
    result = await play(PUSHING)

    assert [window.label for window in result.windows] == [PUSH_WINDOW] * 6


@pytest.mark.asyncio
async def test_pushing_summons_2_5_and_12_pigs_in_the_pen_then_in_the_open_and_steps_5_ticks() -> (
    None
):
    result = await play(PUSHING)
    crowds = [ring(count, centre) for centre in ((4.5, 4.5), (10.5, 4.5)) for count in (2, 5, 12)]

    assert [window.commands for window in result.windows] == [
        (*crowd, *[STEP] * 5) for crowd in crowds
    ]
    assert [window.ticks for window in result.windows] == [5] * 6


def test_the_pigs_of_a_crowd_stand_apart_so_that_each_has_a_name_of_its_own() -> None:
    assert ring(2, (4.5, 4.5)) == [pig(4.7, 4.5), pig(4.3, 4.5)]
    assert len(set(ring(12, (4.5, 4.5)))) == 12


@pytest.mark.asyncio
async def test_pushing_kills_each_crowd_and_steps_until_the_bodies_are_gone() -> None:
    result = await play(PUSHING)

    assert [window.before for window in result.windows[1:]] == [CLEAR] * 5


@pytest.mark.asyncio
async def test_pushing_takes_the_pen_away_then_undoes_the_fixture_after_the_last_crowd() -> None:
    result = await play(PUSHING)

    assert result.after == (*CLEAR, "fill 3 -60 3 5 -60 5 minecraft:air", *TEARDOWN)
