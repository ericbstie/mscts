"""Reports: what a Run found, rendered for a reader who does not know the codebase."""

import json
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

from mscts.compare import ABSENT, Divergence, Observability, Outcome, Verdict
from mscts.measure import Measurement, stats
from mscts.run import RunResult, ScenarioResult, SideSummary
from mscts.target import Target

MECHANICS: Mapping[str, str] = MappingProxyType(
    {
        "status": "Server list ping (status)",
        "join": "Joining a world (join)",
    }
)
"""A plain title for each mechanic: the first segment of a Scenario id."""

VALUE_LIMIT = 80
"""The longest value shown in full; a longer one is cut, with its full length."""

WIRE_EXAMPLES = 5
"""How many examples each packet's wire-only differences show."""

_MINECRAFT = "minecraft:"

_NOT_PLAYED: Mapping[Outcome, str] = MappingProxyType(
    {
        Outcome.BLOCKED: "was not played (blocked)",
        Outcome.ERROR: "could not be judged (error)",
    }
)
"""How a Verdict that is no Comparison of the two servers reads, by its outcome."""
_INTO = chr(0x203A)
"""Between a packet and a field path: a single right-pointing angle quotation mark."""


@dataclass(frozen=True, slots=True)
class Report:
    """What a Run found, ready to render.

    Attributes:
        target: The Target both servers were run at.
        reference: The Reference side: its name, version and startup Measurements.
        candidate: The Candidate side, likewise.
        results: One ScenarioResult per Scenario, in the order played.
        notes: Plain remarks for the reader, e.g. what this Report leaves out.
    """

    target: Target
    reference: SideSummary
    candidate: SideSummary
    results: tuple[ScenarioResult, ...]
    notes: tuple[str, ...]

    @classmethod
    def of(cls, run: RunResult, *, target: Target, notes: Sequence[str]) -> "Report":
        """The Report of `run`, played at `target`."""
        return cls(
            target=target,
            reference=run.reference,
            candidate=run.candidate,
            results=run.results,
            notes=tuple(notes),
        )

    @property
    def repeat(self) -> int:
        """How many times each Scenario was played."""
        return max((len(result.verdicts) for result in self.results), default=0)


def render_text(report: Report) -> str:
    """`report` as plain text for a terminal, section after section."""
    sections = [
        _header(report),
        _summary(report),
        _observable(report),
        _wire_only(report),
        _unsettled(report),
        _timings(report),
        _notes(report),
        _legend(report),
    ]
    return "\n\n".join(section for section in sections if section) + "\n"


def _header(report: Report) -> str:
    target = report.target
    rows = (
        ("Reference", _side(report.reference)),
        ("Candidate", _side(report.candidate)),
        ("Target", f"Minecraft {target.minecraft_version} (protocol {target.protocol_version})"),
        ("Repetitions", f"{report.repeat} of each scenario"),
    )
    return "mscts Report\n" + "\n".join(f"  {label:<12} {value}" for label, value in rows)


def _side(side: SideSummary) -> str:
    if side.version is None:
        return f"{side.name} (its status named no version)"
    return f"{side.name} (its status says version {json.dumps(side.version)})"


def _state(result: ScenarioResult) -> str:
    verdicts = result.verdicts
    if any(verdict.outcome is Outcome.ERROR for verdict in verdicts):
        return "could not be run"
    if any(verdict.observable for verdict in verdicts):
        return "different"
    if any(verdict.divergences for verdict in verdicts):
        return "different on the wire only"
    if any(verdict.outcome is Outcome.BLOCKED for verdict in verdicts):
        return "blocked"
    return "identical"


def _summary(report: Report) -> str:
    count = len(report.results)
    states = [_state(result) for result in report.results]
    if set(states) <= {"identical"}:
        return f"No differences from vanilla were found in the {count} scenarios run."
    order = ("identical", "different", "different on the wire only", "blocked", "could not be run")
    counts = ", ".join(f"{states.count(state)} {state}" for state in order if state in states)
    return f"{count} scenarios: {counts}."


def _mechanic(scenario_id: str) -> str:
    prefix = scenario_id.split("/", 1)[0]
    return MECHANICS.get(prefix, prefix)


def _by_mechanic(results: Iterable[ScenarioResult]) -> dict[str, list[ScenarioResult]]:
    grouped: dict[str, list[ScenarioResult]] = {}
    for result in results:
        grouped.setdefault(_mechanic(result.scenario_id), []).append(result)
    return grouped


