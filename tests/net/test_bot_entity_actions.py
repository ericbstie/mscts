"""Bot actions on entities: what the vanilla client sends for each.

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
from mscts.entities import Entity
from mscts.net import ProtocolError
from mscts.transcript import Transcript
from tests.net.fakes import status_server, with_bot
from tests.net.test_bot_blocks import PUNCH
from tests.net.test_bot_move import (
    CODEC,
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
