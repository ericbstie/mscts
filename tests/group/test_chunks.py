"""The chunks Groups: what Control sets up and undoes, what the walker does, and the windows.

Every test plays a Group against a fake server that sends the walker the chunks of its view,
and reads the Transcript for what each Bot sent and the Marks. What a server answers is never
asserted.
"""

import asyncio
import json
from contextlib import suppress
from dataclasses import dataclass, field
from typing import cast

import pytest

from mscts import run
from mscts.bot import SYNC_REQUESTS, TICK_GAP_S
from mscts.case_titles import TITLES
from mscts.codec.packets import CodecError, Direction, Packet
from mscts.compare import OBSERVE_CLOSE, OBSERVE_OPEN
from mscts.group import GROUPS, GroupKind
from mscts.groups import chunks
from mscts.net import Endpoint
from mscts.spec import ServerSpec
from mscts.transcript import Event, Transcript
from tests.group.test_blocks import sent
from tests.group.test_control import chat, playing, tree
from tests.net.fakes import EMPTY_CHUNK, NO_STATISTICS, JoinScript, Peer, join_server

TICK_S = 2 * TICK_GAP_S
"""The fake's tick: just over what a barrier needs to see one pass, so a play is quick."""
LATE_S = 0.1
"""How long after the join the fake sends the rest of the walker's view: past the join's barrier."""
CHAT_COMMAND, CLIENT_COMMAND = "minecraft:chat_command", "minecraft:client_command"
MOVE = "minecraft:move_player_pos"
MOVES = {MOVE, "minecraft:move_player_pos_rot"}
"""What a step can be sent as: the first after the join turns the player too (the fake's yaw)."""
AWARD_STATS, CHUNK = "minecraft:award_stats", "minecraft:level_chunk_with_light"
MARKER = "tellraw @s "
CONTROL, WALKER = "control", chunks.WALKER
TELEPORT = f"tp {WALKER} {chunks.FAR_AT}"
COMMANDS = tree("gamerule", "tick", "tp", "tellraw")
SET_UP = ("gamerule player_movement_check false", "gamerule respawn_radius 0", "tick freeze")
UNDO = (
    "tp walker 0.5 -60 0.5",
    "tick unfreeze",
    "gamerule respawn_radius 10",
    "gamerule player_movement_check true",
)
"""What Control ends with: the walker put back at the spawn, then each setting, the last first."""

type Chunk = tuple[int, int]


@dataclass
class ChunksServer:
    """A fake server that joins like vanilla and sends the walker the chunks of its view.

    The join's first batch holds the chunks `first`, (0, 0) unless told otherwise; the rest of
    the view at `distance` follows `LATE_S` later, after any barrier the join ends with.
    Control's teleport of the walker to `chunks.FAR_AT` sends the walker the view around
    `chunks.FAR`, and its first step into chunk (-1, 0) sends it the chunks that step brings
    into its view. A marker (`tellraw @s "<token>"`) gets its token back; no other command gets
    feedback. Chunk `withheld` is never sent. With `ring`, the chunks one view distance
    further out follow a whole barrier after the view: a view one ring too big, sent nearest
    first, as vanilla sends a view. With `undecodable`, a chunk with no payload, which the codec
    refuses, comes before the rest of the view.
    """

    distance: int = chunks.VIEW_DISTANCE
    withheld: Chunk | None = None
    first: frozenset[Chunk] = frozenset({(0, 0)})
    ring: bool = False
    undecodable: bool = False
    seen: list[Packet] = field(default_factory=list)
    walker: Peer | None = None
    late: set[asyncio.Task[None]] = field(default_factory=set)
    viewed: bool = False

    async def __call__(self, peer: Peer) -> None:
        """Serve one connection: a Handler."""
        # A Bot that leaves with something unread resets the connection instead of closing it.
        with suppress(ConnectionError):
            batch = [EMPTY_CHUNK | {"chunk_x": x, "chunk_z": z} for x, z in sorted(self.first)]
            script = JoinScript(commands=COMMANDS, first_batch=batch, then=self._play)
            await join_server(self.seen, script)(peer)

    async def _play(self, peer: Peer) -> None:
        hellos = [packet for packet in self.seen if packet.name == "minecraft:hello"]
        if (hellos[-1].fields or {})["name"] == WALKER:
            self.walker = peer
            rest = chunks.view(chunks.SPAWN, self.distance) - self.first
            task = asyncio.create_task(self._send_view(peer, rest))
            self.late.add(task)
            task.add_done_callback(self.late.discard)
        requests, after_view, crossed = 0, 0, False
        async for packet in peer.packets():
            self.seen.append(packet)
            if (
                packet.name in MOVES
                and cast("float", (packet.fields or {})["x"]) < 0
                and not crossed
            ):
                crossed = True
                west = chunks.view((-1, 0), self.distance) - chunks.view(
                    chunks.SPAWN, self.distance
                )
                await self.send(peer, west)
            elif packet.name == CLIENT_COMMAND:
                requests += 1
                after_view += self.viewed and peer is self.walker
                if self.ring and after_view == SYNC_REQUESTS + 1:
                    far = chunks.view(chunks.SPAWN, self.distance + 1)
                    await self.send(peer, far - chunks.view(chunks.SPAWN, self.distance))
                if (requests - 1) % SYNC_REQUESTS != 0:
                    await asyncio.sleep(TICK_S)  # a barrier's answers come a tick apart
                await peer.write(peer.raw_frame(AWARD_STATS, NO_STATISTICS))
            elif packet.name == CHAT_COMMAND:
                command = str((packet.fields or {})["command"])
                if command.startswith(MARKER):
                    await peer.write(chat(peer, json.loads(command.removeprefix(MARKER))))
                elif command == TELEPORT and self.walker is not None:
                    await self.send(self.walker, chunks.view(chunks.FAR, self.distance))

    async def _send_view(self, peer: Peer, rest: frozenset[Chunk]) -> None:
        if self.undecodable:
            await asyncio.sleep(LATE_S)
            await peer.write(peer.raw_frame(CHUNK))
        await self.send(peer, rest, after_s=LATE_S)
        self.viewed = True

    async def send(self, peer: Peer, positions: frozenset[Chunk], *, after_s: float = 0) -> None:
        """Send a chunk at each of `positions` but `withheld`, in one write, `after_s` from now."""
        await asyncio.sleep(after_s)
        frames = [
            peer.frame(CHUNK, **(EMPTY_CHUNK | {"chunk_x": x, "chunk_z": z}))
            for x, z in sorted(positions - {self.withheld})
        ]
        await peer.write(b"".join(frames))