def _distinct(
    verdicts: Sequence[Verdict], pick: Callable[[Verdict], Iterable[Divergence]]
) -> list[tuple[Divergence, int]]:
    """Each distinct Divergence `pick` finds in `verdicts`, with how many Verdicts had it."""
    seen: dict[str, tuple[Divergence, int]] = {}
    for verdict in verdicts:
        for key, divergence in {repr(d): d for d in pick(verdict)}.items():
            _, count = seen.get(key, (divergence, 0))
            seen[key] = (divergence, count + 1)
    return list(seen.values())


def _observable_of(verdict: Verdict) -> tuple[Divergence, ...]:
    return verdict.observable


def _wire_only_of(verdict: Verdict) -> list[Divergence]:
    return [d for d in verdict.divergences if d.observability is Observability.WIRE_ONLY]


def _observable(report: Report) -> str:
    lines: list[str] = []
    for title, results in _by_mechanic(report.results).items():
        block: list[str] = []
        for result in results:
            found = _distinct(result.verdicts, _observable_of)
            if not found:
                continue
            block.append(f"    {result.scenario_id}")
            runs = len(result.verdicts)
            for divergence, count in found:
                seen_in = "" if count == runs else f" (in {count} of {runs} runs)"
                block.append(f"      - {_describe(divergence, report)}{seen_in}")
        if block:
            lines += [f"  {title}", *block]
    if not lines:
        return ""
    return _heading("Differences a player would notice") + "\n" + "\n".join(lines)


def _wire_only(report: Report) -> str:
    lines: list[str] = []
    for title, results in _by_mechanic(report.results).items():
        packets: dict[str, dict[str, Divergence]] = {}
        for result in results:
            for divergence, _ in _distinct(result.verdicts, _wire_only_of):
                key = repr((divergence.path, divergence.reference, divergence.candidate))
                packets.setdefault(divergence.packet, {})[key] = divergence
        if not packets:
            continue
        lines.append(f"  {title}")
        for packet, divergences in packets.items():
            examples = list(divergences.values())
            plural = "value differs" if len(examples) == 1 else "values differ"
            lines.append(f"    {_packet(packet)}: {len(examples)} {plural} on the wire, e.g.")
            lines += [
                f"      - {_change(divergence, report)}" for divergence in examples[:WIRE_EXAMPLES]
            ]
            if len(examples) > WIRE_EXAMPLES:
                lines.append(f"      - and {len(examples) - WIRE_EXAMPLES} more")
    if not lines:
        return ""
    heading = _heading(
        "Wire-only differences (a vanilla client reads both alike; not counted in scores)"
    )
    return heading + "\n" + "\n".join(lines)


def _unsettled(report: Report) -> str:
    lines: list[str] = []
    for result in report.results:
        runs = len(result.verdicts)
        details: dict[str, int] = {}
        for verdict in result.verdicts:
            if verdict.outcome in _NOT_PLAYED:
                line = f"{_NOT_PLAYED[verdict.outcome]}: {verdict.detail}"
                details[line] = details.get(line, 0) + 1
        for line, count in details.items():
            seen_in = "" if count == runs else f" (in {count} of {runs} runs)"
            lines.append(f"  {result.scenario_id} {line}{seen_in}")
        different = sum(1 for verdict in result.verdicts if verdict.observable)
        if 0 < different < runs:
            lines.append(f"  {result.scenario_id} was different in {different} of {runs} runs")
    if not lines:
        return ""
    return _heading("Not judged, or not the same every run") + "\n" + "\n".join(lines)


def _timings(report: Report) -> str:
    reference = _collect(report, report.reference, "reference")
    candidate = _collect(report, report.candidate, "candidate")
    names = list(dict.fromkeys([*reference, *candidate]))
    reference_name, candidate_name = report.reference.name, report.candidate.name
    rows = [
        (
            "measurement",
            f"{reference_name} median",
            "p95",
            f"{candidate_name} median",
            "p95",
            "n",
        ),
    ]
    for name in names:
        ours, theirs = reference.get(name, []), candidate.get(name, [])
        rows.append((name, *_median_p95(ours), *_median_p95(theirs), _counts(ours, theirs)))
    widths = [max(len(row[column]) for row in rows) for column in range(len(rows[0]))]
    lines = [_aligned(row, widths) for row in rows] if names else ["  nothing was measured"]
    unplayed = [
        result.scenario_id
        for result in report.results
        if any(verdict.outcome in _NOT_PLAYED for verdict in result.verdicts)
    ]
    if unplayed:
        lines.append(f"  Not measured where it was not played (see above): {', '.join(unplayed)}")
    return _heading("Timings (ms)") + "\n" + "\n".join(lines)


