"""Reports: a short list of what a Run found (#9, ADR-0012)."""

from collections.abc import Sequence
from dataclasses import dataclass

from mscts.compare import Divergence, Outcome
from mscts.run import GroupResult, RunResult, SideSummary
from mscts.target import Target
from mscts.test_cases import TITLES


@dataclass(frozen=True, slots=True)
class Report:
    """What a Run found, ready to render.

    Attributes:
        target: The Target both servers were run at.
        reference: The Reference's name, status version and startup Measurements.
        candidate: The Candidate side, likewise.
        results: One GroupResult per Group, in the order played.
        notes: Remarks retained for other Report formats.
        elapsed_s: Total Run time in seconds, including launch and shutdown.
    """

    target: Target
    reference: SideSummary
    candidate: SideSummary
    results: tuple[GroupResult, ...]
    notes: tuple[str, ...]
    elapsed_s: float

    @classmethod
    def of(
        cls, run: RunResult, *, target: Target, notes: Sequence[str], elapsed_s: float
    ) -> "Report":
        """The Report of a Run at the Target, taking elapsed_s seconds."""
        return cls(target, run.reference, run.candidate, run.results, tuple(notes), elapsed_s)

    @property
    def repeat(self) -> int:
        """How many times each Group was played."""
        return max((len(result.verdicts) for result in self.results), default=0)


def render_text(report: Report) -> str:
    """One first line, each differing test case once, Group failures, and total time."""
    cases = dict.fromkeys(
        divergence.test_case
        for result in report.results
        for verdict in result.verdicts
        for divergence in verdict.divergences
        if divergence.test_case
    )
    lines = [f"Running tests against {report.candidate.name}"]
    for name in cases:
        title = TITLES.get(name)
        lines.append(f"- {title}  {name}" if title else f"- {name}")
    for result in report.results:
        details = _group_details(result)
        if details:
            lines.append(f"- {'; '.join(details)}  {result.group_id}")
    if len(lines) == 1:
        lines.append("No differences.")
    seconds = f"{report.elapsed_s:.1f}".removesuffix(".0")
    return "\n".join([*lines, f"Took {seconds} s"]) + "\n"


def _group_details(result: GroupResult) -> list[str]:
    details: dict[str, None] = {}
    for verdict in result.verdicts:
        if verdict.outcome is Outcome.BLOCKED:
            details[f"Not tested: {verdict.detail}"] = None
        elif verdict.outcome is Outcome.ERROR:
            details[f"Error: {verdict.detail}"] = None
        for divergence in verdict.divergences:
            if not divergence.test_case:
                details[_group_difference(divergence)] = None
    return list(details)


def _group_difference(divergence: Divergence) -> str:
    if divergence.kind == "failed":
        return f"Candidate failed: {divergence.candidate}"
    return (
        f"Bot {divergence.bot!r} exchanged {divergence.reference} packets with the Reference, "
        f"{divergence.candidate} with the Candidate"
    )
