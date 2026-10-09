"""Each test case of each Group passes or fails, and the passes make the score (#101)."""

from collections.abc import Mapping
from dataclasses import replace

import pytest

import mscts.compare
from mscts.compare import ABSENT, Divergence, Outcome, Verdict, compare
from mscts.group import Group
from mscts.groups import status
from mscts.report import CaseResult, GroupLine, Line, LineResult, Totals, report_lines, totals
from mscts.run import GroupError, judge
from mscts.transcript import Transcript
from tests.compare.build import GROUP, packet, transcript
from tests.test_report import _field, _listed, _report, _result, _verdict


def _compared(*names: str, group_id: str = "status/basic") -> Verdict:
    """A matching repetition that compared `names`."""
    return Verdict(group_id, Outcome.MATCH, (), test_cases=tuple(sorted(names)))


def test_each_compared_test_case_of_each_group_has_a_result_in_play_order() -> None:
    report = _report(
        _result(_compared("b", "a")),
        _result(_verdict(_field("c"), group_id="status/ping")),
    )
    assert report_lines(report) == (
        CaseResult("status/basic", "a", LineResult.PASS),
        CaseResult("status/basic", "b", LineResult.PASS),
        CaseResult("status/ping", "c", LineResult.FAIL),
    )


def test_test_cases_compared_in_different_repetitions_are_listed_once_and_sorted() -> None:
    report = _report(_result(_compared("b"), _compared("a", "b")))
    assert report_lines(report) == (
        CaseResult("status/basic", "a", LineResult.PASS),
        CaseResult("status/basic", "b", LineResult.PASS),
    )


def test_a_test_case_that_differs_in_any_repetition_fails() -> None:
    report = _report(_result(_compared("a"), _verdict(_field("a")), _compared("a")))
    assert report_lines(report) == (CaseResult("status/basic", "a", LineResult.FAIL),)


def test_a_compared_test_case_that_differs_only_in_network_traffic_passes_and_says_so() -> None:
    traffic = _listed(_field("a", traffic=True))
    mixed = _verdict(_field("b", traffic=True), replace(_field("b"), index=1))
    assert report_lines(_report(_result(traffic), _result(replace(mixed, group_id="x/y")))) == (
        CaseResult("status/basic", "a", LineResult.PASS, network_traffic_only=True),
        CaseResult("x/y", "b", LineResult.FAIL),
    )


def test_a_blocked_group_is_one_failing_line_that_was_not_tested() -> None:
    blocked = Verdict("join/basic", Outcome.BLOCKED, detail="prerequisite status/basic was not run")
    assert report_lines(_report(_result(blocked, blocked))) == (
        GroupLine(
            "join/basic",
            LineResult.NOT_TESTED,
            "Not tested: prerequisite status/basic was not run",
        ),
    )


def test_a_failed_prerequisite_fails_each_test_case_the_group_has_in_any_repetition() -> None:
    # #285, review B: vanilla's play of the Group lists its test cases; the Candidate,
    # never played, fails each, as if it had sent every value wrong.
    what = "prerequisite status/basic was mismatch"
    failed = replace(FAILED, bot="", candidate=what)
    unplayed = replace(_verdict(failed, group_id="join/basic"), test_cases=("a",))
    passed = _compared("a", "b", group_id="join/basic")

    assert report_lines(_report(_result(unplayed, passed))) == (
        CaseResult("join/basic", "a", LineResult.FAIL),
        CaseResult("join/basic", "b", LineResult.FAIL),
        GroupLine("join/basic", LineResult.FAIL, f"Candidate failed: {what}"),
    )


def test_a_blocked_verdict_fails_no_test_case() -> None:
    # Review A B1: a `blocked` Verdict was played on neither server.
    blocked = Verdict(
        "join/basic", Outcome.BLOCKED, detail="prerequisite x was not run", test_cases=("a",)
    )
    passed = _compared("a", group_id="join/basic")

    assert report_lines(_report(_result(blocked, passed))) == (
        CaseResult("join/basic", "a", LineResult.PASS),
        GroupLine("join/basic", LineResult.NOT_TESTED, "Not tested: prerequisite x was not run"),
    )


def test_an_error_group_is_one_line_left_out_of_the_score() -> None:
    error = Verdict("status/basic", Outcome.ERROR, detail="the Reference did not start")
    assert report_lines(_report(_result(error))) == (
        GroupLine("status/basic", LineResult.ERROR, "Error: the Reference did not start"),
    )


