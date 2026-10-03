"""Each test case of each Group passes or fails, and the passes make the score (#101)."""

from dataclasses import replace

import pytest

from mscts.compare import ABSENT, Divergence, Outcome, Verdict, compare
from mscts.report import CaseResult, Result, Totals, case_results, totals
from mscts.transcript import Transcript
from tests.compare.build import packet, transcript
from tests.test_report import _field, _report, _result, _verdict


def _compared(*names: str, group_id: str = "status/basic") -> Verdict:
    """A matching repetition that compared `names`."""
    return Verdict(group_id, Outcome.MATCH, (), test_cases=tuple(sorted(names)))


def test_each_compared_test_case_of_each_group_has_a_result_in_play_order() -> None:
    report = _report(
        _result(_compared("b", "a")),
        _result(_verdict(_field("c"), group_id="status/ping")),
    )
    assert case_results(report) == (
        CaseResult("status/basic", "a", Result.PASS),
        CaseResult("status/basic", "b", Result.PASS),
        CaseResult("status/ping", "c", Result.FAIL),
    )


def test_test_cases_compared_in_different_repetitions_are_listed_once_and_sorted() -> None:
    report = _report(_result(_compared("b"), _compared("a", "b")))
    assert [line.test_case for line in case_results(report)] == ["a", "b"]


def test_a_test_case_that_differs_in_any_repetition_fails() -> None:
    report = _report(_result(_compared("a"), _verdict(_field("a")), _compared("a")))
    assert case_results(report) == (CaseResult("status/basic", "a", Result.FAIL),)


def test_a_test_case_that_differs_only_in_network_traffic_passes_and_says_so() -> None:
    traffic = _verdict(_field("a", traffic=True))
    mixed = _verdict(_field("b", traffic=True), replace(_field("b"), index=1))
    assert case_results(_report(_result(traffic), _result(replace(mixed, group_id="x/y")))) == (
        CaseResult("status/basic", "a", Result.PASS, network_traffic_only=True),
        CaseResult("x/y", "b", Result.FAIL),
    )


def test_a_blocked_group_is_one_failing_line_that_was_not_tested() -> None:
    blocked = Verdict(
        "join/basic", Outcome.BLOCKED, detail="prerequisite status/basic was mismatch"
    )
    assert case_results(_report(_result(blocked, blocked))) == (
        CaseResult(
            "join/basic",
            "",
            Result.NOT_TESTED,
            reasons="Not tested: prerequisite status/basic was mismatch",
        ),
    )


def test_an_error_group_is_one_line_left_out_of_the_score() -> None:
    error = Verdict("status/basic", Outcome.ERROR, detail="the Reference did not start")
    assert case_results(_report(_result(error))) == (
        CaseResult("status/basic", "", Result.ERROR, reasons="Error: the Reference did not start"),
    )


def test_a_candidate_failure_fails_its_group_besides_the_test_cases_it_compared() -> None:
    failed = Divergence("joiner", 0, "failed", "", None, ABSENT, "disconnected", "")
    verdict = replace(_verdict(failed, group_id="join/basic"), test_cases=("a",))
    error = Verdict("join/basic", Outcome.ERROR, detail="vanilla stopped")
    blocked = Verdict("join/basic", Outcome.BLOCKED, detail="needs /tick")
    reasons = "Candidate failed: disconnected; Error: vanilla stopped; Not tested: needs /tick"
    assert case_results(_report(_result(verdict, error, blocked))) == (
        CaseResult("join/basic", "a", Result.PASS),
        CaseResult("join/basic", "", Result.FAIL, reasons=reasons),
    )


def test_a_group_that_was_not_tested_and_errored_is_not_tested() -> None:
    error = Verdict("join/basic", Outcome.ERROR, detail="vanilla stopped")
    blocked = Verdict("join/basic", Outcome.BLOCKED, detail="needs /tick")
    [line] = case_results(_report(_result(error, blocked)))
    assert line.result is Result.NOT_TESTED


def test_a_bot_difference_fails_its_group() -> None:
    bot = Divergence("status", 0, "bot", "", None, 4, 3, "")
    [line] = case_results(_report(_result(_verdict(bot))))
    assert (line.test_case, line.result) == ("", Result.FAIL)


def test_totals_count_each_result_and_score_the_passes_among_what_was_scored() -> None:
    lines = [
        *[CaseResult("g/a", str(n), Result.PASS) for n in range(7)],
        CaseResult("g/a", "x", Result.FAIL),
        CaseResult("g/b", "", Result.NOT_TESTED, reasons="Not tested: needs /tick"),
        CaseResult("g/c", "", Result.ERROR, reasons="Error: vanilla stopped"),
    ]
    result = totals(lines)
    assert result == Totals(passed=7, failed=2, not_tested=1, errors=1)
    assert (result.scored, result.score) == (9, pytest.approx(7 / 9))


def test_nothing_scored_has_no_score() -> None:
    assert totals([CaseResult("g/c", "", Result.ERROR, reasons="Error: x")]).score is None


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
        result = totals(case_results(_report(_result(passing), _result(verdict)))).score
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
    lines = case_results(_report(_result(left_out)))
    assert {line.test_case: line.result for line in lines if line.test_case} == {
        "bar": Result.FAIL,
        "foo": Result.FAIL,
        "foo.a": Result.FAIL,
        "foo.b.c": Result.FAIL,
    }
