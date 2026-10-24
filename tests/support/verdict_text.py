"""A Run's mismatching plays in words, for an assertion message (#456, #471).

pytest cuts a long repr in its assertion message, so a list of Verdicts loses the
Divergences a one-off mismatch needs to be read from the log.
"""

from collections import Counter
from collections.abc import Iterator, Sequence
from pathlib import Path

from mscts.compare import Divergence, Outcome, Verdict
from mscts.run import RunResult
from mscts.timeline import timeline
from mscts.transcript import Transcript

_TIMELINES_HEADING = "The timelines of the plays that did not match:"


def describe_mismatches(result: RunResult, where: Path) -> str:
    """Each play of `result` that is not a match, a line per Divergence; "" if all match.

    A line names the Group, the play, and the Divergence's Bot, packet, stream index, path
    (its kind for a whole packet) and both values. Every Divergence is listed, and a Verdict
    read back from a report.json that capped its Divergences says how many it left out; one
    without Divergences gives its outcome and detail. The lines are followed by the file of
    each kept play's timelines (`keep_timelines`), written in `where`.
    """
    lines = [
        *_mismatch_lines(result.verdicts),
        *_timeline_lines(keep_timelines(result, where)),
    ]
    return "\n".join(lines)


def keep_timelines(result: RunResult, where: Path) -> list[Path]:
    """Write a file in `where` for each play of `result` that kept its Transcripts; return them.

    The file holds the play's timeline on the Reference, then on the Candidate, and is
    named after the Group and the repetition (`status-basic.2.txt`). Nothing is written, and
    `where` is not made, for a Run that kept no Transcripts.
    """
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


def _timeline_lines(kept: Sequence[Path]) -> list[str]:
    return [_TIMELINES_HEADING, *(f"  {path}" for path in kept)] if kept else []


def _mismatch_lines(verdicts: Sequence[Verdict]) -> Iterator[str]:
    """A line per Divergence of each Verdict that is not a match, led by its play.

    `verdicts` are a Run's, each Group's in play order, so a Verdict's play is its place
    among its Group's.
    """
    for play, verdict in _plays(verdicts):
        if verdict.outcome is not Outcome.MATCH:
            for line in _verdict_lines(verdict):
                yield f"{play}: {line}"


def _plays(verdicts: Sequence[Verdict]) -> Iterator[tuple[str, Verdict]]:
    """Each Verdict with its play: `<group> play <n> of <its Group's plays>`."""
    plays = Counter(verdict.group_id for verdict in verdicts)
    played: Counter[str] = Counter()
    for verdict in verdicts:
        played[verdict.group_id] += 1
        yield (
            f"{verdict.group_id} play {played[verdict.group_id]} of {plays[verdict.group_id]}",
            verdict,
        )


def _verdict_lines(verdict: Verdict) -> Iterator[str]:
    if not verdict.divergences:
        yield f"{verdict.outcome}: {verdict.detail}" if verdict.detail else f"{verdict.outcome}"
    yield from map(_divergence_line, verdict.divergences)
    if verdict.omitted:
        yield f"{verdict.omitted} more Divergences omitted"


def _divergence_line(divergence: Divergence) -> str:
    where = divergence.kind if divergence.path is None else divergence.path
    return (
        f"bot {divergence.bot!r} {divergence.packet} at {divergence.index}, {where}:"
        f" reference {divergence.reference!r}, candidate {divergence.candidate!r}"
    )
