"""Reports: a short list of what a Run found (#9, ADR-0012)."""

import json
import re
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from mscts.case_titles import TITLES
from mscts.compare import ABSENT, Divergence, Observability, Outcome
from mscts.run import GroupResult, RunResult, SideSummary
from mscts.target import Target

_NO_DIFFERENCES = "No differences."
_GROUP_TIMES = "Group times"


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


class Result(StrEnum):
    """How one line of a Report came out."""

    PASS = "pass"  # noqa: S105  # nosec B105
    FAIL = "fail"
    NOT_TESTED = "not tested"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class CaseResult:
    """One line of a Report: a test case, or a Group that has no test case to show for it.

    Attributes:
        group_id: The Group it belongs to.
        test_case: The test case's name, or "" for the Group's own line.
        result: Whether it passed. NOT_TESTED fails too; ERROR is left out of the score.
        network_traffic_only: True if it differs, but only in network traffic.
        reasons: Why the Group's own line is there, such as `Not tested: …`; else "".
    """

    group_id: str
    test_case: str
    result: Result
    network_traffic_only: bool = False
    reasons: str = ""


@dataclass(frozen=True, slots=True)
class Totals:
    """How many lines of a Report came out each way.

    Attributes:
        passed: Lines that passed.
        failed: Lines that failed, counting those not tested.
        not_tested: Of the failed lines, those not tested.
        errors: Lines left out of the score because mscts or the Reference failed.
    """

    passed: int
    failed: int
    not_tested: int
    errors: int

    @property
    def scored(self) -> int:
        """How many lines the score counts."""
        return self.passed + self.failed

    @property
    def score(self) -> float | None:
        """The share of scored lines that passed, or None if no line was scored."""
        return self.passed / self.scored if self.scored else None


NETWORK_TRAFFIC_ONLY_PASSES: bool = True
"""Whether a test case that differs only in network traffic passes (ADR-0007)."""


def case_results(report: Report) -> tuple[CaseResult, ...]:
    """Each test case of each Group, in the order played, then the Group's own line if any."""
    results: list[CaseResult] = []
    for group in report.results:
        found: dict[str, set[bool]] = {
            name: set() for verdict in group.verdicts for name in verdict.test_cases
        }
        for verdict in group.verdicts:
            for divergence in verdict.divergences:
                if divergence.test_case:
                    found.setdefault(divergence.test_case, set()).add(
                        divergence.observability is Observability.NETWORK_TRAFFIC
                    )
        results.extend(_case_result(group.group_id, name, found[name]) for name in sorted(found))
        details = _group_details(group)
        if details:
            kinds = {kind for kind, _ in details}
            result = next(kind for kind in _GROUP_RESULTS if kind in kinds)
            reasons = "; ".join(reason for _, reason in details)
            results.append(CaseResult(group.group_id, "", result, reasons=reasons))
    return tuple(results)


_GROUP_RESULTS = (Result.FAIL, Result.NOT_TESTED, Result.ERROR)
"""A Group line's result: the first of these that any of its reasons has."""


def _case_result(group_id: str, name: str, traffic: set[bool]) -> CaseResult:
    """`traffic` holds, for each way the test case differs, whether it is network traffic."""
    if not traffic:
        return CaseResult(group_id, name, Result.PASS)
    if traffic == {True}:
        result = Result.PASS if NETWORK_TRAFFIC_ONLY_PASSES else Result.FAIL
        return CaseResult(group_id, name, result, network_traffic_only=True)
    return CaseResult(group_id, name, Result.FAIL)


def totals(results: Iterable[CaseResult]) -> Totals:
    """How many of `results` came out each way."""
    counts = Counter(result.result for result in results)
    return Totals(
        passed=counts[Result.PASS],
        failed=counts[Result.FAIL] + counts[Result.NOT_TESTED],
        not_tested=counts[Result.NOT_TESTED],
        errors=counts[Result.ERROR],
    )


@dataclass(frozen=True, slots=True)
class _Literal:
    """Text mscts did not write, such as a value or a name: Markdown shows it as code."""

    text: str


type _Line = tuple[str | _Literal, ...]
"""One line of a Report: plain text and literals, written one after the other."""


