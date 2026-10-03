"""An Instance a failed Group left frozen is unusable for the rest of the Run (#228)."""

import functools
from pathlib import Path

import pytest

from mscts import run as run_module
from mscts.compare import Outcome
from mscts.group import Group, GroupContext, GroupKind
from mscts.run import run
from tests.group.test_control import ControlServer
from tests.run.occupancy import attached

GROUP_TIMEOUT_S = 0.5
"""Each Bot operation's bound here: short, since the frozen side never answers its unfreeze."""


def refusing_to_unfreeze() -> ControlServer:
    """A fake whose Control answers no command from `tick unfreeze` on."""

    def stop_at_unfreeze(command: str) -> None:
        if command == "tick unfreeze":
            server.answers_markers = False

    server = ControlServer(on_command=stop_at_unfreeze)
    return server


async def _fails_frozen(context: GroupContext) -> None:
    await context.freeze()
    msg = "the Group failed while the world was frozen"
    raise RuntimeError(msg)


async def _joins(context: GroupContext) -> None:
    bot = await context.bot("alice")
    await bot.join()


FAILS_FROZEN = Group(id="test/fails-frozen", run=_fails_frozen, kind=GroupKind.TICK_EXACT)
JOINS = Group(id="test/joins", run=_joins)


@pytest.fixture(autouse=True)
def quick(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bound each Bot operation briefly, and skip the wait for no player online."""
    monkeypatch.setattr(
        run_module,
        "run_group",
        functools.partial(run_module.run_group, timeout_s=GROUP_TIMEOUT_S),
    )

    async def settled(*_: object) -> None:
        return None

    monkeypatch.setattr(run_module, "_unsettled", settled)


@pytest.mark.asyncio
@pytest.mark.parametrize("frozen", ["Reference", "Candidate"])
async def test_a_group_after_one_that_left_a_side_frozen_is_an_error(
    frozen: str, tmp_path: Path
) -> None:
    stuck, working = refusing_to_unfreeze(), ControlServer()
    sides = (stuck, working) if frozen == "Reference" else (working, stuck)
    async with (
        attached("vanilla", sides[0]) as reference,
        attached("vanilla", sides[1]) as candidate,
    ):
        verdicts = await run(
            [FAILS_FROZEN, JOINS], reference, candidate, workdir=tmp_path, repeat=2
        )

    later = [verdict for verdict in verdicts if verdict.group_id == JOINS.id]
    assert [verdict.outcome for verdict in later] == [Outcome.ERROR, Outcome.ERROR], later
    assert all(
        verdict.detail
        == f"the {frozen} is unusable: test/fails-frozen failed and left its world frozen"
        for verdict in later
    ), later


@pytest.mark.asyncio
async def test_a_side_that_unfroze_stays_usable(tmp_path: Path) -> None:
    async with (
        attached("vanilla", ControlServer()) as reference,
        attached("vanilla", ControlServer()) as candidate,
    ):
        verdicts = await run([FAILS_FROZEN, JOINS], reference, candidate, workdir=tmp_path)

    assert [verdict.outcome for verdict in verdicts] == [Outcome.ERROR, Outcome.MATCH], verdicts
