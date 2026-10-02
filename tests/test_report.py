"""The default Report is a list of differences and the total Run time (#9)."""

from dataclasses import replace

import pytest

from mscts.compare import ABSENT, Divergence, DivergenceKind, Observability, Outcome, Verdict
from mscts.report import Report, render_text
from mscts.run import GroupResult, SideSummary
from mscts.target import TARGET


def _field(name: str, *, traffic: bool = False) -> Divergence:
    return Divergence(
        bot="status",
        index=0,
        kind="field",
        packet="minecraft:status_response",
        path=name,
        reference="reference value",
        candidate="candidate value",
        test_case=name,
        observability=Observability.NETWORK_TRAFFIC if traffic else Observability.GAMEPLAY,
    )


def _verdict(*divergences: Divergence, group_id: str = "status/basic") -> Verdict:
    return Verdict(
        group_id,
        Outcome.MISMATCH if divergences else Outcome.MATCH,
        divergences,
        test_cases=tuple(sorted({d.test_case for d in divergences if d.test_case})),
    )


def _result(*verdicts: Verdict) -> GroupResult:
    return GroupResult(verdicts[0].group_id, verdicts, (), ())


def _report(*results: GroupResult, elapsed_s: float = 41.0) -> Report:
    return Report(
        TARGET,
        SideSummary("vanilla", "26.3", ()),
        SideSummary("pumpkin", "Pumpkin 26.2", ()),
        results,
        ("--out is not implemented yet",),
        elapsed_s,
    )


def test_the_default_output_is_only_the_candidate_differences_and_total_time() -> None:
    report = _report(_result(_verdict(_field("status_response.description"))))
    assert render_text(report) == (
        "Running tests against pumpkin\n"
        "- Server list description  status_response.description\n"
        "Took 41 s\n"
    )


def test_no_differences_is_said_plainly() -> None:
    assert render_text(_report(_result(_verdict()))) == (
        "Running tests against pumpkin\nNo differences.\nTook 41 s\n"
    )


def test_the_first_line_uses_only_the_candidate_adapter_name() -> None:
    report = _report(_result(_verdict()))
    report = replace(report, candidate=SideSummary("vanilla", "26.3", ()))
    assert render_text(report) == "Running tests against vanilla\nNo differences.\nTook 41 s\n"


def test_a_network_traffic_difference_is_an_ordinary_line() -> None:
    report = _report(_result(_verdict(_field("status_response.favicon", traffic=True))))
    assert render_text(report) == (
        "Running tests against pumpkin\n- Server list icon  status_response.favicon\nTook 41 s\n"
    )


def test_each_test_case_is_listed_once_across_groups_repetitions_and_values() -> None:
    field = _field("status_response.players.max")
    other = replace(field, reference=1, candidate=2, index=3)
    text = render_text(
        _report(
            _result(_verdict(field, other), _verdict(field)),
            _result(_verdict(field, group_id="status/ping")),
        )
    )
    assert text == (
        "Running tests against pumpkin\n- Player limit  status_response.players.max\nTook 41 s\n"
    )


def test_same_test_cases_are_not_reported_as_differences() -> None:
    verdict = replace(_verdict(), test_cases=("status_response.players.max",))
    assert "No differences." in render_text(_report(_result(verdict)))


def test_an_unknown_test_case_is_reported_by_name() -> None:
    text = render_text(_report(_result(_verdict(_field("status_response.new_field")))))
    assert text == "Running tests against pumpkin\n- status_response.new_field\nTook 41 s\n"


def test_list_elements_share_one_line_without_their_values_or_indices() -> None:
    first = replace(_field("status_response.players.sample[].name"), path="players.sample[0].name")
    second = replace(first, path="players.sample[1].name", candidate="another name")
    text = render_text(_report(_result(_verdict(first, second))))
    assert text == (
        "Running tests against pumpkin\n- status_response.players.sample[].name\nTook 41 s\n"
    )


@pytest.mark.parametrize("kind", ["missing", "unexpected"])
def test_a_whole_packet_difference_keeps_its_test_case_name(kind: DivergenceKind) -> None:
    field = _field("status_response")
    field = replace(field, kind=kind, path=None)
    assert "- status_response\n" in render_text(_report(_result(_verdict(field))))


def test_groups_that_could_not_be_compared_follow_the_differences() -> None:
    different = _verdict(_field("status_response.players.max"))
    blocked = Verdict("redstone/timing", Outcome.BLOCKED, detail="needs /tick")
    error = Verdict("status/error", Outcome.ERROR, detail="the Reference did not start")
    failed = Divergence(
        "joiner",
        0,
        "failed",
        "",
        None,
        ABSENT,
        "disconnected during join",
        "",
    )
    text = render_text(
        _report(
            _result(blocked),
            _result(different),
            _result(error),
            _result(_verdict(failed, group_id="join/basic")),
        )
    )
    assert text == (
        "Running tests against pumpkin\n"
        "- Player limit  status_response.players.max\n"
        "- Not tested: needs /tick  redstone/timing\n"
        "- Error: the Reference did not start  status/error\n"
        "- Candidate failed: disconnected during join  join/basic\n"
        "Took 41 s\n"
    )


def test_uncompared_groups_do_not_claim_no_differences() -> None:
    report = _report(_result(Verdict("status/basic", Outcome.ERROR, detail="failed")))
    assert render_text(report) == (
        "Running tests against pumpkin\n- Error: failed  status/basic\nTook 41 s\n"
    )


def test_a_group_lists_distinct_failure_details_once_in_one_line() -> None:
    error = Verdict("status/basic", Outcome.ERROR, detail="first reason")
    other = replace(error, detail="second reason")
    text = render_text(_report(_result(error, error, other)))
    assert text == (
        "Running tests against pumpkin\n"
        "- Error: first reason; Error: second reason  status/basic\n"
        "Took 41 s\n"
    )


def test_a_bot_difference_without_a_test_case_still_names_its_group() -> None:
    bot = Divergence("status", 0, "bot", "", None, 4, 3, "")
    text = render_text(_report(_result(_verdict(bot))))
    assert text == (
        "Running tests against pumpkin\n"
        "- Bot 'status' exchanged 4 packets with the Reference, "
        "3 with the Candidate  status/basic\n"
        "Took 41 s\n"
    )


def test_total_time_keeps_tenths_of_a_second() -> None:
    assert render_text(_report(elapsed_s=0.25)).endswith("Took 0.2 s\n")
