"""The spawn Groups: what Control sets, which player joins, and what each play samples.

Every test plays a Group against a fake server that puts every player at a pose of its own, and
reads what the Bots sent and the samples the plays recorded. Where a real server puts a new
player is never asserted: that is what the statistical tier compares.
"""

import math
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass, field
from typing import override

import pytest

from mscts.group import DEFAULT_RUNS, GROUPS, GroupContext, GroupKind
from mscts.groups import spawn
from mscts.spec import ServerSpec
from mscts.stats import Numbers, SampleLog, Series
from mscts.transcript import Transcript
from tests.group.test_blocks import CHAT_COMMAND, MARKER, BlocksServer
from tests.group.test_control import CODEC, PLAY_TIMEOUT_S, tree
from tests.net.fakes import SPAWN, JoinScript, Peer, join_server, serve

GROUP_ID = "spawn/join-position"
COMMANDS = tree("setworldspawn", "gamerule", "tellraw")
POSE = {**SPAWN, "x": 3.5, "y": -59.0, "z": -4.5}
"""Where the fake puts every new player: 3 east and 5 north of the middle of the spawn block."""
SAMPLES = {
    "spawn.x": Numbers((3.0,), (1,)),
    "spawn.y": Numbers((-59.0,), (1,)),
    "spawn.z": Numbers((-5.0,), (1,)),
    "spawn.distance": Numbers((math.hypot(3.0, 5.0),), (1,)),
}
"""What one play records when the player is put at `POSE`."""
SET_SPAWN = "setworldspawn 0 -60 0"


@dataclass
class SpawnServer(BlocksServer):
    """A fake server that puts every player at `pose` and answers Control's commands."""

    pose: Mapping[str, float] = field(default_factory=lambda: POSE)

    @override
    async def __call__(self, peer: Peer) -> None:
        """Serve one connection: a Handler."""
        # The answers are `BlocksServer`'s; only the join teleport and the commands differ.
        with suppress(ConnectionError):
            await join_server(
                self.seen,
                JoinScript(commands=COMMANDS, spawn=lambda _: self.pose, then=self._play),
            )(peer)

    def told(self) -> list[str]:
        """What the Bots did, in order: `join <name>`, and every command but a marker."""
        told = []
        for packet in self.seen:
            fields = packet.fields or {}
            if packet.name == "minecraft:hello":
                told.append(f"join {fields['name']}")
            elif packet.name == CHAT_COMMAND and not str(fields["command"]).startswith(MARKER):
                told.append(str(fields["command"]))
        return told


async def play(
    group_id: str, plays: int = 1, server: SpawnServer | None = None
) -> tuple[Mapping[str, Series], SpawnServer]:
    """Play `group_id` `plays` times against one fake server; return the samples and the server."""
    server = server or SpawnServer()
    samples = SampleLog()
    async with serve(CODEC, server, timeout_s=PLAY_TIMEOUT_S) as endpoint:
        for _ in range(plays):
            samples.new_play()
            transcript = Transcript(group_id=group_id, server="fake")
            context = GroupContext(endpoint, transcript, timeout_s=2.0, samples=samples)
            try:
                await GROUPS[group_id].run(context)
            finally:
                await context.close()
    return samples.series(), server


def test_it_is_statistical_masks_nothing_and_has_no_prerequisites_or_spec() -> None:
    group = GROUPS[GROUP_ID]
    default = ServerSpec(host="127.0.0.1", port=25566)

    assert group.run is spawn.join_position
    assert group.kind is GroupKind.STATISTICAL
    assert group.runs == DEFAULT_RUNS
    assert (group.masks, group.requires) == ((), ())
    assert group.spec(default) == default


@pytest.mark.asyncio
async def test_a_play_records_the_offset_height_and_distance_from_the_spawn_block() -> None:
    samples, _ = await play(GROUP_ID)

    assert samples == SAMPLES


@pytest.mark.asyncio
async def test_each_play_joins_a_new_player_and_records_its_own_samples() -> None:
    samples, server = await play(GROUP_ID, plays=3)

    joined = [told for told in server.told() if told.startswith("join spawn")]
    assert joined == ["join spawnpos0", "join spawnpos1", "join spawnpos2"]
    assert samples["spawn.x"] == Numbers((3.0, 3.0, 3.0), (1, 1, 1))


@pytest.mark.asyncio
async def test_control_pins_the_world_spawn_before_the_player_joins_and_nothing_else() -> None:
    _, server = await play(GROUP_ID)

    assert server.told() == ["join control", SET_SPAWN, "join spawnpos0"]
