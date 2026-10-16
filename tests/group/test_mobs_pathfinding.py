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
COMMANDS = tree(
    "gamerule", "tp", "tick", "summon", "kill", "time", "fill", "setblock", "tellraw", "op", "deop"
)
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


type Sent = tuple[str, Mapping[str, object]]
"""A packet the fake sends the Bot: its name and fields."""

type Step = tuple[int, Sent]
"""A packet the fake sends the Bot once the world runs, and the tick it is sent on."""

START = 1000
"""The game time when Control first reads it."""

STEPPED = text("[control: Stepping 300 ticks]")
"""What the fake tells the Bot, an operator, when Control steps the world."""

CALIBRATION_TICKS = 40
CALIBRATION_RUNS_OUT_S = (SYNC_REQUESTS + 1) * TICK_S
"""How long after its answer the calibration step runs out: after `tick step` has returned
through Control, whose barrier answers come a tick apart."""

CALIBRATION_STAMP = 5
"""How far into the calibration step the `set_time` the play calibrates on is stamped."""


def set_time(game_time: int) -> bytes:
    """A `set_time` payload: the game time, a Long, then no clocks."""
    return game_time.to_bytes(8, "big") + b"\x00"


@dataclass
class MobsServer:
    """A fake server for the mobs Groups.

    Each summon becomes an `add_entity` to the Bot, with ids from `ZOMBIE_ID` on. A kill of
    the tagged entities removes them all. The frozen world's game time is `START` at first.
    A step of `CALIBRATION_TICKS` sends the Bot a `set_time` stamped with the frozen time,
    which a play must pass over, and one stamped `CALIBRATION_STAMP` ticks on, from the tick
    that ends a tick later. The next `time query gametime` is answered with that tick, plus
    `lag`; `CALIBRATION_RUNS_OUT_S` later the step runs out, and the Bot is sent a `set_time`
    with the new frozen time. A summon before then fails the fake: no mob may live before the
    play's step. Every step also tells the Bot, an operator, that Control stepped the world, in
    a `system_chat` that is no answer (`TickCommand.step` tells every operator).

    Any other step plays. It too sends the Bot a `set_time` stamped with the frozen time first,
    and another stamped `stamped` ticks into the step, sent in the tick after, before that
    tick's packets of `after_step`. Each `time query gametime` in it is answered with the game
    time before the step plus the tick of the last packet sent, plus `lag`, and the next packet
    of the step is sent just before the answer. So a play reads the tick of each packet once:
    on seeing it, or once it has waited `_IDLE_S` for the next; and each packet arrives while
    the query before it is unanswered. While the world steps, it runs a tick for each barrier
    answer a tick after the last (`Bot.sync`), as a real world runs on while a barrier waits.
    Once every packet is sent, the time is `end`, and one tick more at each read after.
    With `hold`, the answer to that read of the play (from 0) comes after the next one's, as
    Pumpkin's answers may.
    """

    after_step: Sequence[Step] = ()
    end: int = 10_000
    lag: int = 0
    """How many ticks late a query in a step is answered, after a packet: 1 on Pumpkin."""
    hold: int | None = None
    stamped: int = CALIBRATION_STAMP
    """How many ticks into the play's step its `set_time` is stamped."""
    seen: list[Packet] = field(default_factory=list)
    reads: int = 0
    """How many times the game time was read in the play's step."""
    _bot: Peer | None = None
    _summoned: list[int] = field(default_factory=list)
    _added: int = 0
    _frozen: int = START
    _calibrating: bool = False
    _now: int = 0
    _sent: int = 0
    _set_time_sent: bool = False
    _stepped: bool = False
    _held: bytes | None = None

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
                    self._now += int(self._stepped)  # and a stepping world runs on meanwhile
                await peer.write(peer.raw_frame("minecraft:award_stats", NO_STATISTICS))
            elif packet.name == CHAT_COMMAND:
                await self._command(peer, str((packet.fields or {})["command"]))

    async def _command(self, peer: Peer, command: str) -> None:
        if command.startswith(MARKER):
            token = json.loads(command.removeprefix(MARKER))
            await peer.send("minecraft:system_chat", content=text(token), overlay=False)
        elif command == TIME_QUERY:
            await self._time(peer)
        elif (summon := _SUMMON.match(command)) is not None:
            await self._add(summon)
        elif command == f"tick step {CALIBRATION_TICKS}":
            self._calibrating = True
            await self._to_bot("minecraft:system_chat", content=STEPPED, overlay=False)
            await self._to_bot_raw("minecraft:set_time", set_time(self._frozen))
            await self._to_bot_raw("minecraft:set_time", set_time(self._calibrated_on))
        elif command.startswith("tick step "):
            self._stepped = True
            await self._to_bot("minecraft:system_chat", content=STEPPED, overlay=False)
            await self._to_bot_raw("minecraft:set_time", set_time(self._frozen))
        elif command == f"kill @e[tag={TAG}]" and self._summoned:
            await self._to_bot("minecraft:remove_entities", entity_ids=list(self._summoned))
            self._summoned.clear()

    @property
    def _calibrated_on(self) -> int:
        """The game time of the `set_time` a play calibrates on."""
        return self._frozen + CALIBRATION_STAMP

    async def _time(self, peer: Peer) -> None:
        """Answer `time query gametime`: frozen, in the calibration step, or in a play."""
        if self._calibrating:
            answer = self._calibrated_on + 1 + self.lag
        elif self._stepped:
            answer = self._frozen + self._now + self.lag
        else:
            answer = self._frozen
        if self._stepped:  # the next packet goes first, so the Bot has it when Control reads
            await self._next()
        await self._answer(peer, gametime_answer(answer))
        if self._calibrating:  # the step runs out after Control's barrier for it has passed
            await asyncio.sleep(CALIBRATION_RUNS_OUT_S)
            self._calibrating = False
            self._frozen += CALIBRATION_TICKS
            await self._to_bot_raw("minecraft:set_time", set_time(self._frozen))

    async def _answer(self, peer: Peer, content: bytes) -> None:
        """Send `content`, unless it is the read `hold` names; then the held one, if any."""
        play_read = self.reads if self._stepped else None
        self.reads += int(self._stepped)
        if play_read is not None and play_read == self.hold:
            self._held = content
            return
        await peer.send("minecraft:system_chat", content=content, overlay=False)
        if self._held is not None:
            held, self._held = self._held, None
            await peer.send("minecraft:system_chat", content=held, overlay=False)

    async def _next(self) -> None:
        """Send the Bot the step's next packet, or move the time on past them all."""
        if not self._set_time_sent and self._set_time_first():
            self._set_time_sent = True
            self._now = self.stamped + 1
            await self._to_bot_raw("minecraft:set_time", set_time(self._frozen + self.stamped))
        elif self._sent < len(self.after_step):
            self._now, (name, fields) = self.after_step[self._sent]
            self._sent += 1
            await self._to_bot(name, **fields)
        else:
            self._now = max(self.end, self._now + 1)

    def _set_time_first(self) -> bool:
        """Whether the step's `set_time` comes before the next packet of `after_step`, if any.

        It is sent in the tick after its stamp, before that tick's other packets.
        """
        return self._sent == len(self.after_step) or self.after_step[self._sent][0] > self.stamped

    async def _add(self, summon: re.Match[str]) -> None:
        assert not self._calibrating, "a mob was summoned while the calibration step ran"
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

    async def _to_bot_raw(self, name: str, payload: bytes) -> None:
        assert self._bot is not None, "Control acted before the Bot joined"
        await self._bot.write(self._bot.raw_frame(name, payload))


