"""The hopper Groups: what Control builds and steps, which containers the Bots open, the undo.

Every test reads one shared play of its Group against a fake server: Control's commands, the
Bots' serverbound packets and the Marks (the Observation windows and the ticks stepped). What a
server answers is never asserted: the fake answers Control's markers and the barrier, opens a
container for each `use_item_on`, and says the game time has moved on at each ask.
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import cast, override

import pytest
from support.control import CONTROL, ControlServer, playing, tree
from support.control_play import Play, control_commands, read
from support.gametime import gametime_answer

from mscts.bot import Face
from mscts.codec.packets import Direction, Packet
from mscts.compare import OBSERVE_CLOSE
from mscts.group import GROUPS, GroupKind
from mscts.spec import ServerSpec
from mscts.transcript import Transcript
from tests.net.fakes import Peer

TRANSFER = "redstone/hopper-transfer"
FULL = "redstone/hopper-full"
PICKUP = "redstone/hopper-pickup"
LOCK = "redstone/hopper-lock"
GROUP_IDS = (TRANSFER, FULL, PICKUP, LOCK)
COMMANDS = tree(
    "gamerule", "tp", "tick", "fill", "setblock", "item", "time", "tellraw", "kill", "summon"
)
USE_ITEM_ON, CONTAINER_CLOSE = "minecraft:use_item_on", "minecraft:container_close"
GENERIC_9X3 = 2
"""`minecraft:generic_9x3`, a chest's menu, in `minecraft:menu`: the fake opens it for any
container."""
CHEST_TITLE = bytes([0x08, 0x00, 0x05]) + b"Chest"  # a network NBT String tag
OPEN_WINDOW = (
    "observe:open minecraft:open_screen minecraft:container_set_content "
    "minecraft:container_set_slot"
)
SLOT_WINDOW = "observe:open minecraft:container_set_content minecraft:container_set_slot"
PICKUP_WINDOW = (
    "observe:open minecraft:add_entity minecraft:set_entity_data minecraft:remove_entities "
    "minecraft:container_set_content minecraft:container_set_slot"
)
LOCK_WINDOW = (
    "observe:open minecraft:block_update minecraft:section_blocks_update "
    "minecraft:container_set_content minecraft:container_set_slot"
)
STEPPED_WINDOWS = {
    TRANSFER: SLOT_WINDOW,
    FULL: SLOT_WINDOW,
    PICKUP: PICKUP_WINDOW,
    LOCK: LOCK_WINDOW,
}
"""The open Mark of each Group's stepped window."""
KILL_ITEMS = "kill @e[type=minecraft:item]"
UNDONE_FIRST = {PICKUP: (KILL_ITEMS,)}
"""What a Group undoes before the Bots close their containers."""
SETUP = (
    "gamerule player_movement_check false",
    "gamerule respawn_radius 0",
    "tp control 96.5 -60 96.5",
    "gamerule random_tick_speed 0",
    "tick freeze",
)
"""What Control does before it builds, in every Group: the redstone arena's."""
UNDO = (
    "fill 1 -60 1 15 -57 15 minecraft:air strict",
    "fill 1 -60 1 15 -57 15 minecraft:air",
    "gamerule random_tick_speed 3",
    "tp watcher 0.5 -60 0.5",
    "gamerule respawn_radius 10",
    "gamerule player_movement_check true",
    "tick unfreeze",
)
"""What the redstone arena undoes after the Bots are back at the spawn, in order."""
STEP = "tick step 1"
TIME_QUERY = "time query gametime"
RECHECK = (TIME_QUERY, "tick step 5", TIME_QUERY)
"""The fast-forward of 5 ticks after the containers close: a chest's recheck of its openers."""


@dataclass
class HopperServer(ControlServer):
    """A ControlServer that opens a container for each `use_item_on`, and tells the game time.

    Each Bot's first container is window 1, as vanilla numbers each player's own
    (`ServerPlayer.nextContainerCounter`). Each answer to `time query gametime` is 1000 ticks
    after the last, so a fast-forward has run by the next ask. With `opens` False, it opens
    nothing.
    """

    opens: bool = True
    game_time: int = field(default=0, init=False)

    @override
    async def _play(self, peer: Peer) -> None:
        await super()._play(cast("Peer", _Opening(peer) if self.opens else peer))

    @override
    def _answer(self, peer: Peer, command: str) -> bytes:
        if command != TIME_QUERY:
            return super()._answer(peer, command)
        answer = gametime_answer(self.game_time)
        self.game_time += 1000
        return peer.frame("minecraft:system_chat", content=answer, overlay=False)


