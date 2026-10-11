"""The entities Groups: what Control sets up, what each window holds, and what is undone after.

Every test plays a Group against a fake server and reads the Transcript for what Control sent
and the Marks (the Observation windows). What a server answers is never asserted: the fake
answers Control's markers, the barrier, and the `execute if entity` that asks whether a tagged
entity is left (nothing is).
"""

import asyncio
import json
import uuid
from contextlib import suppress
from dataclasses import dataclass, field

import pytest

import mscts.groups
from mscts.bot import SYNC_REQUESTS
from mscts.codec.packets import Direction, Packet
from mscts.codec.registry_names import registry_names
from mscts.compare import OBSERVE_CLOSE, OBSERVE_OPEN
from mscts.group import GROUPS, GroupKind
from mscts.groups import entities
from mscts.spec import Difficulty, ServerSpec
from mscts.target import TARGET
from mscts.transcript import Transcript
from tests.group.test_control import playing, text, tree
from tests.net.fakes import NO_STATISTICS, TICK_S, JoinScript, Peer, join_server

CONTROL = "control"
WATCHER = "watcher"
MARKER = "tellraw @s "
CHAT_COMMAND, CLIENT_COMMAND = "minecraft:chat_command", "minecraft:client_command"
COMMANDS = tree(
    "gamerule", "tp", "tick", "summon", "kill", "data", "effect", "attribute", "setblock",
    "execute", "tellraw",
)  # fmt: skip
NONE_LEFT = "commands.execute.conditional.fail"
STEP = "tick step 1"

PACKETS = (
    "minecraft:bundle_delimiter",
    "minecraft:add_entity",
    "minecraft:set_entity_data",
    "minecraft:update_attributes",
    "minecraft:set_equipment",
    "minecraft:rotate_head",
    "minecraft:entity_event",
    "minecraft:damage_event",
    "minecraft:hurt_animation",
    "minecraft:remove_entities",
)
LABEL = f"{OBSERVE_OPEN} {' '.join(PACKETS)}"
TAG = "mscts_entities"

SETUP = (
    "gamerule player_movement_check false",
    "gamerule respawn_radius 0",
    "tp control 96.5 -60 96.5",
    "tick freeze",
)
"""What Control runs before the watcher joins, in order."""

TEARDOWN = (
    "gamerule mob_drops false",
    f"kill @e[tag={TAG}]",
    "gamerule mob_drops true",
    "tick unfreeze",
    f"execute if entity @e[tag={TAG}]",
    "gamerule respawn_radius 10",
    "gamerule player_movement_check true",
    "tick unfreeze",
)
"""What Control runs after the last window: the tagged entities go, then the rules come back,
then the GroupContext unfreezes the world it froze (`GroupContext.close`, here)."""


PIG = registry_names(TARGET.minecraft_version, "minecraft:entity_type").index("minecraft:pig")
PIG_ID = 300


@dataclass
class EntitiesServer:
    """A fake server that joins like vanilla and answers Control's markers and the barrier.

    It answers an `execute if entity` with the failure that says no entity matched. With
    `pig_goes_after` set, it tells the watcher about a pig as it joins, and removes it once the
    watcher has sent that many barrier requests after Control's `execute if entity` (a body that
    is still dying); None leaves the pig there.
    """

    seen: list[Packet] = field(default_factory=list)
    pig_goes_after: int | None = 0
    with_pig: bool = False
    _asked: bool = False

    async def __call__(self, peer: Peer) -> None:
        """Serve one connection: a Handler."""
        with suppress(ConnectionError):
            await join_server(self.seen, JoinScript(commands=COMMANDS, then=self._play))(peer)

    async def _play(self, peer: Peer) -> None:
        if self.with_pig and peer.name == WATCHER:
            await peer.send("minecraft:add_entity", **_pig())
        requests = 0
        async for packet in peer.packets():
            self.seen.append(packet)
            if packet.name == CLIENT_COMMAND:
                requests += 1
                if (requests - 1) % SYNC_REQUESTS != 0:
                    await asyncio.sleep(TICK_S)  # a barrier's answers come a tick apart
                await peer.write(peer.raw_frame("minecraft:award_stats", NO_STATISTICS))
                await self._maybe_remove_pig(peer)
            elif packet.name == CHAT_COMMAND:
                command = str((packet.fields or {})["command"])
                if command.startswith(MARKER):
                    await self._say(peer, json.loads(command.removeprefix(MARKER)))
                elif command.startswith("execute if entity"):
                    self._asked = True
                    await self._say(peer, NONE_LEFT)

    async def _maybe_remove_pig(self, peer: Peer) -> None:
        """Count the watcher's requests after the ask, and remove the pig at the set count."""
        if not (self.with_pig and self._asked and peer.name == WATCHER):
            return
        if self.pig_goes_after is None:
            return
        self.pig_goes_after -= 1
        if self.pig_goes_after == 0:
            await peer.send("minecraft:remove_entities", entity_ids=[PIG_ID])

    async def _say(self, peer: Peer, message: str) -> None:
        await peer.write(peer.frame("minecraft:system_chat", content=text(message), overlay=False))


