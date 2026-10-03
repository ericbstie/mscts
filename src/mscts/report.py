"""Reports: a short list of what a Run found (#9, ADR-0012)."""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from mscts.case_titles import TITLES
from mscts.compare import ABSENT, Divergence, Outcome
from mscts.run import GroupResult, RunResult, SideSummary
from mscts.target import Target


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


def render_text(report: Report, *, verbose: bool = False) -> str:
    """One first line, each differing test case once, Group failures, and total time."""
    cases = dict.fromkeys(
        divergence.test_case
        for result in report.results
        for verdict in result.verdicts
        for divergence in verdict.divergences
        if divergence.test_case
    )
    candidate = report.candidate
    lines = [f"Running tests against {candidate.name}"]
    if verbose:
        lines.extend(_header(report))
    elif candidate.installed_version is not None:  # the exact build tested (#156)
        lines.append(f"Candidate: {candidate.name} {candidate.installed_version}")
    for name in cases:
        title = TITLES.get(name)
        lines.append(f"- {title}  {name}" if title else f"- {name}")
        if verbose:
            lines.extend(_values(report, name))
    group_lines = _group_lines(report, verbose=verbose)
    lines.extend(group_lines)
    if not cases and not group_lines:
        lines.append("No differences.")
    if verbose:
        lines.extend(_group_times(report.results))
    return "\n".join([*lines, f"Took {_seconds(report.elapsed_s)} s"]) + "\n"


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


def _header(report: Report) -> list[str]:
    def side(summary: SideSummary) -> str:
        version = summary.installed_version or "(installed version unknown)"
        return f"{summary.name} {version}"

    target = (
        f"Minecraft {report.target.minecraft_version} (protocol {report.target.protocol_version})"
    )
    return [
        f"  Reference    {side(report.reference)}",
        f"  Candidate    {side(report.candidate)}",
        f"  Target       {target}",
        f"  Repetitions  {report.repeat} of each group",
    ]


def _values(report: Report, name: str) -> list[str]:
    return list(
        dict.fromkeys(
            _difference_values(report, divergence)
            for result in report.results
            for verdict in result.verdicts
            for divergence in verdict.divergences
            if divergence.test_case == name
        )
    )


def _difference_values(report: Report, divergence: Divergence) -> str:
    path = f"{divergence.path}: " if divergence.path and "[" in divergence.path else ""
    return (
        f"  {path}{report.reference.name} {_sent(divergence.reference)}, "
        f"{report.candidate.name} {_sent(divergence.candidate)}"
    )


def _sent(value: object) -> str:
    if value is ABSENT:
        return "leaves it out"
    if isinstance(value, bytes):
        return f"sends bytes {value.hex()}"
    return f"sends {json.dumps(value, ensure_ascii=False, sort_keys=True, default=_json_value)}"


def _group_times(results: Sequence[GroupResult]) -> list[str]:
    lines = ["Group times"]
    for result in results:
        if all(verdict.outcome is Outcome.BLOCKED for verdict in result.verdicts):
            duration = "not played"
        elif result.elapsed_s:
            duration = f"{_seconds(sum(result.elapsed_s))} s"
        else:
            duration = "not recorded"
        lines.append(f"  {result.group_id} {duration}")
    return lines


def _seconds(value: float) -> str:
    return f"{value:.1f}".removesuffix(".0")


def _group_lines(report: Report, *, verbose: bool) -> list[str]:
    lines = []
    for result in report.results:
        details = _group_details(result)
        if not details:
            continue
        lines.append(f"- {'; '.join(details)}  {result.group_id}")
        if verbose:
            lines.extend(
                dict.fromkeys(
                    _difference_values(report, divergence)
                    for verdict in result.verdicts
                    for divergence in verdict.divergences
                    if not divergence.test_case
                )
            )
    return lines


def _json_value(value: object) -> object:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, bytes):
        return {"bytes": value.hex()}
    msg = f"Unsupported Report value: {type(value).__name__}"
    raise TypeError(msg)
