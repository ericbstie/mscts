"""The blocks Groups: what the builder sends, in which windows, and what is undone after.

Every test plays a Group against a fake server and reads the Transcript for what each Bot
sent (the commands) and the Marks (the Observation windows). What a server answers is never
asserted: the fake only gives the builder the feedback a vanilla operator gets.
"""

import asyncio
import json
import re
from contextlib import suppress
from dataclasses import dataclass, field, replace
from typing import Self

import pytest

from mscts.bot import SYNC_REQUESTS, TICK_GAP_S
from mscts.codec.packets import Direction, Packet
from mscts.compare import OBSERVE_CLOSE, OBSERVE_OPEN
from mscts.group import GROUPS, GroupKind
from mscts.groups import blocks
from mscts.spec import ServerSpec
from mscts.transcript import Transcript
from tests.group.test_control import playing, text, tree
from tests.net.fakes import NO_STATISTICS, JoinScript, Peer, join_server

TICK_S = 2 * TICK_GAP_S
"""The fake's tick: just over what a barrier needs to see one pass, so a play is quick."""
FEEDBACK_AFTER_S = 5 * TICK_S
"""How late a slow server's feedback is: after the barrier's answers, which come a tick apart."""
CHAT_COMMAND, CLIENT_COMMAND = "minecraft:chat_command", "minecraft:client_command"
SYSTEM_CHAT, AWARD_STATS = "minecraft:system_chat", "minecraft:award_stats"
MARKER = "tellraw @s "
CONTROL = "control"
COMMANDS = tree("setblock", "fill", "clone", "data", "tellraw", "tick", "gamerule", "kill", "tp")
GROUP_IDS = ("blocks/setblock", "blocks/fill", "blocks/clone")
UNDO = ("kill @e[type=minecraft:item]", "gamerule random_tick_speed 3", "tick unfreeze")
"""What Control ends with, whatever happened: the last commands of every play."""
START = (
    f"tp builder {blocks.BUILDER_AT}",
    f"tp control {blocks.CONTROL_AT}",
    "tick freeze",
    "gamerule random_tick_speed 0",
)
"""What Control starts with: it moves the builder and itself into place, then freezes the world."""


def chat(peer: Peer, message: str) -> bytes:
    """A system_chat frame saying `message`."""
    return peer.frame(SYSTEM_CHAT, content=text(message), overlay=False)


@dataclass
class BlocksServer:
    """A fake server that joins like vanilla and answers commands like one run by operators.

    A marker (`tellraw @s "<token>"`) gets its token back at once. Any other command gets
    feedback, `feedback_after_s` later and while the server goes on answering the barrier
    (a server behind schedule), unless `feedback` is False. With `broadcast`, each command
    Control sends is also told to the builder, as vanilla tells every other operator.
    """

    seen: list[Packet] = field(default_factory=list)
    feedback: bool = True
    feedback_after_s: float = 0.0
    broadcast: bool = False
    _builder: Peer | None = field(default=None, init=False)

    async def __call__(self, peer: Peer) -> None:
        """Serve one connection: a Handler."""
        # A Bot that leaves with something unread (a late answer, or what Control said
        # last) resets the connection instead of closing it, and `join_server` reads on.
        with suppress(ConnectionError):
            await join_server(self.seen, JoinScript(commands=COMMANDS, then=self._play))(peer)

    def _player(self) -> str:
        hellos = [packet for packet in self.seen if packet.name == "minecraft:hello"]
        return str((hellos[-1].fields or {})["name"])

    async def _play(self, peer: Peer) -> None:
        player = self._player()
        if player == blocks.BUILDER:
            self._builder = peer
        requests = 0
        feedbacks: list[asyncio.Task[None]] = []
        async with asyncio.TaskGroup() as later:
            try:
                async for packet in peer.packets():
                    self.seen.append(packet)
                    if packet.name == CLIENT_COMMAND:
                        requests += 1
                        if (requests - 1) % SYNC_REQUESTS != 0:
                            await asyncio.sleep(TICK_S)  # a barrier's answers come a tick apart
                        await peer.write(peer.raw_frame(AWARD_STATS, NO_STATISTICS))
                    elif packet.name == CHAT_COMMAND:
                        command = str((packet.fields or {})["command"])
                        message = await self._answer(peer, player, command)
                        if message is not None:
                            feedbacks.append(later.create_task(self._say(peer, message)))
            except ConnectionError:
                pass  # the Bot left with something unread (a reset), or the builder did
            finally:
                for feedback in feedbacks:  # the Bot has gone: nobody is left to tell
                    feedback.cancel()

    async def _answer(self, peer: Peer, player: str, command: str) -> str | None:
        """Answer a marker, or tell the builder what Control did; return the feedback, if any."""
        if command.startswith(MARKER):
            await peer.write(chat(peer, json.loads(command.removeprefix(MARKER))))
            return None
        if self.broadcast and player == CONTROL and self._builder is not None:
            await self._builder.write(chat(self._builder, f"[control: {command}]"))
        return f"done: {command}" if self.feedback else None

    async def _say(self, peer: Peer, message: str) -> None:
        await asyncio.sleep(self.feedback_after_s)
        with suppress(ConnectionError):  # the Bot may have left first
            await peer.write(chat(peer, message))


