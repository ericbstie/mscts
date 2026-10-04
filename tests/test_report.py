"""The default Report: a line per test case, then totals, score and Run time (#9, #101)."""

import re
from dataclasses import replace
from uuid import UUID

import pytest

import mscts.compare
from mscts.compare import (
    ABSENT,
    TICK_PATH,
    Divergence,
    DivergenceKind,
    Observability,
    Outcome,
    Verdict,
)
from mscts.report import LineResult, Report, render_markdown, render_text, report_lines
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


FAILED_ONE = "0 passed, 1 failed\nScore: 0% (0 of 1 test case passes)\nTook 41 s\n"
PASSED_ONE = "1 passed, 0 failed\nScore: 100% (1 of 1 test case passes)\nTook 41 s\n"


def _compared(*names: str, group_id: str = "status/basic") -> Verdict:
    return Verdict(group_id, Outcome.MATCH, (), test_cases=names)


def test_the_default_output_is_one_line_per_test_case_then_totals_and_time() -> None:
    report = _report(
        _result(
            replace(
                _verdict(_field("status_response.description")),
                test_cases=("status_response.description", "status_response.players.max"),
            )
        )
    )
    assert render_text(report) == (
        "Running tests against pumpkin\n"
        "✗ status/basic/status_response.description Server list description\n"
        "✓ status/basic/status_response.players.max Player limit\n"
        "1 passed, 1 failed\n"
        "Score: 50% (1 of 2 test cases pass)\n"
        "Took 41 s\n"
    )


def test_a_run_without_differences_scores_100_percent() -> None:
    report = _report(_result(_compared("status_response.players.max")))
    assert render_text(report) == (
        "Running tests against pumpkin\n"
        "✓ status/basic/status_response.players.max Player limit\n" + PASSED_ONE
    )


def test_the_first_line_uses_only_the_candidate_adapter_name() -> None:
    report = _report(_result(_verdict()))
    report = replace(report, candidate=SideSummary("vanilla", "26.3", ()))
    assert render_text(report).startswith("Running tests against vanilla\n")


def test_a_network_traffic_difference_passes_and_says_so() -> None:
    report = _report(_result(_verdict(_field("status_response.favicon", traffic=True))))
    assert render_text(report) == (
        "Running tests against pumpkin\n"
        "✓ status/basic/status_response.favicon Server list icon (network traffic only)\n"
        + PASSED_ONE
    )


def test_a_network_traffic_difference_fails_if_network_traffic_does_not_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The switch lives with Verdict, where run.blocked reads it too (#221).
    monkeypatch.setattr(mscts.compare, "NETWORK_TRAFFIC_ONLY_PASSES", False)
    report = _report(_result(_verdict(_field("status_response.favicon", traffic=True))))
    lines = report_lines(report)
    assert [line.result for line in lines] == [LineResult.FAIL], lines


def test_each_test_case_is_listed_once_per_group_across_repetitions_and_values() -> None:
    field = _field("status_response.players.max")
    other = replace(field, reference=1, candidate=2, index=3)
    text = render_text(
        _report(
            _result(_verdict(field, other), _verdict(field)),
            _result(_verdict(field, group_id="status/ping")),
        )
    )
    assert text == (
        "Running tests against pumpkin\n"
        "✗ status/basic/status_response.players.max Player limit\n"
        "✗ status/ping/status_response.players.max Player limit\n"
        "0 passed, 2 failed\n"
        "Score: 0% (0 of 2 test cases pass)\n"
        "Took 41 s\n"
    )


def test_an_unknown_test_case_is_listed_by_name() -> None:
    text = render_text(_report(_result(_verdict(_field("status_response.new_field")))))
    assert text == (
        "Running tests against pumpkin\n✗ status/basic/status_response.new_field\n" + FAILED_ONE
    )


def test_list_elements_share_one_line_without_their_values_or_indices() -> None:
    first = replace(_field("hurt_animation.entity_id"), path="entity_id")
    second = replace(first, path="entity_id", candidate="another name")
    text = render_text(_report(_result(_verdict(first, second))))
    assert text == (
        "Running tests against pumpkin\n✗ status/basic/hurt_animation.entity_id\n" + FAILED_ONE
    )


@pytest.mark.parametrize("kind", ["missing", "unexpected"])
def test_a_whole_packet_difference_keeps_its_test_case_name(kind: DivergenceKind) -> None:
    field = _field("status_response")
    field = replace(field, kind=kind, path=None)
    assert "✗ status/basic/status_response\n" in render_text(_report(_result(_verdict(field))))


def test_a_group_without_test_cases_to_list_has_one_line_with_its_reasons() -> None:
    different = _verdict(_field("status_response.players.max"))
    blocked = Verdict("redstone/timing", Outcome.BLOCKED, detail="needs /tick")
    error = Verdict("status/error", Outcome.ERROR, detail="the Reference did not start")
    failed = Divergence("joiner", 0, "failed", "", None, ABSENT, "disconnected during join", "")
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
        "✗ redstone/timing Not tested: needs /tick\n"
        "✗ status/basic/status_response.players.max Player limit\n"
        "! status/error Error: the Reference did not start\n"
        "✗ join/basic Candidate failed: disconnected during join\n"
        "0 passed, 3 failed (1 not tested), 1 error (not scored)\n"
        "Score: 0% (0 of 3 test cases pass)\n"
        "Took 41 s\n"
    )


