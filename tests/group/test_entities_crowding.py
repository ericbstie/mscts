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
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass, field

import pytest
from support.control import playing, text, tree
from support.control_play import Window, control_commands, read
from support.gametime import gametime_answer

import mscts.groups
from mscts.bot import SYNC_REQUESTS
from mscts.case_titles import TITLES
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
HEALTH = 9
"""The index of a living entity's health in its entity data."""
FULL_HEALTH = 10.0

PUSHING = "entities/pushing"

_SUMMON = re.compile(r"summon minecraft:pig (\S+) (\S+) (\S+) ")


@dataclass
class CrowdServer:
    """A fake server that joins like vanilla and answers Control, the barrier and the game time.

    Each pig Control summons becomes an `add_entity` to the watcher, with ids from
    `FIRST_PIG_ID` on, and a kill of the tagged entities removes them all. The frozen world's
    game time moves on only with `tick step`. What the watcher is told reaches it only with
    the answer to its next statistics request, as a tick's packets reach a player some time
    after Control's command: so a play reads them only after a barrier.
    """

    health: Mapping[int, Sequence[tuple[int, float]]] = field(default_factory=dict)
    """The pigs whose health changes on each tick: by the tick since the freeze, each pig by
    its number in summon order, from 0, and its new health."""
    full_health_sent: bool = True
    """Whether a pig's full health follows its `add_entity`, as vanilla sends it."""
    seen: list[Packet] = field(default_factory=list)
    _watcher: Peer | None = None
    _pigs: list[int] = field(default_factory=list)
    _summoned: int = 0
    _game_time: int = 0
    _queued: list[bytes] = field(default_factory=list)

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
                told = b"".join(self._queued) if peer is self._watcher else b""
                if peer is self._watcher:
                    self._queued.clear()
                await peer.write(told + peer.raw_frame("minecraft:award_stats", NO_STATISTICS))
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
            self._step(int(command.removeprefix("tick step ")))
        elif (summon := _SUMMON.match(command)) is not None:
            self._add(*(float(axis) for axis in summon.groups()))
        elif command == KILL_PIGS and self._pigs:
            self._to_watcher("minecraft:remove_entities", entity_ids=list(self._pigs))
            self._pigs.clear()

    def _add(self, x: float, y: float, z: float) -> None:
        entity_id = FIRST_PIG_ID + self._summoned
        self._summoned += 1
        self._pigs.append(entity_id)
        self._to_watcher(
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
        if self.full_health_sent:
            self._send_health(entity_id, FULL_HEALTH)

    def _step(self, ticks: int) -> None:
        """Run `ticks` ticks: send the health of each pig `health` changes in them."""
        for tick in range(self._game_time + 1, self._game_time + ticks + 1):
            for number, health in self.health.get(tick, ()):
                self._send_health(FIRST_PIG_ID + number, health)
        self._game_time += ticks

    def _send_health(self, entity_id: int, health: float) -> None:
        entry = {"index": HEALTH, "serializer": "float", "value": health}
        self._to_watcher("minecraft:set_entity_data", entity_id=entity_id, entries=[entry])

    def _to_watcher(self, name: str, **fields: object) -> None:
        if self._watcher is not None:
            self._queued.append(self._watcher.frame(name, **fields))


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
        _PLAYS[group_id] = await replay(group_id, DEFAULT_SERVERS[group_id]())
    return _PLAYS[group_id]


DEFAULT_SERVERS: dict[str, Callable[[], CrowdServer]] = {
    "entities/pushing": CrowdServer,
    "entities/cramming": lambda: CrowdServer(health=DEFAULT_HITS),
}
"""The fake server each Group's default play is against."""


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


# `entities/cramming`

CRAMMING = "entities/cramming"

CRAM_SETUP = (
    "gamerule player_movement_check false",
    "gamerule respawn_radius 0",
    "tp control 96.5 -60 96.5",
    "gamerule mob_griefing false",
    "gamerule mob_drops false",
    "gamerule max_entity_cramming 0",
    "tick freeze",
)
"""What Control runs before the watcher joins: cramming starts off."""

GRID = [
    pig(x, z)
    for z in (12.34, 12.42, 12.5, 12.58, 12.66)
    for x in (8.3, 8.38, 8.46, 8.54, 8.62, 8.7)
]
"""The 30 pigs, 0.08 blocks apart in rows of 6 round (8.5, 12.5), from the north-west."""

CRAM_PLAY = (
    *GRID,
    TIME_QUERY,
    "tick step 10",
    TIME_QUERY,
    "gamerule max_entity_cramming 24",
    STEP,
    TIME_QUERY,
    "tick step 9",
    TIME_QUERY,
    *[STEP] * 10,
)
"""What Control runs once the watcher has joined: the crowd stands 10 ticks with cramming off,
then 1 tick, 9 more and 10 more, a tick at a time, with it on."""

CRAM_TEARDOWN = (
    KILL_PIGS,
    KILL_ITEMS,
    "gamerule mob_drops false",
    KILL_PIGS,
    "gamerule mob_drops true",
    "tick unfreeze",
    "gamerule max_entity_cramming 24",
    "gamerule mob_drops true",
    "gamerule mob_griefing true",
    "gamerule respawn_radius 10",
    "gamerule player_movement_check true",
    "tick unfreeze",
)

ON = 10
"""The tick, counted from the freeze, after which cramming is on: cramming's tick k is ON + k."""


def test_cramming_is_statistical_on_the_default_spec_and_plays_20_times() -> None:
    group = GROUPS[CRAMMING]
    default = ServerSpec(host="127.0.0.1", port=25566)

    assert group.kind is GroupKind.STATISTICAL
    assert group.runs == 20
    assert group.requires == ()
    assert group.masks == ()
    assert group.spec(default) == default


@pytest.mark.asyncio
async def test_cramming_turns_cramming_off_and_freezes_before_a_watcher_of_its_play_joins() -> None:
    result = await play(CRAMMING)
    joined = joined_at(result.transcript)
    before_join = [c for t, c in control_commands(result.transcript) if t < joined]
    watchers = {e.bot for e in result.transcript.events if e.bot != CONTROL}

    assert before_join == list(CRAM_SETUP)
    assert len(watchers) == 1
    assert next(iter(watchers)).startswith("crowd")


@pytest.mark.asyncio
async def test_cramming_summons_30_pigs_then_steps_10_ticks_off_and_20_on() -> None:
    result = await play(CRAMMING)
    commands = [c for _, c in control_commands(result.transcript)]

    assert commands == [*CRAM_SETUP, *CRAM_PLAY, *CRAM_TEARDOWN]
    assert result.windows == ()


DEFAULT_HITS = {
    ON + 1: ((0, 4.0), (1, 4.0), (2, 4.0)),
    ON + 5: ((3, 4.0),),
    ON + 10: ((4, 4.0),),
    ON + 11: ((0, 0.0), (5, 4.0)),
    ON + 14: ((1, 0.0),),
}
"""What the default fake sends: three pigs hurt on cramming's tick 1, one on tick 5 and one on
tick 10; on tick 11 one dies and another is hurt, and on tick 14 another dies."""


@pytest.mark.asyncio
async def test_cramming_samples_the_pigs_hurt_by_tick_1_and_by_tick_10_and_the_last_death() -> None:
    result = await play(CRAMMING)

    assert result.samples == {
        "cramming.hurt_when_off": (0.0,),
        "cramming.hurt_by_tick_1": (3.0,),
        "cramming.hurt_by_tick_10": (5.0,),
        "cramming.last_death": (14.0,),
        "cramming.alive": (28.0,),
    }


@pytest.mark.asyncio
async def test_cramming_counts_a_pig_hurt_while_cramming_is_off() -> None:
    result = await replay(CRAMMING, CrowdServer(health={3: ((7, 4.0),)}))

    assert result.samples["cramming.hurt_when_off"] == (1.0,)
    assert result.samples["cramming.hurt_by_tick_1"] == (1.0,)


@pytest.mark.asyncio
async def test_cramming_samples_no_death_when_no_pig_dies_with_cramming_on() -> None:
    result = await replay(CRAMMING, CrowdServer(health={5: ((0, 0.0),)}))

    assert "cramming.last_death" not in result.samples
    assert result.samples["cramming.alive"] == (29.0,)


@pytest.mark.asyncio
async def test_cramming_samples_a_death_on_the_last_tick_and_none_after_it() -> None:
    late = {ON + 20: ((0, 0.0),), ON + 21: ((1, 0.0),)}
    result = await replay(CRAMMING, CrowdServer(health=late))

    assert result.samples["cramming.last_death"] == (20.0,)
    assert result.samples["cramming.alive"] == (29.0,)


@pytest.mark.asyncio
async def test_cramming_takes_a_pig_the_server_sent_no_health_for_as_unhurt() -> None:
    # Pumpkin sends no health when a pig appears; vanilla sends 10.
    result = await replay(CRAMMING, CrowdServer(health=DEFAULT_HITS, full_health_sent=False))

    assert result.samples["cramming.hurt_by_tick_1"] == (3.0,)
    assert result.samples["cramming.alive"] == (28.0,)


@pytest.mark.asyncio
async def test_every_sample_of_cramming_has_a_title() -> None:
    result = await play(CRAMMING)

    assert sorted(set(result.samples) - TITLES.keys()) == []