@pytest.fixture(autouse=True)
def settled(monkeypatch: pytest.MonkeyPatch) -> list[Endpoint]:
    """Where the Group waited for no player to be online, instead of polling the fake."""
    endpoints: list[Endpoint] = []

    async def until_no_player_online(endpoint: Endpoint) -> None:
        endpoints.append(endpoint)

    monkeypatch.setattr(chunks, "until_no_player_online", until_no_player_online)
    return endpoints


async def play(group_id: str, server: ChunksServer | None = None) -> Transcript:
    """Play `group_id` against a fake server; return its Transcript."""
    transcript = Transcript(group_id=group_id, server="fake")
    async with playing(server or ChunksServer(), transcript) as context:
        await GROUPS[group_id].run(context)
    return transcript


def window(transcript: Transcript) -> tuple[int, int]:
    """When the play's one window opened, and when it closed for the walker."""
    (opened,) = [mark.t_ns for mark in transcript.marks if mark.label.startswith(OBSERVE_OPEN)]
    (closed,) = [m.t_ns for m in transcript.marks if m.label == f"{OBSERVE_CLOSE} {WALKER}"]
    return opened, closed


def received(transcript: Transcript, name: str) -> list[Event]:
    """The packets called `name` the walker received."""
    return [
        event
        for event in transcript.events
        if event.bot == WALKER
        and event.packet.direction is Direction.CLIENTBOUND
        and event.packet.name == name
    ]


def position(event: Event) -> Chunk:
    """Which chunk a `level_chunk_with_light` event carries."""
    fields = event.packet.fields or {}
    return cast("int", fields["chunk_x"]), cast("int", fields["chunk_z"])


def joined(server: ChunksServer) -> list[str]:
    """The players who joined, in order."""
    return [str((p.fields or {})["name"]) for p in server.seen if p.name == "minecraft:hello"]


def test_a_view_is_vanillas_chunk_tracking_view() -> None:
    assert chunks.view((0, 0), 2) == {(x, z) for x in range(-3, 4) for z in range(-3, 4)}
    far = chunks.view((0, 0), 5)
    assert {(6, 4), (5, 5), (4, 6), (-6, -4)} <= far, "|x| - 2 squared and summed is under 25"
    assert not {(6, 5), (5, 6), (6, 6), (7, 0)} & far
    assert chunks.view((20, -1), 2) == {(x + 20, z - 1) for x, z in chunks.view((0, 0), 2)}


JOINS = ("chunks/join-view", "chunks/view-distance")
ALL = (*JOINS, "chunks/teleport", "chunks/walk")
DISTANCES = {
    "chunks/join-view": 2,
    "chunks/view-distance": 5,
    "chunks/teleport": 2,
    "chunks/walk": 2,
}