FAILED = Divergence("joiner", 0, "failed", "", None, ABSENT, "disconnected", "")
"""A Candidate failure of a whole Group: it names no test case."""


def test_a_candidate_failure_fails_its_group_and_each_of_its_test_cases() -> None:
    verdict = replace(_verdict(FAILED, group_id="join/basic"), test_cases=("a",))
    error = Verdict("join/basic", Outcome.ERROR, detail="vanilla stopped")
    blocked = Verdict("join/basic", Outcome.BLOCKED, detail="prerequisite x was not run")
    reasons = (
        "Candidate failed: disconnected; Error: vanilla stopped; "
        "Not tested: prerequisite x was not run"
    )
    assert report_lines(_report(_result(verdict, error, blocked))) == (
        CaseResult("join/basic", "a", LineResult.FAIL),
        GroupLine("join/basic", LineResult.FAIL, reasons),
    )


def test_a_candidate_failure_fails_the_test_cases_of_the_groups_other_repetitions() -> None:
    failed = _verdict(FAILED)  # no test case: the Group was not compared in this one (#262)
    report = _report(_result(_compared("a", "b"), failed, _compared("a")))
    assert report_lines(report) == (
        CaseResult("status/basic", "a", LineResult.FAIL),
        CaseResult("status/basic", "b", LineResult.FAIL),
        GroupLine("status/basic", LineResult.FAIL, "Candidate failed: disconnected"),
    )


def test_a_candidate_failure_fails_a_test_case_that_differs_only_in_network_traffic() -> None:
    traffic = replace(_verdict(_field("a", traffic=True)), test_cases=("a", "b"))
    report = _report(_result(traffic, _verdict(FAILED)))
    assert report_lines(report) == (
        CaseResult("status/basic", "a", LineResult.FAIL, network_traffic_only=False),
        CaseResult("status/basic", "b", LineResult.FAIL),
        GroupLine("status/basic", LineResult.FAIL, "Candidate failed: disconnected"),
    )


def test_a_candidate_failure_in_every_repetition_with_no_test_case_is_one_line() -> None:
    failed = _verdict(FAILED)
    assert report_lines(_report(_result(failed, failed))) == (
        GroupLine("status/basic", LineResult.FAIL, "Candidate failed: disconnected"),
    )


def test_a_group_that_was_not_tested_and_errored_is_not_tested() -> None:
    error = Verdict("join/basic", Outcome.ERROR, detail="vanilla stopped")
    blocked = Verdict("join/basic", Outcome.BLOCKED, detail="prerequisite x was not run")
    [line] = report_lines(_report(_result(error, blocked)))
    assert line.result is LineResult.NOT_TESTED


def test_a_bot_difference_fails_its_group() -> None:
    bot = Divergence("status", 0, "bot", "", None, 4, 3, "")
    [line] = report_lines(_report(_result(_verdict(bot))))
    assert line == GroupLine(
        "status/basic",
        LineResult.FAIL,
        "Bot 'status' exchanged 4 packets with the Reference, 3 with the Candidate",
    )


def test_a_bot_only_one_side_had_exchanged_no_packets_with_the_other() -> None:
    bot = Divergence("status", 0, "bot", "", None, 4, ABSENT, "")
    [line] = report_lines(_report(_result(_verdict(bot))))
    assert isinstance(line, GroupLine)
    assert line.reasons.endswith("4 packets with the Reference, 0 with the Candidate")


def test_totals_count_each_result_and_score_the_passes_among_what_was_scored() -> None:
    lines = [
        *[CaseResult("g/a", str(n), LineResult.PASS) for n in range(7)],
        CaseResult("g/a", "x", LineResult.FAIL),
        GroupLine("g/b", LineResult.NOT_TESTED, "Not tested: prerequisite x was not run"),
        GroupLine("g/c", LineResult.ERROR, "Error: vanilla stopped"),
    ]
    result = totals(lines)
    assert result == Totals(passed=7, failed=2, not_tested=1, errors=1)
    assert (result.scored, result.score) == (9, pytest.approx(7 / 9))


def test_nothing_scored_has_no_score() -> None:
    assert totals([GroupLine("g/c", LineResult.ERROR, "Error: x")]).score is None


