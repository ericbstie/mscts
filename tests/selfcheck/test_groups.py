"""G2: every registered Group's Self-check is `match`, in every repetition.

One test per Group in `GROUPS`, found at collection (`support.selfcheck`), so a Group is
covered as soon as it is registered, with no new test file. The Self-check plays the Group,
and the prerequisites it needs first, against two distinct Reference Instances (the
`conftest.py` boots them once for the whole tier), and every Verdict must be `match`.

It is two Instances, never one against itself, on purpose: a Self-check is how a Group proves
it needs no further Mask, i.e. that whatever two independently booted servers may legitimately
differ in (per-boot identifiers and state, anything drawn at random at startup) is already
masked. One Instance compared with itself shares all of that, so a missing Mask would pass
here and only show up as a false `mismatch` against every Candidate.

A Group whose `spec` changes the ServerSpec cannot play on that pair, which was booted at the
default one. Its Self-check launches two Instances of its own for that ServerSpec instead,
which costs two boots.

A statistical Group rejects by chance 1 time in 100, so a Self-check that only its
`distribution` tests rejected is played once more with fresh plays, and fails only if that
is not `match` either (#388, `support.selfcheck.play_and_replay`).
"""

import functools
from pathlib import Path

import pytest
from support.reference import attached, own_reference
from support.selfcheck import (
    describe_failure,
    needs_instances_of_their_own,
    play_and_replay,
)

from mscts.group import Group, GroupKind, resolve
from mscts.run import RunResult, run_results
from mscts.runner import Instance

pytestmark = [
    pytest.mark.selfcheck,
    pytest.mark.asyncio(loop_scope="session"),
    # The time limit is a mark on each case, from `support.selfcheck.time_limit_s`: 90 s a
    # play (at least 900 s) and more for the Groups in `SLOW_PLAY_LIMIT_S` (#182, #423).
    # Bot operations have their own bounds.
]


async def test_selfcheck(  # noqa: PLR0913, PLR0917 - a test is its fixtures
    group_id: str,
    reference: Instance,
    second_reference: Instance,
    cache_dir: Path,
    repeat: int,
    tmp_path: Path,
) -> None:
    groups = resolve([group_id])
    pair = (reference, second_reference)
    play = functools.partial(_play, groups, pair, cache_dir, repeat=repeat)
    # The replay gets Instances of its own: the shared pair keeps each Bot's saved position
    # (`spawn/*`), so a replay on it would sample the first play's again.
    replay = functools.partial(_play_on_own, groups, cache_dir, repeat=repeat)
    plays = await play_and_replay(groups, play, replay, tmp_path)
    # A statistical Group is one comparison whatever the repeat (#24): `run_results`.
    assert [len(played.verdicts) for played in plays[0].results] == [
        1 if group.kind is GroupKind.STATISTICAL else repeat for group in groups
    ]
    # A statistical Group rejected by chance is played once more (#388).
    message = describe_failure(plays, tmp_path / "timelines")
    if message:
        pytest.fail(message, pytrace=False)


async def _play(
    groups: tuple[Group, ...],
    pair: tuple[Instance, Instance],
    cache_dir: Path,
    workdir: Path,
    repeat: int,
) -> RunResult:
    """Play `groups` on the shared `pair`, or on Instances of the Run's own if they need to."""
    first, second = (attached(instance) for instance in pair)
    if not needs_instances_of_their_own(groups, first.spec):
        return await run_results(
            groups, first, second, workdir=workdir, repeat=repeat, keep_transcripts=True
        )
    return await _play_on_own(groups, cache_dir, workdir, repeat)


async def _play_on_own(
    groups: tuple[Group, ...], cache_dir: Path, workdir: Path, repeat: int
) -> RunResult:
    """Play `groups` on two Instances launched for this play alone, and stopped after it."""
    with own_reference(cache_dir) as server:
        return await run_results(
            groups, server, server, workdir=workdir, repeat=repeat, keep_transcripts=True
        )
