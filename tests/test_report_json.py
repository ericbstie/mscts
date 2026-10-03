"""report.json holds the whole Report and reads back as the same Report (#190)."""

import json
import math
from dataclasses import replace
from uuid import UUID

import pytest

from mscts import report_json
from mscts.compare import ABSENT, Divergence, Observability, Outcome, Verdict
from mscts.measure import Measurement
from mscts.report import Report
from mscts.run import GroupResult, SideSummary
from mscts.target import TARGET


def _divergence(reference: object, candidate: object) -> Divergence:
    return Divergence(
        bot="status",
        index=3,
        kind="field",
        packet="minecraft:status_response",
        path="json_response.players.sample[0]",
        reference=reference,
        candidate=candidate,
        test_case="status_response.players.sample[]",
        observability=Observability.NETWORK_TRAFFIC,
    )


def _report(*divergences: Divergence) -> Report:
    verdict = Verdict(
        "status/basic",
        Outcome.MISMATCH,
        divergences,
        "",
        ("status_response.players.sample[]",),
    )
    blocked = Verdict("join/basic", Outcome.BLOCKED, (), "prerequisite status/basic was mismatch")
    return Report(
        TARGET,
        SideSummary("vanilla", "26.3", (Measurement("instance.startup", "ms", 20963.1),), "26.3"),
        SideSummary("pumpkin", None, (), None),
        (
            GroupResult(
                "status/basic",
                (verdict,),
                ((Measurement("status.rtt", "ms", 0.5),),),
                ((Measurement("status.rtt", "ms", 0.25),),),
                (0.125,),
            ),
            GroupResult("join/basic", (blocked,), ((),), ((),)),
        ),
        ("a note",),
        22.75,
    )


def test_a_report_reads_back_as_the_same_report() -> None:
    report = _report(_divergence("mscts", {"text": "mscts", "extra": [1, 2.5, True, None]}))

    assert report_json.loads(report_json.dumps(report)) == report


def test_report_json_carries_each_line_and_the_totals_of_the_report() -> None:
    data = json.loads(report_json.dumps(_report(_divergence("mscts", {"text": "mscts"}))))

    assert data["test_cases"] == [
        {
            "group_id": "status/basic",
            "test_case": "status_response.players.sample[]",
            "result": "pass",
            "network_traffic_only": True,
            "reasons": "",
        },
        {
            "group_id": "join/basic",
            "test_case": "",
            "result": "not tested",
            "network_traffic_only": False,
            "reasons": "Not tested: prerequisite status/basic was mismatch",
        },
    ]
    assert data["totals"] == {
        "passed": 1,
        "failed": 1,
        "not_tested": 1,
        "errors": 0,
        "scored": 2,
        "score": 0.5,
    }
    assert list(data)[3:5] == ["test_cases", "totals"], list(data)


def test_a_report_with_nothing_scored_has_a_null_score() -> None:
    report = replace(_report(), results=())

    assert json.loads(report_json.dumps(report))["totals"]["score"] is None


def test_the_lines_and_totals_are_worked_out_again_not_read_back() -> None:
    report = _report()
    data = json.loads(report_json.dumps(report))
    del data["test_cases"]
    data["totals"] = "anything"

    assert report_json.loads(json.dumps(data)) == report


def test_report_json_is_indented_json_ending_in_a_newline() -> None:
    text = report_json.dumps(_report())

    assert text.startswith('{\n  "target": {\n    "minecraft_version": "26.3",\n'), text
    assert text.endswith("\n}\n"), text


def test_values_json_cannot_hold_read_back_as_themselves() -> None:
    uuid = UUID("12345678-1234-5678-1234-567812345678")
    values = [ABSENT, b"\x00\xff", uuid, [b"\x01", {"id": uuid}], math.inf, -math.inf]
    report = _report(*(_divergence(value, value) for value in values))

    assert report_json.loads(report_json.dumps(report)) == report


def test_not_a_number_reads_back_as_not_a_number() -> None:
    report = report_json.loads(report_json.dumps(_report(_divergence(math.nan, 1.0))))

    value = report.results[0].verdicts[0].divergences[0].reference
    assert isinstance(value, float), value
    assert math.isnan(value)


@pytest.mark.parametrize("tag", ["absent", "bytes", "uuid", "float", "dict"])
def test_a_server_object_shaped_like_a_tag_reads_back_as_that_object(tag: str) -> None:
    report = _report(_divergence({tag: "ff"}, {tag: {tag: True}}))

    assert report_json.loads(report_json.dumps(report)) == report


def test_a_server_object_with_a_tag_and_other_keys_is_written_as_it_is() -> None:
    value = {"bytes": "ff", "text": "x"}
    report = _report(_divergence(value, 1))

    text = report_json.dumps(report)

    divergence = json.loads(text)["results"][0]["verdicts"][0]["divergences"][0]
    assert divergence["reference"] == value
    assert report_json.loads(text) == report


def test_a_time_json_cannot_write_is_refused() -> None:
    with pytest.raises(ValueError, match="Out of range float values are not JSON compliant"):
        report_json.dumps(replace(_report(), elapsed_s=math.inf))