@pytest.fixture(autouse=True)
def _short_idle(monkeypatch: pytest.MonkeyPatch) -> None:
    """A play waits 0.1 s, not a second, for a packet before it reads the game time."""
    monkeypatch.setattr(mobs_pathfinding, "_IDLE_S", 0.1)


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
    joined = _bot_name(transcript)
    run = context.player_name("").removesuffix(str(context.play))  # random, so left out
    bot = joined.replace(run, "", 1)
    commands = tuple(command.replace(joined, bot) for command in _commands(transcript))
    return Play(commands, bot, samples)


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

CALIBRATE = (TIME_QUERY, f"tick step {CALIBRATION_TICKS}")
"""What Control runs to calibrate the play's clock, in the frozen world before the summons: the
Bot reads the game time after the `set_time` itself."""

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


SPECS = {
    "mobs/chase-open": Difficulty.NORMAL,
    "mobs/chase-maze": Difficulty.NORMAL,
    "mobs/doors-hard": Difficulty.HARD,
    "mobs/doors-normal": Difficulty.NORMAL,
    "mobs/targets": Difficulty.NORMAL,
}


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


RUNS = {
    "mobs/chase-open": 25,
    "mobs/chase-maze": 20,
    "mobs/doors-hard": 15,
    "mobs/doors-normal": 10,
    "mobs/targets": 15,
}
"""How many plays each Group has on each server: as many as fit its Self-check in about 10
minutes, from the length of a vanilla play."""