def _aligned(row: Sequence[str], widths: Sequence[int]) -> str:
    """`row` as a table line: the first cell left-aligned, the numbers right-aligned."""
    first, *numbers = zip(row, widths, strict=True)
    cells = [first[0].ljust(first[1]), *(cell.rjust(width) for cell, width in numbers)]
    return "  " + "  ".join(cells)


def _collect(report: Report, side: SideSummary, role: str) -> dict[str, list[float]]:
    values: dict[str, list[float]] = {}
    for result in report.results:
        repetitions = result.reference if role == "reference" else result.candidate
        for measurements in repetitions:
            _add(values, measurements)
    _add(values, side.startup)
    return values


def _add(values: dict[str, list[float]], measurements: Iterable[Measurement]) -> None:
    for measurement in measurements:
        values.setdefault(measurement.name, []).append(measurement.value)


def _median_p95(values: Sequence[float]) -> tuple[str, str]:
    if not values:
        return "-", "-"
    summary = stats(values)
    return _ms(summary.median), _ms(summary.p95)


def _counts(reference: Sequence[float], candidate: Sequence[float]) -> str:
    if len(reference) == len(candidate):
        return str(len(reference))
    return f"{len(reference)}/{len(candidate)}"


def _ms(value: float) -> str:
    if value < 10:  # noqa: PLR2004 - below 10 ms, hundredths still matter
        return f"{value:.2f}"
    return f"{value:,.0f}"


def _notes(report: Report) -> str:
    if not report.notes:
        return ""
    return _heading("Notes") + "\n" + "\n".join(f"  - {note}" for note in report.notes)


def _legend(report: Report) -> str:
    candidate = report.candidate.name
    return (
        _heading("How to read this")
        + "\n"
        + f"  observable: a vanilla client would read {candidate}'s value differently from"
        " vanilla's, so a player could notice it.\n"
        + "  wire-only: the bytes differ, but a vanilla client decodes both to the same"
        " thing, so no player could notice it."
    )


def _heading(text: str) -> str:
    return f"{text}\n{'-' * len(text)}"


def _packet(name: str) -> str:
    return name.removeprefix(_MINECRAFT)


def _describe(divergence: Divergence, report: Report) -> str:
    """One observable Divergence, in plain words."""
    reference, candidate = report.reference.name, report.candidate.name
    packet = _packet(divergence.packet)
    match divergence.kind:
        case "failed":
            return f"the Candidate failed: {divergence.candidate}"
        case "missing":
            return f"{packet}: {reference} sends this packet, {candidate} does not"
        case "unexpected":
            return f"{packet}: {candidate} sends this packet, {reference} does not"
        case "bot":
            return (
                f"bot {divergence.bot!r} exchanged {divergence.reference} packets with"
                f" {reference}, {divergence.candidate} with {candidate}"
            )
        case _:
            return _field(divergence, report)


def _field(divergence: Divergence, report: Report) -> str:
    return f"{_packet(divergence.packet)} {_INTO} {_change(divergence, report)}"


def _change(divergence: Divergence, report: Report) -> str:
    where = divergence.path if divergence.path is not None else "the whole packet"
    return (
        f"{where}: {_sends(report.reference.name, divergence.reference)}, "
        f"{_sends(report.candidate.name, divergence.candidate)}"
    )


def _sends(server: str, value: object) -> str:
    if value is ABSENT:
        return f"{server} leaves it out"
    return f"{server} sends {_show(value)}"


def _show(value: object) -> str:
    if isinstance(value, bytes):
        text = value.hex()
        shown = text if len(text) <= VALUE_LIMIT else f"{text[: VALUE_LIMIT - 1]}…"
        return f"{len(value)} bytes 0x{shown}"
    try:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    except (TypeError, ValueError, RecursionError):
        text = f"a {type(value).__name__} that cannot be shown"
    if len(text) <= VALUE_LIMIT:
        return text
    return f"{text[: VALUE_LIMIT - 1]}… ({len(text)} chars)"
