"""The spawn Groups: what Control sets, which player joins, and what each play samples.

Every test plays a Group against a fake server that puts every player at a pose of its own, and
reads what the Bots sent and the samples the plays recorded. Where a real server puts a new
player is never asserted: that is what the statistical tier compares.
"""

import math
import re
from collections.abc import Awaitable, Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass, field
from typing import override

import pytest

from mscts.codec.packets import State
from mscts.group import DEFAULT_RUNS, GROUPS, GroupContext, GroupKind
from mscts.groups import spawn
from mscts.net import ProtocolError
from mscts.spec import ServerSpec
from mscts.stats import Numbers, SampleLog, Series
from mscts.transcript import Transcript
from tests.group.test_blocks import CHAT_COMMAND, MARKER, BlocksServer
from tests.group.test_control import CODEC, PLAY_TIMEOUT_S, tree
from tests.net.fakes import SPAWN, JoinScript, Peer, join_server, serve

GROUP_ID = "spawn/join-position"
EXACT_ID = "spawn/join-position-exact"
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


def _without_run(name: str) -> str:
    """`name` of a spawn player, `<prefix><run><play>`, as `<prefix><play>`."""
    return re.sub(r"^(spawn(?:pos|exact))[A-Za-z0-9]{4}(\d+)$", r"\1\2", name)


@dataclass
class SpawnServer(BlocksServer):
    """A fake server that puts every player at `pose` and answers Control's commands.

    It lets in `places` connections, if given, and refuses the others at the login.
    """

    pose: Mapping[str, float] = field(default_factory=lambda: POSE)
    places: int | None = None
    _connections: int = field(default=0, init=False)

    @override
    async def __call__(self, peer: Peer) -> None:
        """Serve one connection: a Handler."""
        # The answers are `BlocksServer`'s; only the join teleport and the commands differ.
        self._connections += 1
        refused = self.places is not None and self._connections > self.places
        script = JoinScript(
            commands=COMMANDS,
            spawn=lambda _: self.pose,
            then=self._play,
            disconnect_in=State.LOGIN if refused else None,
        )
        with suppress(ConnectionError):
            await join_server(self.seen, script)(peer)

    def told(self) -> list[str]:
        """What the Bots did, in order: `join <name>`, and every command but a marker.

        A name reads `<prefix><play>`: the Run's random characters are left out.
        """
        told = []
        for packet in self.seen:
            fields = packet.fields or {}
            if packet.name == "minecraft:hello":
                told.append("join " + _without_run(str(fields["name"])))
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


@pytest.mark.parametrize(
    ("group_id", "run"),
    [(GROUP_ID, spawn.join_position), (EXACT_ID, spawn.join_position_exact)],
)
def test_it_is_statistical_masks_nothing_and_has_no_prerequisites_or_spec(
    group_id: str, run: Callable[[GroupContext], Awaitable[None]]
) -> None:
    group = GROUPS[group_id]
    default = ServerSpec(host="127.0.0.1", port=25566)

    assert group.run is run
    assert group.kind is GroupKind.STATISTICAL
    assert group.runs == DEFAULT_RUNS
    assert (group.masks, group.requires) == ((), ())
    assert group.spec(default) == default


@pytest.mark.asyncio
@pytest.mark.parametrize("group_id", [GROUP_ID, EXACT_ID])
async def test_a_play_records_the_offset_height_and_distance_from_the_spawn_block(
    group_id: str,
) -> None:
    samples, _ = await play(group_id)

    assert samples == SAMPLES


@pytest.mark.asyncio
@pytest.mark.parametrize(("group_id", "prefix"), [(GROUP_ID, "spawnpos"), (EXACT_ID, "spawnexact")])
async def test_each_play_joins_a_new_player_and_records_its_own_samples(
    group_id: str, prefix: str
) -> None:
    samples, server = await play(group_id, plays=3)

    joined = [told for told in server.told() if told.startswith("join spawn")]
    assert joined == [f"join {prefix}{play}" for play in range(3)]
    assert samples["spawn.x"] == Numbers((3.0, 3.0, 3.0), (1, 1, 1))


@pytest.mark.asyncio
async def test_control_pins_the_world_spawn_before_the_player_joins_and_nothing_else() -> None:
    _, server = await play(GROUP_ID)

    assert server.told() == ["join control", SET_SPAWN, "join spawnpos0"]


@pytest.mark.asyncio
async def test_the_exact_group_sets_the_radius_to_0_and_puts_the_rules_back_after_the_join() -> (
    None
):
    _, server = await play(EXACT_ID)

    assert server.told() == [
        "join control",
        SET_SPAWN,
        "gamerule player_movement_check false",
        "gamerule respawn_radius 0",
        "join spawnexact0",
        "gamerule respawn_radius 10",
        "gamerule player_movement_check true",
    ]


@pytest.mark.asyncio
async def test_the_exact_group_puts_the_rules_back_when_the_player_cannot_join() -> None:
    server = SpawnServer(places=1)  # Control only

    with pytest.raises(ProtocolError, match=r"disconnected spawnexact[A-Za-z0-9]{4}0"):
        await play(EXACT_ID, server=server)

    assert server.told()[-2:] == [
        "gamerule respawn_radius 10",
        "gamerule player_movement_check true",
    ]
