"""Mob pathfinding Groups: how a zombie notices, reaches and attacks a player who stands still.

Each play joins a Bot of its own, an operator, puts it at a fixed place and has Control build
the play's layout. Then the world is frozen, and Control summons the mobs, so that none of them
moves before the clock starts. Control reads the game time and steps the world a fixed number
of ticks (`tick step`): the play's tick budget. The Bot reads what the server sends it about the
mobs, and when something a sample is about arrives (the zombie's move, a `damage_event`, the
door's block change), the Bot reads the game time itself, without waiting for the answer before
it reads on (`_Clock`). In the same step, the clock measures how many ticks such a read adds on
this Instance, its offset, on the first `set_time` of the step. A sample is the number of ticks
between the two readings, less the offset. A frozen world does not advance its game time, so
the first tick the mobs live is tick 1.

Every mob is summoned with NBT, which makes vanilla skip `Mob.finalizeSpawn`, where a summoned
zombie gets its random equipment, baby chance, left hand, door breaking and reinforcement chance
(`SummonCommand.createEntity`, 26.3 javap). It wears a leather helmet, so that it does not
burn in daylight, and keeps it, drops nothing and never despawns. Each mob is tagged, so the
play removes only its own. Mobs' AI draws on a random source of each mob, not the world seed,
so two Instances differ in every play: the samples are compared as distributions (#24).
"""

import asyncio
import contextlib
import math
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import cast

from mscts.bot import Bot
from mscts.codec.packets import Packet
from mscts.entities import Entity
from mscts.group import Control, GroupContext, GroupKind, group
from mscts.groups._world import CONTROL_AT, gametime, normal, remove_tagged_until_gone
from mscts.spec import CONTROL_PLAYER, Difficulty, ServerSpec

_TAG = "mscts_mobs"
"""What every mob a play summons is tagged with, so that it removes only those."""

_ZOMBIE_NBT = (
    'PersistenceRequired:1b,DeathLootTable:"minecraft:empty",drop_chances:{head:0.0f},'
    'equipment:{head:{id:"minecraft:leather_helmet",count:1}}'
)
"""A zombie that never despawns, drops nothing, and wears a helmet it keeps: a zombie in
daylight burns unless its head is covered (`Zombie.aiStep`)."""

_IDLE_S = 1.0
"""How long the Bot waits for a packet before it reads the game time to see whether the tick
budget has run out."""

_WAIT_S = 10.0
"""How long the Bot waits for a `set_time`, which a server sends every 20 ticks (1 s), or for an
answer to its read of the game time."""

_SYSTEM_CHAT = "minecraft:system_chat"

_TIME_QUERY = "time query gametime"
_SET_TIME = "minecraft:set_time"

_DAMAGE = "minecraft:damage_event"
_MOVES = (
    "minecraft:move_entity_pos",
    "minecraft:move_entity_pos_rot",
    "minecraft:entity_position_sync",
    "minecraft:teleport_entity",
)
"""The packets that tell a client where an entity has moved."""

type _Position = tuple[float, float, float]


def _stamped(packet: Packet) -> int:
    """The game time a `set_time` carries: the first 8 bytes of its payload, a Long."""
    return int.from_bytes(packet.payload[:8], "big", signed=True)


def _summon(entity: str, at: _Position, nbt: str) -> str:
    """The `/summon` of `entity` at `at`, facing west, with `nbt` and the tag."""
    x, y, z = at
    return f'summon minecraft:{entity} {x} {y} {z} {{{nbt},Rotation:[90f,0f],Tags:["{_TAG}"]}}'


@dataclass(frozen=True, slots=True)
class _Layout:
    """What one play sets up.

    Attributes:
        bot: The Bot's name before the play's number.
        bot_at: Where the Bot stands.
        summons: The mobs, summoned in the frozen world.
        build: The commands that place the play's blocks, before the world is frozen.
        clear: The commands that take them away again, once the mobs have gone.
    """

    bot: str
    bot_at: _Position
    summons: tuple[str, ...]
    build: tuple[str, ...] = ()
    clear: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _Calibration:
    """The read a play's clock calibrates on, made on the first `set_time` of the play's step.

    Attributes:
        read: Which of the clock's reads it is, from 0.
        sent_in: The tick, counted from the clock's start, that sent the `set_time`: a server
            stamps it with the game time from before that tick, so this is its stamp plus one.
    """

    read: int
    sent_in: int

    def offset(self, answers: Sequence[int], budget: int) -> int:
        """How far the answer to the read, among `answers` sorted, is past the tick it is about.

        Raises:
            RuntimeError: The answer came once `budget` ticks had run, so it may show too few.
        """
        answer = answers[self.read]
        if answer >= budget:
            msg = f"the play's step ran out before the calibration read: {answer} >= {budget}"
            raise RuntimeError(msg)
        return answer - self.sent_in