class _Opening:
    """`peer`, but each `use_item_on` it reads opens a container first."""

    def __init__(self, peer: Peer) -> None:
        self._peer = peer

    def __getattr__(self, name: str) -> object:
        return getattr(self._peer, name)

    async def packets(self) -> AsyncIterator[Packet]:
        async for packet in self._peer.packets():
            if packet.name == USE_ITEM_ON:
                frame = self._peer.frame(
                    "minecraft:open_screen",
                    window_id=1,
                    window_type=GENERIC_9X3,
                    window_title=CHEST_TITLE,
                )
                await self._peer.write(frame)
            yield packet


@dataclass(frozen=True)
class Played:
    """A play: Control's commands by window, and every Bot's serverbound packets in order."""

    play: Play
    sent: tuple[tuple[str, str, dict[str, object]], ...]
    """Each Bot's serverbound packet but Control's: its Bot, its name and its fields."""
    after: tuple[str, ...]
    """After the last window: Control's commands and each Bot's close (`close <Bot>`), in order."""

    def opens(self) -> list[tuple[str, object, object]]:
        """Which Bot used its hand on which block and face, in order."""
        return [(bot, f["pos"], f["face"]) for bot, name, f in self.sent if name == USE_ITEM_ON]

    def closes(self) -> list[tuple[str, object]]:
        """Which Bot closed which window, in order."""
        return [(bot, f["window_id"]) for bot, name, f in self.sent if name == CONTAINER_CLOSE]


async def replay(group_id: str, server: ControlServer) -> Played:
    """Play `group_id` against `server`; return what was read from its Transcript."""
    transcript = Transcript(group_id=group_id, server="fake")
    async with playing(server, transcript) as context:
        await GROUPS[group_id].run(context)
    sent = [
        (event.t_ns, event.bot, event.packet.name, dict(event.packet.fields or {}))
        for event in transcript.events
        if event.bot != CONTROL and event.packet.direction is Direction.SERVERBOUND
    ]
    closes = [(t_ns, f"close {bot}") for t_ns, bot, name, _ in sent if name == CONTAINER_CLOSE]
    closed = max(mark.t_ns for mark in transcript.marks if mark.label == OBSERVE_CLOSE)
    timeline = sorted([*closes, *control_commands(transcript)])
    return Played(
        play=read(transcript),
        sent=tuple((bot, name, fields) for _, bot, name, fields in sent),
        after=tuple(entry for t_ns, entry in timeline if t_ns > closed),
    )


_PLAYS: dict[str, Played] = {}
"""Each Group's play against a default fake server; no test changes it."""


async def play(group_id: str) -> Played:
    """The play of `group_id` against a default fake server, played the first time it is asked."""
    if group_id not in _PLAYS:
        _PLAYS[group_id] = await replay(group_id, HopperServer(commands=COMMANDS))
    return _PLAYS[group_id]


pytestmark = [pytest.mark.timeout(300), pytest.mark.usefixtures("long_play")]


def steps(ticks: int) -> tuple[str, ...]:
    """`ticks` steps of one tick each."""
    return (STEP,) * ticks


def at(x: int, y: int, z: int) -> dict[str, int]:
    """A block position as a Packet's field holds it."""
    return {"x": x, "y": y, "z": z}


# Every Group


@pytest.mark.parametrize("group_id", GROUP_IDS)
def test_each_group_is_registered_tick_exact_with_the_default_spec_and_no_mask(
    group_id: str,
) -> None:
    group = GROUPS[group_id]
    default = ServerSpec(host="127.0.0.1", port=25566)

    assert group.kind is GroupKind.TICK_EXACT
    assert group.requires == ()
    assert group.spec(default) == default
    assert group.masks == ()


@pytest.mark.parametrize("group_id", GROUP_IDS)
@pytest.mark.asyncio
async def test_control_sets_up_the_redstone_arena_before_it_builds(group_id: str) -> None:
    first = (await play(group_id)).play.first

    assert first[:5] == SETUP


