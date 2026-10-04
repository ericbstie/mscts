"""The movement Groups: the moves each case sends, in which windows, and what is undone after.

Every test plays a Group against a fake server and reads the Transcript for what each Bot
sent (its moves, Control's commands) and the Marks (the Observation windows). What a server
answers is never asserted: the fake only kicks the floating survival Bot, so that
`movement/flying` can end.
"""

import asyncio
import json
from contextlib import suppress
from dataclasses import dataclass, field

import pytest

from mscts.bot import SYNC_REQUESTS
from mscts.codec.packets import Direction, Packet
from mscts.compare import OBSERVE_CLOSE, OBSERVE_OPEN
from mscts.group import GROUPS, GroupKind
from mscts.groups import movement
from mscts.net import ProtocolError
from mscts.spec import ServerSpec
from mscts.transcript import Transcript
from tests.group.test_control import playing, text, tree
from tests.net.fakes import NO_STATISTICS, TICK_S, JoinScript, Peer, join_server

CONTROL = "control"
MARKER = "tellraw @s "
CHAT_COMMAND, CLIENT_COMMAND = "minecraft:chat_command", "minecraft:client_command"
MOVES = ("minecraft:move_player_pos", "minecraft:move_player_pos_rot")
COMMANDS = tree("gamerule", "tp", "tick", "fill", "setblock", "gamemode", "tellraw")
KICKED = bytes.fromhex("08 0004") + b"kick"
"""A disconnect's reason: an NBT String text component."""

GROUP_IDS = (
    "movement/too-fast",
    "movement/into-blocks",
    "movement/flying",
    "movement/before-teleport",
)
TICK_EXACT = ("movement/into-blocks", "movement/before-teleport")
BOTS = {
    "movement/too-fast": ("runner",),
    "movement/into-blocks": ("walker",),
    "movement/flying": ("creative_flyer", "lander", "flyer"),
    "movement/before-teleport": ("walker",),
}
CHECK_OFF, CHECK_ON = "gamerule player_movement_check false", "gamerule player_movement_check true"


@dataclass
class MovementServer:
    """A fake server that joins like vanilla, answers Control's markers and the barrier.

    It kicks each Bot named in `kicks` once it has moved twice (its hover), as vanilla kicks
    a survival player that floats: by default `flyer` alone, at once, where vanilla waits 80
    ticks.
    """

    seen: list[Packet] = field(default_factory=list)
    kicks: tuple[str, ...] = ("flyer",)
    stall_after: str | None = None
    """A command after which the fake leaves Control's next marker unanswered (a server that
    ran it but whose answer is late)."""

    async def __call__(self, peer: Peer) -> None:
        """Serve one connection: a Handler."""
        with suppress(ConnectionError):
            await join_server(self.seen, JoinScript(commands=COMMANDS, then=self._play))(peer)

    def _player(self) -> str:
        hellos = [packet for packet in self.seen if packet.name == "minecraft:hello"]
        return str((hellos[-1].fields or {})["name"])

    async def _play(self, peer: Peer) -> None:
        player = self._player()
        requests = moves = 0
        stalled = False
        async for packet in peer.packets():
            self.seen.append(packet)
            if packet.name == CLIENT_COMMAND:
                requests += 1
                if (requests - 1) % SYNC_REQUESTS != 0:
                    await asyncio.sleep(TICK_S)  # a barrier's answers come a tick apart
                await peer.write(peer.raw_frame("minecraft:award_stats", NO_STATISTICS))
            elif packet.name == CHAT_COMMAND:
                command = str((packet.fields or {})["command"])
                if command == self.stall_after:
                    stalled = True
                elif command.startswith(MARKER) and stalled:
                    stalled = False
                elif command.startswith(MARKER):
                    token = json.loads(command.removeprefix(MARKER))
                    await peer.write(
                        peer.frame("minecraft:system_chat", content=text(token), overlay=False)
                    )
            elif packet.name in MOVES and player in self.kicks:
                moves += 1
                if moves == 2:  # _hover's second move
                    # Vanilla closes the connection after it; the fake reads on until the Bot
                    # closes it, so the client_tick_end that follows the move is not left unread.
                    await peer.write(peer.raw_frame("minecraft:disconnect", KICKED))


@dataclass(frozen=True)
class Window:
    """One Observation window: its label, and what was sent inside it, in order.

    Attributes:
        label: Its open Mark's label.
        sent: Each Bot's moves, as `(bot, (x, y, z))`, and Control's commands, as
            `("control", command)`, in the order they were sent; markers left out.
        before: Control's commands since the last window closed.
    """

    label: str
    sent: tuple[tuple[str, object], ...]
    before: tuple[str, ...]

    def moves(self, bot: str) -> list[tuple[float, float, float]]:
        return [what for who, what in self.sent if who == bot]  # ty: ignore[invalid-return-type]