@dataclass(slots=True)
class _Clock:
    """The play's clock: the Bot, an operator, reads the game time on its own connection.

    A read does not wait for its answer: the Bot sends `time query gametime` and reads on, so
    an event that arrives while an earlier read is unanswered is read as it arrives too. The
    answers come back in the order sent on vanilla; Pumpkin runs each command in a task of its
    own. The reads are made in the order of the ticks they are about, so once every read is
    answered, the answers, smallest first, go to the reads in the order they were made.

    The clock calibrates itself in the play's step. A server sends every player the game time
    (`set_time`) every 20 ticks, as it was before the tick that sends it
    (docs/research/2026-10-15-time-query-lag.md). On the first stamped after the step began,
    the clock reads the game time, as on an event. How far the answer is past the tick that
    sent it is the offset: how many ticks a read after a packet adds on this Instance. Each
    sample subtracts it.

    Attributes:
        bot: The play's Bot, which reads the game time.
        start: The game time before the play's step.
    """

    bot: Bot
    start: int
    _reads: list[str | None] = field(default_factory=list)
    _answers: list[int] = field(default_factory=list)
    _calibration: _Calibration | None = None

    @property
    def listens(self) -> tuple[str, ...]:
        """The packets the clock takes: answers, and a `set_time` until it has calibrated."""
        return (_SYSTEM_CHAT,) if self._calibration is not None else (_SYSTEM_CHAT, _SET_TIME)

    async def read(self, name: str | None) -> None:
        """Ask the game time for the sample called `name`; None for no sample."""
        self._reads.append(name)
        await self.bot.command(_TIME_QUERY)

    async def take(self, packet: Packet) -> None:
        """Take `packet`, one the clock listens to: an answer's ticks, or a `set_time`."""
        if packet.name == _SET_TIME:
            await self._calibrate_on(_stamped(packet) - self.start)
        elif (answer := _answer(packet)) is not None:
            self._answers.append(answer - self.start)

    async def _calibrate_on(self, stamped: int) -> None:
        """Read for the calibration on a `set_time` `stamped` ticks on, if that is after the start.

        The clock listens for no `set_time` once it has one, so this is the first.
        """
        if stamped > 0:
            self._calibration = _Calibration(read=len(self._reads), sent_in=stamped + 1)
            await self.read(None)

    def ran(self, budget: int) -> bool:
        """Whether an answer shows that `budget` ticks have run."""
        return any(ticks >= budget for ticks in self._answers)

    async def samples(self, budget: int) -> dict[str, int]:
        """Wait for the calibration and every answer; each sample read's tick, less the offset.

        Raises:
            RuntimeError: The calibration was answered once the `budget` of the play had run.
        """
        calibration = await self._answered()
        answers = sorted(self._answers)
        offset = calibration.offset(answers, budget)
        return {
            name: ticks - offset
            for name, ticks in zip(self._reads, answers, strict=False)
            if name is not None
        }

    async def _answered(self) -> _Calibration:
        """Wait until the clock has calibrated and every read is answered; the calibration."""
        while True:
            calibration = self._calibration
            if calibration is not None and len(self._answers) >= len(self._reads):
                return calibration
            await self.take(await self.bot.expect(*self.listens, timeout_s=_WAIT_S))


def _answer(packet: Packet) -> int | None:
    """The game time `packet` gives, if it answers `time query gametime`."""
    try:
        return gametime((packet,))
    except ValueError:
        return None


@contextlib.asynccontextmanager
async def _arena(context: GroupContext, layout: _Layout) -> AsyncIterator[tuple[Bot, _Clock]]:
    """Join the play's Bot, set `layout` up in a frozen world; yield the Bot and its clock.

    Control goes away first, so that no mob takes it for a target. The Bot is made an
    operator, so that it reads the game time itself. Once the play is over, the mobs go, then
    anything they dropped (Pumpkin drops loot whatever the NBT and the game rule), and the Bot
    waits until it is told their bodies are gone; the blocks go, and the Bot stops being an
    operator, last.
    """
    control = context.control
    async with contextlib.AsyncExitStack() as undo:
        await control.run(f"tp {CONTROL_PLAYER} {CONTROL_AT}")
        name = context.player_name(layout.bot)
        bot = await context.bot(name)
        await bot.join()
        x, y, z = layout.bot_at
        await control.run(f"tp {name} {x} {y} {z}")
        await control.run(f"op {name}")
        undo.push_async_callback(control.run, f"deop {name}")
        for command in reversed(layout.clear):
            undo.push_async_callback(control.run, command)
        for command in layout.build:
            await control.run(command)
        undo.push_async_callback(remove_tagged_until_gone, control, _TAG, bot)
        undo.push_async_callback(control.run, "kill @e[type=minecraft:item]")
        undo.push_async_callback(control.run, f"kill @e[tag={_TAG}]")
        await context.freeze()
        for summon in layout.summons:
            await control.run(summon)
        await bot.sync()
        yield bot, _Clock(bot, gametime(await control.run(_TIME_QUERY)))


