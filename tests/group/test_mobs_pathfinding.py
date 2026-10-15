"""The mobs Groups: what Control sets up, what each play samples, and what is undone after.

Every test plays a Group against a fake server. The fake joins like vanilla, answers Control's
markers and the barrier, tells the Bot about each entity Control summons, and sends the Bot a
scripted list of packets once Control steps the world. It answers each `time query gametime`
with the next of a scripted list of game times, so a test knows which tick each sample holds.
"""

import asyncio
import json
import re
import uuid
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field

import pytest

import mscts.groups
from mscts.bot import SYNC_REQUESTS
from mscts.codec.packets import Direction, Packet, State
from mscts.codec.registry_names import registry_names
from mscts.group import GROUPS, GroupContext, GroupKind
from mscts.groups import mobs_pathfinding
from mscts.spec import Difficulty, ServerSpec
from mscts.stats import Sample, SampleLog
from mscts.target import TARGET
from mscts.transcript import Transcript
from tests.group.test_control import CODEC, PLAY_TIMEOUT_S, text, tree
from tests.net.fakes import NO_STATISTICS, TICK_S, JoinScript, Peer, join_server, serve

CONTROL = "control"
MARKER = "tellraw @s "
CHAT_COMMAND, CLIENT_COMMAND = "minecraft:chat_command", "minecraft:client_command"
COMMANDS = tree("gamerule", "tp", "tick", "summon", "kill", "time", "fill", "setblock", "tellraw")
TAG = "mscts_mobs"
TIME_QUERY = "time query gametime"

GAMETIME_ANSWER = bytes.fromhex(
    "0a09000477697468040000000100000000000000380800097472616e736c617465001c"
    "636f6d6d616e64732e74696d652e71756572792e67616d6574696d650000"
)[:-1]
"""What vanilla 26.3 answered to `time query gametime` at game time 56: a system_chat's
content, recorded live, without the overlay byte that follows it."""

PUMPKIN_GAMETIME_ANSWER = bytes.fromhex(
    "0a0800097472616e736c617465001c636f6d6d616e64732e74696d652e71756572792e67616d6574696d65"
    "090004776974680800000001000231360000"
)[:-1]
"""What Pumpkin answered at game time 16, recorded live as above: the time as a String, after
the translation key."""

ENTITY_TYPES = registry_names(TARGET.minecraft_version, "minecraft:entity_type")
PLAYER_ID = 1
"""The Bot's own entity id: the fake never tells the Bot about it, as vanilla does not."""

_SUMMON = re.compile(r"summon minecraft:(\w+) (\S+) (\S+) (\S+) ")


def gametime_answer(value: int) -> bytes:
    """Vanilla's answer to `time query gametime` at game time `value`."""
    return GAMETIME_ANSWER[:13] + value.to_bytes(8, "big") + GAMETIME_ANSWER[21:]


def moved(entity_id: int, dx: float, dz: float = 0.0) -> tuple[str, dict[str, object]]:
    """A `move_entity_pos` of `entity_id` by `dx` and `dz` blocks."""
    linear = {"x": round(dx * 4096), "y": 0, "z": round(dz * 4096)}
    return "minecraft:move_entity_pos", {
        "entity_id": entity_id,
        "movement": {"on_ground": True, "linear": linear},
    }


def hurt(entity_id: int) -> tuple[str, dict[str, object]]:
    """A `damage_event` of `entity_id`, hit by the zombie (the first entity summoned)."""
    return "minecraft:damage_event", {
        "entity_id": entity_id,
        "source_type": 0,
        "source_cause_id": ZOMBIE_ID,
        "source_direct_id": ZOMBIE_ID,
        "source_position": None,
    }


ZOMBIE_ID = 100
"""The entity id the fake gives the first entity Control summons; the next gets 101."""


