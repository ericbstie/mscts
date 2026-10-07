"""report.json: the whole Report as JSON, and the Report back from it (#190).

The file is the Report's fields, nested as in `Report`: `target`, `reference`, `candidate`,
`results`, `notes` and `elapsed_s`. After `candidate` come `lines`, each test case of each
Group and each Group's own line (#101), and their `totals` with the score. Both follow
from `results`, so `loads` ignores them. A Divergence's values are JSON where JSON can
hold them. Each other value is an object with a single tag key: `{"absent": true}` for a side
that leaves the value out, `{"bytes": "<hex>"}`, `{"uuid": "<uuid>"}`, and
`{"float": "nan"}` (or `"inf"`, `"-inf"`). An object the server sent whose only key is
one of those tags, or `dict`, is written as `{"dict": {...}}`, so it never reads back as
a tag.

A Verdict keeps at most `MAX_PER_TEST_CASE` Divergences of a test case (#254): a default Run
against Pumpkin wrote 88 MB without it, 35,000 Divergences in a Verdict, nearly all of them
the elements of one list. Each Verdict's `omitted` counts those left out.
"""

import json
import math
import typing
from collections.abc import Mapping
from typing import cast
from uuid import UUID

from mscts.compare import (
    ABSENT,
    Absent,
    Divergence,
    DivergenceKind,
    Observability,
    Outcome,
    Verdict,
)
from mscts.measure import Measurement
from mscts.report import GroupLine, Line, Report, Totals, report_lines, totals
from mscts.run import GroupResult, SideSummary
from mscts.target import Target

MAX_PER_TEST_CASE = 20
"""How many Divergences of one test case a Verdict keeps in report.json (#254, ADR-0006)."""

_TAGS = frozenset({"absent", "bytes", "uuid", "float", "dict"})
_NON_FINITE = frozenset({"nan", "inf", "-inf"})
_KINDS = tuple(map(str, typing.get_args(DivergenceKind.__value__)))
_UNITS = tuple(map(str, typing.get_args(typing.get_type_hints(Measurement)["unit"])))


class ReportJsonError(ValueError):
    """Text that is not a report.json; the message says where it differs."""


def dumps(report: Report) -> str:
    """The report.json text of `report`: indented JSON ending in a newline."""
    return json.dumps(_report(report), indent=2, ensure_ascii=False, allow_nan=False) + "\n"


def loads(text: str) -> Report:
    """The Report a report.json text holds; ReportJsonError if it holds none."""
    try:
        data = json.loads(text, parse_constant=_no_constant)
    except (ValueError, RecursionError) as error:
        msg = f"not JSON: {error}"
        raise ReportJsonError(msg) from None
    return _read_report(_Object.of(data, "the report"))


def _no_constant(name: str) -> object:
    msg = f"{name} is not a JSON value"
    raise ValueError(msg)


def _report(report: Report) -> dict[str, object]:
    target = report.target
    lines = report_lines(report)
    return {
        "target": {
            "minecraft_version": target.minecraft_version,
            "protocol_version": target.protocol_version,
            "java_major": target.java_major,
        },
        "reference": _side(report.reference),
        "candidate": _side(report.candidate),
        "lines": [_line(line) for line in lines],
        "totals": _totals(totals(lines)),
        "results": [_result(result) for result in report.results],
        "notes": list(report.notes),
        "elapsed_s": report.elapsed_s,
    }


def _line(line: Line) -> dict[str, object]:
    if isinstance(line, GroupLine):
        return {"group_id": line.group_id, "result": str(line.result), "reasons": line.reasons}
    return {
        "group_id": line.group_id,
        "test_case": line.test_case,
        "result": str(line.result),
        "network_traffic_only": line.network_traffic_only,
    }


def _totals(counts: Totals) -> dict[str, object]:
    return {
        "passed": counts.passed,
        "failed": counts.failed,
        "not_tested": counts.not_tested,
        "errors": counts.errors,
        "scored": counts.scored,
        "score": counts.score,
    }


