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


class LineResult(StrEnum):
    """How one line of a Report came out."""

    PASS = "pass"  # noqa: S105  # nosec B105
    FAIL = "fail"
    NOT_TESTED = "not tested"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class CaseResult:
    """One line of a Report: how one test case of one Group came out.

    Attributes:
        group_id: The Group.
        test_case: The test case's name.
        result: PASS or FAIL.
        network_traffic_only: True if it differs, but only in network traffic.
    """

    group_id: str
    test_case: str
    result: LineResult
    network_traffic_only: bool = False


@dataclass(frozen=True, slots=True)
class GroupLine:
    """One line of a Report for a Group itself: why it failed, or was not compared.

    Attributes:
        group_id: The Group.
        result: FAIL if the Candidate failed or a Bot's packet count differed, else
            NOT_TESTED if it was blocked, else ERROR, which is left out of the score.
        reasons: Each distinct reason, joined by "; ", such as `Not tested: needs /tick`.
    """

    group_id: str
    result: LineResult
    reasons: str


type Line = CaseResult | GroupLine
"""One line of a Report."""


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


def report_lines(report: Report) -> tuple[Line, ...]:
    """Each test case of each Group, in the order played, then the Group's own line if any."""
    results: list[Line] = []
    for group in report.results:
        divergences = [
            divergence
            for verdict in group.verdicts
            for divergence in verdict.divergences
            if divergence.test_case
        ]
        found: dict[str, set[bool]] = {
            name: set()
            for names in (
                *(verdict.test_cases for verdict in group.verdicts),
                (divergence.test_case for divergence in divergences),
            )
            for name in names
        }
        for divergence in divergences:
            traffic = divergence.observability is Observability.NETWORK_TRAFFIC
            for name in _differing(divergence, found):
                found[name].add(traffic)
        results.extend(_case_result(group.group_id, name, found[name]) for name in sorted(found))
        details = _group_details(group)
        if details:
            kinds = {kind for kind, _ in details}
            result = next(kind for kind in _GROUP_RESULTS if kind in kinds)
            reasons = "; ".join(reason for _, reason in details)
            results.append(GroupLine(group.group_id, result, reasons))
    return tuple(results)


def _differing(divergence: Divergence, names: Iterable[str]) -> list[str]:
    """The test cases among `names` that `divergence` makes differ.

    A `missing` Packet's: the packet's test case and each of its fields', which the
    Comparison lists for a Packet left out, so leaving a Packet out fails each field
    sending it wrong would (#101). Any other Divergence's: its own test case.
    """
    case = divergence.test_case
    if divergence.kind != "missing":
        return [case]
    fields = (f"{case}.", f"{case}[")
    return [name for name in names if name == case or name.startswith(fields)]


_GROUP_RESULTS = (LineResult.FAIL, LineResult.NOT_TESTED, LineResult.ERROR)
"""A Group line's result: the first of these that any of its reasons has."""


def _case_result(group_id: str, name: str, traffic: set[bool]) -> CaseResult:
    """`traffic` holds, for each way the test case differs, whether it is network traffic."""
    if not traffic:
        return CaseResult(group_id, name, LineResult.PASS)
    if traffic == {True}:
        result = LineResult.PASS if NETWORK_TRAFFIC_ONLY_PASSES else LineResult.FAIL
        return CaseResult(group_id, name, result, network_traffic_only=True)
    return CaseResult(group_id, name, LineResult.FAIL)


def totals(results: Iterable[Line]) -> Totals:
    """How many of `results` came out each way."""
    counts = Counter(result.result for result in results)
    return Totals(
        passed=counts[LineResult.PASS],
        failed=counts[LineResult.FAIL] + counts[LineResult.NOT_TESTED],
        not_tested=counts[LineResult.NOT_TESTED],
        errors=counts[LineResult.ERROR],
    )


@dataclass(frozen=True, slots=True)
class _Literal:
    """Text mscts did not write, such as a value or a name: Markdown shows it as code."""

    text: str


type _Line = tuple[str | _Literal, ...]
"""One line of a Report: plain text and literals, written one after the other."""


_LISTED = frozenset(LineResult)
"""The results a Report lists a line for (ADR-0012, amended by #101: all of them).

The totals and the score count every line, listed or not.
"""

_MARKS = {
    LineResult.PASS: "✓",
    LineResult.FAIL: "✗",
    LineResult.NOT_TESTED: "✗",
    LineResult.ERROR: "!",
}
"""Each line's mark: `!` for an error, which is not scored, so neither passes nor fails."""


@dataclass(frozen=True, slots=True)
class _Entry:
    """One listed line: a test case, or a Group without test cases to show for it.

    Attributes:
        mark: ✓ if it passed, ! if it is an error, else ✗ (`_MARKS`).
        name: `<group>/<test case>`, or the Group id for the Group's own line.
        label: The test case's title, or the Group's reasons; "" if it has neither.
        values: The verbose lines under it.
    """

    mark: str
    name: str
    label: str
    values: tuple[_Line, ...]


@dataclass(frozen=True, slots=True)
class _Document:
    """What a Report says, before it is written as text or Markdown.

    Attributes:
        title: The first line.
        build: The line naming the Candidate's exact build, when the verbose header,
            which names it too, is not shown and the build is known; else None.
        facts: The verbose header's labelled values, or none.
        entries: Each listed line, in the order played.
        times: The verbose time of each Group (`status/basic 0.1 s`), or None.
        closing: The last lines: the totals, the score and the total Run time.
    """

    title: str
    build: str | None
    facts: tuple[tuple[str, str], ...]
    entries: tuple[_Entry, ...]
    times: tuple[str, ...] | None
    closing: tuple[str, ...]