@dataclass
class MobsServer:
    """A fake server for the mobs Groups.

    Each summon becomes an `add_entity` to the Bot, with ids from `ZOMBIE_ID` on. Once Control
    steps the world (`tick step`), the Bot is sent `after_step`. Each `time query gametime`
    is answered with the next of `gametimes`. A kill of the tagged entities removes them all.
    """

    gametimes: list[int] = field(default_factory=list)
    after_step: Sequence[tuple[str, Mapping[str, object]]] = ()
    seen: list[Packet] = field(default_factory=list)
    _bot: Peer | None = None
    _summoned: list[int] = field(default_factory=list)
    _added: int = 0

    async def __call__(self, peer: Peer) -> None:
        """Serve one connection: a Handler."""
        with suppress(ConnectionError):
            await join_server(self.seen, JoinScript(commands=COMMANDS, then=self._play))(peer)

    async def _play(self, peer: Peer) -> None:
        if peer.name != CONTROL:
            self._bot = peer
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
            answer = gametime_answer(self.gametimes.pop(0))
            await peer.send("minecraft:system_chat", content=answer, overlay=False)
        elif (summon := _SUMMON.match(command)) is not None:
            await self._add(summon)
        elif command.startswith("tick step "):
            for name, fields in self.after_step:
                await self._to_bot(name, **fields)
        elif command == f"kill @e[tag={TAG}]" and self._summoned:
            await self._to_bot("minecraft:remove_entities", entity_ids=list(self._summoned))
            self._summoned.clear()

    async def _add(self, summon: re.Match[str]) -> None:
        entity_id = ZOMBIE_ID + self._added
        self._added += 1
        self._summoned.append(entity_id)
        kind, x, y, z = summon.groups()
        await self._to_bot(
            "minecraft:add_entity",
            entity_id=entity_id,
            entity_uuid=uuid.UUID(int=entity_id),
            type=ENTITY_TYPES.index(f"minecraft:{kind}"),
            x=float(x),
            y=float(y),
            z=float(z),
            velocity={"scale": 0, "x": 0, "y": 0, "z": 0},
            pitch=0,
            yaw=0,
            head_yaw=0,
            data=0,
        )

    async def _to_bot(self, name: str, /, **fields: object) -> None:
        assert self._bot is not None, "Control acted before the Bot joined"
        await self._bot.send(name, **fields)


@dataclass(frozen=True)
class Play:
    """A played Group: what Control ran, the Bot's name, and the samples it recorded."""

    commands: tuple[str, ...]
    bot: str
    samples: Mapping[str, tuple[Sample, ...]]


def _commands(transcript: Transcript) -> tuple[str, ...]:
    """Every command Control sent but a marker, in order."""
    return tuple(
        command
        for event in transcript.events
        if event.bot == CONTROL
        and event.packet.direction is Direction.SERVERBOUND
        and event.packet.name == CHAT_COMMAND
        and not (command := str((event.packet.fields or {})["command"])).startswith(MARKER)
    )


def _bot_name(transcript: Transcript) -> str:
    return next(
        str((e.packet.fields or {})["name"])
        for e in transcript.events
        if e.packet.name == "minecraft:hello" and e.bot != CONTROL
    )


@asynccontextmanager
async def _playing(server: MobsServer, play_number: int) -> AsyncIterator[GroupContext]:
    """A GroupContext of the `play_number`th play against `server`, closed however it ends."""
    samples = SampleLog()
    for _ in range(play_number + 1):
        samples.new_play()
    transcript = Transcript(group_id="test/mobs", server="fake")
    async with serve(CODEC, server, timeout_s=PLAY_TIMEOUT_S) as endpoint:
        context = GroupContext(endpoint, transcript, timeout_s=2.0, samples=samples)
        try:
            yield context
        finally:
            await context.close()


async def replay(group_id: str, server: MobsServer, play_number: int = 0) -> Play:
    """Play `group_id` against `server` as its `play_number`th play; what it shows."""
    async with _playing(server, play_number) as context:
        await GROUPS[group_id].run(context)
    transcript = context._transcript  # noqa: SLF001 - the test reads what the play recorded
    samples = {name: series.values for name, series in context.samples.items()}
    return Play(_commands(transcript), _bot_name(transcript), samples)