def test_a_report_with_nothing_scored_has_no_score() -> None:
    report = _report(_result(Verdict("status/basic", Outcome.ERROR, detail="failed")))
    assert render_text(report) == (
        "Running tests against pumpkin\n"
        "! status/basic Error: failed\n"
        "0 passed, 0 failed, 1 error (not scored)\n"
        "Score: none (no test case was scored)\n"
        "Took 41 s\n"
    )


def test_counts_of_more_than_one_use_plurals_and_the_score_is_rounded_down() -> None:
    errors = [_result(Verdict(f"status/e{n}", Outcome.ERROR, detail="failed")) for n in range(2)]
    report = _report(_result(_compared(*"abcdefg"), _verdict(_field("x"), _field("y"))), *errors)
    text = render_text(report)
    assert "\n7 passed, 2 failed, 2 errors (not scored)\n" in text, text
    assert "\nScore: 77.7% (7 of 9 test cases pass)\n" in text, text


def test_a_group_lists_distinct_failure_details_once_in_one_line() -> None:
    error = Verdict("status/basic", Outcome.ERROR, detail="first reason")
    other = replace(error, detail="second reason")
    text = render_text(_report(_result(error, error, other)))
    assert "! status/basic Error: first reason; Error: second reason\n" in text, text


def test_a_bot_difference_without_a_test_case_still_names_its_group() -> None:
    bot = Divergence("status", 0, "bot", "", None, 4, 3, "")
    text = render_text(_report(_result(_verdict(bot))))
    assert text == (
        "Running tests against pumpkin\n"
        "✗ status/basic Bot 'status' exchanged 4 packets with the Reference, "
        "3 with the Candidate\n" + FAILED_ONE
    )


def test_total_time_keeps_tenths_of_a_second() -> None:
    assert render_text(_report(elapsed_s=0.25)).endswith("Took 0.2 s\n")


def test_verbose_header_uses_installed_versions_instead_of_status_claims() -> None:
    report = _report(_result(_verdict(_field("status_response.description"))))
    report = replace(
        report,
        reference=replace(report.reference, installed_version="26.3"),
        candidate=replace(report.candidate, installed_version="nightly-abc"),
    )
    assert render_text(report, verbose=True) == (
        "Running tests against pumpkin\n"
        "  Reference    vanilla 26.3\n"
        "  Candidate    pumpkin nightly-abc\n"
        "  Target       Minecraft 26.3 (protocol 777)\n"
        "  Repetitions  1 of each group\n"
        "✗ status/basic/status_response.description Server list description\n"
        '  vanilla sends "reference value", pumpkin sends "candidate value"\n'
        "Group times\n"
        "  status/basic not recorded\n" + FAILED_ONE
    )


def test_verbose_values_are_under_their_case_and_keep_distinct_values() -> None:
    field = replace(
        _field("status_response.description"), reference="mscts", candidate={"text": "mscts"}
    )
    other = replace(field, candidate={"text": "other"})
    report = _report(_result(_verdict(field), _verdict(field, replace(field, index=3), other)))
    text = render_text(report, verbose=True)
    assert text.count("✗ status/basic/status_response.description Server list description\n") == 1
    assert text.count('  vanilla sends "mscts", pumpkin sends {"text": "mscts"}\n') == 1
    assert 'pumpkin sends {"text": "other"}\n' in text, text


def test_verbose_values_belong_to_their_own_group() -> None:
    field = _field("status_response.players.max")
    other = replace(field, candidate="other value")
    report = _report(_result(_verdict(field)), _result(_verdict(other, group_id="status/ping")))
    text = render_text(report, verbose=True)
    assert (
        "✗ status/ping/status_response.players.max Player limit\n"
        '  vanilla sends "reference value", pumpkin sends "other value"\n'
        "Group times\n"
    ) in text, text