@pytest.mark.parametrize("group_id", GROUP_IDS)
@pytest.mark.asyncio
async def test_the_bots_open_their_containers_in_a_window_then_the_world_steps_in_another(
    group_id: str,
) -> None:
    opened, stepped = (await play(group_id)).play.windows

    assert (opened.label, opened.commands, opened.ticks) == (OPEN_WINDOW, (), 0)
    assert stepped.label == STEPPED_WINDOWS[group_id]
    assert stepped.commands[-1] == STEP


@pytest.mark.parametrize("group_id", GROUP_IDS)
@pytest.mark.asyncio
async def test_each_bot_closes_its_container_then_the_chests_recheck_runs_before_the_undo(
    group_id: str,
) -> None:
    played = await play(group_id)
    bots = [bot for bot, _, _ in played.opens()]

    assert played.closes() == [(bot, 1) for bot in bots]
    assert played.after == (
        *UNDONE_FIRST.get(group_id, ()),
        *(f"close {bot}" for bot in bots),
        *RECHECK,
        *(f"tp {bot} 0.5 -60 0.5" for bot in reversed(bots)),
        *UNDO,
    )


@pytest.mark.parametrize("group_id", GROUP_IDS)
@pytest.mark.asyncio
async def test_the_group_says_so_when_a_container_does_not_open(group_id: str) -> None:
    with pytest.raises(ValueError, match="did not open"):
        await replay(group_id, HopperServer(commands=COMMANDS, opens=False))


# `redstone/hopper-transfer`


@pytest.mark.asyncio
async def test_transfer_builds_a_chest_over_a_hopper_into_a_hopper_into_a_chest() -> None:
    first = (await play(TRANSFER)).play.first
    source = (
        '{Items:[{Slot:0b,id:"minecraft:stone",count:1},{Slot:2b,id:"minecraft:oak_log",count:2}]}'
    )
    dirt = '{Items:[{Slot:1b,id:"minecraft:dirt",count:1}]}'

    assert first[5:] == (
        "setblock 5 -60 8 minecraft:hopper[facing=east]",
        f"setblock 4 -60 8 minecraft:hopper[facing=east]{dirt}",
        f"setblock 4 -59 8 minecraft:chest{source}",
        "setblock 6 -60 8 minecraft:chest",
        "tp source 3.5 -60 6.5",
        "tp upper 3.5 -60 10.5",
        "tp lower 5.5 -60 10.5",
        "tp target 7.5 -60 6.5",
    )


@pytest.mark.asyncio
async def test_transfer_opens_the_source_both_hoppers_and_the_target() -> None:
    opens = (await play(TRANSFER)).opens()
    up = int(Face.UP)

    assert opens == [
        ("source", at(4, -59, 8), up),
        ("upper", at(4, -60, 8), up),
        ("lower", at(5, -60, 8), up),
        ("target", at(6, -60, 8), up),
    ]


@pytest.mark.asyncio
async def test_transfer_steps_until_the_lower_hoppers_last_push_has_shown() -> None:
    # The lower hopper pushes its last log on tick 32. The target's menu sends it in the next
    # server tick, which runs before the step's barrier ends.
    _, stepped = (await play(TRANSFER)).play.windows

    assert stepped.commands == steps(32)
    assert stepped.ticks == 32


# `redstone/hopper-full`


@pytest.mark.asyncio
async def test_full_builds_a_hopper_of_dirt_facing_a_chest_full_of_stone() -> None:
    first = (await play(FULL)).play.first
    dirt = '{Items:[{Slot:0b,id:"minecraft:dirt",count:3}]}'
    stone = ",".join(f'{{Slot:{slot}b,id:"minecraft:stone",count:64}}' for slot in range(27))

    assert first[5:] == (
        f"setblock 4 -60 8 minecraft:hopper[facing=east]{dirt}",
        f"setblock 5 -60 8 minecraft:chest{{Items:[{stone}]}}",
        "tp hopper 3.5 -60 10.5",
        "tp chest 6.5 -60 10.5",
    )


@pytest.mark.asyncio
async def test_full_opens_the_hopper_and_the_chest() -> None:
    opens = (await play(FULL)).opens()
    up = int(Face.UP)

    assert opens == [("hopper", at(4, -60, 8), up), ("chest", at(5, -60, 8), up)]