PLAY_NUMBER = 7
"""Which play of its Group each cached play is: the Bot's name ends in it."""

_SERVERS: dict[str, Callable[[], MobsServer]] = {}
"""The fake server each Group's cached play is played against, by Group id."""

_PLAYS: dict[str, Play] = {}
"""Each Group's play against its `_SERVERS` fake; no test changes it."""


async def play(group_id: str) -> Play:
    """The play of `group_id` against its default fake server, played the first time it is asked."""
    if group_id not in _PLAYS:
        _PLAYS[group_id] = await replay(group_id, _SERVERS[group_id](), PLAY_NUMBER)
    return _PLAYS[group_id]


def summoned(entity: str, at: str, nbt: str) -> str:
    return f'summon minecraft:{entity} {at} {{{nbt},Rotation:[90f,0f],Tags:["{TAG}"]}}'


ZOMBIE = (
    'PersistenceRequired:1b,DeathLootTable:"minecraft:empty",drop_chances:{head:0.0f},'
    'equipment:{head:{id:"minecraft:leather_helmet",count:1}}'
)

TEARDOWN = (
    f"kill @e[tag={TAG}]",
    "kill @e[type=minecraft:item]",
    "gamerule mob_drops false",
    f"kill @e[tag={TAG}]",
    "gamerule mob_drops true",
    "tick unfreeze",
)
"""What Control runs once a play is over: the mobs and anything they dropped go, then the Bot
waits until it is told the bodies are gone (`remove_tagged_until_gone`)."""


# Registration


def test_the_groups_package_imports_the_module_so_that_every_run_has_its_groups() -> None:
    assert "mobs_pathfinding" in mscts.groups.__all__
    assert mscts.groups.mobs_pathfinding is mobs_pathfinding


SPECS = {"mobs/chase-open": Difficulty.NORMAL, "mobs/chase-maze": Difficulty.NORMAL}


@pytest.mark.parametrize("group_id", sorted(SPECS))
def test_each_group_is_statistical_needs_nothing_masks_nothing_and_sets_its_difficulty(
    group_id: str,
) -> None:
    group = GROUPS[group_id]
    default = ServerSpec(host="127.0.0.1", port=25566)

    assert group.kind is GroupKind.STATISTICAL
    assert group.requires == ()
    assert group.masks == ()
    assert group.spec(default) == ServerSpec(
        host="127.0.0.1", port=25566, difficulty=SPECS[group_id]
    )


# The clock: the game time Control reads


def _answer(content: bytes) -> Packet:
    frame = CODEC.encode(
        State.PLAY,
        Direction.CLIENTBOUND,
        "minecraft:system_chat",
        {"content": content, "overlay": False},
    )
    return CODEC.decode(State.PLAY, Direction.CLIENTBOUND, frame)


def test_the_game_time_is_read_from_vanillas_answer_a_long() -> None:
    assert mobs_pathfinding.gametime([_answer(GAMETIME_ANSWER)]) == 56


def test_the_game_time_is_read_from_pumpkins_answer_a_string_after_the_key() -> None:
    assert mobs_pathfinding.gametime([_answer(PUMPKIN_GAMETIME_ANSWER)]) == 16


def test_the_game_time_is_read_from_its_answer_among_other_messages() -> None:
    said = [_answer(text("Summoned new Zombie")), _answer(gametime_answer(2**40))]

    assert mobs_pathfinding.gametime(said) == 2**40


def test_no_answer_with_the_game_time_is_a_value_error() -> None:
    with pytest.raises(ValueError, match="no answer to time query gametime"):
        mobs_pathfinding.gametime([_answer(text("Unknown command"))])


# `mobs/chase-open`

OPEN_SETUP = (
    "tp control 96.5 -60 96.5",
    "tp open7 0.5 -60.0 0.5",
    "tick freeze",
    summoned("zombie", "16.5 -60.0 0.5", ZOMBIE),
    TIME_QUERY,
    "tick step 300",
)