@pytest.mark.parametrize("group_id", sorted(RUNS))
def test_each_group_plays_as_many_times_as_its_budget_of_time_allows(group_id: str) -> None:
    assert GROUPS[group_id].runs == RUNS[group_id]


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


def test_a_number_in_another_answer_is_not_the_game_time() -> None:
    daytime = GAMETIME_ANSWER.replace(b"gametime", b"daytime_")
    said = [_answer(daytime), _answer(gametime_answer(77))]

    assert mobs_pathfinding.gametime(said) == 77


def test_an_answer_with_the_key_but_no_arguments_is_no_game_time() -> None:
    with pytest.raises(ValueError, match="no answer to time query gametime"):
        mobs_pathfinding.gametime([_answer(text("commands.time.query.gametime"))])


def test_no_answer_with_the_game_time_is_a_value_error() -> None:
    with pytest.raises(ValueError, match="no answer to time query gametime"):
        mobs_pathfinding.gametime([_answer(text("Unknown command"))])


# `mobs/chase-open`

OPEN_SETUP = (
    "tp control 96.5 -60 96.5",
    "tp open7 0.5 -60.0 0.5",
    "op open7",
    "tick freeze",
    *CALIBRATE,
    summoned("zombie", "16.5 -60.0 0.5", ZOMBIE),
    TIME_QUERY,
    "tick step 300",
)


