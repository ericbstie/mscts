"""A join inside `observe(until="minecraft:chunk_batch_finished")` has the same window twice.

#30's measurement: closed by the barrier, a join's window held 1 to 6 chunk batches and the
mobs that wander into view, so it never matched. Closed at the first `chunk_batch_finished`,
every side holds the same play packets up to it, since no mob spawns near the spawn to send
its sounds (#183, ADR-0013). This plays a Group 20 times on each of two vanilla Instances
of the test's own (the Group changes game rules and the world spawn) and
compares the windows as Compare takes them: the packet names, their counts and the chunk
positions. It asserts no `match` Verdict: the contents still differ until #106 and #22 (hash
orders, a clock value, light encoding).
"""

import asyncio
import logging
from collections import Counter
from pathlib import Path

import pytest
from support.chunks import OVERWORLD_SECTIONS, decode_chunk
from support.reference import booted

from mscts.codec.packets import Direction, State
from mscts.compare import OBSERVE_CLOSE, OBSERVE_OPEN, is_heartbeat
from mscts.group import Group, GroupContext
from mscts.net import Endpoint
from mscts.run import run_group
from mscts.settle import until_no_player_online
from mscts.transcript import Transcript

pytestmark = pytest.mark.reference

LOG = logging.getLogger(__name__)
_REPEAT = 20
_BATCH_FINISHED = "minecraft:chunk_batch_finished"
_CHUNK = "minecraft:level_chunk_with_light"
_MOVEMENT_CHECK = "gamerule player_movement_check"
"""The game rule whose check makes a join repeat its first `player_position` (by javap,
`ServerGamePacketListenerImpl.shouldCheckPlayerMovement`)."""

type Window = tuple[Counter[str], list[tuple[int, int]]]
"""A window's play packet names with their counts, and the positions of its chunks."""


async def _join_until_the_first_batch(context: GroupContext) -> None:
    """Fixture, then one Bot joins in a window that ends where the first chunk batch arrives."""
    try:
        await context.control.run(f"{_MOVEMENT_CHECK} false")
        # A fresh world spawns the player somewhere random: pin it, so the chunks are the same.
        await context.control.run("gamerule respawn_radius 0")
        await context.control.run("setworldspawn 0 -60 0")
        await context.control.leave()
        await until_no_player_online(context.endpoint)
        bot = await context.bot("alice")
        async with context.observe(until=_BATCH_FINISHED):
            await bot.join()
    finally:
        await context.control.run(f"{_MOVEMENT_CHECK} true")


JOIN_UNTIL = Group(id="probe/join-until", run=_join_until_the_first_batch)
"""A probe Group, not registered: the join #30 compares."""


async def _query_the_rules(context: GroupContext) -> None:
    said = await context.control.run(_MOVEMENT_CHECK)
    assert any(b"true" in packet.payload for packet in said), said


QUERY = Group(id="probe/query-rules", run=_query_the_rules)
"""A probe Group, not registered: it asks Control for the value of the game rule."""


def window_of(transcript: Transcript) -> Window:
    """What Compare takes of alice's play packets: those stamped inside the Group's one window.

    Without the packets Compare never compares in a window (`is_heartbeat`).
    """
    (opened,) = (mark for mark in transcript.marks if mark.label == OBSERVE_OPEN)
    (closed,) = (mark for mark in transcript.marks if mark.label == OBSERVE_CLOSE)
    inside = [
        event
        for event in transcript.events
        if event.bot == "alice"
        and event.packet.direction is Direction.CLIENTBOUND
        and event.packet.state is State.PLAY
        and not is_heartbeat(event.packet)
        and opened.t_ns <= event.t_ns < closed.t_ns
    ]
    chunks = [
        decode_chunk(event.packet.payload, OVERWORLD_SECTIONS)
        for event in inside
        if event.packet.name == _CHUNK
    ]
    return Counter(event.packet.name for event in inside), sorted((c.x, c.z) for c in chunks)


async def play(group: Group, endpoint: Endpoint) -> Transcript:
    """Play `group` against the Instance, then wait for the server to be empty again."""
    try:
        return await run_group(group, endpoint, server="vanilla")
    finally:
        await until_no_player_online(endpoint)


@pytest.mark.asyncio
@pytest.mark.timeout(900)  # two boots, then 20 plays of three joins on each side
async def test_a_join_inside_a_window_closed_by_a_packet_holds_the_same_packets_20_of_20(
    cache_dir: Path, tmp_path: Path
) -> None:
    differing: list[str] = []
    async with (
        booted(cache_dir, tmp_path / "first") as first,
        booted(cache_dir, tmp_path / "second") as second,
    ):
        for number in range(1, _REPEAT + 1):
            transcripts = await asyncio.gather(
                play(JOIN_UNTIL, first.endpoint), play(JOIN_UNTIL, second.endpoint)
            )
            one, other = (window_of(transcript) for transcript in transcripts)
            if (one[0][_BATCH_FINISHED], other[0][_BATCH_FINISHED]) != (1, 1):
                differing.append(f"play {number}: not exactly one chunk batch finished in each")
            if one[0] != other[0]:
                differing.append(f"play {number}: names {one[0] - other[0]} / {other[0] - one[0]}")
            if one[1] != other[1] or not one[1]:
                differing.append(f"play {number}: chunks {one[1]} / {other[1]}")
        # The Group undid its Fixture, on both: Control rejoined and set the rule back.
        for endpoint in (first.endpoint, second.endpoint):
            await play(QUERY, endpoint)

    same = _REPEAT - len({line.split(":")[0] for line in differing})
    LOG.info("the same window in %d of %d plays", same, _REPEAT)
    assert differing == [], f"{same} of {_REPEAT}: {differing}"