def _side(side: SideSummary) -> dict[str, object]:
    return {
        "name": side.name,
        "version": side.version,
        "startup": _measurements(side.startup),
        "installed_version": side.installed_version,
    }


def _measurements(measurements: tuple[Measurement, ...]) -> list[dict[str, object]]:
    return [{"name": m.name, "unit": m.unit, "value": m.value} for m in measurements]


def _result(result: GroupResult) -> dict[str, object]:
    return {
        "group_id": result.group_id,
        "verdicts": [_verdict(verdict) for verdict in result.verdicts],
        "reference": [_measurements(play) for play in result.reference],
        "candidate": [_measurements(play) for play in result.candidate],
        "elapsed_s": list(result.elapsed_s),
    }


def _verdict(verdict: Verdict) -> dict[str, object]:
    stored = _stored(verdict.divergences)
    return {
        "group_id": verdict.group_id,
        "outcome": verdict.outcome.value,
        "divergences": [_divergence(divergence) for divergence in stored],
        "omitted": verdict.omitted + len(verdict.divergences) - len(stored),
        "detail": verdict.detail,
        "test_cases": list(verdict.test_cases),
    }


def _stored(divergences: tuple[Divergence, ...]) -> tuple[Divergence, ...]:
    """The Divergences report.json stores: all but the surplus of a test case (#254).

    The first `MAX_PER_TEST_CASE` of each test case stay, in order. Past them a Divergence
    stays only if it is the first of its test case with its kind, observability, kind of
    value (a list or mapping, which a replaced value fans out over its leaves) and whether
    it is a whole Packet's (a `field` Divergence with no path, which fans out over its
    fields). That is all the Report's lines read from a Divergence, so they and the totals
    come out the same. A Divergence of no test case is a Group's own difference and always
    stays.
    """
    seen: dict[str, int] = {}
    shown: set[tuple[str, str, Observability, bool, bool]] = set()
    stored: list[Divergence] = []
    for divergence in divergences:
        case = divergence.test_case
        way = (
            case,
            divergence.kind,
            divergence.observability,
            _holds_values(divergence),
            _is_whole_packet(divergence),
        )
        seen[case] = seen.get(case, 0) + 1
        if not case or seen[case] <= MAX_PER_TEST_CASE or way not in shown:
            stored.append(divergence)
        shown.add(way)
    return tuple(stored)


def _holds_values(divergence: Divergence) -> bool:
    return isinstance(divergence.reference, dict | list)


def _is_whole_packet(divergence: Divergence) -> bool:
    return divergence.kind == "field" and divergence.path is None


def _divergence(divergence: Divergence) -> dict[str, object]:
    return {
        "bot": divergence.bot,
        "index": divergence.index,
        "kind": divergence.kind,
        "packet": divergence.packet,
        "path": divergence.path,
        "reference": _value(divergence.reference),
        "candidate": _value(divergence.candidate),
        "test_case": divergence.test_case,
        "observability": divergence.observability.value,
    }


def _value(value: object) -> object:
    """`value` as JSON, tagging what JSON cannot hold."""
    tagged = _tagged(value)
    if tagged is not None:
        return tagged
    if isinstance(value, list):
        return [_value(item) for item in cast("list[object]", value)]
    if isinstance(value, dict):
        return _dict(cast("dict[object, object]", value))
    if value is None or isinstance(value, bool | int | float | str):
        return value
    msg = f"a Report value cannot be a {type(value).__name__}"
    raise TypeError(msg)


def _tagged(value: object) -> dict[str, object] | None:
    """The tagged object that stands for `value`, or None if JSON holds it as it is."""
    match value:
        case Absent():
            return {"absent": True}
        case float() if not math.isfinite(value):
            return {"float": repr(value)}
        case bytes():
            return {"bytes": value.hex()}
        case UUID():
            return {"uuid": str(value)}
    return None