def _pig() -> dict[str, object]:
    """An `add_entity` of a pig, standing still at the spawn."""
    return {
        "entity_id": PIG_ID,
        "entity_uuid": uuid.UUID(int=PIG_ID),
        "type": PIG,
        "x": 4.5,
        "y": -60.0,
        "z": 4.5,
        "velocity": {"scale": 0, "x": 0, "y": 0, "z": 0},
        "pitch": 0,
        "yaw": 0,
        "head_yaw": 0,
        "data": 0,
    }


@dataclass(frozen=True)
class Window:
    """One Observation window: its label, and Control's commands before it and inside it."""

    label: str
    before: tuple[str, ...]
    inside: tuple[str, ...]


@dataclass(frozen=True)
class Play:
    """A played Group: its windows, Control's commands before the first and after the last."""

    windows: tuple[Window, ...]
    first: tuple[str, ...]
    after: tuple[str, ...]
    transcript: Transcript


def _commands(transcript: Transcript) -> list[tuple[int, str]]:
    """Every command Control sent but a marker, with when."""
    return [
        (event.t_ns, str((event.packet.fields or {})["command"]))
        for event in transcript.events
        if event.bot == CONTROL
        and event.packet.direction is Direction.SERVERBOUND
        and event.packet.name == CHAT_COMMAND
        and not str((event.packet.fields or {})["command"]).startswith(MARKER)
    ]


def read(transcript: Transcript) -> Play:
    """The windows of `transcript`, each from its open Mark to its close Mark."""
    commands = _commands(transcript)
    opens = [(m.t_ns, m.label) for m in transcript.marks if m.label.startswith(OBSERVE_OPEN)]
    closes = [m.t_ns for m in transcript.marks if m.label == OBSERVE_CLOSE]
    assert len(opens) == len(closes), transcript.marks
    windows = []
    previous = 0
    for (opened, label), closed in zip(opens, closes, strict=True):
        windows.append(
            Window(
                label=label,
                before=tuple(c for t, c in commands if previous <= t < opened),
                inside=tuple(c for t, c in commands if opened <= t <= closed),
            )
        )
        previous = closed
    first = tuple(c for t, c in commands if t < opens[0][0]) if opens else ()
    after = tuple(c for t, c in commands if t > previous)
    return Play(tuple(windows), first, after, transcript)


async def replay(group_id: str, server: EntitiesServer) -> Play:
    """Play `group_id` against `server`; read what the Transcript shows."""
    transcript = Transcript(group_id=group_id, server="fake")
    async with playing(server, transcript) as context:
        await GROUPS[group_id].run(context)
    return read(transcript)


_PLAYS: dict[str, Play] = {}
"""Each Group's play against a default `EntitiesServer`; no test changes it."""


async def play(group_id: str) -> Play:
    """The play of `group_id` against a default fake server, played the first time it is asked."""
    if group_id not in _PLAYS:
        _PLAYS[group_id] = await replay(group_id, EntitiesServer())
    return _PLAYS[group_id]


def joined_at(transcript: Transcript) -> int:
    """When the watcher said hello."""
    return next(
        e.t_ns for e in transcript.events if e.bot == WATCHER and e.packet.name == "minecraft:hello"
    )


