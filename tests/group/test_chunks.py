"""The chunks Groups: what Control sets up and undoes, what the walker does, and the windows.

Every test plays a Group against a fake server that sends the walker the chunks of its view,
and reads the Transcript for what each Bot sent and the Marks. What a server answers is never
asserted.
"""

import asyncio
import json
from contextlib import suppress
from dataclasses import dataclass, field

import pytest

from mscts.bot import SYNC_REQUESTS, TICK_GAP_S
from mscts.case_titles import TITLES
from mscts.codec.packets import Direction, Packet
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
CHAT_COMMAND, CLIENT_COMMAND = "minecraft:chat_command", "minecraft:client_command"
AWARD_STATS, CHUNK = "minecraft:award_stats", "minecraft:level_chunk_with_light"
MARKER = "tellraw @s "
CONTROL, WALKER = "control", chunks.WALKER
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

    The join's first batch holds chunk (0, 0) (`join_server`); the rest of the view at
    `distance` follows at once. A marker (`tellraw @s "<token>"`) gets its token back; no
    other command gets feedback. Chunk `withheld` is never sent.
    """

    distance: int = chunks.VIEW_DISTANCE
    withheld: Chunk | None = None
    seen: list[Packet] = field(default_factory=list)

    async def __call__(self, peer: Peer) -> None:
        """Serve one connection: a Handler."""
        # A Bot that leaves with something unread resets the connection instead of closing it.
        with suppress(ConnectionError):
            await join_server(self.seen, JoinScript(commands=COMMANDS, then=self._play))(peer)

    async def _play(self, peer: Peer) -> None:
        hellos = [packet for packet in self.seen if packet.name == "minecraft:hello"]
        if (hellos[-1].fields or {})["name"] == WALKER:
            await self.send(peer, chunks.view(chunks.SPAWN, self.distance) - {(0, 0)})
        requests = 0
        async for packet in peer.packets():
            self.seen.append(packet)
            if packet.name == CLIENT_COMMAND:
                requests += 1
                if (requests - 1) % SYNC_REQUESTS != 0:
                    await asyncio.sleep(TICK_S)  # a barrier's answers come a tick apart
                await peer.write(peer.raw_frame(AWARD_STATS, NO_STATISTICS))
            elif packet.name == CHAT_COMMAND:
                command = str((packet.fields or {})["command"])
                if command.startswith(MARKER):
                    await peer.write(chat(peer, json.loads(command.removeprefix(MARKER))))

    async def send(self, peer: Peer, positions: frozenset[Chunk]) -> None:
        """Send a chunk at each of `positions` but `withheld`, in one write."""
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
DISTANCES = {"chunks/join-view": 2, "chunks/view-distance": 5}


@pytest.mark.parametrize("group_id", JOINS)
def test_each_join_group_is_exact_requires_join_basic_and_sets_its_view_distance(
    group_id: str,
) -> None:
    group = GROUPS[group_id]
    default = ServerSpec(host="127.0.0.1", port=25566)

    assert group.kind is GroupKind.EXACT
    assert (group.masks, group.requires) == ((), ("join/basic",))
    assert group.spec(default).view_distance == DISTANCES[group_id]


@pytest.mark.asyncio
@pytest.mark.parametrize("group_id", JOINS)
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
    monkeypatch.setattr(chunks, "SENT_TIMEOUT_S", 0.2)
    transcript = Transcript(group_id="chunks/join-view", server="fake")
    with pytest.raises(TimeoutError):
        async with playing(ChunksServer(withheld=(3, 3)), transcript) as context:
            await GROUPS["chunks/join-view"].run(context)

    assert [command for _, command in sent(transcript, CONTROL)] == [*SET_UP, *UNDO]