def _chase() -> MobsServer:
    """The zombie comes half a block closer in its second move, and then hits the Bot."""
    return MobsServer(
        gametimes=[1000, 1028, 1148],
        after_step=(
            moved(ZOMBIE_ID, -0.25),
            moved(ZOMBIE_ID, -0.25),
            moved(ZOMBIE_ID, -0.25),
            hurt(PLAYER_ID),
        ),
    )


_SERVERS["mobs/chase-open"] = _chase


@pytest.mark.asyncio
async def test_chase_open_joins_a_bot_of_its_play_and_summons_a_zombie_16_blocks_east() -> None:
    result = await play("mobs/chase-open")

    assert result.bot == "open7"
    assert result.commands[: len(OPEN_SETUP)] == OPEN_SETUP


@pytest.mark.asyncio
async def test_chase_open_samples_when_the_zombie_came_half_a_block_closer_and_hit() -> None:
    result = await play("mobs/chase-open")

    assert result.samples == {"chase_open.moved": (28.0,), "chase_open.hit": (148.0,)}
    assert result.commands[-len(TEARDOWN) - 2 :] == (TIME_QUERY, *TEARDOWN, "tick unfreeze")


@pytest.mark.asyncio
async def test_a_chase_samples_nothing_it_did_not_see_and_ends_when_the_budget_has_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(mobs_pathfinding, "_IDLE_S", 0.2)
    # The zombie comes 0.4 blocks closer, then nothing: the budget runs out at the third read.
    server = MobsServer(gametimes=[1000, 1100, 1299, 1300], after_step=(moved(ZOMBIE_ID, -0.4),))

    result = await replay("mobs/chase-open", server)

    assert result.samples == {}
    assert result.commands[len(OPEN_SETUP) :] == (
        TIME_QUERY,
        TIME_QUERY,
        TIME_QUERY,
        *TEARDOWN,
        "tick unfreeze",
    )
    assert server.gametimes == []


# `mobs/chase-maze`

MAZE_WALL = (
    "fill 8 -60 -10 8 -60 4 minecraft:oak_fence",
    "fill 8 -60 6 8 -60 10 minecraft:oak_fence",
)
MAZE_CLEAR = "fill 8 -60 -10 8 -60 10 minecraft:air"

MAZE_SETUP = (
    "tp control 96.5 -60 96.5",
    "tp maze7 0.5 -60.0 0.5",
    *MAZE_WALL,
    "tick freeze",
    summoned("zombie", "16.5 -60.0 0.5", ZOMBIE),
    TIME_QUERY,
    "tick step 400",
)


def _through_the_gap() -> MobsServer:
    """The zombie walks to the gap at z 5 (8 blocks west, 4.5 north), through it, and hits."""
    return MobsServer(
        gametimes=[1000, 1105, 1179],
        after_step=(
            moved(ZOMBIE_ID, -4.0, 4.5),
            moved(ZOMBIE_ID, -3.0),  # x 9.5: not yet in the gap
            moved(ZOMBIE_ID, -1.0),  # x 8.5: in it
            moved(ZOMBIE_ID, -1.0),
            hurt(PLAYER_ID),
        ),
    )


_SERVERS["mobs/chase-maze"] = _through_the_gap


@pytest.mark.asyncio
async def test_chase_maze_builds_a_fence_with_a_gap_between_the_bot_and_the_zombie() -> None:
    result = await play("mobs/chase-maze")

    assert result.bot == "maze7"
    assert result.commands[: len(MAZE_SETUP)] == MAZE_SETUP


@pytest.mark.asyncio
async def test_chase_maze_samples_when_the_zombie_got_into_the_gap_and_hit() -> None:
    result = await play("mobs/chase-maze")

    assert result.samples == {"chase_maze.gap": (105.0,), "chase_maze.hit": (179.0,)}


@pytest.mark.asyncio
async def test_chase_maze_takes_the_fence_down_after_the_mobs_have_gone() -> None:
    result = await play("mobs/chase-maze")

    assert result.commands[-len(TEARDOWN) - 3 :] == (
        TIME_QUERY,
        *TEARDOWN,
        MAZE_CLEAR,
        "tick unfreeze",
    )