@dataclass(frozen=True)
class Window:
    """One Observation window of a play, and what the Bots did around and inside it.

    Attributes:
        label: Its open Mark's label.
        before: Control's commands since the last window closed.
        builder: The commands the builder sent inside it.
        control: The commands Control sent inside it.
        feedback: How many system_chat packets the builder received inside it.
    """

    label: str
    before: tuple[str, ...]
    builder: tuple[str, ...]
    control: tuple[str, ...]
    feedback: int


@dataclass(frozen=True)
class Play:
    """What a played Group sent: each window, and Control's commands after the last."""

    windows: tuple[Window, ...]
    after: tuple[str, ...]


def sent(transcript: Transcript, bot: str) -> list[tuple[int, str]]:
    """The commands `bot` sent, with when, but Control's markers."""
    commands = [
        (event.t_ns, str((event.packet.fields or {})["command"]))
        for event in transcript.events
        if event.bot == bot
        and event.packet.direction is Direction.SERVERBOUND
        and event.packet.name == CHAT_COMMAND
    ]
    return [(t_ns, command) for t_ns, command in commands if not command.startswith(MARKER)]


def read(transcript: Transcript) -> Play:
    """The windows of `transcript` (each opened and closed) and Control's commands after them.

    A window closes where the builder's does: each Bot's ends at its own barrier.
    """
    builder, control = sent(transcript, blocks.BUILDER), sent(transcript, CONTROL)
    opens = [mark for mark in transcript.marks if mark.label.startswith(OBSERVE_OPEN)]
    closes = [m for m in transcript.marks if m.label == f"{OBSERVE_CLOSE} {blocks.BUILDER}"]
    assert len(opens) == len(closes), transcript.marks
    heard = [
        event.t_ns
        for event in transcript.events
        if event.bot == blocks.BUILDER
        and event.packet.direction is Direction.CLIENTBOUND
        and event.packet.name == SYSTEM_CHAT
    ]
    windows = []
    previous = 0
    for opened, closed in zip(opens, closes, strict=True):
        assert opened.t_ns <= closed.t_ns
        windows.append(
            Window(
                label=opened.label,
                before=tuple(c for t, c in control if previous <= t < opened.t_ns),
                builder=tuple(c for t, c in builder if opened.t_ns <= t <= closed.t_ns),
                control=tuple(c for t, c in control if opened.t_ns <= t <= closed.t_ns),
                feedback=sum(opened.t_ns <= t <= closed.t_ns for t in heard),
            )
        )
        previous = closed.t_ns
    return Play(tuple(windows), tuple(c for t, c in control if t > previous))


async def play(group_id: str, server: BlocksServer | None = None) -> tuple[Transcript, Play]:
    """Play `group_id` against a fake server; return its Transcript and what was read from it."""
    transcript = Transcript(group_id=group_id, server="fake")
    async with playing(server or BlocksServer(), transcript) as context:
        await GROUPS[group_id].run(context)
    return transcript, read(transcript)


async def played(group_id: str) -> Play:
    return (await play(group_id))[1]