@dataclass(frozen=True)
class Play:
    """A played Group: each window, Control's commands before the first and after the last."""

    windows: tuple[Window, ...]
    first: tuple[str, ...]
    after: tuple[str, ...]


def _sent(transcript: Transcript) -> list[tuple[int, str, object]]:
    """Every move and every command but a marker, with when and by whom."""
    sent: list[tuple[int, str, object]] = []
    for event in transcript.events:
        if event.packet.direction is not Direction.SERVERBOUND:
            continue
        fields = event.packet.fields or {}
        if event.packet.name in MOVES:
            sent.append((event.t_ns, event.bot, (fields["x"], fields["y"], fields["z"])))
        elif event.packet.name == CHAT_COMMAND and not str(fields["command"]).startswith(MARKER):
            sent.append((event.t_ns, event.bot, str(fields["command"])))
    return sent


def read(transcript: Transcript) -> Play:
    """The windows of `transcript`, each from its open Mark to the end of every Bot's."""
    sent = _sent(transcript)
    opens = [mark.t_ns for mark in transcript.marks if mark.label.startswith(OBSERVE_OPEN)]
    labels = [mark.label for mark in transcript.marks if mark.label.startswith(OBSERVE_OPEN)]
    closes = [mark.t_ns for mark in transcript.marks if mark.label == OBSERVE_CLOSE]
    assert len(opens) == len(closes), transcript.marks
    windows = []
    previous = 0
    for label, opened, closed in zip(labels, opens, closes, strict=True):
        windows.append(
            Window(
                label=label,
                sent=tuple((who, what) for t, who, what in sent if opened <= t <= closed),
                before=tuple(
                    str(what) for t, who, what in sent if previous <= t < opened and who == CONTROL
                ),
            )
        )
        previous = closed
    control = [(t, str(what)) for t, who, what in sent if who == CONTROL]
    first = tuple(c for t, c in control if t < opens[0]) if opens else ()
    return Play(tuple(windows), first, tuple(c for t, c in control if t > previous))


async def play(group_id: str, server: MovementServer | None = None) -> tuple[Transcript, Play]:
    """Play `group_id` against a fake server; return its Transcript and what was read from it."""
    transcript = Transcript(group_id=group_id, server="fake")
    async with playing(server or MovementServer(), transcript) as context:
        await GROUPS[group_id].run(context)
    return transcript, read(transcript)


async def played(group_id: str) -> Play:
    return (await play(group_id))[1]


def tp(bot: str, at: tuple[float, float, float]) -> str:
    return "tp {} {} {} {}".format(bot, *at)


STEP = (CONTROL, "tick step 1")


def first_open(transcript: Transcript) -> int:
    """When the first Observation window opened."""
    return next(m.t_ns for m in transcript.marks if m.label.startswith(OBSERVE_OPEN))


# Registration


@pytest.mark.parametrize("group_id", GROUP_IDS)
def test_each_group_is_registered_with_the_default_spec_and_no_mask(group_id: str) -> None:
    group = GROUPS[group_id]
    default = ServerSpec(host="127.0.0.1", port=25566)

    assert group.kind is (GroupKind.TICK_EXACT if group_id in TICK_EXACT else GroupKind.EXACT)
    assert group.requires == ()
    assert group.masks == ()
    assert group.spec(default) == default


def test_the_windows_compare_the_teleports_back_and_the_kicks() -> None:
    assert movement.PACKETS == ("minecraft:player_position", "minecraft:disconnect")


@pytest.mark.asyncio
@pytest.mark.parametrize("group_id", GROUP_IDS)
async def test_every_window_is_narrowed_to_the_teleports_back_and_the_kicks(group_id: str) -> None:
    result = await played(group_id)

    assert result.windows
    assert {window.label for window in result.windows} == {
        f"{OBSERVE_OPEN} {' '.join(movement.PACKETS)}"
    }


# The movement check around the join, and the undo


@pytest.mark.asyncio
@pytest.mark.parametrize("group_id", GROUP_IDS)
async def test_the_bots_join_with_the_movement_check_off_and_it_is_on_after(group_id: str) -> None:
    server = MovementServer()
    transcript, result = await play(group_id, server)

    hellos = [
        event.t_ns
        for event in transcript.events
        if event.packet.name == "minecraft:hello" and event.bot in BOTS[group_id]
    ]
    commands = [(t, what) for t, who, what in _sent(transcript) if who == CONTROL]
    off = next(t for t, command in commands if command == CHECK_OFF)
    on = next(t for t, command in commands if command == CHECK_ON)
    assert len(hellos) == len(BOTS[group_id])
    assert all(off < hello < on for hello in hellos)
    # Undone last (the rule's default), but for the unfreeze that ends a tick-exact Group.
    assert [command for command in result.after if command != "tick unfreeze"][-1] == CHECK_ON