def test_verbose_shows_the_values_of_a_network_traffic_difference() -> None:
    report = _report(_result(_verdict(_field("status_response.favicon", traffic=True))))
    assert (
        "(network traffic only)\n"
        '  vanilla sends "reference value", pumpkin sends "candidate value"\n'
    ) in render_text(report, verbose=True)


def test_verbose_preserves_absent_null_and_bytes_without_inventing_values() -> None:
    missing = replace(_field("new.field"), reference=ABSENT, candidate=None)
    payload = replace(_field("new.payload"), reference=b"\x00\xff", candidate=b"\x01")
    text = render_text(_report(_result(_verdict(missing, payload))), verbose=True)
    assert "/new.field\n  vanilla leaves it out, pumpkin sends null\n" in text, text
    assert "/new.payload\n  vanilla sends bytes 00ff, pumpkin sends bytes 01\n" in text, text


def test_verbose_list_values_keep_the_element_path() -> None:
    field = replace(_field("list[].name"), path="list[2].name")
    assert '  list[2].name: vanilla sends "reference value"' in render_text(
        _report(_result(_verdict(field))), verbose=True
    )


def test_verbose_group_times_total_all_repetitions_and_mark_blocked_groups() -> None:
    played = replace(_result(_verdict(), _verdict()), elapsed_s=(0.4, 0.6))
    blocked = _result(Verdict("join/basic", Outcome.BLOCKED, detail="needs /tick"))
    text = render_text(_report(played, blocked), verbose=True)
    assert "Group times\n  status/basic 1 s\n  join/basic not played\n" in text, text
    assert "Timings (ms)" not in text
    assert "Notes" not in text
    assert "How to read this" not in text


def test_default_output_leaves_group_times_to_verbose() -> None:
    result = replace(_result(_compared("a")), elapsed_s=(0.25,))
    assert "Group times" not in render_text(_report(result))


def test_verbose_renders_uuid_and_nested_binary_values() -> None:
    value = {"id": UUID("12345678-1234-5678-1234-567812345678"), "data": [b"\x00\xff"]}
    field = replace(_field("new.record"), reference=value, candidate=ABSENT)
    text = render_text(_report(_result(_verdict(field))), verbose=True)
    assert '"data": [{"bytes": "00ff"}]' in text, text
    assert '"id": "12345678-1234-5678-1234-567812345678"' in text, text


BUILT = SideSummary("pumpkin", "26.3", (), "nightly 4426d11 (sha256 b8382a8a…)")


def test_the_default_output_names_the_candidate_s_exact_build() -> None:
    report = replace(_report(_result(_compared("a"))), candidate=BUILT)
    assert render_text(report) == (
        "Running tests against pumpkin\n"
        "Candidate: pumpkin nightly 4426d11 (sha256 b8382a8a…)\n"
        "✓ status/basic/a\n" + PASSED_ONE
    )


def test_the_verbose_output_names_the_candidate_s_build_once() -> None:
    report = replace(_report(_result(_verdict())), candidate=BUILT)
    text = render_text(report, verbose=True)
    assert text.count("nightly 4426d11") == 1, text
    assert "  Candidate    pumpkin nightly 4426d11 (sha256 b8382a8a…)\n" in text, text


def test_markdown_names_the_candidate_s_exact_build_under_the_heading() -> None:
    report = replace(_report(_result(_compared("a"))), candidate=BUILT)
    assert render_markdown(report) == (
        "# Running tests against pumpkin\n"
        "\n"
        "Candidate: pumpkin nightly 4426d11 (sha256 b8382a8a…)\n"
        "\n"
        "- ✓ `status/basic/a`\n"
        "\n"
        "1 passed, 0 failed\\\n"
        "Score: 100% (1 of 1 test case passes)\\\n"
        "Took 41 s\n"
    )


def test_markdown_is_the_default_report_with_a_heading_and_names_as_code() -> None:
    report = _report(
        _result(_verdict(_field("status_response.description"), _field("new.field", traffic=True))),
        _result(Verdict("join/basic", Outcome.BLOCKED, detail="needs /tick")),
    )
    assert render_markdown(report) == (
        "# Running tests against pumpkin\n"
        "\n"
        "- ✓ `status/basic/new.field` (network traffic only)\n"
        "- ✗ `status/basic/status_response.description` Server list description\n"
        "- ✗ `join/basic` Not tested: needs /tick\n"
        "\n"
        "1 passed, 2 failed (1 not tested)\\\n"
        "Score: 33.3% (1 of 3 test cases pass)\\\n"
        "Took 41 s\n"
    )


def test_markdown_of_a_run_with_no_groups_has_no_list() -> None:
    assert render_markdown(_report()) == (
        "# Running tests against pumpkin\n"
        "\n"
        "0 passed, 0 failed\\\n"
        "Score: none (no test case was scored)\\\n"
        "Took 41 s\n"
    )