@pytest.mark.parametrize(
    "replaced", [{}, {"a": 0}, {"a": []}], ids=["left-out", "scalar", "empty-list"]
)
def test_replacing_a_compound_field_scores_no_higher_than_sending_each_leaf_wrong(
    replaced: dict[str, object],
) -> None:
    compound = {"a": {f"k{n}": n for n in range(10)}}
    wrong = {"a": {f"k{n}": n + 1000 for n in range(10)}}

    def play(group_id: str, fields: Mapping[str, object]) -> Transcript:
        return transcript(("alice", packet("minecraft:foo", fields=fields)), group_id=group_id)

    many = {f"g{n}": n for n in range(100)}
    passing = compare(play("x/b", many), play("x/b", many), ())

    def score(fields: Mapping[str, object]) -> float:
        verdict = compare(play("x/a", compound), play("x/a", fields), ())
        result = totals(report_lines(_report(_result(passing), _result(verdict)))).score
        assert result is not None
        return result

    assert score(wrong) == pytest.approx(100 / 110)
    assert score(replaced) <= score(wrong)


def test_replacing_a_compound_of_empty_ones_scores_no_higher_than_filling_them_wrong() -> None:
    def score(reference: Mapping[str, object], *sent: Mapping[str, object]) -> float:
        many = {f"g{n}": n for n in range(100)}
        passing = transcript(("alice", packet("minecraft:bar", fields=many)), group_id="x/b")
        verdict = compare(
            transcript(("alice", packet("minecraft:foo", fields=reference)), group_id="x/a"),
            transcript(
                *(("alice", packet("minecraft:foo", fields=one)) for one in sent), group_id="x/a"
            ),
            (),
        )
        lines = report_lines(_report(_result(compare(passing, passing, ())), _result(verdict)))
        result = totals(lines).score
        assert result is not None
        return result

    nested = {"a": {"b": {}, "c": []}}
    assert score(nested, {"a": 0}) <= score(nested, {"a": {"b": 0, "c": 0}})
    empty = {"a": {}, "b": []}
    assert score(empty) <= score(empty, {"a": 0, "b": 0})


def test_the_leaves_of_a_replaced_compound_fail_and_its_siblings_do_not() -> None:
    verdict = compare(
        transcript(
            ("alice", packet("minecraft:foo", fields={"a": {"b": 1}, "ab": 2})), group_id="x/a"
        ),
        transcript(("alice", packet("minecraft:foo", fields={"a": 0, "ab": 2})), group_id="x/a"),
        (),
    )
    assert report_lines(_report(_result(verdict))) == (
        CaseResult("x/a", "foo.a", LineResult.FAIL),
        CaseResult("x/a", "foo.a.b", LineResult.FAIL),
        CaseResult("x/a", "foo.ab", LineResult.PASS),
    )


def test_a_list_replaced_by_a_scalar_fails_each_of_its_elements_test_cases() -> None:
    # Audit 2026-10-04 L4 (mutant P9): `foo.a[].b` is under `foo.a`, past a `[`.
    verdict = compare(
        transcript(
            ("alice", packet("minecraft:foo", fields={"a": [{"b": 1}], "ab": 2})), group_id="x/a"
        ),
        transcript(("alice", packet("minecraft:foo", fields={"a": 0, "ab": 2})), group_id="x/a"),
        (),
    )
    assert report_lines(_report(_result(verdict))) == (
        CaseResult("x/a", "foo.a", LineResult.FAIL),
        CaseResult("x/a", "foo.a[].b", LineResult.FAIL),
        CaseResult("x/a", "foo.ab", LineResult.PASS),
    )


LIGHT_UPDATE = packet(
    "minecraft:light_update",
    fields={
        "chunk_x": 3,
        "chunk_z": 4,
        "data": {
            "sky_light_mask": b"",
            "block_light_mask": b"",
            "empty_sky_light_mask": b"",
            "empty_block_light_mask": b"",
            "sky_light_arrays": [],
            "block_light_arrays": [],
        },
    },
)


def test_a_chunk_packet_left_out_fails_each_of_its_fields() -> None:
    # Audit 2026-10-04 L4 (mutant P4): a missing chunk packet shows `chunk 3 4`, a string, so
    # only its being `missing` fans it out to each field.
    other = packet("minecraft:set_time", fields={"game_time": 1})
    verdict = compare(
        transcript(("alice", LIGHT_UPDATE), ("alice", other)),
        transcript(("alice", other), server="pumpkin"),
        (),
    )
    [missing] = [d for d in verdict.divergences if d.kind == "missing"]
    assert missing.reference == "chunk 3 4"

    lines = [
        line for line in report_lines(_report(_result(verdict))) if isinstance(line, CaseResult)
    ]
    light = [line for line in lines if line.test_case.startswith("light_update")]
    assert len(light) > 1
    assert {line.result for line in light} == {LineResult.FAIL}


