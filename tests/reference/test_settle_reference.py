"""A Group plays only after the previous Group's Bots have left the server (#97).

`Bot.close()` closes the socket, and vanilla removes the player on its next tick, so a
Group that plays right after one that joined Bots could still see them online. The
first test pins the wait against the shared Reference: a joined Bot shows in the status
at once, and once it is closed `until_no_player_online` returns with the status empty. The
second is the ordering this was found by: the probe Group (`support.probe.SETBLOCK_OBSERVED`)
joins two Bots, `watcher` and Control's `control`, and `status/basic` plays after it and
must not see them in `players.online`.

The second test's Instances are the Run's own, not the shared Reference: the probe freezes
ticking (`tick freeze`), which would leave every later test of the session on a frozen
server.
"""

from pathlib import Path

import pytest
from support.probe import SETBLOCK_OBSERVED
from support.reference import own_reference
from support.selfcheck import describe_unmatched

from mscts.bot import Bot
from mscts.compare import Outcome
from mscts.group import resolve
from mscts.run import run
from mscts.runner import Instance
from mscts.settle import until_no_player_online
from mscts.target import TARGET
from mscts.transcript import Transcript

_REPEAT = 20
_TIMEOUT_S = 10.0


async def _online(reference: Instance) -> object:
    """What the Reference's status says is `players.online`."""
    bot = await Bot.connect(
        reference.endpoint,
        TARGET,
        name="status",
        transcript=Transcript(group_id="settle", server="vanilla"),
        timeout_s=_TIMEOUT_S,
    )
    try:
        players = (await bot.status())["players"]
    finally:
        await bot.close()
    assert isinstance(players, dict)
    return {str(key): value for key, value in players.items()}["online"]


@pytest.mark.reference
@pytest.mark.asyncio(loop_scope="session")
async def test_the_status_empties_soon_after_a_joined_bot_is_closed(reference: Instance) -> None:
    bot = await Bot.connect(
        reference.endpoint,
        TARGET,
        name="settler",  # a name no other test joins with
        transcript=Transcript(group_id="settle", server="vanilla"),
        timeout_s=_TIMEOUT_S,
    )
    try:
        await bot.join()
        online_while_joined = await _online(reference)
    finally:
        await bot.close()

    await until_no_player_online(reference.endpoint)

    assert online_while_joined == 1
    assert await _online(reference) == 0


@pytest.mark.reference
@pytest.mark.asyncio
@pytest.mark.timeout(600)  # two boots, then 20 plays of a joining Group and a status on each side
async def test_status_basic_right_after_a_group_that_joined_bots_matches_20_of_20(
    cache_dir: Path, tmp_path: Path
) -> None:
    groups = (SETBLOCK_OBSERVED, *resolve(["status/basic"]))
    with own_reference(cache_dir) as reference:
        verdicts = await run(groups, reference, reference, workdir=tmp_path / "run", repeat=_REPEAT)

    assert [verdict.group_id for verdict in verdicts] == [group.id for group in groups] * _REPEAT
    not_matching = [verdict for verdict in verdicts if verdict.outcome is not Outcome.MATCH]
    if not_matching:
        pytest.fail(describe_unmatched(not_matching), pytrace=False)
