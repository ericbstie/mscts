"""A Self-check's Verdicts in words, for an assertion message (#456).

pytest cuts a long repr in its assertion message, so a list of Verdicts loses the
Divergences a one-off mismatch needs to be read from the log.
"""

from collections import Counter
from collections.abc import Iterator, Sequence

from mscts.compare import Divergence, Outcome, Verdict


def describe_mismatches(verdicts: Sequence[Verdict]) -> str:
    """Each Verdict that is not a match, a line per Divergence; "" if all match.

    `verdicts` are a Run's, each Group's in play order, so a Verdict's play is its place
    among its Group's. A line names the Group, the play, and the Divergence's Bot, packet,
    stream index, path (its kind for a whole packet) and both values. A Verdict read back
    from a report.json that capped its Divergences says how many it left out, and one
    without Divergences gives its outcome and detail.
    """
    return "\n".join(
        f"{play}: {line}"
        for play, verdict in _plays(verdicts)
        if verdict.outcome is not Outcome.MATCH
        for line in _verdict_lines(verdict)
    )


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
        yield f"{verdict.outcome}: {verdict.detail}"
    yield from map(_divergence_line, verdict.divergences)
    if verdict.omitted:
        yield f"{verdict.omitted} more Divergences omitted"


def _divergence_line(divergence: Divergence) -> str:
    where = divergence.kind if divergence.path is None else divergence.path
    return (
        f"bot {divergence.bot!r} {divergence.packet} at {divergence.index}, {where}:"
        f" reference {divergence.reference!r}, candidate {divergence.candidate!r}"
    )