_COLORS = {"✓": "32", "✗": "31", "!": "33"}
"""Each mark's ANSI colour on a terminal: green, red and yellow."""


def render_text(report: Report, *, verbose: bool = False, color: bool = False) -> str:
    """A first line, a line per test case, the totals, the score and the total time.

    With `color`, for a terminal, each mark is in its colour (`_COLORS`).
    """
    document = _document(report, verbose=verbose)
    lines = [document.title]
    if document.build is not None:
        lines.append(document.build)
    lines.extend(f"  {label:<13}{value}" for label, value in document.facts)
    for entry in document.entries:
        label = f" {entry.label}" if entry.label else ""
        mark = f"\x1b[{_COLORS[entry.mark]}m{entry.mark}\x1b[0m" if color else entry.mark
        lines.append(f"{mark} {entry.name}{label}")
        lines.extend(f"  {_plain(line)}" for line in entry.values)
    if document.times is not None:
        lines.append(_GROUP_TIMES)
        lines.extend(f"  {time}" for time in document.times)
    return "\n".join([*lines, *document.closing]) + "\n"


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
    if document.entries:
        blocks.append("\n".join(_markdown_entry(entry) for entry in document.entries))
    if document.times is not None:
        blocks.append(f"## {_GROUP_TIMES}")
        blocks.append("\n".join(f"- {_escape(time)}" for time in document.times))
    blocks.append("\\\n".join(_escape(line) for line in document.closing))
    return "\n\n".join(blocks) + "\n"


def _markdown_entry(entry: _Entry) -> str:
    label = f" {_escape(entry.label)}" if entry.label else ""
    values = (f"\n  - {_markdown(line)}" for line in entry.values)
    return f"- {entry.mark} {_code(entry.name)}{label}{''.join(values)}"


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
    lines = report_lines(report)
    groups = {result.group_id: result for result in report.results}
    entries = tuple(
        _entry(report, groups[line.group_id], line, verbose=verbose)
        for line in lines
        if line.result in _LISTED
    )
    candidate = report.candidate
    version = candidate.installed_version  # the exact build tested (#156)
    return _Document(
        title=f"Running tests against {candidate.name}",
        build=None if verbose or version is None else f"Candidate: {candidate.name} {version}",
        facts=_header(report) if verbose else (),
        entries=entries,
        times=_group_times(report.results) if verbose else None,
        closing=(*_totals_lines(totals(lines)), f"Took {_seconds(report.elapsed_s)} s"),
    )


def _entry(report: Report, group: GroupResult, line: Line, *, verbose: bool) -> _Entry:
    if isinstance(line, GroupLine):
        name, label, case = line.group_id, line.reasons, ""
    else:
        name, case = f"{line.group_id}/{line.test_case}", line.test_case
        traffic = " (network traffic only)" if line.network_traffic_only else ""
        label = f"{TITLES.get(case, '')}{traffic}".strip()
    values = _values(report, group, case) if verbose else ()
    return _Entry(_MARKS[line.result], name, label, values)


def _totals_lines(counts: Totals) -> tuple[str, str]:
    """The totals line (`7 passed, 2 failed (1 not tested), 1 error (not scored)`) and score."""
    not_tested = f" ({counts.not_tested} not tested)" if counts.not_tested else ""
    errors = (
        f", {counts.errors} error{'s' if counts.errors > 1 else ''} (not scored)"
        if counts.errors
        else ""
    )
    totals_line = f"{counts.passed} passed, {counts.failed} failed{not_tested}{errors}"
    if not counts.scored:
        return totals_line, "Score: none (no test case was scored)"
    tenths = counts.passed * 1000 // counts.scored  # rounded down: only all passing is 100%
    percent = f"{tenths // 10}.{tenths % 10}".removesuffix(".0")
    cases = "test case passes" if counts.scored == 1 else "test cases pass"
    return totals_line, f"Score: {percent}% ({counts.passed} of {counts.scored} {cases})"


def _group_details(result: GroupResult) -> list[tuple[LineResult, str]]:
    """Why the Group gets its own line, each reason once with how it makes the line come out."""
    details: dict[tuple[LineResult, str], None] = {}
    for verdict in result.verdicts:
        if verdict.outcome is Outcome.BLOCKED:
            details[LineResult.NOT_TESTED, f"Not tested: {verdict.detail}"] = None
        elif verdict.outcome is Outcome.ERROR:
            details[LineResult.ERROR, f"Error: {verdict.detail}"] = None
        for divergence in verdict.divergences:
            if not divergence.test_case:
                details[LineResult.FAIL, _group_difference(divergence)] = None
    return list(details)


def _group_difference(divergence: Divergence) -> str:
    if divergence.kind == "failed":
        return f"Candidate failed: {divergence.candidate}"
    reference, candidate = (
        0 if count is ABSENT else count for count in (divergence.reference, divergence.candidate)
    )
    return (
        f"Bot {divergence.bot!r} exchanged {reference} packets with the Reference, "
        f"{candidate} with the Candidate"
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


def _values(report: Report, group: GroupResult, test_case: str) -> tuple[_Line, ...]:
    """The Group's distinct values for the test case, or for the Group itself if it is ""."""
    return tuple(
        dict.fromkeys(
            _difference_values(report, divergence)
            for verdict in group.verdicts
            for divergence in verdict.divergences
            if divergence.test_case == test_case
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


def _json_value(value: object) -> object:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, bytes):
        return {"bytes": value.hex()}
    msg = f"Unsupported Report value: {type(value).__name__}"
    raise TypeError(msg)