@pytest.mark.asyncio
@pytest.mark.parametrize("group_id", GROUP_IDS)
async def test_the_movement_check_is_turned_on_when_turning_it_off_times_out(group_id: str) -> None:
    # The command may have run though its answer never came: the undo is already pushed.
    transcript = Transcript(group_id=group_id, server="fake")
    async with playing(MovementServer(stall_after=CHECK_OFF), transcript) as context:
        with pytest.raises(TimeoutError):
            await GROUPS[group_id].run(context)

    control = [what for _, who, what in _sent(transcript) if who == CONTROL]
    assert control == [CHECK_OFF, CHECK_ON]


@pytest.mark.asyncio
@pytest.mark.parametrize("group_id", GROUP_IDS)
async def test_the_movement_check_is_on_again_before_the_first_window(group_id: str) -> None:
    # Without it, every window plays with vanilla's speed check off, and a Candidate that has
    # none would match `movement/too-fast`.
    result = await played(group_id)

    assert result.first.index(CHECK_OFF) < result.first.index(CHECK_ON)


@pytest.mark.asyncio
@pytest.mark.parametrize("group_id", TICK_EXACT)
async def test_a_tick_exact_group_freezes_the_world_and_clears_its_blocks_after(
    group_id: str,
) -> None:
    result = await played(group_id)

    assert "tick freeze" in result.first
    assert result.after == (
        "fill 5 -60 1 5 -58 13 minecraft:air",
        CHECK_ON,
        "tick unfreeze",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("group_id", ["movement/too-fast", "movement/flying"])
async def test_the_speed_and_flying_groups_play_in_a_running_world(group_id: str) -> None:
    transcript, _ = await play(group_id)

    commands = [what for _, who, what in _sent(transcript) if who == CONTROL]
    assert not any(str(command).startswith("tick ") for command in commands)


# movement/too-fast


@pytest.mark.asyncio
async def test_too_fast_moves_each_distance_once_from_the_start() -> None:
    result = await played("movement/too-fast")
    start = (8.5, -60.0, 8.5)

    assert [window.before[-1] for window in result.windows] == [tp("runner", start)] * 7
    assert [window.moves("runner") for window in result.windows][:5] == [
        [(8.5 + distance, -60.0, 8.5)] for distance in (1, 5, 9, 11, 20)
    ]


@pytest.mark.asyncio
async def test_too_fast_sends_several_moves_in_one_tick_with_no_barrier_between() -> None:
    transcript, result = await play("movement/too-fast")

    assert [window.moves("runner") for window in result.windows][5:] == [
        [(16.5, -60.0, 8.5), (24.5, -60.0, 8.5)],
        [(8.5 + 2 * k, -60.0, 8.5) for k in range(1, 7)],
    ]
    last = [mark.t_ns for mark in transcript.marks if mark.label.startswith(OBSERVE_OPEN)][-1]
    moves = [t for t, who, what in _sent(transcript) if who == "runner" and t > last]
    requests = [
        event.t_ns
        for event in transcript.events
        if event.bot == "runner" and event.packet.name == CLIENT_COMMAND and event.t_ns > last
    ]
    assert len(moves) == 6
    assert not any(moves[0] < t < moves[-1] for t in requests)


# movement/into-blocks


@pytest.mark.asyncio
async def test_into_blocks_builds_its_blocks_once_the_world_is_frozen() -> None:
    result = await played("movement/into-blocks")

    frozen = result.first.index("tick freeze")
    assert result.first[frozen + 1 :] == (
        "fill 5 -60 1 5 -58 3 minecraft:stone",  # a wall across the lane at z = 2
        "fill 5 -60 5 5 -58 7 minecraft:stone",  # a wall across the lane at z = 6 ...
        "fill 5 -60 6 5 -59 6 minecraft:air",  # ... with a gap 1 block wide and 2 high
        "setblock 5 -60 10 minecraft:stone",  # a full block at z = 10
        "setblock 5 -60 13 minecraft:oak_slab[type=bottom]",  # a bottom slab at z = 13
        tp("walker", (4.5, -60.0, 2.5)),
    )
    assert result.first[frozen - 1] == tp("walker", (4.5, -60.0, 2.5))


@pytest.mark.asyncio
async def test_into_blocks_steps_the_world_after_each_move() -> None:
    result = await played("movement/into-blocks")

    assert [window.sent for window in result.windows] == [
        (("walker", (5.5, -60.0, 2.5)), STEP),
        (
            ("walker", (5.0, -60.0, 6.5)),
            STEP,
            ("walker", (5.5, -60.0, 6.5)),
            STEP,
            ("walker", (6.0, -60.0, 6.5)),
            STEP,
            ("walker", (6.5, -60.0, 6.5)),
            STEP,
        ),
        (("walker", (5.5, -59.0, 10.5)), STEP),
        (("walker", (5.5, -59.5, 13.5)), STEP),
    ]
    assert [window.before[-1] for window in result.windows] == [
        tp("walker", (4.5, -60.0, z)) for z in (2.5, 6.5, 10.5, 13.5)
    ]


# movement/before-teleport


@pytest.mark.asyncio
async def test_before_teleport_sends_its_moves_back_to_back_then_steps() -> None:
    result = await played("movement/before-teleport")

    [window] = result.windows
    assert window.sent == (
        ("walker", (5.5, -60.0, 2.5)),
        ("walker", (5.6, -60.0, 2.5)),
        ("walker", (5.7, -60.0, 2.5)),
        ("walker", (4.0, -60.0, 2.5)),
        STEP,
    )
    assert window.before[-1] == tp("walker", (4.5, -60.0, 2.5))
    assert "fill 5 -60 1 5 -58 3 minecraft:stone" in result.first


# movement/flying


@pytest.mark.asyncio
async def test_flying_hovers_the_creative_bot_first_then_waits_for_the_kick() -> None:
    transcript, result = await play("movement/flying")

    [window] = result.windows
    assert window.sent == (
        ("creative_flyer", (2.5, -58.5, 2.5)),
        ("creative_flyer", (2.5, -58.4, 2.5)),
        ("lander", (10.5, -58.5, 2.5)),
        ("lander", (10.5, -58.4, 2.5)),
        ("lander", (10.5, -60.0, 2.5)),
        ("flyer", (6.5, -58.5, 2.5)),
        ("flyer", (6.5, -58.4, 2.5)),
    )
    # The lander floats across its barriers, and lands on the ground.
    lander = [
        e for e in transcript.events if e.bot == "lander" and e.t_ns >= first_open(transcript)
    ]
    hovered = [i for i, e in enumerate(lander) if e.packet.name in MOVES]
    asked = [i for i, e in enumerate(lander) if e.packet.name == CLIENT_COMMAND]
    between = [i for i in asked if hovered[1] < i < hovered[2]]
    assert len(between) == movement.LANDER_BARRIERS * SYNC_REQUESTS
    assert (lander[hovered[2]].packet.fields or {})["flags"] == 1  # on ground
    assert "gamemode creative creative_flyer" in window.before
    assert result.after[0] == "gamemode survival creative_flyer"
    kicks = [e for e in transcript.events if e.packet.name == "minecraft:disconnect"]
    assert [event.bot for event in kicks] == ["flyer"]


@pytest.mark.asyncio
async def test_flying_fails_a_server_that_kicks_a_short_hover() -> None:
    # Review B of #277, S1: with only the kick compared, a server that kicks a survival
    # player as soon as it floats matched vanilla, which waits 80 ticks. The lander floats
    # for a few ticks, then lands, and must not be kicked.
    transcript = Transcript(group_id="movement/flying", server="fake")
    async with playing(MovementServer(kicks=("flyer", "lander")), transcript) as context:
        with pytest.raises(ProtocolError, match="lander"):
            await GROUPS["movement/flying"].run(context)


@pytest.mark.asyncio
async def test_flying_reports_each_hover_move_in_the_air() -> None:
    transcript, _ = await play("movement/flying")

    flags = {
        (event.packet.fields or {})["flags"]
        for event in transcript.events
        if event.packet.name in MOVES
        and event.bot in BOTS["movement/flying"]
        and (event.packet.fields or {})["y"] != -60.0  # in the air, not the lander landing
    }
    assert flags == {0}  # not on ground


@pytest.mark.asyncio
async def test_flying_undoes_its_settings_when_the_flyer_is_never_kicked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(movement, "KICK_TIMEOUT_S", 0.3)
    transcript = Transcript(group_id="movement/flying", server="fake")
    async with playing(MovementServer(kicks=()), transcript) as context:
        with pytest.raises(TimeoutError):
            await GROUPS["movement/flying"].run(context)

    control = [what for _, who, what in _sent(transcript) if who == CONTROL]
    assert control[-2:] == ["gamemode survival creative_flyer", CHECK_ON]
