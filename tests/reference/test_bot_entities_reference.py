"""A Bot's entities against a live vanilla 26.3: a summoned zombie, found by type and place.

Boots a Reference of its own at easy difficulty, since peaceful discards a zombie on its first
tick (Mob.checkDespawn). The summon is one Observation window, read by time as Compare reads
it. The zombie has no AI, so it stays where it was put, and an unbreakable helmet, so the sun
does not set it on fire (Mob.burnUndead). The cleanup kills it, even when the body fails.
"""

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

import pytest

from mscts.codec.packets import Direction
from mscts.codec.registry_names import registry_names
from mscts.compare import OBSERVE_CLOSE, OBSERVE_OPEN
from mscts.group import GroupContext
from mscts.runner import Instance
from mscts.spec import Difficulty
from mscts.target import TARGET
from mscts.transcript import Transcript

pytestmark = pytest.mark.reference

_TIMEOUT_S = 10.0
WATCHER = "watcher"
TAG = "mscts_entities"
"""The tag on what this test summons, so the cleanup kills only that."""

ZOMBIE_AT = (2.5, -60.0, 0.5)
"""On the flat world's grass, two blocks east of the watcher."""
SUMMON = (
    "summon minecraft:zombie 2.5 -60 0.5 {NoAI:1b,PersistenceRequired:1b,"
    f'Tags:["{TAG}"],equipment:{{head:{{id:"minecraft:leather_helmet",count:1,'
    'components:{"minecraft:unbreakable":{}}}}}'
)
CLEANUP = f"kill @e[tag={TAG}]"


def zombies_added(transcript: Transcript) -> list[dict[str, object]]:
    """The zombie `add_entity` packets the watcher received inside its one window."""
    [opened] = [mark.t_ns for mark in transcript.marks if mark.label == OBSERVE_OPEN]
    [closed] = [
        mark.t_ns for mark in transcript.marks if mark.label == f"{OBSERVE_CLOSE} {WATCHER}"
    ]
    zombie = registry_names(TARGET.minecraft_version, "minecraft:entity_type").index(
        "minecraft:zombie"
    )
    return [
        dict(event.packet.fields or {})
        for event in transcript.events
        if event.bot == WATCHER
        and event.packet.direction is Direction.CLIENTBOUND
        and event.packet.name == "minecraft:add_entity"
        and (event.packet.fields or {}).get("type") == zombie
        and opened <= event.t_ns < closed
    ]


@pytest.mark.timeout(180)  # its own boot and stop, a join, three commands and the barriers
@pytest.mark.asyncio
async def test_a_bot_finds_a_zombie_summoned_near_it(
    boot_reference: Callable[..., AbstractAsyncContextManager[Instance]],
) -> None:
    transcript = Transcript(group_id="reference/bot-entities", server="vanilla")
    async with boot_reference(difficulty=Difficulty.EASY) as reference:
        context = GroupContext(reference.endpoint, transcript, timeout_s=_TIMEOUT_S)
        try:
            watcher = await context.bot(WATCHER)
            await watcher.join()
            await context.control.run("tp watcher 0.5 -60 0.5 0 0")
            try:
                async with context.observe():
                    await context.control.run(SUMMON)
                found = watcher.entities.find("zombie", near=ZOMBIE_AT)
            finally:
                await context.control.run(CLEANUP)
        finally:
            await context.close()

    [added] = zombies_added(transcript)
    assert found.id == added["entity_id"]
    assert found.type == "minecraft:zombie"
    assert (found.x, found.y, found.z) == ZOMBIE_AT
