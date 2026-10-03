"""Entities a Group spawns compare by the order they appear in a window (#21).

The probe Group has Control summon three pigs inside an Observation window, and a watcher
sees them spawn. Vanilla gives every pig a random UUID, so the Self-check matches only
because each entity id and UUID is numbered in the order it first appears in the window.
Two Reference Instances of the test's own play it 20 times each.
"""

from pathlib import Path

import pytest
from support.reference import own_reference
from support.selfcheck import keep_timelines_and_describe

from mscts.compare import Outcome
from mscts.group import Group, GroupContext
from mscts.run import run_results

_REPEAT = 20

PIGS_AT = ("4 -60 4", "6 -60 4", "8 -60 4")
"""Where the probe summons its pigs, in order: in the spawn chunk, on the flat world's grass."""

SUMMON = 'summon minecraft:pig {at} {{NoAI:1b,DeathLootTable:"minecraft:empty",Tags:["probe"]}}'
"""With NBT, `summon` skips the spawn's random rolls (a baby, a variant); and a pig with no
loot leaves nothing behind when the probe kills it."""


async def _pigs(context: GroupContext) -> None:
    """Control summons the pigs inside a window; the watcher sees them spawn."""
    # No animal spawns inside the window on its own: mob spawning is off (ADR-0013).
    watcher = await context.bot("watcher")
    await watcher.join()
    await context.control.run("tick freeze")
    async with context.observe("minecraft:add_entity", "minecraft:set_entity_data"):
        for at in PIGS_AT:
            await context.control.run(SUMMON.format(at=at))
    # Every repetition plays on the same Instances, and a pig still there is sent at the
    # next join. A killed pig dies over 20 ticks, and only while a player is near it.
    await context.control.run("tick unfreeze")
    await context.control.run("kill @e[tag=probe]")
    removed = 0
    while removed < len(PIGS_AT):
        packet = await watcher.expect("minecraft:remove_entities", timeout_s=10)
        assert packet.fields is not None
        entity_ids = packet.fields["entity_ids"]
        assert isinstance(entity_ids, list)
        removed += len(entity_ids)


PIGS = Group(id="probe/pigs", run=_pigs)


@pytest.mark.reference
@pytest.mark.asyncio
@pytest.mark.timeout(900)  # two boots, then 20 plays of two joins, a window and the kills
async def test_a_group_that_summons_pigs_inside_a_window_self_checks_20_of_20(
    cache_dir: Path, tmp_path: Path
) -> None:
    with own_reference(cache_dir) as reference:
        result = await run_results(
            [PIGS], reference, reference, workdir=tmp_path / "selfcheck", repeat=_REPEAT
        )

    verdicts = result.verdicts
    assert len(verdicts) == _REPEAT
    if any(verdict.outcome is not Outcome.MATCH for verdict in verdicts):
        pytest.fail(keep_timelines_and_describe(result, tmp_path / "timelines"), pytrace=False)
    # It compared the pigs' ids and UUIDs, numbered, and their metadata.
    cases = set(verdicts[0].test_cases)
    for case in ("add_entity.entity_id", "add_entity.entity_uuid", "set_entity_data.entity_id"):
        assert case in cases, cases