@dataclass(frozen=True, slots=True)
class _Entry:
    """One listed difference or Group failure.

    Attributes:
        label: Its title or reason, if it has one.
        name: Its test case name or Group id.
        values: The verbose lines under it.
    """

    label: str
    name: str
    values: tuple[_Line, ...]


@dataclass(frozen=True, slots=True)
class _Document:
    """What a Report says, before it is written as text or Markdown.

    Attributes:
        title: The first line.
        build: The line naming the Candidate's exact build, when the verbose header,
            which names it too, is not shown and the build is known; else None.
        facts: The verbose header's labelled values, or none.
        entries: Each differing test case, then each Group that failed or was skipped.
        times: The verbose time of each Group (`status/basic 0.1 s`), or None.
        total: The last line, the total Run time.
    """

    title: str
    build: str | None
    facts: tuple[tuple[str, str], ...]
    entries: tuple[_Entry, ...]
    times: tuple[str, ...] | None
    total: str


def render_text(report: Report, *, verbose: bool = False) -> str:
    """One first line, each differing test case once, Group failures, and total time."""
    document = _document(report, verbose=verbose)
    lines = [document.title]
    if document.build is not None:
        lines.append(document.build)
    lines.extend(f"  {label:<13}{value}" for label, value in document.facts)
    for entry in document.entries:
        lines.append(f"- {entry.label}  {entry.name}" if entry.label else f"- {entry.name}")
        lines.extend(f"  {_plain(line)}" for line in entry.values)
    if not document.entries:
        lines.append(_NO_DIFFERENCES)
    if document.times is not None:
        lines.append(_GROUP_TIMES)
        lines.extend(f"  {time}" for time in document.times)
    return "\n".join([*lines, document.total]) + "\n"


def render_markdown(report: Report, *, verbose: bool = False) -> str:
    """What render_text says, as Markdown: the first line a heading, names and values code."""
    document = _document(report, verbose=verbose)
    blocks = [f"# {_escape(document.title)}"]
    if document.build is not None:
        blocks.append(_escape(document.build))
    if document.facts:
        blocks.append(
            "\\\n".join(f"{_escape(label)}: {_escape(value)}" for label, value in document.facts)
        )
    blocks.append("\n".join(_markdown_entry(entry) for entry in document.entries))
    if not document.entries:
        blocks[-1] = _NO_DIFFERENCES
    if document.times is not None:
        blocks.append(f"## {_GROUP_TIMES}")
        blocks.append("\n".join(f"- {_escape(time)}" for time in document.times))
    blocks.append(_escape(document.total))
    return "\n\n".join(blocks) + "\n"


def _markdown_entry(entry: _Entry) -> str:
    label = f"{_escape(entry.label)} " if entry.label else ""
    values = (f"\n  - {_markdown(line)}" for line in entry.values)
    return f"- {label}{_code(entry.name)}{''.join(values)}"


def _markdown(line: _Line) -> str:
    return "".join(
        _code(span.text) if isinstance(span, _Literal) else _escape(span) for span in line
    )


_SPECIAL = frozenset("\\`*_[]<>&|~")
"""The characters Markdown could read as formatting inside a line."""

_LINE_BREAKS = {"\n": "\\\\n", "\r": "\\\\r"}
"""Each line break as Markdown that shows it as `\\n` or `\\r`, so the line goes on."""


def _escape(text: str) -> str:
    """`text` as Markdown that shows it as it is, on one line."""
    return "".join(
        f"\\{char}" if char in _SPECIAL else _LINE_BREAKS.get(char, char) for char in text
    )


def _code(text: str) -> str:
    """`text` as a Markdown code span: fenced by more backticks than it holds in a row."""
    fence = "`" * (1 + max((len(run) for run in re.findall("`+", text)), default=0))
    padding = " " if text and (text[0] in "` " or text[-1] in "` ") else ""
    return f"{fence}{padding}{text}{padding}{fence}"


def _plain(line: _Line) -> str:
    return "".join(span.text if isinstance(span, _Literal) else span for span in line)