def test_verbose_markdown_keeps_the_header_values_and_group_times() -> None:
    field = replace(_field("list[].name"), path="list[2].name", candidate=ABSENT)
    report = _report(_result(_verdict(field)))
    report = replace(report, candidate=replace(report.candidate, installed_version="nightly-abc"))
    assert render_markdown(report, verbose=True) == (
        "# Running tests against pumpkin\n"
        "\n"
        "Reference: vanilla (installed version unknown)\\\n"
        "Candidate: pumpkin nightly-abc\\\n"
        "Target: Minecraft 26.3 (protocol 777)\\\n"
        "Repetitions: 1 of each group\n"
        "\n"
        "- ✗ `status/basic/list[].name`\n"
        '  - `list[2].name`: vanilla sends `"reference value"`, pumpkin leaves it out\n'
        "\n"
        "## Group times\n"
        "\n"
        "- status/basic not recorded\n"
        "\n"
        "0 passed, 1 failed\\\n"
        "Score: 0% (0 of 1 test case passes)\\\n"
        "Took 41 s\n"
    )


def test_markdown_shows_server_text_as_it_is() -> None:
    field = replace(_field("new.field"), reference="`a``b`", candidate=b"")
    failed = Divergence("joiner", 0, "failed", "", None, ABSENT, "closed: <b>*now*</b> [x]_\\", "")
    report = _report(_result(_verdict(field)), _result(_verdict(failed, group_id="join/basic")))
    text = render_markdown(report, verbose=True)
    assert '  - vanilla sends ```"`a``b`"```, pumpkin sends bytes ``\n' in text, text
    assert (
        "- ✗ `join/basic` Candidate failed: closed: \\<b\\>\\*now\\*\\</b\\> \\[x\\]\\_\\\\\n"
        in text
    ), text


def test_markdown_shows_a_line_break_in_server_text_without_breaking_the_line() -> None:
    forged = "x\n\n# pumpkin passes\r\nScore: 100%"
    failed = Divergence("joiner", 0, "failed", "", None, ABSENT, forged, "")
    text = render_markdown(_report(_result(_verdict(failed, group_id="join/basic"))))
    assert text == (
        "# Running tests against pumpkin\n"
        "\n"
        "- ✗ `join/basic` Candidate failed: x\\\\n\\\\n# pumpkin passes\\\\r\\\\nScore: 100%\n"
        "\n" + FAILED_ONE.replace("\nS", "\\\nS").replace("\nT", "\\\nT")
    )


@pytest.mark.parametrize(
    ("path", "code"),
    [
        ("`p[0]`", "`` `p[0]` ``"),
        ("p[0]`", "`` p[0]` ``"),
        (" p[0] ", "`  p[0]  `"),
        ("p[0]", "`p[0]`"),
    ],
    ids=["backticks", "trailing-backtick", "spaces", "plain"],
)
def test_markdown_code_keeps_its_edges(path: str, code: str) -> None:
    field = replace(_field("p[]"), path=path)
    text = render_markdown(_report(_result(_verdict(field))), verbose=True)
    assert f"  - {code}: vanilla sends" in text, text


def test_colour_marks_a_pass_green_a_failure_red_and_an_error_yellow() -> None:
    error = Verdict("status/error", Outcome.ERROR, detail="failed")
    report = _report(
        _result(_compared("a")),
        _result(_verdict(_field("b"), group_id="status/ping")),
        _result(error),
    )
    text = render_text(report, color=True)
    assert "\x1b[32m✓\x1b[0m status/basic/a\n" in text, text
    assert "\x1b[31m✗\x1b[0m status/ping/b\n" in text, text
    assert "\x1b[33m!\x1b[0m status/error Error: failed\n" in text, text
    assert re.sub("\x1b\\[[0-9]+m", "", text) == render_text(report)


def test_the_report_has_no_colour_unless_asked() -> None:
    report = _report(_result(_compared("a")), _result(_verdict(_field("b"))))
    assert "\x1b" not in render_text(report)
    assert "\x1b" not in render_markdown(report)


def test_verbose_shows_the_tick_each_server_sent_a_packet_on() -> None:
    # #23: a tick-exact Group's packet sent on another tick.
    late = replace(
        _field("block_update"),
        packet="minecraft:block_update",
        path=TICK_PATH,
        reference=1,
        candidate=2,
    )
    text = render_text(_report(_result(_verdict(late))), verbose=True)
    assert "Single block change\n  (tick): vanilla sends 1, pumpkin sends 2\n" in text, text