@pytest.mark.asyncio
async def test_full_makes_room_for_stone_then_for_dirt_and_steps_past_the_third_push() -> None:
    # A hopper whose target is full moves nothing, and tries again on the next tick
    # (`HopperBlockEntity.tryMoveItems` sets no cooldown): it pushes on tick 7, once there is
    # room for its dirt, then 8 ticks apart: the third on tick 23.
    _, stepped = (await play(FULL)).play.windows
    chest = "item replace block 5 -60 8"

    assert stepped.commands == (
        *steps(3),
        f"{chest} container.13 with minecraft:stone 63",
        *steps(3),
        f"{chest} container.20 with minecraft:air",
        *steps(17),
    )
    assert stepped.ticks == 23


# `redstone/hopper-pickup`


def item(at: str, stack: str) -> str:
    """The summon of a still item entity holding `stack`, facing south, at `at`."""
    return f"summon minecraft:item {at} {{Item:{stack},NoGravity:1b,Rotation:[0f,0f]}}"


@pytest.mark.asyncio
async def test_pickup_builds_three_hoppers_one_bare_one_under_stone_one_under_a_slab() -> None:
    first = (await play(PICKUP)).play.first

    assert first[5:] == (
        "setblock 3 -60 4 minecraft:hopper",
        "setblock 7 -60 4 minecraft:hopper",
        "setblock 7 -59 4 minecraft:stone",
        "setblock 11 -60 4 minecraft:hopper",
        "setblock 11 -59 4 minecraft:smooth_stone_slab[type=bottom]",
        "tp bare 3.5 -60 7.5",
        "tp covered 7.5 -60 7.5",
        "tp slabbed 11.5 -60 7.5",
    )


@pytest.mark.asyncio
async def test_pickup_opens_the_three_hoppers() -> None:
    opens = (await play(PICKUP)).opens()
    up = int(Face.UP)

    assert opens == [
        ("bare", at(3, -60, 4), up),
        ("covered", at(7, -60, 4), up),
        ("slabbed", at(11, -60, 4), up),
    ]


@pytest.mark.asyncio
async def test_pickup_puts_an_item_on_each_then_a_second_on_the_bare_one_during_its_cooldown() -> (
    None
):
    # The bare hopper takes the stone on tick 1 and waits 8 ticks
    # (`HopperBlockEntity.tryMoveItems`): it takes the dirt on tick 9.
    _, stepped = (await play(PICKUP)).play.windows

    assert stepped.commands == (
        item("3.5 -59 4.5", '{id:"minecraft:stone",count:3}'),
        item("7.5 -58 4.5", '{id:"minecraft:oak_log",count:1}'),
        item("11.5 -58.5 4.5", '{id:"minecraft:stone",count:1}'),
        *steps(2),
        item("3.5 -59 4.5", '{id:"minecraft:dirt",count:2}'),
        *steps(7),
    )
    assert stepped.ticks == 9


# `redstone/hopper-lock`

LOCK_ON = "setblock 4 -60 7 minecraft:redstone_block"
LOCK_OFF = "setblock 4 -60 7 minecraft:air"


@pytest.mark.asyncio
async def test_lock_builds_a_hopper_of_dirt_facing_an_empty_chest() -> None:
    first = (await play(LOCK)).play.first
    dirt = '{Items:[{Slot:0b,id:"minecraft:dirt",count:3}]}'

    assert first[5:] == (
        f"setblock 4 -60 8 minecraft:hopper[facing=east]{dirt}",
        "setblock 5 -60 8 minecraft:chest",
        "tp hopper 3.5 -60 10.5",
        "tp chest 6.5 -60 10.5",
    )


@pytest.mark.asyncio
async def test_lock_opens_the_hopper_and_the_chest() -> None:
    opens = (await play(LOCK)).opens()
    up = int(Face.UP)

    assert opens == [("hopper", at(4, -60, 8), up), ("chest", at(5, -60, 8), up)]


@pytest.mark.asyncio
async def test_lock_powers_the_hopper_three_times_once_inside_its_cooldown() -> None:
    # A locked hopper's cooldown still counts down (`HopperBlockEntity.pushItemsTick`): it
    # pushes on tick 4, on tick 12 through the lock from 6 to 9, and on 23, once the lock from
    # 18 to 22 has gone.
    _, stepped = (await play(LOCK)).play.windows

    assert stepped.commands == (
        LOCK_ON,
        *steps(3),
        LOCK_OFF,
        *steps(3),
        LOCK_ON,
        *steps(3),
        LOCK_OFF,
        *steps(9),
        LOCK_ON,
        *steps(4),
        LOCK_OFF,
        STEP,
    )
    assert stepped.ticks == 23