def _chase() -> MobsServer:
    """The zombie comes half a block closer in its second move, and then hits the Bot."""
    return MobsServer(
        after_step=(
            (25, moved(ZOMBIE_ID, -0.25)),
            (28, moved(ZOMBIE_ID, -0.25)),
            (31, moved(ZOMBIE_ID, -0.25)),
            (100, hurt(ZOMBIE_ID)),  # the zombie's own hurt is not a hit
            (148, hurt(PLAYER_ID)),
            (160, hurt(PLAYER_ID)),
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
    assert result.commands[-len(TEARDOWN) - 2 :] == (*TEARDOWN, "deop open7", "tick unfreeze")


@pytest.mark.asyncio
async def test_a_server_that_answers_a_tick_late_gives_the_same_samples() -> None:
    # Pumpkin answers a query sent after a packet a tick later than vanilla: the play's
    # calibration measures that, and every sample subtracts it.
    server = MobsServer(after_step=_chase().after_step, lag=1)

    result = await replay("mobs/chase-open", server)

    assert result.samples == {"chase_open.moved": (28.0,), "chase_open.hit": (148.0,)}


@pytest.mark.asyncio
async def test_an_event_arriving_while_a_read_is_unanswered_is_read_at_its_own_tick() -> None:
    # The hit is sent while the read of the step to the waypoint is still unanswered.
    server = MobsServer(
        after_step=(
            (25, moved(ZOMBIE_ID, -0.25)),
            (28, moved(ZOMBIE_ID, -0.25)),
            (30, hurt(PLAYER_ID)),
        ),
    )

    result = await replay("mobs/chase-open", server)

    assert result.samples == {"chase_open.moved": (28.0,), "chase_open.hit": (30.0,)}


@pytest.mark.asyncio
async def test_answers_that_come_out_of_order_go_to_the_reads_in_the_order_of_their_ticks() -> None:
    # The answer to the read of the step to the waypoint (the third read: the step's `set_time`
    # and the zombie's move each come after one) comes after the answer to the read of the hit.
    server = MobsServer(
        after_step=((28, moved(ZOMBIE_ID, -0.5)), (30, hurt(PLAYER_ID))),
        hold=2,
    )

    result = await replay("mobs/chase-open", server)

    assert result.samples == {"chase_open.moved": (28.0,), "chase_open.hit": (30.0,)}


@pytest.mark.asyncio
async def test_a_calibration_answered_after_its_step_ran_out_fails_the_play() -> None:
    # Answered with the game time the step ends at: it may have run out first.
    server = MobsServer(
        after_step=_chase().after_step, lag=CALIBRATION_TICKS - CALIBRATION_STAMP - 1
    )

    with pytest.raises(RuntimeError, match="calibration step ran out"):
        await replay("mobs/chase-open", server)


@pytest.mark.asyncio
async def test_a_chase_samples_nothing_it_did_not_see_and_ends_when_the_budget_has_run() -> None:
    # The zombie comes 0.4 blocks closer at tick 100, then nothing: tick 300 ends the play.
    server = MobsServer(after_step=((100, moved(ZOMBIE_ID, -0.4)),), end=300)

    result = await replay("mobs/chase-open", server)

    assert result.samples == {}
    assert server.reads == 4  # the fourth answer, 300, is the budget: no fifth read
    assert result.commands[len(OPEN_SETUP) :] == (*TEARDOWN, "deop open0", "tick unfreeze")


# `mobs/chase-maze`

MAZE_WALL = (
    "fill 8 -60 -10 8 -60 4 minecraft:oak_fence",
    "fill 8 -60 6 8 -60 10 minecraft:oak_fence",
)
MAZE_CLEAR = "fill 8 -60 -10 8 -60 10 minecraft:air"

MAZE_SETUP = (
    "tp control 96.5 -60 96.5",
    "tp maze7 0.5 -60.0 0.5",
    "op maze7",
    *MAZE_WALL,
    "tick freeze",
    *CALIBRATE,
    summoned("zombie", "16.5 -60.0 0.5", ZOMBIE),
    TIME_QUERY,
    "tick step 400",
)


def _through_the_gap() -> MobsServer:
    """The zombie walks to the gap at z 5 (8 blocks west, 4.5 north), through it, and hits."""
    return MobsServer(
        after_step=(
            (40, moved(ZOMBIE_ID, -4.0, 4.5)),
            (90, moved(ZOMBIE_ID, -3.0)),  # x 9.5: not yet in the gap
            (105, moved(ZOMBIE_ID, -1.0)),  # x 8.5: in it
            (120, moved(ZOMBIE_ID, -1.0)),
            (179, hurt(PLAYER_ID)),
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
        *TEARDOWN,
        MAZE_CLEAR,
        "deop maze7",
        "tick unfreeze",
    )


# `mobs/doors-hard` and `mobs/doors-normal`

PEN = (
    "fill 5 -60 -1 7 -60 1 minecraft:oak_fence",
    "setblock 6 -60 0 minecraft:air",
    "setblock 5 -60 0 minecraft:oak_door[facing=east,half=lower]",
    "setblock 5 -59 0 minecraft:oak_door[facing=east,half=upper]",
)
PEN_CLEAR = "fill 5 -60 -1 7 -59 1 minecraft:air"


def doors_setup(bot: str, budget: int) -> tuple[str, ...]:
    return (
        "tp control 96.5 -60 96.5",
        f"tp {bot} 0.5 -60.0 3.5",
        f"op {bot}",
        *PEN,
        "tick freeze",
        *CALIBRATE,
        summoned("zombie", "6.5 -60.0 0.5", f"{ZOMBIE},CanBreakDoors:1b"),
        TIME_QUERY,
        f"tick step {budget}",
    )


def cracked(x: int, y: int, z: int, stage: int = 0) -> tuple[str, dict[str, object]]:
    """A `block_destruction` by the zombie of the block at x, y, z."""
    return "minecraft:block_destruction", {
        "entity_id": ZOMBIE_ID,
        "pos": {"x": x, "y": y, "z": z},
        "stage": stage,
    }


def door_gone(section_x: int = 0, state: int = 0) -> tuple[str, dict[str, object]]:
    """A `section_blocks_update` that turns both halves of the door to air, as vanilla sends.

    With `section_x` 1, it is the same change 16 blocks east of the door; with `state` 1, the
    door turns to stone.
    """
    blocks = [{"x": 5, "y": y, "z": 0, "state": state} for y in (4, 5)]
    return "minecraft:section_blocks_update", {
        "section": {"x": section_x, "y": -4, "z": 0},
        "blocks": blocks,
    }


def block_changed(x: int, y: int, z: int, state: int) -> tuple[str, dict[str, object]]:
    """A `block_update` of the block at x, y, z to `state`."""
    return "minecraft:block_update", {"pos": {"x": x, "y": y, "z": z}, "block_state": state}


def _broken_in() -> MobsServer:
    """The zombie cracks another block, then the door, and breaks the door: as on hard."""
    return MobsServer(
        after_step=(
            (10, cracked(6, -60, 1)),
            (31, cracked(5, -59, 0)),
            (55, cracked(5, -59, 0, stage=1)),
            (100, door_gone(section_x=1)),
            (150, door_gone(state=1)),
            (200, block_changed(5, -60, 0, 1)),
            (230, block_changed(5, -58, 0, 0)),
            (271, door_gone()),
            (280, door_gone()),
        ),
    )


_SERVERS["mobs/doors-hard"] = _broken_in


@pytest.mark.asyncio
async def test_doors_hard_pens_a_zombie_that_can_break_doors_behind_an_oak_door() -> None:
    result = await play("mobs/doors-hard")

    assert result.bot == "doorhard7"
    assert result.commands[: len(doors_setup("doorhard7", 400))] == doors_setup("doorhard7", 400)


@pytest.mark.asyncio
async def test_doors_hard_samples_when_the_zombie_began_to_break_the_door_and_broke_it() -> None:
    result = await play("mobs/doors-hard")

    assert result.samples == {"doors_hard.started": (31.0,), "doors_hard.broken": (271.0,)}
    assert result.commands[-len(TEARDOWN) - 3 :] == (
        *TEARDOWN,
        PEN_CLEAR,
        "deop doorhard7",
        "tick unfreeze",
    )


@pytest.mark.asyncio
async def test_a_door_broken_with_one_block_update_counts_too() -> None:
    server = MobsServer(after_step=((265, block_changed(5, -59, 0, 0)),))

    result = await replay("mobs/doors-hard", server)

    assert result.samples == {"doors_hard.broken": (265.0,)}


DOORS_NORMAL_TICKS = 300


@pytest.mark.asyncio
async def test_doors_normal_pens_the_same_zombie_for_a_shorter_budget() -> None:
    server = MobsServer(after_step=((271, door_gone()),))
    result = await replay("mobs/doors-normal", server, PLAY_NUMBER)

    assert result.bot == "doornormal7"
    setup = doors_setup("doornormal7", DOORS_NORMAL_TICKS)
    assert result.commands[: len(setup)] == setup


@pytest.mark.parametrize(
    ("after_step", "door"),
    [
        ((), "held"),
        (((40, cracked(6, -60, 1)),), "held"),
        (((40, block_changed(5, -60, 0, 1)),), "held"),
        (((40, cracked(5, -60, 0)),), "cracked"),
        (((40, cracked(5, -60, 0)), (280, door_gone())), "broken"),
    ],
)
@pytest.mark.asyncio
async def test_doors_normal_samples_whether_the_door_held_cracked_or_broke(
    after_step: Sequence[Step], door: str
) -> None:
    server = MobsServer(after_step=after_step, end=300)

    result = await replay("mobs/doors-normal", server)

    assert result.samples == {"doors_normal.door": (door,)}
    assert result.commands[-4:] == ("tick unfreeze", PEN_CLEAR, "deop doornormal0", "tick unfreeze")


# `mobs/targets`

VILLAGER = (
    'PersistenceRequired:1b,DeathLootTable:"minecraft:empty",'
    'VillagerData:{type:"minecraft:plains",profession:"minecraft:none",level:1}'
)
VILLAGER_ID = ZOMBIE_ID + 1

TARGETS_SETUP = (
    "tp control 96.5 -60 96.5",
    "tp target7 0.5 -60.0 0.5",
    "op target7",
    "time set noon",
    "gamerule advance_time false",
    "tick freeze",
    *CALIBRATE,
    summoned("zombie", "8.5 -60.0 0.5", ZOMBIE),
    summoned("villager", "16.5 -60.0 0.5", VILLAGER),
    TIME_QUERY,
    "tick step 300",
)


def _goes_for(victim: int) -> MobsServer:
    """The zombie moves, then hits `victim`: the Bot (`PLAYER_ID`) or the villager."""
    return MobsServer(
        after_step=(
            (30, moved(ZOMBIE_ID, -1.0)),
            (50, hurt(ZOMBIE_ID)),
            (79, hurt(victim)),
            (90, hurt(PLAYER_ID + VILLAGER_ID - victim)),
        ),
    )


_SERVERS["mobs/targets"] = lambda: _goes_for(PLAYER_ID)


@pytest.mark.asyncio
async def test_targets_puts_a_zombie_between_the_bot_and_a_villager_at_noon() -> None:
    result = await play("mobs/targets")

    assert result.bot == "target7"
    assert result.commands[: len(TARGETS_SETUP)] == TARGETS_SETUP


@pytest.mark.asyncio
async def test_targets_samples_whom_the_zombie_hits_first_and_when() -> None:
    result = await play("mobs/targets")

    assert result.samples == {"targets.first": ("player",), "targets.hit": (79.0,)}
    assert result.commands[-4:] == (
        "tick unfreeze",
        "gamerule advance_time true",
        "deop target7",
        "tick unfreeze",
    )


@pytest.mark.asyncio
async def test_targets_samples_the_villager_when_the_zombie_hits_it_first() -> None:
    result = await replay("mobs/targets", _goes_for(VILLAGER_ID))

    assert result.samples == {"targets.first": ("villager",), "targets.hit": (79.0,)}


@pytest.mark.asyncio
async def test_targets_samples_no_one_when_the_zombie_hits_no_one_in_its_budget() -> None:
    server = MobsServer(after_step=((50, hurt(ZOMBIE_ID)),), end=300)

    result = await replay("mobs/targets", server)

    assert result.samples == {"targets.first": ("none",)}