@pytest.mark.parametrize("group_id", ALL)
def test_each_group_is_exact_requires_nothing_and_sets_its_view_distance(
    group_id: str,
) -> None:
    group = GROUPS[group_id]
    default = ServerSpec(host="127.0.0.1", port=25566)

    assert group.kind is GroupKind.EXACT
    assert (group.masks, group.requires) == ((), ())
    assert group.spec(default).view_distance == DISTANCES[group_id]


@pytest.mark.asyncio
@pytest.mark.parametrize("group_id", ALL)
async def test_control_sets_the_fixture_leaves_and_undoes_it_after_the_walker_joined(
    group_id: str, settled: list[Endpoint]
) -> None:
    server = ChunksServer(distance=DISTANCES[group_id])
    transcript = await play(group_id, server)

    opened, closed = window(transcript)
    control = sent(transcript, CONTROL)
    assert [command for t, command in control if t < opened] == list(SET_UP)
    assert [command for t, command in control if t > closed] == list(UNDO)
    assert joined(server) == [CONTROL, WALKER, CONTROL], "the walker joins alone"
    assert len(settled) == 1, "once Control has left"


@pytest.mark.asyncio
@pytest.mark.parametrize("group_id", JOINS)
async def test_the_window_holds_the_join_and_every_chunk_of_the_view(group_id: str) -> None:
    transcript = await play(group_id, ChunksServer(distance=DISTANCES[group_id]))

    opened, closed = window(transcript)
    (label,) = [mark.label for mark in transcript.marks if mark.label.startswith(OBSERVE_OPEN)]
    assert label == f"{OBSERVE_OPEN} {' '.join(chunks.PACKETS)}"
    walker = [event.t_ns for event in transcript.events if event.bot == WALKER]
    assert opened <= min(walker), "the whole join"
    arrived = received(transcript, CHUNK)
    assert len(arrived) == len(chunks.view(chunks.SPAWN, DISTANCES[group_id]))
    assert max(event.t_ns for event in arrived) < closed


@pytest.mark.asyncio
@pytest.mark.parametrize("group_id", JOINS)
async def test_the_window_holds_a_ring_too_many_sent_a_barrier_after_the_view(
    group_id: str,
) -> None:
    # Review B of #280, S2: the window closed at the barrier after the view, so a view one
    # ring too big, its outer ring sent last, matched vanilla's.
    distance = DISTANCES[group_id]
    transcript = await play(group_id, ChunksServer(distance=distance, ring=True))

    _, closed = window(transcript)
    ring = chunks.view(chunks.SPAWN, distance + 1) - chunks.view(chunks.SPAWN, distance)
    arrived = {position(event): event.t_ns for event in received(transcript, CHUNK)}
    assert ring <= arrived.keys()
    assert max(arrived[chunk] for chunk in ring) < closed


def test_the_windows_compare_the_chunks_sent_and_forgotten_and_the_view_centre() -> None:
    assert chunks.PACKETS == (
        "minecraft:level_chunk_with_light",
        "minecraft:forget_level_chunk",
        "minecraft:set_chunk_cache_center",
    )


def test_the_view_centre_has_titles() -> None:
    centre = "set_chunk_cache_center"
    assert {centre, f"{centre}.chunk_x", f"{centre}.chunk_z"} <= TITLES.keys()


@pytest.mark.asyncio
async def test_a_chunk_never_sent_fails_the_group_and_control_still_undoes_the_fixture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(run, "GROUP_TIMEOUT_S", 0.5)
    transcript = Transcript(group_id="chunks/join-view", server="fake")
    with pytest.raises(TimeoutError):
        async with playing(ChunksServer(withheld=(3, 3)), transcript) as context:
            await GROUPS["chunks/join-view"].run(context)

    assert [command for _, command in sent(transcript, CONTROL)] == [*SET_UP, *UNDO]


@pytest.mark.asyncio
async def test_the_teleport_window_holds_control_teleporting_the_walker_once_it_had_its_view() -> (
    None
):
    transcript = await play("chunks/teleport")

    opened, closed = window(transcript)
    assert [command for t, command in sent(transcript, CONTROL) if opened < t < closed] == [
        TELEPORT
    ]
    arrived = {position(event): event.t_ns for event in received(transcript, CHUNK)}
    spawn, far = chunks.view(chunks.SPAWN, 2), chunks.view(chunks.FAR, 2)
    assert max(arrived[chunk] for chunk in spawn) < opened, "the whole view before the window"
    assert opened < min(arrived[chunk] for chunk in far)
    assert max(arrived[chunk] for chunk in far) < closed