def _document(report: Report, *, verbose: bool) -> _Document:
    """What the Report says: the verbose header, values and Group times only if `verbose`."""
    cases = dict.fromkeys(
        divergence.test_case
        for result in report.results
        for verdict in result.verdicts
        for divergence in verdict.divergences
        if divergence.test_case
    )
    candidate = report.candidate
    version = candidate.installed_version  # the exact build tested (#156)
    entries = [
        _Entry(TITLES.get(name, ""), name, _values(report, name) if verbose else ())
        for name in cases
    ]
    entries.extend(_group_entries(report, verbose=verbose))
    return _Document(
        title=f"Running tests against {candidate.name}",
        build=None if verbose or version is None else f"Candidate: {candidate.name} {version}",
        facts=_header(report) if verbose else (),
        entries=tuple(entries),
        times=_group_times(report.results) if verbose else None,
        total=f"Took {_seconds(report.elapsed_s)} s",
    )


def _group_details(result: GroupResult) -> list[tuple[Result, str]]:
    """Why the Group gets its own line, each reason once with how it makes the line come out."""
    details: dict[tuple[Result, str], None] = {}
    for verdict in result.verdicts:
        if verdict.outcome is Outcome.BLOCKED:
            details[Result.NOT_TESTED, f"Not tested: {verdict.detail}"] = None
        elif verdict.outcome is Outcome.ERROR:
            details[Result.ERROR, f"Error: {verdict.detail}"] = None
        for divergence in verdict.divergences:
            if not divergence.test_case:
                details[Result.FAIL, _group_difference(divergence)] = None
    return list(details)


def _group_difference(divergence: Divergence) -> str:
    if divergence.kind == "failed":
        return f"Candidate failed: {divergence.candidate}"
    return (
        f"Bot {divergence.bot!r} exchanged {divergence.reference} packets with the Reference, "
        f"{divergence.candidate} with the Candidate"
    )


def _header(report: Report) -> tuple[tuple[str, str], ...]:
    def side(summary: SideSummary) -> str:
        version = summary.installed_version or "(installed version unknown)"
        return f"{summary.name} {version}"

    target = (
        f"Minecraft {report.target.minecraft_version} (protocol {report.target.protocol_version})"
    )
    return (
        ("Reference", side(report.reference)),
        ("Candidate", side(report.candidate)),
        ("Target", target),
        ("Repetitions", f"{report.repeat} of each group"),
    )


def _values(report: Report, name: str) -> tuple[_Line, ...]:
    return tuple(
        dict.fromkeys(
            _difference_values(report, divergence)
            for result in report.results
            for verdict in result.verdicts
            for divergence in verdict.divergences
            if divergence.test_case == name
        )
    )


def _difference_values(report: Report, divergence: Divergence) -> _Line:
    path: _Line = (
        (_Literal(divergence.path), ": ") if divergence.path and "[" in divergence.path else ()
    )
    return (
        *path,
        f"{report.reference.name} ",
        *_sent(divergence.reference),
        f", {report.candidate.name} ",
        *_sent(divergence.candidate),
    )


def _sent(value: object) -> _Line:
    if value is ABSENT:
        return ("leaves it out",)
    if isinstance(value, bytes):
        return ("sends bytes ", _Literal(value.hex()))
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, default=_json_value)
    return ("sends ", _Literal(text))


def _group_times(results: Sequence[GroupResult]) -> tuple[str, ...]:
    times = []
    for result in results:
        if all(verdict.outcome is Outcome.BLOCKED for verdict in result.verdicts):
            duration = "not played"
        elif result.elapsed_s:
            duration = f"{_seconds(sum(result.elapsed_s))} s"
        else:
            duration = "not recorded"
        times.append(f"{result.group_id} {duration}")
    return tuple(times)


def _seconds(value: float) -> str:
    return f"{value:.1f}".removesuffix(".0")


def _group_entries(report: Report, *, verbose: bool) -> list[_Entry]:
    entries = []
    for result in report.results:
        details = [reason for _, reason in _group_details(result)]
        if not details:
            continue
        values = (
            dict.fromkeys(
                _difference_values(report, divergence)
                for verdict in result.verdicts
                for divergence in verdict.divergences
                if not divergence.test_case
            )
            if verbose
            else {}
        )
        entries.append(_Entry("; ".join(details), result.group_id, tuple(values)))
    return entries


def _json_value(value: object) -> object:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, bytes):
        return {"bytes": value.hex()}
    msg = f"Unsupported Report value: {type(value).__name__}"
    raise TypeError(msg)
