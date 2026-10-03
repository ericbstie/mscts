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
"""

from pathlib import Path

import pytest
from support.reference import attached, own_reference
from support.selfcheck import keep_timelines_and_describe, needs_instances_of_their_own

from mscts.compare import Outcome
from mscts.group import Group, resolve
from mscts.run import RunResult, run_results
from mscts.runner import Instance

pytestmark = [
    pytest.mark.selfcheck,
    pytest.mark.asyncio(loop_scope="session"),
    # The Groups bound each Bot operation themselves; this is only for a Run that hangs.
    pytest.mark.timeout(900),
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
    result = await _play(groups, (reference, second_reference), cache_dir, tmp_path, repeat)
    verdicts = result.verdicts
    assert [verdict.group_id for verdict in verdicts] == [group.id for group in groups] * repeat
    if any(verdict.outcome is not Outcome.MATCH for verdict in verdicts):
        message = keep_timelines_and_describe(result, tmp_path / "timelines")
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
    with own_reference(cache_dir) as server:
        return await run_results(
            groups, server, server, workdir=workdir, repeat=repeat, keep_transcripts=True
        )