@contextlib.asynccontextmanager
async def _stepping(control: Control, ticks: int) -> AsyncIterator[None]:
    """Let the frozen world run `ticks` ticks while the body reads what the Bot is sent.

    Control returns a few ticks into the step, once its marker is answered and its barrier
    passed (about 150 ms on vanilla), so a body that waited for it would read the first
    packets of the step late. It waits for Control on the way out.
    """
    step = asyncio.ensure_future(control.run(f"tick step {ticks}"))
    try:
        yield
    finally:
        await step


async def _next(bot: Bot, clock: _Clock, budget: int, names: tuple[str, ...]) -> Packet | None:
    """The next packet called one of `names` to arrive at `bot`; None once `budget` has run.

    It gives the clock what it listens to on the way. When nothing has come for `_IDLE_S`, the
    clock is read to see whether the budget has run.
    """
    while not clock.ran(budget):
        try:
            packet = await bot.expect(*names, *clock.listens, timeout_s=_IDLE_S)
        except TimeoutError:
            await clock.read(None)
            continue
        if packet.name in names:
            return packet
        await clock.take(packet)
    return None


def _hurts_the_bot(bot: Bot, packet: Packet) -> bool:
    """Whether `packet` is a `damage_event` of the Bot's own player: of no entity it tracks."""
    return packet.name == _DAMAGE and (packet.fields or {}).get("entity_id") not in bot.entities


@dataclass(frozen=True, slots=True)
class _Chase:
    """A zombie chasing the Bot, and the two ticks a play of it samples.

    Attributes:
        layout: What the play sets up; its only zombie chases the Bot.
        budget: How many ticks the world runs.
        waypoint: The name of the sample of the first tick the zombie is where `reached` says.
        reached: Whether the zombie, as the Bot last saw it, has got to the waypoint.
        hit: The name of the sample of the tick the zombie first hurts the Bot.
    """

    layout: _Layout
    budget: int
    waypoint: str
    reached: Callable[[Entity], bool]
    hit: str


async def _chase(context: GroupContext, chase: _Chase) -> None:
    """Play `chase`: sample when the zombie first gets to its waypoint, and when it first hits."""
    async with _arena(context, chase.layout) as (bot, clock):
        zombie = bot.entities.find("zombie").id
        async with _stepping(context.control, chase.budget):
            reached = False
            while (packet := await _next(bot, clock, chase.budget, (_DAMAGE, *_MOVES))) is not None:
                if _hurts_the_bot(bot, packet):
                    await clock.read(chase.hit)
                    break
                if not reached and chase.reached(bot.entities[zombie]):
                    reached = True
                    await clock.read(chase.waypoint)
        _sample_each(context, await clock.samples(chase.budget))


def _sample_each(context: GroupContext, samples: Mapping[str, int]) -> None:
    """Record each of `samples`, a tick by its sample's name."""
    for name, tick in samples.items():
        context.sample(name, tick)


# `mobs/chase-open`: a zombie 16 blocks from the Bot on open ground.

_OPEN = _Layout(
    bot="open",
    bot_at=(0.5, -60.0, 0.5),
    summons=(_summon("zombie", (16.5, -60.0, 0.5), _ZOMBIE_NBT),),
)

CHASE_TICKS = 300
"""The tick budget of a chase in the open: vanilla's zombie hits the Bot at about tick 150."""

_MOVED_WITHIN = 15.5
"""How near the Bot the zombie, summoned 16 blocks away, must be to have moved towards it."""


@group("mobs/chase-open", spec=normal, kind=GroupKind.STATISTICAL, runs=25)
async def chase_open(context: GroupContext) -> None:
    """Sample the tick the zombie is first half a block closer, and the tick it first hits."""
    await _chase(
        context,
        _Chase(
            layout=_OPEN,
            budget=CHASE_TICKS,
            waypoint="chase_open.moved",
            reached=lambda zombie: math.hypot(zombie.x - 0.5, zombie.z - 0.5) <= _MOVED_WITHIN,
            hit="chase_open.hit",
        ),
    )