def _dict(value: dict[object, object]) -> dict[str, object]:
    written: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            msg = f"a Report value's keys are text, not {type(key).__name__}"
            raise TypeError(msg)
        written[key] = _value(item)
    return {"dict": written} if written.keys() & _TAGS and len(written) == 1 else written


class _Object:
    """A JSON object read from report.json, and where it is, for error messages."""

    def __init__(self, data: Mapping[str, object], where: str) -> None:
        self._data = data
        self._where = where

    @classmethod
    def of(cls, data: object, where: str) -> "_Object":
        if not isinstance(data, dict):
            msg = f"{where} is not an object"
            raise ReportJsonError(msg)
        return cls(cast("dict[str, object]", data), where)

    def entries(self) -> Mapping[str, object]:
        return self._data

    def raw(self, key: str) -> object:
        if key not in self._data:
            msg = f"{self._where} has no {key!r}"
            raise ReportJsonError(msg)
        return self._data[key]

    def text(self, key: str) -> str:
        return _typed(self.raw(key), str, f"{self._where}.{key}")

    def maybe_text(self, key: str) -> str | None:
        value = self.raw(key)
        return None if value is None else _typed(value, str, f"{self._where}.{key}")

    def count(self, key: str, *, missing: int) -> int:
        """The non-negative integer at `key`, or `missing` if the object has no such key."""
        if key not in self._data:
            return missing
        value = self.integer(key)
        if value < 0:
            msg = f"{self._where}.{key} is {value}, not 0 or more"
            raise ReportJsonError(msg)
        return value

    def integer(self, key: str) -> int:
        value = self.raw(key)
        if isinstance(value, bool) or not isinstance(value, int):
            msg = f"{self._where}.{key} is not an integer"
            raise ReportJsonError(msg)
        return value

    def number(self, key: str) -> float:
        return _number(self.raw(key), f"{self._where}.{key}")

    def choice(self, key: str, choices: tuple[str, ...]) -> str:
        value = self.text(key)
        if value not in choices:
            msg = f"{self._where}.{key} is {value!r}, not one of {', '.join(choices)}"
            raise ReportJsonError(msg)
        return value

    def items(self, key: str) -> list[tuple[object, str]]:
        return _items(self.raw(key), f"{self._where}.{key}")

    def objects(self, key: str) -> list["_Object"]:
        return [_Object.of(item, where) for item, where in self.items(key)]

    def texts(self, key: str) -> tuple[str, ...]:
        return tuple(_typed(item, str, where) for item, where in self.items(key))

    def numbers(self, key: str) -> tuple[float, ...]:
        return tuple(_number(item, where) for item, where in self.items(key))

    def value(self, key: str) -> object:
        return _read_value(self.raw(key), f"{self._where}.{key}")

    def object(self, key: str) -> "_Object":
        return _Object.of(self.raw(key), f"{self._where}.{key}")


def _typed[T](value: object, kind: type[T], where: str) -> T:
    if not isinstance(value, kind):
        msg = f"{where} is not {_KIND_NAMES.get(kind, kind.__name__)}"
        raise ReportJsonError(msg)
    return value


_KIND_NAMES: Mapping[type, str] = {str: "text", list: "a list"}