def summoned(entity: str, at: tuple[float, float, float], nbt: str) -> str:
    x, y, z = at
    return f'summon minecraft:{entity} {x} {y} {z} {{{nbt},Rotation:[90f,0f],Tags:["{TAG}"]}}'


GROUP_IDS = ("entities/summon", "entities/data-changes", "entities/death")
KINDS = {
    "entities/summon": GroupKind.EXACT,
    "entities/data-changes": GroupKind.EXACT,
    "entities/death": GroupKind.TICK_EXACT,
}


# Registration and the shape of every play


@pytest.mark.parametrize("group_id", GROUP_IDS)
def test_each_group_has_its_kind_needs_nothing_masks_nothing_and_plays_on_normal_difficulty(
    group_id: str,
) -> None:
    group = GROUPS[group_id]
    default = ServerSpec(host="127.0.0.1", port=25566)

    assert group.kind is KINDS[group_id]
    assert group.requires == ()
    assert group.masks == ()
    assert group.spec(default) == ServerSpec(
        host="127.0.0.1", port=25566, difficulty=Difficulty.NORMAL
    )


def test_the_groups_package_imports_the_module_so_that_every_run_has_its_groups() -> None:
    assert "entities" in mscts.groups.__all__
    assert mscts.groups.entities is entities


def test_the_windows_compare_how_an_entity_looks_is_hurt_and_goes() -> None:
    assert entities.PACKETS == PACKETS


@pytest.mark.asyncio
@pytest.mark.parametrize("group_id", GROUP_IDS)
async def test_every_window_is_narrowed_to_the_entity_packets(group_id: str) -> None:
    result = await play(group_id)

    assert result.windows
    assert {window.label for window in result.windows} == {LABEL}


@pytest.mark.asyncio
@pytest.mark.parametrize("group_id", GROUP_IDS)
async def test_control_pins_the_join_goes_away_and_freezes_before_the_watcher_joins(
    group_id: str,
) -> None:
    result = await play(group_id)
    joined = joined_at(result.transcript)
    before_join = [c for t, c in _commands(result.transcript) if t < joined]

    assert before_join == list(SETUP)


@pytest.mark.asyncio
@pytest.mark.parametrize("group_id", GROUP_IDS)
async def test_the_tagged_entities_go_and_the_rules_come_back_after_the_last_window(
    group_id: str,
) -> None:
    result = await play(group_id)

    assert result.after[-len(TEARDOWN) :] == TEARDOWN


def _asked_at(transcript: Transcript) -> int:
    """When Control asked whether a tagged entity is left."""
    return next(t for t, c in _commands(transcript) if c.startswith("execute if entity"))


def _watcher_requests_after(transcript: Transcript, t_ns: int) -> int:
    return sum(
        1
        for e in transcript.events
        if e.bot == WATCHER and e.packet.name == CLIENT_COMMAND and e.t_ns > t_ns
    )


@pytest.mark.asyncio
async def test_the_watcher_waits_until_it_is_told_the_last_body_is_gone() -> None:
    result = await replay("entities/summon", EntitiesServer(with_pig=True, pig_goes_after=4))
    asked = _asked_at(result.transcript)

    assert _watcher_requests_after(result.transcript, asked) >= 4
    assert result.after[-len(TEARDOWN) :] == TEARDOWN


@pytest.mark.asyncio
async def test_a_body_that_never_goes_ends_the_play_with_a_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(entities, "_GONE_SYNCS", 2)

    with pytest.raises(TimeoutError, match="still tracked"):
        await replay("entities/summon", EntitiesServer(with_pig=True, pig_goes_after=None))


@pytest.mark.asyncio
async def test_the_tests_of_a_group_share_one_play_of_it() -> None:
    """A play takes seconds (the fake's ticks are real), so a Group is played once per process."""
    assert await play("entities/summon") is await play("entities/summon")


# `entities/summon`