# `mobs/chase-maze`: the same chase, with a fence between them that has one gap, 4.5 blocks
# north of the straight line. Fences are 1.5 blocks high: the zombie sees the Bot over the
# fence, and so goes for it, but cannot jump it.

_FENCE_X = 8
_MAZE = _Layout(
    bot="maze",
    bot_at=(0.5, -60.0, 0.5),
    summons=(_summon("zombie", (16.5, -60.0, 0.5), _ZOMBIE_NBT),),
    build=(
        f"fill {_FENCE_X} -60 -10 {_FENCE_X} -60 4 minecraft:oak_fence",
        f"fill {_FENCE_X} -60 6 {_FENCE_X} -60 10 minecraft:oak_fence",
    ),
    clear=(f"fill {_FENCE_X} -60 -10 {_FENCE_X} -60 10 minecraft:air",),
)

MAZE_TICKS = 400
"""The tick budget of a chase through the gap: vanilla's zombie hits the Bot at about tick 180."""

_IN_THE_GAP = _FENCE_X + 0.9
"""The zombie's x once it is in the gap: its edge, 0.3 blocks from its centre, is in the fence's
block, where only the gap lets it be."""


@group("mobs/chase-maze", spec=normal, kind=GroupKind.STATISTICAL, runs=20)
async def chase_maze(context: GroupContext) -> None:
    """Sample the tick the zombie first gets into the gap, and the tick it first hits."""
    await _chase(
        context,
        _Chase(
            layout=_MAZE,
            budget=MAZE_TICKS,
            waypoint="chase_maze.gap",
            reached=lambda zombie: zombie.x < _IN_THE_GAP,
            hit="chase_maze.hit",
        ),
    )


# `mobs/doors-hard` and `mobs/doors-normal`: a zombie that can break doors (`CanBreakDoors`),
# penned in by oak fences with an oak door on the west side. The Bot stands 3 blocks south of
# the door, where the zombie sees it over the fence: so the zombie goes for it, its path runs
# through the door, and it walks into the door. A zombie breaks a door only on hard
# (`Zombie.DOOR_BREAKING_PREDICATE`): it hits it for 240 ticks (`BreakDoorGoal`), and the
# server shows the door cracking (`block_destruction`) from the first of them.

_DOOR = (5, 0)
"""The x and z of the door; its halves are at y -60 and -59."""

_DOOR_YS = (-60, -59)
_AIR = 0
"""The block state id of air."""

_CRACK = "minecraft:block_destruction"
_BLOCK = "minecraft:block_update"
_SECTION = "minecraft:section_blocks_update"
_SECTION_SIZE = 16


def _pen(bot: str) -> _Layout:
    """The pen with its door, the zombie in it, and the Bot called `bot` in sight of it."""
    door = "minecraft:oak_door[facing=east,half={}]"
    return _Layout(
        bot=bot,
        bot_at=(0.5, -60.0, 3.5),
        summons=(_summon("zombie", (6.5, -60.0, 0.5), f"{_ZOMBIE_NBT},CanBreakDoors:1b"),),
        build=(
            "fill 5 -60 -1 7 -60 1 minecraft:oak_fence",
            "setblock 6 -60 0 minecraft:air",
            f"setblock 5 -60 0 {door.format('lower')}",
            f"setblock 5 -59 0 {door.format('upper')}",
        ),
        clear=("fill 5 -60 -1 7 -59 1 minecraft:air",),
    )


def _cracks_the_door(packet: Packet) -> bool:
    """Whether `packet` shows a block of the door cracking."""
    if packet.name != _CRACK:
        return False
    x, _, z = _xyz((packet.fields or {})["pos"])
    return (x, z) == _DOOR


