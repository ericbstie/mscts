"""A Bot joining a Pumpkin Instance lands in the Reference's flat world, at the spec's difficulty.

The world save PumpkinAdapter.prepare writes (ADR-0007) is what makes Pumpkin's world
flat and sets its difficulty; this boots the installed Pumpkin on it and joins.
support.chunks holds what the Reference sends (pinned in the reference tier).

Not asserted here, because they are Candidate differences no Adapter can remove (the
Comparison reports them): Pumpkin's play `login` says `is_flat` false and `sea_level` 63,
where the Reference's says true and -63 (docs/research/2026-09-26-pumpkin.md). The
spawn x and z differ too: vanilla adds a random spawn radius.
"""

import dataclasses
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from support.chunks import (
    FLAT_SPAWN_Y,
    OVERWORLD_SECTIONS,
    decode_chunk,
    play_packets,
    unlike_the_reference_flat_world,
)
from support.leak_guard import kill_survivors

from mscts import install
from mscts.adapters.base import Installation
from mscts.adapters.pumpkin import PumpkinAdapter
from mscts.bot import Bot, status_probe
from mscts.codec.packets import Packet
from mscts.runner import free_endpoint, running
from mscts.spec import Difficulty, ServerSpec
from mscts.target import TARGET
from mscts.transcript import Transcript

pytestmark = [pytest.mark.candidate, pytest.mark.asyncio]

_READY_TIMEOUT_S = 60
_STOP_TIMEOUT_S = 30
_TIMEOUT_S = 10.0
_GUARD = "MSCTS_LEAK_GUARD"
# Change Difficulty's first byte (wiki Packets, revision 3790659).
_DIFFICULTY_IDS = {
    Difficulty.PEACEFUL: 0,
    Difficulty.EASY: 1,
    Difficulty.NORMAL: 2,
    Difficulty.HARD: 3,
}


@pytest.fixture
def leak_token() -> Iterator[str]:
    token = uuid.uuid4().hex
    yield token
    leaked = kill_survivors(f"{_GUARD}={token}", within=3.0)
    assert not leaked, f"Pumpkin processes outlived the test: {leaked}"


@pytest.fixture
def installation(cache_dir: Path) -> Installation:
    return install.require(PumpkinAdapter(), TARGET, cache_dir)


async def _join(
    installation: Installation, spec: ServerSpec, workdir: Path, token: str
) -> Transcript:
    """Boot Pumpkin prepared for `spec`, join a Bot until its first position, stop Pumpkin."""
    plan = PumpkinAdapter().prepare(installation, spec, workdir)
    plan = dataclasses.replace(plan, env={**plan.env, _GUARD: token})
    transcript = Transcript(scenario_id="candidate/flat-world", server="pumpkin")
    async with running(
        plan,
        ready=status_probe(TARGET),
        ready_timeout=_READY_TIMEOUT_S,
        stop_timeout=_STOP_TIMEOUT_S,
    ):
        bot = await Bot.connect(
            plan.endpoint, TARGET, name="flat_world", transcript=transcript, timeout_s=_TIMEOUT_S
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
    installation: Installation, tmp_path: Path, leak_token: str
) -> None:
    endpoint = free_endpoint()
    spec = ServerSpec(host=endpoint.host, port=endpoint.port)  # the default: flat, peaceful
    transcript = await _join(installation, spec, tmp_path / "pumpkin", leak_token)
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
    installation: Installation, tmp_path: Path, leak_token: str, difficulty: Difficulty
) -> None:
    endpoint = free_endpoint()
    spec = ServerSpec(host=endpoint.host, port=endpoint.port, difficulty=difficulty)
    transcript = await _join(installation, spec, tmp_path / "pumpkin", leak_token)
    change = _first(transcript, "minecraft:change_difficulty")
    assert change.payload == bytes([_DIFFICULTY_IDS[difficulty], 0])