def test_a_tag_spells_its_value() -> None:
    uuid = UUID("12345678-1234-5678-1234-567812345678")
    report = _report(_divergence(ABSENT, [b"\x00\xff", uuid, -math.inf, {"bytes": "x"}]))

    divergence = json.loads(report_json.dumps(report))["results"][0]["verdicts"][0]
    [written] = divergence["divergences"]

    assert written["reference"] == {"absent": True}
    assert written["candidate"] == [
        {"bytes": "00ff"},
        {"uuid": str(uuid)},
        {"float": "-inf"},
        {"dict": {"bytes": "x"}},
    ]


def test_a_value_json_cannot_spell_is_refused() -> None:
    with pytest.raises(TypeError, match="a Report value cannot be a tuple"):
        report_json.dumps(_report(_divergence((1, 2), 1)))


def test_a_value_key_that_is_not_text_is_refused() -> None:
    with pytest.raises(TypeError, match="keys are text, not int"):
        report_json.dumps(_report(_divergence({1: 2}, 1)))


_DELETE = object()
_DIVERGENCE = ("results", 0, "verdicts", 0, "divergences", 0)


def _broken(path: tuple[str | int, ...], value: object) -> str:
    """A report.json with the value at `path` replaced by `value` (or deleted)."""
    data = json.loads(report_json.dumps(_report(_divergence("a", "b"))))
    parent = data
    for step in path[:-1]:
        parent = parent[step]
    if value is _DELETE:
        del parent[path[-1]]
    else:
        parent[path[-1]] = value
    return json.dumps(data)


_MALFORMED = [
    (("target",), _DELETE, "the report has no 'target'"),
    (("target", "protocol_version"), "777", r"report\.target\.protocol_version is not an integer"),
    (("target", "java_major"), True, r"java_major is not an integer"),
    (("target", "minecraft_version"), 26, r"minecraft_version is not text"),
    (("elapsed_s",), "1", r"the report\.elapsed_s is not a number"),
    (("elapsed_s",), False, r"the report\.elapsed_s is not a number"),
    (("notes",), "a note", r"the report\.notes is not a list"),
    (("notes", 0), 1, r"the report\.notes\[0\] is not text"),
    (("reference",), [], r"the report\.reference is not an object"),
    (("reference", "version"), 26, r"the report\.reference\.version is not text"),
    (("reference", "startup", 0, "unit"), "s", r"unit is 's', not one of ms, bytes, count"),
    (("results", 0, "elapsed_s", 0), None, r"results\[0\]\.elapsed_s\[0\] is not a number"),
    (("results", 0, "reference", 0), {}, r"results\[0\]\.reference\[0\] is not a list"),
    (("results", 0, "candidate", 0, 0), 1, r"candidate\[0\]\[0\] is not an object"),
    (("results", 0, "verdicts", 0, "outcome"), "pass", r"outcome is 'pass', not one of match"),
    ((*_DIVERGENCE, "kind"), "other", r"kind is 'other', not one of bot, missing"),
    ((*_DIVERGENCE, "observability"), "wire", r"observability is 'wire', not one of gameplay"),
    ((*_DIVERGENCE, "index"), 0.5, r"divergences\[0\]\.index is not an integer"),
    ((*_DIVERGENCE, "reference"), {"absent": False}, r"reference\.absent is not true"),
    ((*_DIVERGENCE, "reference"), {"bytes": "xyz"}, r"reference\.bytes is not a bytes value"),
    ((*_DIVERGENCE, "reference"), {"bytes": 1}, r"reference\.bytes is not text"),
    ((*_DIVERGENCE, "reference"), {"uuid": "x"}, r"reference\.uuid is not a uuid value"),
    ((*_DIVERGENCE, "reference"), {"float": "1.5"}, r"reference\.float is '1\.5', not one"),
    ((*_DIVERGENCE, "reference"), {"dict": []}, r"reference\.dict is not an object"),
    ((*_DIVERGENCE, "reference"), [[{"uuid": 1}]], r"reference\[0\]\[0\]\.uuid is not text"),
    ((*_DIVERGENCE, "reference"), {"a": {"uuid": 1}}, r"reference\.a\.uuid is not text"),
]


@pytest.mark.parametrize(("path", "value", "message"), _MALFORMED)
def test_a_malformed_report_json_says_where(
    path: tuple[str | int, ...], value: object, message: str
) -> None:
    with pytest.raises(report_json.ReportJsonError, match=message):
        report_json.loads(_broken(path, value))


@pytest.mark.parametrize(
    "text",
    ["", "{", "NaN", '{"elapsed_s": Infinity}', "[" * 100_000],
    ids=["empty", "cut", "nan", "infinity", "deep"],
)
def test_text_that_is_not_json_is_a_malformed_report(text: str) -> None:
    with pytest.raises(report_json.ReportJsonError, match="not JSON"):
        report_json.loads(text)


def test_json_that_is_not_an_object_is_a_malformed_report() -> None:
    with pytest.raises(report_json.ReportJsonError, match="the report is not an object"):
        report_json.loads("[]")