@pytest.mark.asyncio
async def test_a_chunk_never_sent_after_the_teleport_fails_the_group_and_control_still_undoes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(run, "GROUP_TIMEOUT_S", 0.5)
    transcript = Transcript(group_id="chunks/teleport", server="fake")
    with pytest.raises(TimeoutError):
        async with playing(ChunksServer(withheld=(23, 3)), transcript) as context:
            await GROUPS["chunks/teleport"].run(context)

    assert [command for _, command in sent(transcript, CONTROL)] == [*SET_UP, TELEPORT, *UNDO]


def walked(transcript: Transcript) -> list[tuple[int, str]]:
    """What the walker sent of its steps and barriers, with when: each step's x, or `sync`."""
    return [
        (e.t_ns, str((e.packet.fields or {})["x"]) if e.packet.name in MOVES else "sync")
        for e in transcript.events
        if e.bot == WALKER
        and e.packet.direction is Direction.SERVERBOUND
        and e.packet.name in {*MOVES, CLIENT_COMMAND}
    ]


@pytest.mark.asyncio
async def test_the_walk_window_holds_a_step_a_tick_and_every_new_chunk() -> None:
    transcript = await play("chunks/walk")

    opened, closed = window(transcript)
    inside = [what for t, what in walked(transcript) if opened < t < closed]
    steps = [str(x) for x in chunks.WALK]
    barrier = ["sync"] * SYNC_REQUESTS
    # A step a tick: a barrier after each step but the last, which the wait for the new
    # column, 3 barriers (about 9 ticks, as groups.md says) and the window's own barrier
    # follow. The count is written out, not read from `chunks.HELD_SYNCS` (review C, L-C2).
    held = barrier * 4
    assert inside == [steps[0], *barrier, steps[1], *barrier, steps[2], *held]
    west = chunks.view((-1, 0), 2) - chunks.view(chunks.SPAWN, 2)
    arrived = {position(event): event.t_ns for event in received(transcript, CHUNK)}
    spawn = chunks.view(chunks.SPAWN, 2)
    assert max(arrived[chunk] for chunk in spawn) < opened, "the whole view before the window"
    assert west <= arrived.keys()
    assert opened < min(arrived[chunk] for chunk in west)
    assert max(arrived[chunk] for chunk in west) < closed


@pytest.mark.asyncio
async def test_a_chunk_never_sent_after_the_step_across_fails_the_group_and_control_undoes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(run, "GROUP_TIMEOUT_S", 0.5)
    transcript = Transcript(group_id="chunks/walk", server="fake")
    with pytest.raises(TimeoutError):
        async with playing(ChunksServer(withheld=(-4, 0)), transcript) as context:
            await GROUPS["chunks/walk"].run(context)

    assert [command for _, command in sent(transcript, CONTROL)] == [*SET_UP, *UNDO]


FIRST_BATCHES = {
    "an-outer-chunk": frozenset({(0, 0), (2, 0)}),
    "the-whole-view": chunks.view(chunks.SPAWN, chunks.VIEW_DISTANCE),
}
"""First batches vanilla's own need not be: the 9 nearest *ready* chunks, so an outer chunk
when fewer of the 3 by 3 are ready (`PlayerChunkSender.collectChunksToSend`, 26.3 javap), or a
server that sends the whole view at once (#280 review, B1)."""


@pytest.mark.asyncio
@pytest.mark.parametrize("first", FIRST_BATCHES.values(), ids=FIRST_BATCHES.keys())
@pytest.mark.parametrize("group_id", ["chunks/join-view", "chunks/teleport", "chunks/walk"])
async def test_a_group_counts_the_chunks_the_first_batch_held(
    group_id: str, first: frozenset[Chunk]
) -> None:
    transcript = await play(group_id, ChunksServer(first=first))

    spawn = chunks.view(chunks.SPAWN, chunks.VIEW_DISTANCE)
    assert spawn <= {position(event) for event in received(transcript, CHUNK)}


@pytest.mark.asyncio
async def test_a_chunk_never_sent_is_named_when_the_group_gives_up_at_a_bots_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(run, "GROUP_TIMEOUT_S", 0.5)
    with pytest.raises(TimeoutError, match=r"\(3, 3\)\] never arrived within 0\.5 s"):
        await play("chunks/join-view", ChunksServer(withheld=(3, 3)))


@pytest.mark.asyncio
async def test_a_chunk_the_codec_refuses_fails_the_group_with_the_decode_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Review B of #280, L4: the Bot's reader stops at the chunk, so the Group fails with why,
    # not with a wait that timed out.
    monkeypatch.setattr(run, "GROUP_TIMEOUT_S", 0.5)
    with pytest.raises(CodecError):
        await play("chunks/join-view", ChunksServer(undecodable=True))
