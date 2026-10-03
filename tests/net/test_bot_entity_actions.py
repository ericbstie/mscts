"""Bot actions on entities, and respawning: what the vanilla client sends for each.

The rules are `Minecraft.startAttack` and `startUseItem`, `MultiPlayerGameMode.attack` and
`interact`, and `LpVec3.write` (26.3 client, javap; docs/research/2026-10-03-bot-entities.md).
An attack or an interaction is one client tick, like a block action: the held slot if it
changed, then the action, then the movement packets, then `client_tick_end`.
"""

import math
import uuid
from collections.abc import Awaitable, Callable, Mapping

import pytest

from mscts.bot import Bot
from mscts.codec.packets import Packet
from mscts.entities import Entity
from mscts.net import ProtocolError
from mscts.transcript import Transcript
from tests.net.fakes import (
    EMPTY_CHUNK,
    Handler,
    JoinScript,
    Peer,
    answer_each_tick,
    join_server,
    status_server,
    with_bot,
)
from tests.net.test_bot_blocks import PUNCH
from tests.net.test_bot_move import (
    CODEC,
    LOGIN,
    RESPAWN,
    TICK_END,
    TICK_PACKETS,
    Sent,
    joined,
    ticks_sent,
)

NAMES = TICK_PACKETS | {"minecraft:attack", "minecraft:interact", "minecraft:punch"}
ZOMBIE = Entity(id=41, uuid=uuid.UUID(int=41), type="minecraft:zombie", x=1.5, y=-60.0, z=2.5)
NOWHERE = {"scale": 0, "x": 0, "y": 0, "z": 0}


def entity_acts(script: Callable[[Bot], Awaitable[None]]) -> list[Sent]:
    """What `script` sent, tick by tick, after a first tick that reports the join pose."""

    async def after_a_tick(bot: Bot) -> None:
        await bot.tick()
        await script(bot)

    return ticks_sent(joined(after_a_tick), NAMES)[1:]


def interact(location: Mapping[str, int], *, hand: int = 0, sneaking: bool = False) -> Sent:
    fields = {"entity_id": 41, "hand": hand, "location": location, "sneaking": sneaking}
    return [("minecraft:interact", fields), TICK_END]


def test_attack_hits_the_entity_then_swings() -> None:
    # startAttack on an entity: MultiPlayerGameMode.attack sends attack, then the swing
    # sends punch.
    async def script(bot: Bot) -> None:
        await bot.attack(ZOMBIE)

    assert entity_acts(script) == [[("minecraft:attack", {"entity_id": 41}), PUNCH, TICK_END]]


def test_interact_uses_the_main_hand_at_the_entity_position() -> None:
    # MultiPlayerGameMode.interact: where on the entity, relative to its position, as an
    # LpVec3; (0, 0, 0) is written as the single zero byte. The client's own swing for a
    # success sends nothing.
    async def script(bot: Bot) -> None:
        await bot.interact(ZOMBIE)

    assert entity_acts(script) == [interact(NOWHERE)]


def test_interact_sends_where_on_the_entity_the_hand_and_the_sneak_key() -> None:
    # LpVec3.write: the scale is the largest axis rounded up, each quantum
    # Math.round((v / scale * 0.5 + 0.5) * 32766); usingSecondaryAction is the sneak key.
    async def script(bot: Bot) -> None:
        await bot.sneak(sneaking=True)
        await bot.interact(ZOMBIE, at=(0.25, -0.5, 1.5), off_hand=True)

    location = {"scale": 2, "x": 18431, "y": 12287, "z": 28670}
    assert entity_acts(script)[1] == interact(location, hand=1, sneaking=True)


def test_interact_rounds_half_a_quantum_up_as_java_does() -> None:
    # (0.5 * 0.5 + 0.5) * 32766 is 24574.5: Math.round gives 24575, where Python's round
    # would give the even 24574.
    async def script(bot: Bot) -> None:
        await bot.interact(ZOMBIE, at=(0.5, 1.0, 0.0))

    location = {"scale": 1, "x": 24575, "y": 32766, "z": 16383}
    assert entity_acts(script) == [interact(location)]