def test_a_compound_sent_in_another_format_marks_only_its_own_test_case() -> None:
    traffic = replace(_field("x.a", traffic=True), reference={"b": 1}, candidate="b")
    verdict = replace(_verdict(traffic), test_cases=("x.a", "x.a.b"))
    assert report_lines(_report(_result(verdict))) == (
        CaseResult("status/basic", "x.a", LineResult.PASS, network_traffic_only=True),
        CaseResult("status/basic", "x.a.b", LineResult.PASS),
    )


def test_leaving_a_packet_out_or_crashing_scores_no_higher_than_sending_it_wrong() -> None:
    fields = {f"f{n}": n for n in range(20)}
    wrong = {name: value + 1000 if value < 10 else value for name, value in fields.items()}

    def play(group_id: str, *sent: dict[str, int]) -> Transcript:
        return transcript(
            *(("alice", packet("minecraft:foo", fields=one)) for one in sent), group_id=group_id
        )

    many = {f"g{n}": n for n in range(100)}
    passing = compare(play("x/b", many), play("x/b", many), ())
    sent_wrong = compare(play("x/a", fields), play("x/a", wrong), ())
    left_out = compare(play("x/a", fields), play("x/a"), ())
    failed = Divergence("alice", 0, "failed", "", None, ABSENT, "EOF", "")
    crashed = replace(left_out, divergences=(failed, *left_out.divergences))

    def score(verdict: Verdict) -> float:
        result = totals(report_lines(_report(_result(passing), _result(verdict)))).score
        assert result is not None
        return result

    assert score(sent_wrong) == pytest.approx(110 / 120)
    assert score(left_out) <= score(sent_wrong)
    assert score(crashed) <= score(sent_wrong)


def test_the_fields_of_a_packet_left_out_fail() -> None:
    left_out = compare(
        transcript(
            ("alice", packet("minecraft:foo", fields={"a": 1, "b": {"c": 2}})), group_id="x/a"
        ),
        transcript(("alice", packet("minecraft:bar", fields={})), group_id="x/a"),
        (),
    )
    lines = report_lines(_report(_result(left_out)))
    assert {line.test_case: line.result for line in lines if isinstance(line, CaseResult)} == {
        "bar": LineResult.FAIL,
        "foo": LineResult.FAIL,
        "foo.a": LineResult.FAIL,
        "foo.b.c": LineResult.FAIL,
    }


def test_a_packet_the_candidate_sent_undecodable_fails_each_field_of_the_reference() -> None:
    sent = {"a": {"b": 1, "c": 2}, "d": 3}
    undecodable = packet("minecraft:foo", b"\xff")  # no fields: it did not decode
    verdict = compare(
        transcript(("alice", packet("minecraft:foo", b"\x01", fields=sent)), group_id="x/a"),
        transcript(("alice", undecodable), group_id="x/a"),
        (),
    )

    lines = report_lines(_report(_result(verdict)))
    assert {line.test_case: line.result for line in lines if isinstance(line, CaseResult)} == {
        "foo": LineResult.FAIL,
        "foo.a.b": LineResult.FAIL,
        "foo.a.c": LineResult.FAIL,
        "foo.d": LineResult.FAIL,
    }
    assert totals(lines) == Totals(passed=0, failed=4, not_tested=0, errors=0)


def test_a_packet_only_the_candidate_sent_fails_its_own_test_case_alone() -> None:
    sent = packet("minecraft:foo", b"\x01", fields={"a": 1})
    verdict = compare(
        transcript(("alice", sent), group_id="x/a"),
        transcript(("alice", sent), ("alice", sent), group_id="x/a"),
        (),
    )

    lines = report_lines(_report(_result(verdict)))
    assert {line.test_case: line.result for line in lines if isinstance(line, CaseResult)} == {
        "foo": LineResult.FAIL,
        "foo.a": LineResult.PASS,
    }