def _number(value: object, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        msg = f"{where} is not a number"
        raise ReportJsonError(msg)
    return float(value)


def _read_report(data: _Object) -> Report:
    target = data.object("target")
    return Report(
        Target(
            target.text("minecraft_version"),
            target.integer("protocol_version"),
            target.integer("java_major"),
        ),
        _read_side(data.object("reference")),
        _read_side(data.object("candidate")),
        tuple(_read_result(result) for result in data.objects("results")),
        data.texts("notes"),
        data.number("elapsed_s"),
    )


def _read_side(data: _Object) -> SideSummary:
    return SideSummary(
        data.text("name"),
        data.maybe_text("version"),
        _read_measurements(data, "startup"),
        data.maybe_text("installed_version"),
    )


def _read_measurements(data: _Object, key: str) -> tuple[Measurement, ...]:
    return tuple(_read_measurement(item) for item in data.objects(key))


def _read_measurement(data: _Object) -> Measurement:
    unit = cast("typing.Literal['ms', 'bytes', 'count']", data.choice("unit", _UNITS))
    return Measurement(data.text("name"), unit, data.number("value"))


def _read_result(data: _Object) -> GroupResult:
    return GroupResult(
        data.text("group_id"),
        tuple(_read_verdict(verdict) for verdict in data.objects("verdicts")),
        _read_plays(data, "reference"),
        _read_plays(data, "candidate"),
        data.numbers("elapsed_s"),
    )


def _read_plays(data: _Object, key: str) -> tuple[tuple[Measurement, ...], ...]:
    return tuple(
        tuple(_read_measurement(_Object.of(item, where)) for item, where in _items(play, where))
        for play, where in data.items(key)
    )


def _items(value: object, where: str) -> list[tuple[object, str]]:
    values = _typed(value, list, where)
    return [(item, f"{where}[{index}]") for index, item in enumerate(values)]


def _read_verdict(data: _Object) -> Verdict:
    return Verdict(
        data.text("group_id"),
        Outcome(data.choice("outcome", tuple(Outcome))),
        tuple(_read_divergence(divergence) for divergence in data.objects("divergences")),
        data.text("detail"),
        data.texts("test_cases"),
        # A report.json from before #254 kept every Divergence, so it left out none.
        data.count("omitted", missing=0),
    )


def _read_divergence(data: _Object) -> Divergence:
    return Divergence(
        bot=data.text("bot"),
        index=data.integer("index"),
        kind=cast("DivergenceKind", data.choice("kind", _KINDS)),
        packet=data.text("packet"),
        path=data.maybe_text("path"),
        reference=data.value("reference"),
        candidate=data.value("candidate"),
        test_case=data.text("test_case"),
        observability=Observability(data.choice("observability", tuple(Observability))),
    )


def _read_value(value: object, where: str) -> object:
    """The value `_value` wrote as `value`."""
    if isinstance(value, list):
        return [_read_value(item, item_where) for item, item_where in _items(value, where)]
    if not isinstance(value, dict):
        return value
    entries = cast("dict[str, object]", value)
    if len(entries) == 1 and entries.keys() & _TAGS:
        [(tag, inner)] = entries.items()
        return _read_tag(tag, inner, f"{where}.{tag}")
    return _read_entries(entries, where)


def _read_entries(entries: Mapping[str, object], where: str) -> dict[str, object]:
    return {key: _read_value(item, f"{where}.{key}") for key, item in entries.items()}


def _read_tag(tag: str, inner: object, where: str) -> object:
    """The value a tagged object stands for."""
    if tag == "absent":
        if inner is not True:
            msg = f"{where} is not true"
            raise ReportJsonError(msg)
        return ABSENT
    if tag == "dict":
        return _read_entries(_Object.of(inner, where).entries(), where)
    return _read_text_tag(tag, _typed(inner, str, where), where)


def _read_text_tag(tag: str, text: str, where: str) -> object:
    """The value of a tag whose value is text: bytes, a UUID or a float JSON cannot hold."""
    try:
        if tag == "bytes":
            return bytes.fromhex(text)
        if tag == "uuid":
            return UUID(text)
    except ValueError:
        msg = f"{where} is not a {tag} value: {text!r}"
        raise ReportJsonError(msg) from None
    if text not in _NON_FINITE:
        msg = f"{where} is {text!r}, not one of {', '.join(sorted(_NON_FINITE))}"
        raise ReportJsonError(msg)
    return float(text)