@pytest.mark.parametrize("group_id", GROUP_IDS)
def test_each_group_is_exact_with_the_builder_an_operator_and_the_drop_masks(
    group_id: str,
) -> None:
    group = GROUPS[group_id]
    default = ServerSpec(host="127.0.0.1", port=25566)

    assert group.kind is GroupKind.EXACT
    assert group.requires == ()
    assert group.spec(default).operators == (blocks.BUILDER,)
    assert group.spec(replace(default, operators=("alice",))).operators == ("alice", "builder")
    assert group.spec(default) == GROUPS[GROUP_IDS[0]].spec(default)  # one Instance pair for all
    assert {(mask.packet, mask.path) for mask in group.masks} == {
        ("minecraft:add_entity", path)
        for path in ("x", "y", "z", "velocity.x", "velocity.z", "yaw")
        if group_id != "blocks/clone"  # a clone drops no item
    }


def test_the_windows_compare_what_a_command_changes_drops_and_says() -> None:
    assert set(blocks.PACKETS) == {
        "minecraft:block_update",
        "minecraft:section_blocks_update",
        "minecraft:block_entity_data",
        "minecraft:level_event",
        "minecraft:add_entity",
        "minecraft:set_entity_data",
        "minecraft:system_chat",
    }
    assert len(blocks.PACKETS) == len(set(blocks.PACKETS))


@pytest.mark.asyncio
@pytest.mark.parametrize("group_id", GROUP_IDS)
async def test_the_builder_runs_one_command_in_each_window_and_control_none(group_id: str) -> None:
    result = await played(group_id)

    assert result.windows
    assert {window.label for window in result.windows} == {
        f"{OBSERVE_OPEN} {' '.join(blocks.PACKETS)}"
    }
    assert [len(window.builder) for window in result.windows] == [1] * len(result.windows)
    assert [window.control for window in result.windows] == [()] * len(result.windows)


@pytest.mark.asyncio
@pytest.mark.parametrize("group_id", GROUP_IDS)
async def test_control_freezes_the_world_before_the_first_window_and_undoes_it_after_the_last(
    group_id: str,
) -> None:
    result = await played(group_id)

    assert result.windows[0].before[: len(START)] == START
    assert result.after[-3:] == UNDO
    assert re.fullmatch(r"fill \S+ \S+ \S+ \S+ \S+ \S+ minecraft:air", result.after[-4])
    assert not any(command in UNDO for window in result.windows for command in window.before)


@pytest.mark.asyncio
@pytest.mark.parametrize("group_id", GROUP_IDS)
async def test_the_builder_gets_its_own_feedback_inside_the_window_when_the_server_is_slow(
    group_id: str,
) -> None:
    # The command runs after the barrier's first answers (a server behind schedule), and what
    # Control said before the window reached the builder first: neither may end the window.
    server = BlocksServer(feedback_after_s=FEEDBACK_AFTER_S, broadcast=True)
    _, result = await play(group_id, server)

    assert [window.feedback for window in result.windows] == [1] * len(result.windows)


