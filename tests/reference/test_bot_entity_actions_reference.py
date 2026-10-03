"""A Bot attacking and respawning against a live vanilla 26.3.

Boots a Reference of its own at easy difficulty for each test, since peaceful discards a zombie
on its first tick, and Control kills the Bot. The zombie is the one
`test_bot_entities_reference` summons: no AI, and an unbreakable helmet against the sun. Each
attack is one Observation window, read by time as Compare reads it. The cleanup kills the
zombie, even when the body fails.
"""

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

import pytest

from mscts.bot import Bot
from mscts.codec.packets import Direction
from mscts.compare import OBSERVE_CLOSE, OBSERVE_OPEN
from mscts.entities import Entity
from mscts.group import GroupContext
from mscts.runner import Instance
from mscts.spec import Difficulty
from mscts.transcript import Transcript
from tests.reference.test_bot_entities_reference import CLEANUP, SUMMON, ZOMBIE_AT

pytestmark = pytest.mark.reference

_TIMEOUT_S = 10.0
ATTACKER = "attacker"
FACING_THE_ZOMBIE = "tp attacker 0.5 -60 0.5 -90 0"
"""Two blocks west of the zombie, facing east, in reach."""

type BootReference = Callable[..., AbstractAsyncContextManager[Instance]]


def damage_in_the_window(transcript: Transcript) -> list[dict[str, object]]:
    """The `damage_event` packets the attacker received inside its one window."""
    [opened] = [mark.t_ns for mark in transcript.marks if mark.label == OBSERVE_OPEN]
    [closed] = [
        mark.t_ns for mark in transcript.marks if mark.label == f"{OBSERVE_CLOSE} {ATTACKER}"
    ]
    return [
        dict(event.packet.fields or {})
        for event in transcript.events
        if event.bot == ATTACKER
        and event.packet.direction is Direction.CLIENTBOUND
        and event.packet.name == "minecraft:damage_event"
        and opened <= event.t_ns < closed
    ]


def attacker_id(transcript: Transcript) -> object:
    """The attacker's entity id, from its play `login`."""
    [login] = [
        event.packet.fields or {}
        for event in transcript.events
        if event.bot == ATTACKER and event.packet.name == "minecraft:login"
    ]
    return login["entity_id"]


async def attack_the_zombie(
    boot_reference: BootReference, transcript: Transcript, *, die_first: bool
) -> Entity:
    """Join, summon the zombie, (die and respawn,) attack it in one window; return it."""
    async with boot_reference(difficulty=Difficulty.EASY) as reference:
        context = GroupContext(reference.endpoint, transcript, timeout_s=_TIMEOUT_S)
        try:
            attacker = await context.bot(ATTACKER)
            await attacker.join()
            await context.control.run(FACING_THE_ZOMBIE)
            try:
                await context.control.run(SUMMON)
                if die_first:
                    await context.control.run(f"kill {ATTACKER}")
                    await attacker.respawn()
                    await context.control.run(FACING_THE_ZOMBIE)
                return await attack_in_a_window(context, attacker)
            finally:
                await context.control.run(CLEANUP)
        finally:
            await context.close()


async def attack_in_a_window(context: GroupContext, attacker: Bot) -> Entity:
    await attacker.sync()  # the zombie's add_entity has arrived
    zombie = attacker.entities.find("zombie", near=ZOMBIE_AT)
    async with context.observe():
        await attacker.attack(zombie)
    return zombie


@pytest.mark.timeout(180)  # its own boot and stop, a join, three commands and the barriers
@pytest.mark.asyncio
async def test_a_bot_attacks_a_zombie_and_the_server_says_it_was_hurt(
    boot_reference: BootReference,
) -> None:
    transcript = Transcript(group_id="reference/bot-attack", server="vanilla")
    zombie = await attack_the_zombie(boot_reference, transcript, die_first=False)

    # ServerPlayer.attack hurts the zombie, and the server tells the players who see it
    # (damage_event), the attacker among them, naming the attacker as the cause.
    [damage] = damage_in_the_window(transcript)
    assert damage["entity_id"] == zombie.id
    assert damage["source_cause_id"] == attacker_id(transcript)
    assert damage["source_direct_id"] == attacker_id(transcript)


@pytest.mark.timeout(180)  # its own boot and stop, a join, a respawn, five commands, barriers
@pytest.mark.asyncio
async def test_a_bot_that_died_respawns_and_its_attack_counts_again(
    boot_reference: BootReference,
) -> None:
    transcript = Transcript(group_id="reference/bot-respawn", server="vanilla")
    zombie = await attack_the_zombie(boot_reference, transcript, die_first=True)

    # The server ignores attacks until the respawned client says it has loaded
    # (hasClientLoaded), so a damage_event shows respawn sent player_loaded.
    [damage] = damage_in_the_window(transcript)
    assert damage["entity_id"] == zombie.id
    assert damage["source_cause_id"] == attacker_id(transcript)
