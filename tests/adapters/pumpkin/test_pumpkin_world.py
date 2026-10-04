"""A Bot joining a Pumpkin Instance lands in the Reference's flat world, at the spec's difficulty.

The world save PumpkinAdapter.prepare writes (ADR-0007) is what makes Pumpkin's world
flat and sets its difficulty; this boots the installed Pumpkin on it and joins.
support.chunks holds what the Reference sends (pinned in the reference tier).

Not asserted here, because they are Candidate differences no Adapter can remove (the
Comparison reports them): Pumpkin's play `login` says `is_flat` false and `sea_level` 63,
where the Reference's says true and -63 (docs/research/2026-09-26-pumpkin.md). The
spawn x and z differ too: vanilla adds a random spawn radius.
"""

from pathlib import Path

import pytest
from support.chunks import (
    FLAT_SPAWN_Y,
    OVERWORLD_SECTIONS,
    decode_chunk,
    play_packets,
    unlike_the_reference_flat_world,
)
from support.reference import booted

from mscts.adapters.pumpkin import PumpkinAdapter
from mscts.bot import Bot
from mscts.codec.packets import Packet
from mscts.spec import Difficulty
from mscts.target import TARGET
from mscts.transcript import Transcript

pytestmark = [pytest.mark.candidate, pytest.mark.asyncio]

_TIMEOUT_S = 10.0
# Change Difficulty's first byte (wiki Packets, revision 3790659).
_DIFFICULTY_IDS = {
    Difficulty.PEACEFUL: 0,
    Difficulty.EASY: 1,
    Difficulty.NORMAL: 2,
    Difficulty.HARD: 3,
}


async def _join(
    cache_dir: Path, workdir: Path, difficulty: Difficulty = Difficulty.PEACEFUL
) -> Transcript:
    """Boot Pumpkin at `difficulty`, join a Bot until its first position, stop Pumpkin."""
    transcript = Transcript(group_id="candidate/flat-world", server="pumpkin")
    async with booted(
        cache_dir, workdir, adapter=PumpkinAdapter(), difficulty=difficulty
    ) as instance:
        bot = await Bot.connect(
            instance.endpoint,
            TARGET,
            name="flat_world",
            transcript=transcript,
            timeout_s=_TIMEOUT_S,
        )
        try:
            await bot.join()
            # Pumpkin places the player after the first chunk batch; vanilla before it.
            if not play_packets(transcript, "minecraft:player_position"):
                await bot.expect("minecraft:player_position", timeout_s=_TIMEOUT_S)
        finally:
            await bot.close()
    return transcript


def _first(transcript: Transcript, name: str) -> Packet:
    return play_packets(transcript, name)[0]


async def test_a_bot_joins_the_reference_flat_world_at_y_minus_60(
    cache_dir: Path, tmp_path: Path
) -> None:
    transcript = await _join(cache_dir, tmp_path / "pumpkin")
    chunks = [
        decode_chunk(packet.payload, OVERWORLD_SECTIONS)
        for packet in play_packets(transcript, "minecraft:level_chunk_with_light")
    ]
    assert chunks
    assert [d for chunk in chunks for d in unlike_the_reference_flat_world(chunk)] == []
    assert (_first(transcript, "minecraft:player_position").fields or {}).get("y") == FLAT_SPAWN_Y
    login = _first(transcript, "minecraft:login").fields or {}
    assert login.get("dimension_name") == "minecraft:overworld"


@pytest.mark.parametrize("difficulty", list(Difficulty), ids=[str(d) for d in Difficulty])
async def test_the_join_sends_the_spec_difficulty_unlocked(
    cache_dir: Path, tmp_path: Path, difficulty: Difficulty
) -> None:
    transcript = await _join(cache_dir, tmp_path / "pumpkin", difficulty=difficulty)
    change = _first(transcript, "minecraft:change_difficulty")
    assert change.payload == bytes([_DIFFICULTY_IDS[difficulty], 0])