def test_failing_a_whole_group_scores_no_higher_than_sending_each_value_wrong() -> None:
    fields = {f"f{n}": n for n in range(10)}
    wrong = {name: value + 1000 for name, value in fields.items()}
    group = Group(id="x/a", run=status.basic)

    def play(group_id: str, *sent: Mapping[str, object]) -> Transcript:
        return transcript(
            *(("alice", packet("minecraft:foo", fields=one)) for one in sent), group_id=group_id
        )

    many = {f"g{n}": n for n in range(100)}
    passing = compare(play("x/b", many), play("x/b", many), ())
    reference = play("x/a", fields)

    def score(candidate: Transcript | GroupError) -> float:
        verdict = judge(group, reference, candidate)
        result = totals(report_lines(_report(_result(passing), _result(verdict)))).score
        assert result is not None
        return result

    # Every value sent right, then the Group raised: before #262, 10 of 10 passed.
    raised = GroupError(play("x/a", fields), "TimeoutError: no answer", bot="alice")
    garbage = play("x/a", {"f0": {1, 2}})  # a value the Comparison cannot take (#239)
    assert score(play("x/a", wrong)) == pytest.approx(100 / 110)
    assert score(raised) <= score(play("x/a", wrong))
    assert score(garbage) <= score(play("x/a", wrong))


STONE = {"count": 64, "item": 1, "components": {"added": [], "removed": []}}
SLOT = {"window_id": 1, "state_id": 5, "slot": 36, "slot_data": STONE}


def _slot_lines(state_id: int) -> tuple[Line, ...]:
    """A Group whose Candidate sends `state_id` and the wrong window in one slot change."""

    def play(fields: Mapping[str, object]) -> Transcript:
        return transcript(("alice", packet("minecraft:container_set_slot", fields=fields)))

    verdict = compare(play(SLOT), play({**SLOT, "window_id": 2, "state_id": state_id}), ())
    return report_lines(_report(_result(verdict)))


@pytest.mark.parametrize("state_id", [5, 9], ids=["equal", "different"])
def test_a_field_that_shows_only_network_traffic_never_counts_toward_the_score(
    state_id: int,
) -> None:
    # #330: with a different state_id, 3 of 4 became 4 of 5.
    assert totals(_slot_lines(state_id)) == Totals(passed=3, failed=1, not_tested=0, errors=0)


def test_a_test_case_a_gameplay_divergence_names_is_scored_even_if_not_listed() -> None:
    # Mutant R3 of #330: only a test case that network traffic alone names is not scored.
    mixed = (_field("b", traffic=True), replace(_field("b"), index=1))
    verdict = Verdict("status/basic", Outcome.MISMATCH, mixed, test_cases=())
    assert report_lines(_report(_result(verdict))) == (
        CaseResult("status/basic", "b", LineResult.FAIL),
    )


def test_a_test_case_no_compared_pair_names_fails_if_network_traffic_does_not_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Review A and B of #341: with the switch off, run._passed fails such a Verdict as a
    # prerequisite, so the Report fails its line too rather than leaving it out.
    monkeypatch.setattr(mscts.compare, "NETWORK_TRAFFIC_ONLY_PASSES", False)
    lines = _slot_lines(9)
    assert (
        CaseResult(GROUP, "container_set_slot.state_id", LineResult.FAIL, network_traffic_only=True)
        in lines
    )
    assert totals(lines) == Totals(passed=3, failed=2, not_tested=0, errors=0)


def test_a_candidate_failure_leaves_a_test_case_no_compared_pair_names_not_scored() -> None:
    # Review B of #341, nit 8: sending that field wrong is not scored, so failing the whole
    # Group does not score it either. Its siblings fail.
    def play(*sent: Mapping[str, object]) -> Transcript:
        return transcript(
            *(("alice", packet("minecraft:container_set_slot", fields=f)) for f in sent)
        )

    traffic = compare(play(SLOT), play({**SLOT, "state_id": 9}), ())
    crashed = replace(_verdict(FAILED, group_id=GROUP), test_cases=traffic.test_cases)
    lines = report_lines(_report(_result(traffic, crashed)))
    assert [(line.test_case, line.result) for line in lines if isinstance(line, CaseResult)] == [
        ("container_set_slot.slot", LineResult.FAIL),
        ("container_set_slot.slot_data.count", LineResult.FAIL),
        ("container_set_slot.slot_data.item", LineResult.FAIL),
        ("container_set_slot.state_id", LineResult.NOT_SCORED),
        ("container_set_slot.window_id", LineResult.FAIL),
    ]


def test_a_field_that_shows_only_network_traffic_is_listed_when_it_differs() -> None:
    assert CaseResult(
        GROUP, "container_set_slot.state_id", LineResult.NOT_SCORED, network_traffic_only=True
    ) in _slot_lines(9)
