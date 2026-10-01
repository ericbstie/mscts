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
"""

from pathlib import Path

import pytest
from support.reference import attached

from mscts.compare import Outcome
from mscts.group import resolve
from mscts.run import run
from mscts.runner import Instance

pytestmark = [
    pytest.mark.selfcheck,
    pytest.mark.asyncio(loop_scope="session"),
    # The Groups bound each Bot operation themselves; this is only for a Run that hangs.
    pytest.mark.timeout(900),
]


async def test_selfcheck(
    group_id: str, reference: Instance, second_reference: Instance, repeat: int, tmp_path: Path
) -> None:
    groups = resolve([group_id])
    verdicts = await run(
        groups,
        attached(reference),
        attached(second_reference),
        workdir=tmp_path,
        repeat=repeat,
    )
    assert [verdict.group_id for verdict in verdicts] == [group.id for group in groups] * repeat
    not_matching = [verdict for verdict in verdicts if verdict.outcome is not Outcome.MATCH]
    assert not_matching == []