def test_interact_writes_a_tiny_location_as_zero() -> None:
    # Below 3.051944088384301E-5 on every axis, LpVec3.write sends the zero vector.
    async def script(bot: Bot) -> None:
        await bot.interact(ZOMBIE, at=(3e-5, -3e-5, 0.0))

    assert entity_acts(script) == [interact(NOWHERE)]


@pytest.mark.parametrize("bad", [math.nan, math.inf])
def test_interact_refuses_a_location_that_is_not_finite(bad: float) -> None:
    async def script(bot: Bot) -> None:
        with pytest.raises(ValueError, match="interact needs a finite location"):
            await bot.interact(ZOMBIE, at=(0.0, bad, 0.0))

    assert entity_acts(script) == []


ACTIONS: list[tuple[str, Callable[[Bot], Awaitable[None]]]] = [
    ("attack", lambda bot: bot.attack(ZOMBIE)),
    ("interact", lambda bot: bot.interact(ZOMBIE)),
    ("respawn", lambda bot: bot.respawn()),
]


@pytest.mark.parametrize(("name", "call"), ACTIONS, ids=[name for name, _ in ACTIONS])
def test_entity_actions_refuse_a_bot_that_is_not_in_play(
    name: str, call: Callable[[Bot], Awaitable[None]]
) -> None:
    transcript = Transcript(group_id="test/entity-actions", server="fake")

    async def use(bot: Bot) -> None:
        with pytest.raises(
            ProtocolError, match=f"{name} needs a Bot in play, not one in handshake"
        ):
            await call(bot)

    with_bot(CODEC, transcript, status_server("{}", []), use)
    assert transcript.events == []


PERFORM_RESPAWN = 0
RESPAWNED_AT = {"x": 0.5, "y": -60.0, "z": 0.5, "yaw": 0.0, "pitch": 0.0}


def dying_server(seen: list[Packet]) -> Handler:
    """Join like vanilla; answer a respawn request as `PlayerList.respawn` does, and `sync`.

    The respawn is the `respawn` packet, the teleport to the spawn, then one chunk batch.
    """

    async def then(peer: Peer) -> None:
        requests = 0
        async for packet in peer.packets():
            seen.append(packet)
            if packet.name != "minecraft:client_command":
                continue
            if packet.fields == {"action": PERFORM_RESPAWN}:
                await peer.send("minecraft:respawn", **RESPAWN, data_kept=0)
                await peer.send(
                    "minecraft:player_position",
                    teleport_id=2,
                    velocity_x=0.0,
                    velocity_y=0.0,
                    velocity_z=0.0,
                    flags=0,
                    **RESPAWNED_AT,
                )
                await peer.send("minecraft:chunk_batch_start")
                await peer.send("minecraft:level_chunk_with_light", **EMPTY_CHUNK)
                await peer.send("minecraft:chunk_batch_finished", batch_size=1)
            else:
                requests += 1
                await answer_each_tick(peer, requests)

    def login_frame(peer: Peer) -> bytes:
        return peer.frame("minecraft:login", **LOGIN)

    return join_server(seen, JoinScript(after_batch=login_frame, then=then))


def test_respawn_asks_then_says_it_has_loaded_once_the_first_batch_is_in() -> None:
    # handleRespawn makes the client wait for its level to load again (setClientLoaded
    # false, startWaitingForNewLevel), and the server ignores attacks and interactions
    # until it says so (hasClientLoaded). As at the join, the Bot says so right after it
    # acknowledged the first chunk batch after the respawn.
    seen: list[Packet] = []

    async def use(bot: Bot) -> None:
        await bot.join()
        await bot.respawn()
        await bot.sync()

    with_bot(CODEC, Transcript(group_id="test/respawn", server="fake"), dying_server(seen), use)
    [asked] = [packet for packet in seen if packet.fields == {"action": PERFORM_RESPAWN}]
    after = seen[seen.index(asked) :]
    assert [(packet.name, packet.fields) for packet in after[:4]] == [
        ("minecraft:client_command", {"action": PERFORM_RESPAWN}),
        ("minecraft:accept_teleportation", {"teleport_id": 2, **RESPAWNED_AT}),
        ("minecraft:chunk_batch_received", {"chunks_per_tick": 9.0}),
        ("minecraft:player_loaded", {}),
    ]
