"""A joined Bot in play on a live vanilla 26.3, with the settings the vanilla client sends.

Boots a Reference of its own at view distance 4. At the default 2 the test could not
tell whether the Bot sent its client information: vanilla assumes view distance 2 until
it arrives (docs/research/2026-09-26-join.md, "How the server combines view distances").
"""

import math
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

import pytest
from support.chunks import OVERWORLD_SECTIONS, decode_chunk, play_packets

from mscts.bot import Bot
from mscts.runner import Instance
from mscts.target import TARGET
from mscts.transcript import Transcript

pytestmark = pytest.mark.reference

_VIEW_DISTANCE = 4
_STAY_S = 5.0
_TIMEOUT_S = 10.0
_CHUNK_SHIFT = 4  # 16 blocks a chunk


def tracked_chunks(center: tuple[int, int], view_distance: int) -> list[tuple[int, int]]:
    """The chunks vanilla sends a player standing in chunk `center`, sorted.

    `ChunkTrackingView.Positioned` (26.3 javap): the square within v + 1 of the center,
    less the chunks `isWithinDistance(..., includeOuter=true)` leaves out, those where
    max(0, |dx| - 2)**2 + max(0, |dz| - 2)**2 is at least v**2.
    """
    reach = view_distance + 1
    center_x, center_z = center
    return sorted(
        (center_x + dx, center_z + dz)
        for dx in range(-reach, reach + 1)
        for dz in range(-reach, reach + 1)
        if max(0, abs(dx) - 2) ** 2 + max(0, abs(dz) - 2) ** 2 < view_distance**2
    )


def test_tracked_chunks_are_the_square_less_its_corners() -> None:
    assert len(tracked_chunks((0, 0), 2)) == 49  # 7 x 7: no chunk left out
    assert len(tracked_chunks((0, 0), 4)) == 11 * 11 - 4
    assert (5, 4) in tracked_chunks((0, 0), 4)
    assert (5, 5) not in tracked_chunks((0, 0), 4)


# Its own boot, the stay and a stop: worst case ready_timeout + join + stay + stop_timeout,
# above the global 120 s pytest-timeout.
@pytest.mark.timeout(180)
@pytest.mark.asyncio
async def test_a_joined_bot_stays_in_play_and_gets_the_chunks_of_its_view_distance(
    boot_reference: Callable[..., AbstractAsyncContextManager[Instance]],
) -> None:
    transcript = Transcript(group_id="reference/play", server="vanilla")
    async with boot_reference(view_distance=_VIEW_DISTANCE) as reference:
        bot = await Bot.connect(
            reference.endpoint, TARGET, name="in_play", transcript=transcript, timeout_s=_TIMEOUT_S
        )
        try:
            await bot.join()
            try:
                kicked = await bot.expect("minecraft:disconnect", timeout_s=_STAY_S)
            except TimeoutError:
                kicked = None
        finally:
            await bot.close()
    assert kicked is None, f"vanilla disconnected the Bot in play: {kicked}"
    # The Bot asks for 12, so the server's 4 is the smaller: every chunk within 4 of the
    # player's, and nothing sent twice.
    position = play_packets(transcript, "minecraft:player_position")[0].fields or {}
    x, z = position.get("x"), position.get("z")
    assert isinstance(x, float)
    assert isinstance(z, float)
    center = (math.floor(x) >> _CHUNK_SHIFT, math.floor(z) >> _CHUNK_SHIFT)
    chunks = [
        decode_chunk(packet.payload, OVERWORLD_SECTIONS)
        for packet in play_packets(transcript, "minecraft:level_chunk_with_light")
    ]
    assert sorted((chunk.x, chunk.z) for chunk in chunks) == tracked_chunks(center, _VIEW_DISTANCE)
