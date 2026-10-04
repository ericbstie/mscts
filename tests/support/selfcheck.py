"""What the Self-check tier (`tests/selfcheck/`) is made of: a test per registered Group.

`tests/selfcheck/conftest.py` imports `pytest_generate_tests` from here, so a test that takes a
`group_id` runs once for each Group in `GROUPS`, with the Group's id as its test id. Nothing
else needs to be written when a Group is registered (#84).
"""

import dataclasses
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

import mscts.groups  # noqa: F401 - registers the shipped Groups
from mscts.compare import Outcome, Verdict
from mscts.group import GROUPS, Group
from mscts.run import RunResult
from mscts.spec import ServerSpec
from mscts.timeline import timeline
from mscts.transcript import Transcript

REPEAT_VAR = "MSCTS_SELFCHECK_REPEAT"
DEFAULT_REPEAT = 3
"""How many times a Group is played by default; a Group's PR runs 20 once, by hand."""
MAX_VERDICTS = 3
"""How many Verdicts that are not `match` a failure message lists."""
MAX_DIVERGENCES = 5
"""How many of a Verdict's differences a failure message lists."""


def repeat_from(environ: Mapping[str, str]) -> int:
    """How many times to play each Group: `MSCTS_SELFCHECK_REPEAT` in `environ`, else 3.

    Raises:
        ValueError: The variable is set to anything but a whole number of at least 1.
    """
    text = environ.get(REPEAT_VAR, "")
    if not text:
        return DEFAULT_REPEAT
    try:
        repeat = int(text)
    except ValueError:
        repeat = 0
    if repeat < 1:
        msg = f"{REPEAT_VAR} is {text!r}: it must be a whole number of at least 1"
        raise ValueError(msg)
    return repeat


def describe_unmatched(verdicts: Sequence[Verdict]) -> str:
    """Each Verdict that is not `match`, with the differences it found, for a failure message.

    Only the first `MAX_VERDICTS` Verdicts and their first `MAX_DIVERGENCES` differences are
    listed, each with the Bot, the packet, the field path and both values; the rest are counted.
    """
    lines: list[str] = []
    for verdict in verdicts[:MAX_VERDICTS]:
        lines.extend(_describe(verdict))
    if len(verdicts) > MAX_VERDICTS:
        lines.append(f"... and {len(verdicts) - MAX_VERDICTS} more Verdicts that are not match")
    return "\n".join(lines)


def keep_timelines_and_describe(result: RunResult, where: Path) -> str:
    """Write the timelines of `result`'s plays that did not match, and describe its failure.

    Each such play gets a file in `where` (`_keep_timelines`). The message is
    `describe_unmatched` of the Verdicts that are not `match`, then each file's path.
    """
    not_matching = [verdict for verdict in result.verdicts if verdict.outcome is not Outcome.MATCH]
    kept = _keep_timelines(result, where)
    files = [f"  {path}" for path in kept]
    heading = ["The timelines of the plays that did not match:"] if kept else []
    return "\n".join([describe_unmatched(not_matching), *heading, *files])


def _keep_timelines(result: RunResult, where: Path) -> list[Path]:
    """Write a file in `where` for each play of `result` that kept its Transcripts; return them.

    The file holds the play's timeline on the Reference, then on the Candidate, and is
    named after the Group and the repetition (`status-basic.2.txt`).
    """
    where.mkdir(parents=True, exist_ok=True)
    kept: list[Path] = []
    for group in result.results:
        for repetition, transcripts in enumerate(group.transcripts, start=1):
            if transcripts is not None:
                name = f"{group.group_id.replace('/', '-')}.{repetition}.txt"
                kept.append(keep_timeline(transcripts, where / name))
    return kept


def keep_timeline(transcripts: Sequence[Transcript], path: Path) -> Path:
    """Write one play's timelines to `path`, one Transcript after another; return `path`.

    The folder `path` is in is made if it is not there.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n\n".join(timeline(transcript) for transcript in transcripts) + "\n")
    return path


def _describe(verdict: Verdict) -> list[str]:
    head = f"{verdict.group_id}: {verdict.outcome}"
    lines = [f"{head}: {verdict.detail}" if verdict.detail else head]
    for divergence in verdict.divergences[:MAX_DIVERGENCES]:
        where = " ".join(
            part for part in (divergence.kind, divergence.packet, divergence.path) if part
        )
        values = f"{divergence.reference!r} vs {divergence.candidate!r}"
        lines.append(f"  {divergence.bot}: {where}: {values}")
    if len(verdict.divergences) > MAX_DIVERGENCES:
        lines.append(f"  ... and {len(verdict.divergences) - MAX_DIVERGENCES} more differences")
    return lines


def needs_instances_of_their_own(groups: Sequence[Group], pair_spec: ServerSpec) -> bool:
    """Whether a Group of `groups` changes the ServerSpec the shared pair was booted with.

    A Run can only play such a Group on Instances it launches itself (`run` refuses an
    Attached side of another ServerSpec). The Endpoint is no part of the ServerSpec here.
    """
    return any(
        dataclasses.replace(group.spec(pair_spec), host=pair_spec.host, port=pair_spec.port)
        != pair_spec
        for group in groups
    )


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    """Give every test that takes a `group_id` one run per registered Group."""
    if "group_id" in metafunc.fixturenames:
        metafunc.parametrize("group_id", list(GROUPS))