@pytest.mark.asyncio
@pytest.mark.parametrize("group_id", GROUP_IDS)
async def test_control_undoes_its_settings_when_the_builder_never_gets_feedback(
    group_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(blocks, "FEEDBACK_TIMEOUT_S", 0.3)
    transcript = Transcript(group_id=group_id, server="fake")
    async with playing(BlocksServer(feedback=False), transcript) as context:
        with pytest.raises(TimeoutError):
            await GROUPS[group_id].run(context)

    control = [command for _, command in sent(transcript, CONTROL)]
    assert tuple(control[: len(START)]) == START
    assert tuple(control[-3:]) == UNDO
    assert len(sent(transcript, blocks.BUILDER)) == 1  # it did not go on to the next case


_NUMBER = r"(-?\d+)"
_SETBLOCK = re.compile(
    rf"setblock {_NUMBER} {_NUMBER} {_NUMBER} (\S+?)(?: (destroy|keep|replace|strict))?"
)
AIR = "minecraft:air"


@dataclass(frozen=True)
class Setblock:
    """A parsed `setblock`: where, which block (with its states and data), and its mode."""

    at: tuple[int, int, int]
    block: str
    mode: str | None


def parse_setblock(command: str) -> Setblock | None:
    """`command` as a Setblock, or None if it is not a `setblock` command."""
    match = _SETBLOCK.fullmatch(command)
    if match is None:
        return None
    x, y, z, block, mode = match.groups()
    return Setblock((int(x), int(y), int(z)), block, mode)


_DATA = re.compile(rf"data get block {_NUMBER} {_NUMBER} {_NUMBER} (\S+)")


@dataclass(frozen=True)
class Readback:
    """A parsed `data get block`: the position it reads, and the path of the data."""

    at: tuple[int, int, int]
    path: str


def parse_readback(command: str) -> Readback | None:
    """`command` as a Readback, or None if it is not a `data get block` command."""
    match = _DATA.fullmatch(command)
    if match is None:
        return None
    x, y, z, path = match.groups()
    return Readback((int(x), int(y), int(z)), path)


def readbacks(result: Play) -> list[tuple[Window, Readback]]:
    """The windows in which the builder reads a block entity back, with what it reads."""
    reads = ((window, parse_readback(window.builder[0])) for window in result.windows)
    return [(window, read) for window, read in reads if read is not None]


async def every_command(group_id: str) -> list[str]:
    """Every command the Group sends, Control's first then the builder's."""
    transcript, _ = await play(group_id)
    return [command for bot in (CONTROL, blocks.BUILDER) for _, command in sent(transcript, bot)]


def setblock_cases(result: Play) -> list[tuple[Setblock, str]]:
    """Each `setblock` window's command, with the block at its position when the window opened."""
    cases = []
    for window in result.windows:
        command = parse_setblock(window.builder[0])
        if command is None:
            continue
        there = AIR  # the flat world is air above its grass, at y = -61
        for setup in window.before:
            earlier = parse_setblock(setup)
            if earlier and earlier.at == command.at:
                there = earlier.block
        cases.append((command, there))
    return cases


@pytest.mark.asyncio
async def test_setblock_tries_each_mode_on_air_and_on_a_block() -> None:
    cases = setblock_cases(await played("blocks/setblock"))

    assert {(command.mode, block != AIR) for command, block in cases if command.mode} == {
        (mode, existing)
        for mode in ("destroy", "keep", "replace", "strict")
        for existing in (False, True)
    }


@pytest.mark.asyncio
async def test_setblock_places_a_block_with_states_a_sign_with_text_and_a_chest_with_an_item() -> (
    None
):
    placed = [command.block for command, _ in setblock_cases(await played("blocks/setblock"))]

    assert "minecraft:oak_stairs[facing=east,half=top]" in placed
    assert any(block.startswith("minecraft:oak_sign") and "front_text" in block for block in placed)
    assert any(
        block.startswith("minecraft:chest") and "Items:[{" in block and "minecraft:diamond" in block
        for block in placed
    )


@pytest.mark.asyncio
async def test_setblock_sets_the_block_that_is_already_there() -> None:
    cases = setblock_cases(await played("blocks/setblock"))

    assert any(command.block == block != AIR for command, block in cases)


@pytest.mark.asyncio
async def test_setblock_reads_back_the_items_of_the_chest_it_placed() -> None:
    # A chest's contents are not sent to a Bot that watches it: only the block state is. The
    # builder's `data get block` answer says them, and that is compared.
    [(window, read)] = readbacks(await played("blocks/setblock"))

    assert read.path == "Items"
    [block] = [setup.block for setup in placed(window) if setup.at == read.at]
    assert block.startswith("minecraft:chest")
    assert "minecraft:diamond" in block


GLASS = "minecraft:glass"
SECTION = 16
"""Blocks high in a chunk section: a section border is where `y // SECTION` changes."""

type Point = tuple[int, int, int]


@dataclass(frozen=True)
class Box:
    """A box of blocks, from its lowest corner to its highest (both inside it)."""

    low: Point
    high: Point

    @classmethod
    def between(cls, one: Point, other: Point) -> Self:
        """The box with these two corners, given in either order."""
        low = (min(one[0], other[0]), min(one[1], other[1]), min(one[2], other[2]))
        high = (max(one[0], other[0]), max(one[1], other[1]), max(one[2], other[2]))
        return cls(low, high)

    @property
    def size(self) -> Point:
        return (
            self.high[0] - self.low[0] + 1,
            self.high[1] - self.low[1] + 1,
            self.high[2] - self.low[2] + 1,
        )

    def holds(self, at: Point) -> bool:
        return all(
            low <= each <= high for low, each, high in zip(self.low, at, self.high, strict=True)
        )

    def overlaps(self, other: Self) -> bool:
        return all(
            low <= other_high and other_low <= high
            for low, high, other_low, other_high in zip(
                self.low, self.high, other.low, other.high, strict=True
            )
        )


_FILL = re.compile(rf"fill {' '.join([_NUMBER] * 6)} (\S+?)(?: (.+))?")


@dataclass(frozen=True)
class Fill:
    """A parsed `fill`: its box, the block, and the mode (or `replace` and a filter) after it."""

    box: Box
    block: str
    option: str | None


def parse_fill(command: str) -> Fill | None:
    """`command` as a Fill, or None if it is not a `fill` command."""
    match = _FILL.fullmatch(command)
    if match is None:
        return None
    *corners, block, option = match.groups()
    x1, y1, z1, x2, y2, z2 = (int(number) for number in corners)
    return Fill(Box.between((x1, y1, z1), (x2, y2, z2)), block, option)


def fill_cases(result: Play) -> list[Fill]:
    """The `fill` each window's builder runs."""
    cases = []
    for window in result.windows:
        command = parse_fill(window.builder[0])
        assert command, window.builder
        cases.append(command)
    return cases


def placed(window: Window) -> list[Setblock]:
    """The blocks Control set before `window` opened, but air."""
    setups = (parse_setblock(command) for command in window.before)
    return [setup for setup in setups if setup is not None and setup.block != AIR]


@pytest.mark.asyncio
async def test_fill_tries_each_mode_the_default_and_a_filter() -> None:
    options = {command.option for command in fill_cases(await played("blocks/fill"))}

    assert options == {
        None,
        "destroy",
        "hollow",
        "keep",
        "outline",
        "replace",
        "replace minecraft:dirt",
        "strict",
    }


@pytest.mark.asyncio
async def test_fill_tries_destroy_last_so_a_server_that_hangs_on_it_answers_the_rest_first() -> (
    None
):
    options = [command.option for command in fill_cases(await played("blocks/fill"))]

    assert options[-1] == "destroy"


@pytest.mark.asyncio
async def test_fill_covers_a_5_by_5_by_5_region_that_crosses_a_chunk_section_border() -> None:
    boxes = {command.box for command in fill_cases(await played("blocks/fill"))}

    assert len(boxes) == 1
    [box] = boxes
    assert box.size == (5, 5, 5)
    assert box.low[1] // SECTION < box.high[1] // SECTION


@pytest.mark.asyncio
async def test_fill_starts_from_a_region_with_blocks_in_both_sections_already_in_it() -> None:
    result = await played("blocks/fill")

    for window, command in zip(result.windows, fill_cases(result), strict=True):
        inside = [setup for setup in placed(window) if command.box.holds(setup.at)]
        assert {setup.at[1] // SECTION for setup in inside} == {
            command.box.low[1] // SECTION,
            command.box.high[1] // SECTION,
        }, window.before


@pytest.mark.asyncio
async def test_fill_leaves_each_window_one_block_that_drops_an_item() -> None:
    # Vanilla resends each new item at the end of the tick in the hash order of its entity id,
    # and the two Instances number their entities differently: two drops in a window can come
    # in a different order on each side, which is no Divergence worth reporting. Glass drops
    # nothing.
    result = await played("blocks/fill")

    for window, command in zip(result.windows, fill_cases(result), strict=True):
        droppers = [
            setup
            for setup in placed(window)
            if setup.block != GLASS and command.box.holds(setup.at)
        ]
        assert len(droppers) == 1, window.before


_CLONE = re.compile(
    rf"clone {' '.join([_NUMBER] * 9)} (replace|masked|filtered \S+)(?: (normal|force|move))?"
)


@dataclass(frozen=True)
class Clone:
    """A parsed `clone`: the box it copies, the box it copies to, which blocks and how."""

    source: Box
    destination: Box
    blocks: str
    how: str | None

    @property
    def mask(self) -> str:
        """Which blocks it copies: `replace`, `masked` or `filtered`."""
        return self.blocks.split()[0]

    @property
    def offset(self) -> Point:
        """How far the copy moves each block."""
        return (
            self.destination.low[0] - self.source.low[0],
            self.destination.low[1] - self.source.low[1],
            self.destination.low[2] - self.source.low[2],
        )


def parse_clone(command: str) -> Clone | None:
    """`command` as a Clone, or None if it is not a `clone` command."""
    match = _CLONE.fullmatch(command)
    if match is None:
        return None
    *numbers, blocks, how = match.groups()
    x1, y1, z1, x2, y2, z2, dx, dy, dz = (int(number) for number in numbers)
    source = Box.between((x1, y1, z1), (x2, y2, z2))
    size = source.size
    destination = Box((dx, dy, dz), (dx + size[0] - 1, dy + size[1] - 1, dz + size[2] - 1))
    return Clone(source, destination, blocks, how)


def clone_cases(result: Play) -> list[tuple[Window, Clone]]:
    """The windows in which the builder runs a `clone`, each with it."""
    cases = ((window, parse_clone(window.builder[0])) for window in result.windows)
    return [(window, clone) for window, clone in cases if clone is not None]


def apart(result: Play) -> list[tuple[Window, Clone]]:
    """The `clone` windows whose source and destination do not overlap."""
    return [
        (window, clone)
        for window, clone in clone_cases(result)
        if not clone.source.overlaps(clone.destination)
    ]


@pytest.mark.asyncio
async def test_clone_tries_each_kind_of_block_with_each_way_to_copy() -> None:
    clones = [clone for _, clone in apart(await played("blocks/clone"))]

    assert {(clone.mask, clone.how) for clone in clones} == {
        (mask, how)
        for mask in ("replace", "masked", "filtered")
        for how in ("normal", "force", "move")
    }
    assert {clone.blocks for clone in clones if clone.mask == "filtered"} == {
        "filtered minecraft:stone"
    }


@pytest.mark.asyncio
async def test_clone_tries_a_source_and_destination_that_overlap_with_and_without_force() -> None:
    result = await played("blocks/clone")

    overlapping = [
        clone for _, clone in clone_cases(result) if clone.source.overlaps(clone.destination)
    ]
    assert {clone.how for clone in overlapping} == {"normal", "force", "move"}


@pytest.mark.asyncio
async def test_clone_copies_a_chest_with_an_item_a_sign_with_text_and_a_block_with_states() -> None:
    result = await played("blocks/clone")

    for window, clone in apart(result):
        source = [setup.block for setup in placed(window) if clone.source.holds(setup.at)]
        assert any(
            block.startswith("minecraft:oak_sign") and "front_text" in block for block in source
        )
        assert any(
            block.startswith("minecraft:chest") and "minecraft:diamond" in block for block in source
        )
        assert any(block.startswith("minecraft:oak_stairs[") for block in source)
        assert "minecraft:stone" in source


@pytest.mark.asyncio
async def test_clone_has_a_block_in_the_destination_where_the_source_has_air() -> None:
    # `masked` leaves it alone and `replace` clears it.
    for window, clone in apart(await played("blocks/clone")):
        dx, dy, dz = clone.offset
        copied = {setup.at for setup in placed(window) if clone.source.holds(setup.at)}
        gaps = [
            setup
            for setup in placed(window)
            if clone.destination.holds(setup.at)
            and (setup.at[0] - dx, setup.at[1] - dy, setup.at[2] - dz) not in copied
        ]
        assert gaps, window.before


@pytest.mark.asyncio
async def test_clone_reads_back_the_items_of_a_chest_it_copied_and_one_it_moved() -> None:
    result = await played("blocks/clone")

    reads = readbacks(result)
    assert len(reads) == 2
    hows = set()
    for window, read in reads:
        [clone] = [parsed for command in window.before if (parsed := parse_clone(command))]
        [chest] = [setup for setup in placed(window) if setup.block.startswith("minecraft:chest")]
        dx, dy, dz = clone.offset
        assert read.at == (chest.at[0] + dx, chest.at[1] + dy, chest.at[2] + dz)
        assert read.path == "Items"
        assert not clone.source.overlaps(clone.destination)
        hows.add(clone.how)
    assert hows == {"normal", "move"}


def positions(command: str) -> list[Point]:
    """Where a command puts or reads blocks: a position, or the corners of its boxes."""
    if (setblock := parse_setblock(command)) is not None:
        return [setblock.at]
    if (readback := parse_readback(command)) is not None:
        return [readback.at]
    if (fill := parse_fill(command)) is not None:
        return [fill.box.low, fill.box.high]
    if (clone := parse_clone(command)) is not None:
        return [clone.source.low, clone.source.high, clone.destination.low, clone.destination.high]
    return []


@pytest.mark.asyncio
@pytest.mark.parametrize("group_id", GROUP_IDS)
async def test_every_block_a_command_changes_is_in_chunk_0_0(group_id: str) -> None:
    # A Bot has had only the chunk it joined in (docs/guide/writing-a-group.md): x and z 0 to 15.
    commands = await every_command(group_id)

    changed = [at for command in commands for at in positions(command)]
    assert changed
    assert all(0 <= x <= 15 and 0 <= z <= 15 for x, _, z in changed), changed


_TP = re.compile(r"tp (builder|control) (-?[\d.]+) (-?[\d.]+) (-?[\d.]+)")
PLAYER_HALF_WIDTH, PLAYER_HEIGHT = 0.3, 1.8
"""A standing player's collision box: 0.6 wide and 1.8 high, its feet at its position."""


def changed_boxes(command: str) -> list[Box]:
    """The boxes of blocks a command sets: a position, or a fill's box, or a clone's two."""
    if (setblock := parse_setblock(command)) is not None:
        return [Box(setblock.at, setblock.at)]
    if (fill := parse_fill(command)) is not None:
        return [fill.box]
    if (clone := parse_clone(command)) is not None:
        return [clone.source, clone.destination]
    return []


def stands_in(at: tuple[float, float, float], box: Box) -> bool:
    """Whether a player standing at `at` touches a block of `box` (each block is 1 x 1 x 1)."""
    x, y, z = at
    low = (x - PLAYER_HALF_WIDTH, y, z - PLAYER_HALF_WIDTH)
    high = (x + PLAYER_HALF_WIDTH, y + PLAYER_HEIGHT, z + PLAYER_HALF_WIDTH)
    return all(
        lo < block_high + 1 and block_low < hi
        for lo, hi, block_low, block_high in zip(low, high, box.low, box.high, strict=True)
    )


FLOOR_Y = -60
"""The feet of a player on the flat world: the top of its grass (the floor is at y -61)."""


def place_of(result: Play, player: str) -> tuple[float, float, float]:
    """Where Control moves `player` before the first window (it moves each exactly once)."""
    moves = [
        move
        for command in result.windows[0].before
        if (move := _TP.fullmatch(command)) and move[1] == player
    ]
    assert len(moves) == 1, result.windows[0].before
    return float(moves[0][2]), float(moves[0][3]), float(moves[0][4])


def touch(one: tuple[float, float, float], other: tuple[float, float, float]) -> bool:
    """Whether two standing players' collision boxes overlap or touch."""
    width, height = 2 * PLAYER_HALF_WIDTH, PLAYER_HEIGHT
    return (
        abs(one[0] - other[0]) <= width
        and abs(one[1] - other[1]) <= height
        and abs(one[2] - other[2]) <= width
    )


def assert_clear_of_every_block(result: Play, player: str, other: str) -> None:
    """`player` is moved to a place on the ground, clear of every block set and of `other`."""
    at = place_of(result, player)
    commands = [
        *(command for window in result.windows for command in (*window.before, *window.builder)),
        *result.after,
    ]
    boxes = [box for command in commands for box in changed_boxes(command)]
    assert boxes
    assert not [box for box in boxes if stands_in(at, box)], at
    assert at[1] == FLOOR_Y, at  # not in the floor, and not above it (it would fall)
    assert not touch(at, place_of(result, other)), (at, other)
    assert (at[0] // SECTION, at[2] // SECTION) == (0, 0)  # it still stands in chunk (0, 0)


@pytest.mark.asyncio
@pytest.mark.parametrize("group_id", GROUP_IDS)
async def test_control_moves_the_builder_clear_of_every_block_a_command_sets(
    group_id: str,
) -> None:
    # Vanilla joins a player at a random place inside the spawn radius, once per world: a
    # block set where the builder stands makes it crawl and choke (a `set_entity_data` on one
    # Instance only).
    assert_clear_of_every_block(await played(group_id), blocks.BUILDER, CONTROL)


@pytest.mark.asyncio
@pytest.mark.parametrize("group_id", GROUP_IDS)
async def test_control_moves_itself_clear_of_every_block_a_command_sets(group_id: str) -> None:
    # The same for Control (#300): it joins at a random place too, and the builder is sent
    # its pose and health inside a window when a block sets them (`set_entity_data`).
    assert_clear_of_every_block(await played(group_id), CONTROL, blocks.BUILDER)