MOB = "NoAI:1b,PersistenceRequired:1b"
STILL = "NoGravity:1b"
ROW = (
    ("pig", MOB),
    ("cow", MOB),
    ("sheep", f"{MOB},Color:3b"),
    ("chicken", MOB),
    ("zombie", MOB),
    ("skeleton", f'{MOB},equipment:{{mainhand:{{id:"minecraft:bow",count:1}}}}'),
    ("creeper", MOB),
    (
        "villager",
        f'{MOB},VillagerData:{{type:"minecraft:plains",profession:"minecraft:farmer",level:1}}',
    ),
    ("armor_stand", STILL),
    ("item_frame", 'Facing:1b,Item:{id:"minecraft:diamond",count:1}'),
    ("oak_boat", STILL),
    ("minecart", STILL),
    ("arrow", STILL),
    ("snowball", STILL),
    ("experience_orb", f"{STILL},Value:5s"),
    ("falling_block", f'{STILL},BlockState:{{Name:"minecraft:sand"}}'),
    ("tnt", f"{STILL},fuse:40s"),
)


@pytest.mark.asyncio
async def test_summon_summons_each_entity_alone_in_its_window_in_rows_of_eight() -> None:
    result = await play("entities/summon")
    places = [(1.5 + 2 * x, -60.0, 9.5 + 2 * z) for z in range(3) for x in range(8)]

    assert [window.inside for window in result.windows] == [
        (summoned(entity, place, nbt),) for (entity, nbt), place in zip(ROW, places, strict=False)
    ]


@pytest.mark.asyncio
async def test_summon_sets_nothing_up_between_its_windows() -> None:
    result = await play("entities/summon")

    assert all(window.before == () for window in result.windows[1:])
    assert result.after == TEARDOWN


# `entities/data-changes`

ZOMBIE = f"@e[tag={TAG},limit=1]"
ROOF = "14 -57 4"
CHANGES = (
    f'data merge entity {ZOMBIE} {{CustomName:"Bob",CustomNameVisible:1b}}',
    f"data merge entity {ZOMBIE} {{Glowing:1b}}",
    f"data merge entity {ZOMBIE} {{Silent:1b}}",
    f"data merge entity {ZOMBIE} {{NoGravity:1b}}",
    f"data merge entity {ZOMBIE} {{Fire:95s}}",
    f"effect give {ZOMBIE} minecraft:invisibility 1000 0 true",
    f"attribute {ZOMBIE} minecraft:movement_speed base set 0.5",
)


@pytest.mark.asyncio
async def test_data_changes_roofs_and_summons_one_zombie_once_the_watcher_has_joined() -> None:
    result = await play("entities/data-changes")

    assert result.first == (
        *SETUP,
        f"setblock {ROOF} minecraft:stone",
        summoned("zombie", (14.5, -60.0, 4.5), MOB),
    )


@pytest.mark.asyncio
async def test_data_changes_makes_each_change_in_its_window_then_steps_once() -> None:
    result = await play("entities/data-changes")

    assert [window.inside for window in result.windows] == [(change, STEP) for change in CHANGES]
    assert all(window.before == () for window in result.windows[1:])


@pytest.mark.asyncio
async def test_data_changes_takes_the_roof_away_after_the_zombie() -> None:
    result = await play("entities/data-changes")

    assert result.after == (f"setblock {ROOF} minecraft:air", *TEARDOWN)


# `entities/death`

NO_LOOT = f'{MOB},DeathLootTable:"minecraft:empty"'
DYING = (("pig", (8.5, -60.0, 4.5)), ("zombie", (11.5, -60.0, 4.5)))


@pytest.mark.asyncio
async def test_death_summons_each_mob_without_loot_just_before_its_window() -> None:
    result = await play("entities/death")

    assert result.first == (*SETUP, summoned("pig", DYING[0][1], NO_LOOT))
    assert [window.before for window in result.windows[1:]] == [
        (summoned(mob, at, NO_LOOT),) for mob, at in DYING[1:]
    ]


@pytest.mark.asyncio
async def test_death_kills_each_mob_in_its_window_then_steps_twenty_ticks() -> None:
    result = await play("entities/death")

    assert [window.inside for window in result.windows] == [
        (f"kill @e[tag={TAG},type=minecraft:{mob}]", *[STEP] * 20) for mob, _ in DYING
    ]
    assert result.after == TEARDOWN