_DOOR_HALVES = tuple((_DOOR[0], y, _DOOR[1]) for y in _DOOR_YS)
_DOOR_IN_SECTIONS = tuple(
    (tuple(axis // _SECTION_SIZE for axis in half), tuple(axis % _SECTION_SIZE for axis in half))
    for half in _DOOR_HALVES
)
"""Each half of the door as a `section_blocks_update` names it: its section, then where in it."""


def _breaks_the_door(packet: Packet) -> bool:
    """Whether `packet` turns a half of the door to air, in one block or in its section."""
    fields = packet.fields or {}
    if packet.name == _BLOCK:
        return fields["block_state"] == _AIR and _xyz(fields["pos"]) in _DOOR_HALVES
    if packet.name != _SECTION:
        return False
    section = _xyz(fields["section"])
    blocks = cast("list[Mapping[str, object]]", fields["blocks"])
    return any(
        block["state"] == _AIR and (section, _xyz(block)) in _DOOR_IN_SECTIONS for block in blocks
    )


def _xyz(value: object) -> tuple[object, object, object]:
    """The x, y and z of `value`, a position the codec decoded."""
    position = cast("Mapping[str, object]", value)
    return position["x"], position["y"], position["z"]


async def _besiege(context: GroupContext, layout: _Layout, budget: int) -> dict[str, int]:
    """Play `layout` for `budget` ticks: the tick the door first cracked and the tick it broke.

    Each is left out if it did not happen; the play ends when the door breaks.
    """
    async with _arena(context, layout) as (bot, clock):
        async with _stepping(context.control, budget):
            started = False
            names = (_CRACK, _BLOCK, _SECTION)
            while (packet := await _next(bot, clock, budget, names)) is not None:
                if _breaks_the_door(packet):
                    await clock.read("broken")
                    break
                if not started and _cracks_the_door(packet):
                    started = True
                    await clock.read("started")
        return await clock.samples(budget)


def _hard(spec: ServerSpec) -> ServerSpec:
    """Play on hard difficulty, the only one on which a zombie breaks doors."""
    return replace(spec, difficulty=Difficulty.HARD)


DOORS_HARD_TICKS = 400
"""The tick budget on hard: vanilla's zombie starts on the door by tick 31 and breaks it 240
ticks later, by tick 271."""


@group("mobs/doors-hard", spec=_hard, kind=GroupKind.STATISTICAL, runs=15)
async def doors_hard(context: GroupContext) -> None:
    """Sample the tick the zombie starts to break the door, and the tick the door breaks."""
    seen = await _besiege(context, _pen("doorhard"), DOORS_HARD_TICKS)
    for event, tick in seen.items():
        context.sample(f"doors_hard.{event}", tick)


DOORS_NORMAL_TICKS = 300
"""The tick budget on normal: long enough for the door to crack, and to break, had the zombie
been on hard."""


@group("mobs/doors-normal", spec=normal, kind=GroupKind.STATISTICAL, runs=10)
async def doors_normal(context: GroupContext) -> None:
    """Sample whether the door held, cracked or broke, as a category."""
    seen = await _besiege(context, _pen("doornormal"), DOORS_NORMAL_TICKS)
    door = "broken" if "broken" in seen else "cracked" if "started" in seen else "held"
    context.sample("doors_normal.door", door)


# `mobs/targets`: a zombie 8 blocks from the Bot and 8 from an unemployed villager, on the
# line between them. A zombie looks for a player to attack before a villager
# (`NearestAttackableTargetGoal` at target priorities 2 and 3), and needs to see the player
# but not the villager. The time of day stays at noon: what a villager does follows it.

_VILLAGER_NBT = (
    'PersistenceRequired:1b,DeathLootTable:"minecraft:empty",'
    'VillagerData:{type:"minecraft:plains",profession:"minecraft:none",level:1}'
)
"""A villager that never despawns and drops nothing, with no job, so it keeps to no workplace."""

_BETWEEN = _Layout(
    bot="target",
    bot_at=(0.5, -60.0, 0.5),
    summons=(
        _summon("zombie", (8.5, -60.0, 0.5), _ZOMBIE_NBT),
        _summon("villager", (16.5, -60.0, 0.5), _VILLAGER_NBT),
    ),
    build=("time set noon", "gamerule advance_time false"),
    clear=("gamerule advance_time true",),
)

TARGETS_TICKS = 300
"""The tick budget: vanilla's zombie hits the Bot by about tick 90."""


@group("mobs/targets", spec=normal, kind=GroupKind.STATISTICAL, runs=15)
async def targets(context: GroupContext) -> None:
    """Sample whom the zombie hurts first, the Bot or the villager, and the tick it does."""
    async with _arena(context, _BETWEEN) as (bot, clock):
        villager = bot.entities.find("villager").id
        first = "none"
        async with _stepping(context.control, TARGETS_TICKS):
            while (packet := await _next(bot, clock, TARGETS_TICKS, (_DAMAGE,))) is not None:
                if _hurts_the_bot(bot, packet):
                    first = "player"
                elif (packet.fields or {}).get("entity_id") == villager:
                    first = "villager"
                else:
                    continue
                await clock.read("targets.hit")
                break
        context.sample("targets.first", first)
        _sample_each(context, await clock.samples(TARGETS_TICKS))
