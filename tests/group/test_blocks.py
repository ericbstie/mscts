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

import pytest

from mscts.bot import TICK_GAP_S
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
COMMANDS = tree("setblock", "fill", "clone", "tellraw", "tick", "gamerule", "kill")
GROUP_IDS = ("blocks/setblock",)
UNDO = ("kill @e[type=minecraft:item]", "gamerule random_tick_speed 3", "tick unfreeze")
"""What Control ends with, whatever happened: the last commands of every play."""


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
                        if requests % 2 == 0:
                            await asyncio.sleep(TICK_S)  # a barrier's second answer, a tick on
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
    """The windows of `transcript` (each opened and closed) and Control's commands after them."""
    builder, control = sent(transcript, blocks.BUILDER), sent(transcript, CONTROL)
    opens = [mark for mark in transcript.marks if mark.label.startswith(OBSERVE_OPEN)]
    closes = [mark for mark in transcript.marks if mark.label == OBSERVE_CLOSE]
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

    assert result.windows[0].before[:2] == ("tick freeze", "gamerule random_tick_speed 0")
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
    assert control[:2] == ["tick freeze", "gamerule random_tick_speed 0"]
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


async def every_command(group_id: str) -> list[str]:
    """Every command the Group sends, Control's first then the builder's."""
    transcript, _ = await play(group_id)
    return [command for bot in (CONTROL, blocks.BUILDER) for _, command in sent(transcript, bot)]


def setblock_cases(result: Play) -> list[tuple[Setblock, str]]:
    """Each window's `setblock`, with the block that was at its position when it opened."""
    cases = []
    for window in result.windows:
        command = parse_setblock(window.builder[0])
        assert command, window.builder
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
@pytest.mark.parametrize("group_id", GROUP_IDS)
async def test_every_block_a_command_changes_is_in_chunk_0_0(group_id: str) -> None:
    # A Bot has had only the chunk it joined in (docs/guide/writing-a-group.md): x and z 0 to 15.
    commands = await every_command(group_id)

    positions = [command.at for each in commands if (command := parse_setblock(each)) is not None]
    assert positions
    assert all(0 <= x <= 15 and 0 <= z <= 15 for x, _, z in positions), positions
