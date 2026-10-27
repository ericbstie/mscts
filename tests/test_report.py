"""The default Report: a line per test case, then totals, score and Run time (#9, #101)."""

import re
from dataclasses import replace
from uuid import UUID

import pytest
from support.report_builders import (
    divergent_field,
    group_result,
    listed_verdict,
    report_of,
    report_verdict,
)

import mscts.compare
from mscts.compare import (
    ABSENT,
    TICK_PATH,
    Divergence,
    DivergenceKind,
    Outcome,
    Verdict,
)
from mscts.report import LineResult, Report, render_markdown, render_text, report_lines
from mscts.run import Restart, SideSummary
from mscts.stats import Difference, Shares, Spread, Summary

FAILED_ONE = "0 passed, 1 failed. (0%)\nTook 41 s\n"
PASSED_ONE = "1 passed, 0 failed. (100%)\nTook 41 s\n"


def _compared(*names: str, group_id: str = "status/basic") -> Verdict:
    return Verdict(group_id, Outcome.MATCH, (), test_cases=names)


def test_the_default_output_is_one_line_per_test_case_then_totals_and_time() -> None:
    report = report_of(
        group_result(
            replace(
                report_verdict(divergent_field("status_response.description")),
                test_cases=("status_response.description", "status_response.players.max"),
            )
        )
    )
    assert render_text(report) == (
        "Running tests against pumpkin\n"
        "✗ status/basic/status_response.description\n"
        "✓ status/basic/status_response.players.max\n"
        "1 passed, 1 failed. (50%)\n"
        "Took 41 s\n"
    )


def test_a_run_without_differences_scores_100_percent() -> None:
    report = report_of(group_result(_compared("status_response.players.max")))
    assert render_text(report) == (
        "Running tests against pumpkin\n✓ status/basic/status_response.players.max\n" + PASSED_ONE
    )


def test_the_first_line_uses_only_the_candidate_adapter_name() -> None:
    report = report_of(group_result(report_verdict()))
    report = replace(report, candidate=SideSummary("vanilla", "26.3", ()))
    assert render_text(report).startswith("Running tests against vanilla\n")


def test_a_compared_test_case_that_differs_only_in_network_traffic_passes_and_says_so() -> None:
    report = report_of(
        group_result(listed_verdict(divergent_field("status_response.favicon", traffic=True)))
    )
    assert render_text(report) == (
        "Running tests against pumpkin\n"
        "✓ status/basic/status_response.favicon (network traffic only)\n" + PASSED_ONE
    )


def test_a_network_traffic_difference_the_comparison_did_not_compare_is_not_scored() -> None:
    # #330: a field the canonical form leaves out is named only where the sides differ.
    traffic = replace(divergent_field("container_set_slot.state_id", traffic=True), path="state_id")
    verdict = report_verdict(traffic, divergent_field("container_set_slot.window_id"))
    assert render_text(report_of(group_result(verdict))) == (
        "Running tests against pumpkin\n"
        "· status/basic/container_set_slot.state_id (network traffic only, not scored)\n"
        "✗ status/basic/container_set_slot.window_id\n" + FAILED_ONE
    )


def test_a_report_json_from_before_330_scores_a_network_traffic_test_case_as_it_did() -> None:
    # It listed the test case of every Divergence, so a network traffic one still passes.
    report = report_of(
        group_result(listed_verdict(divergent_field("status_response.favicon", traffic=True)))
    )
    assert render_text(report).endswith(PASSED_ONE)


def test_a_network_traffic_difference_fails_if_network_traffic_does_not_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The switch lives with Verdict, where run.prerequisite_verdict reads it too (#221).
    monkeypatch.setattr(mscts.compare, "NETWORK_TRAFFIC_ONLY_PASSES", False)
    report = report_of(
        group_result(report_verdict(divergent_field("status_response.favicon", traffic=True)))
    )
    lines = report_lines(report)
    assert [line.result for line in lines] == [LineResult.FAIL], lines


def test_each_test_case_is_listed_once_per_group_across_repetitions_and_values() -> None:
    field = divergent_field("status_response.players.max")
    other = replace(field, reference=1, candidate=2, index=3)
    text = render_text(
        report_of(
            group_result(report_verdict(field, other), report_verdict(field)),
            group_result(report_verdict(field, group_id="status/ping")),
        )
    )
    assert text == (
        "Running tests against pumpkin\n"
        "✗ status/basic/status_response.players.max\n"
        "✗ status/ping/status_response.players.max\n"
        "0 passed, 2 failed. (0%)\n"
        "Took 41 s\n"
    )


def test_an_unknown_test_case_is_listed_by_name() -> None:
    text = render_text(
        report_of(group_result(report_verdict(divergent_field("status_response.new_field"))))
    )
    assert text == (
        "Running tests against pumpkin\n✗ status/basic/status_response.new_field\n" + FAILED_ONE
    )


def test_list_elements_share_one_line_without_their_values_or_indices() -> None:
    first = replace(divergent_field("hurt_animation.entity_id"), path="entity_id")
    second = replace(first, path="entity_id", candidate="another name")
    text = render_text(report_of(group_result(report_verdict(first, second))))
    assert text == (
        "Running tests against pumpkin\n✗ status/basic/hurt_animation.entity_id\n" + FAILED_ONE
    )


@pytest.mark.parametrize("kind", ["missing", "unexpected"])
def test_a_whole_packet_difference_keeps_its_test_case_name(kind: DivergenceKind) -> None:
    field = divergent_field("status_response")
    field = replace(field, kind=kind, path=None)
    assert "✗ status/basic/status_response\n" in render_text(
        report_of(group_result(report_verdict(field)))
    )


def test_a_group_without_test_cases_to_list_has_one_line_with_its_reasons() -> None:
    different = report_verdict(divergent_field("status_response.players.max"))
    blocked = Verdict("redstone/timing", Outcome.BLOCKED, detail="prerequisite x was not run")
    error = Verdict("status/error", Outcome.ERROR, detail="the Reference did not start")
    failed = Divergence("joiner", 0, "failed", "", None, ABSENT, "disconnected during join", "")
    text = render_text(
        report_of(
            group_result(blocked),
            group_result(different),
            group_result(error),
            group_result(report_verdict(failed, group_id="join/basic")),
        )
    )
    assert text == (
        "Running tests against pumpkin\n"
        "✗ redstone/timing Not tested: prerequisite x was not run\n"
        "✗ status/basic/status_response.players.max\n"
        "! status/error Error: the Reference did not start\n"
        "✗ join/basic Candidate failed: disconnected during join\n"
        "0 passed, 3 failed (1 not tested). (0%)\n"
        "1 error (not scored)\n"
        "Took 41 s\n"
    )


def test_a_report_with_nothing_scored_has_no_score() -> None:
    report = report_of(group_result(Verdict("status/basic", Outcome.ERROR, detail="failed")))
    assert render_text(report) == (
        "Running tests against pumpkin\n"
        "! status/basic Error: failed\n"
        "0 passed, 0 failed.\n"
        "1 error (not scored)\n"
        "Took 41 s\n"
    )


def test_counts_of_more_than_one_use_plurals_and_the_score_is_rounded_down() -> None:
    errors = [
        group_result(Verdict(f"status/e{n}", Outcome.ERROR, detail="failed")) for n in range(2)
    ]
    report = report_of(
        group_result(
            _compared(*"abcdefg"), report_verdict(divergent_field("x"), divergent_field("y"))
        ),
        *errors,
    )
    text = render_text(report)
    assert "\n7 passed, 2 failed. (77.7%)\n2 errors (not scored)\n" in text, text


def test_a_group_lists_distinct_failure_details_once_in_one_line() -> None:
    error = Verdict("status/basic", Outcome.ERROR, detail="first reason")
    other = replace(error, detail="second reason")
    text = render_text(report_of(group_result(error, error, other)))
    assert "! status/basic Error: first reason; Error: second reason\n" in text, text


def test_a_bot_difference_without_a_test_case_still_names_its_group() -> None:
    bot = Divergence("status", 0, "bot", "", None, 4, 3, "")
    text = render_text(report_of(group_result(report_verdict(bot))))
    assert text == (
        "Running tests against pumpkin\n"
        "✗ status/basic Bot 'status' exchanged 4 packets with the Reference, "
        "3 with the Candidate\n" + FAILED_ONE
    )


def test_total_time_keeps_tenths_of_a_second() -> None:
    assert render_text(report_of(elapsed_s=0.25)).endswith("Took 0.2 s\n")


def test_verbose_header_uses_installed_versions_instead_of_status_claims() -> None:
    report = report_of(group_result(report_verdict(divergent_field("status_response.description"))))
    report = replace(
        report,
        reference=replace(report.reference, installed_version="26.3"),
        candidate=replace(report.candidate, installed_version="nightly-abc"),
    )
    assert render_text(report, verbose=True) == (
        "Running tests against pumpkin nightly-abc\n"
        "  Reference    vanilla 26.3\n"
        "  Target       Minecraft 26.3 (protocol 777)\n"
        "  Repetitions  1 of each group\n"
        "✗ status/basic/status_response.description\n"
        '  vanilla sends "reference value", pumpkin sends "candidate value"\n'
        "Group times\n"
        "  status/basic not recorded\n" + FAILED_ONE
    )


def test_verbose_values_are_under_their_case_and_keep_distinct_values() -> None:
    field = replace(
        divergent_field("status_response.description"),
        reference="mscts",
        candidate={"text": "mscts"},
    )
    other = replace(field, candidate={"text": "other"})
    report = report_of(
        group_result(report_verdict(field), report_verdict(field, replace(field, index=3), other))
    )
    text = render_text(report, verbose=True)
    assert text.count("✗ status/basic/status_response.description\n") == 1
    assert text.count('  vanilla sends "mscts", pumpkin sends {"text": "mscts"}\n') == 1
    assert 'pumpkin sends {"text": "other"}\n' in text, text


def test_verbose_values_belong_to_their_own_group() -> None:
    field = divergent_field("status_response.players.max")
    other = replace(field, candidate="other value")
    report = report_of(
        group_result(report_verdict(field)),
        group_result(report_verdict(other, group_id="status/ping")),
    )
    text = render_text(report, verbose=True)
    assert (
        "✗ status/ping/status_response.players.max\n"
        '  vanilla sends "reference value", pumpkin sends "other value"\n'
        "Group times\n"
    ) in text, text


def test_verbose_shows_the_values_of_a_network_traffic_difference() -> None:
    report = report_of(
        group_result(listed_verdict(divergent_field("status_response.favicon", traffic=True)))
    )
    assert (
        "(network traffic only)\n"
        '  vanilla sends "reference value", pumpkin sends "candidate value"\n'
    ) in render_text(report, verbose=True)


def test_verbose_preserves_absent_null_and_bytes_without_inventing_values() -> None:
    missing = replace(divergent_field("new.field"), reference=ABSENT, candidate=None)
    payload = replace(divergent_field("new.payload"), reference=b"\x00\xff", candidate=b"\x01")
    text = render_text(report_of(group_result(report_verdict(missing, payload))), verbose=True)
    assert "/new.field\n  vanilla leaves it out, pumpkin sends null\n" in text, text
    assert "/new.payload\n  vanilla sends bytes 00ff, pumpkin sends bytes 01\n" in text, text


def test_verbose_list_values_keep_the_element_path() -> None:
    field = replace(divergent_field("list[].name"), path="list[2].name")
    assert '  list[2].name: vanilla sends "reference value"' in render_text(
        report_of(group_result(report_verdict(field))), verbose=True
    )


def test_verbose_group_times_total_all_repetitions_and_mark_blocked_groups() -> None:
    played = replace(group_result(report_verdict(), report_verdict()), elapsed_s=(0.4, 0.6))
    blocked = group_result(
        Verdict("join/basic", Outcome.BLOCKED, detail="prerequisite x was not run")
    )
    text = render_text(report_of(played, blocked), verbose=True)
    assert "Group times\n  status/basic 1 s\n  join/basic not played\n" in text, text
    assert "Timings (ms)" not in text
    assert "Notes" not in text
    assert "How to read this" not in text


def test_verbose_group_times_show_a_play_on_vanilla_alone() -> None:
    # #266, #285: the Candidate failed a prerequisite, so only vanilla played the Group.
    what = "prerequisite x was mismatch"
    failed = Divergence("", 0, "failed", "", None, ABSENT, what, "")
    unplayed = Verdict("join/basic", Outcome.MISMATCH, (failed,), f"the Candidate failed: {what}")
    played = replace(group_result(unplayed), elapsed_s=(0.5,))
    text = render_text(report_of(played), verbose=True)
    assert "Group times\n  join/basic 0.5 s\n" in text, text


def test_default_output_leaves_group_times_to_verbose() -> None:
    result = replace(group_result(_compared("a")), elapsed_s=(0.25,))
    assert "Group times" not in render_text(report_of(result))


def test_verbose_renders_uuid_and_nested_binary_values() -> None:
    value = {"id": UUID("12345678-1234-5678-1234-567812345678"), "data": [b"\x00\xff"]}
    field = replace(divergent_field("new.record"), reference=value, candidate=ABSENT)
    text = render_text(report_of(group_result(report_verdict(field))), verbose=True)
    assert '"data": [{"bytes": "00ff"}]' in text, text
    assert '"id": "12345678-1234-5678-1234-567812345678"' in text, text


BUILT = SideSummary("pumpkin", "26.3", (), "nightly 4426d11 (sha256 b8382a8a…)")


def test_the_first_line_names_the_candidate_s_exact_build() -> None:
    report = replace(report_of(group_result(_compared("a"))), candidate=BUILT)
    assert render_text(report) == (
        "Running tests against pumpkin nightly 4426d11 (sha256 b8382a8a…)\n"
        "✓ status/basic/a\n" + PASSED_ONE
    )


def test_the_verbose_output_names_the_candidate_s_build_once() -> None:
    report = replace(report_of(group_result(report_verdict())), candidate=BUILT)
    text = render_text(report, verbose=True)
    assert text.count("nightly 4426d11") == 1, text
    assert text.startswith("Running tests against pumpkin nightly 4426d11 (sha256 b8382a8a…)\n")


def test_markdown_names_the_candidate_s_exact_build_in_the_heading() -> None:
    report = replace(report_of(group_result(_compared("a"))), candidate=BUILT)
    assert render_markdown(report) == (
        "# Running tests against pumpkin nightly 4426d11 (sha256 b8382a8a…)\n"
        "\n"
        "- ✓ `status/basic/a`\n"
        "\n"
        "1 passed, 0 failed. (100%)\\\n"
        "Took 41 s\n"
    )


def test_markdown_is_the_default_report_with_a_heading_and_names_as_code() -> None:
    report = report_of(
        group_result(
            listed_verdict(
                divergent_field("status_response.description"),
                divergent_field("new.field", traffic=True),
            )
        ),
        group_result(Verdict("join/basic", Outcome.BLOCKED, detail="prerequisite x was not run")),
    )
    assert render_markdown(report) == (
        "# Running tests against pumpkin\n"
        "\n"
        "- ✓ `status/basic/new.field` (network traffic only)\n"
        "- ✗ `status/basic/status_response.description`\n"
        "- ✗ `join/basic` Not tested: prerequisite x was not run\n"
        "\n"
        "1 passed, 2 failed (1 not tested). (33.3%)\\\n"
        "Took 41 s\n"
    )


def test_markdown_of_a_run_with_no_groups_has_no_list() -> None:
    assert render_markdown(report_of()) == (
        "# Running tests against pumpkin\n\n0 passed, 0 failed.\\\nTook 41 s\n"
    )


def test_verbose_markdown_keeps_the_header_values_and_group_times() -> None:
    field = replace(divergent_field("list[].name"), path="list[2].name", candidate=ABSENT)
    report = report_of(group_result(report_verdict(field)))
    report = replace(report, candidate=replace(report.candidate, installed_version="nightly-abc"))
    assert render_markdown(report, verbose=True) == (
        "# Running tests against pumpkin nightly-abc\n"
        "\n"
        "Reference: vanilla (installed version unknown)\\\n"
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
        "0 passed, 1 failed. (0%)\\\n"
        "Took 41 s\n"
    )


NO_ANSWER = "did not answer a status request within 10 s"


def _restarted(*restarts: Restart, reference: tuple[Restart, ...] = ()) -> Report:
    report = report_of(group_result(_compared("a", group_id="crafting/grid")))
    return replace(
        report,
        reference=replace(report.reference, restarts=reference),
        candidate=replace(report.candidate, restarts=restarts),
    )


def test_a_restart_has_a_line_after_the_test_cases_that_says_after_which_group_and_why() -> None:
    report = _restarted(Restart("crafting/grid", NO_ANSWER))
    assert render_text(report) == (
        "Running tests against pumpkin\n"
        "✓ crafting/grid/a\n"
        "Restarted pumpkin after crafting/grid, because it did not answer a status request "
        "within 10 s.\n" + PASSED_ONE
    )


def test_restarts_name_each_server_and_count_the_same_one_once() -> None:
    again = Restart("crafting/grid", NO_ANSWER)
    report = _restarted(again, Restart("blocks/door", NO_ANSWER), again, reference=(again,))
    lines = render_text(report).splitlines()
    assert [line for line in lines if line.startswith("Restarted")] == [
        f"Restarted vanilla after crafting/grid, because it {NO_ANSWER}.",
        f"Restarted pumpkin 2 times after crafting/grid, because it {NO_ANSWER}.",
        f"Restarted pumpkin after blocks/door, because it {NO_ANSWER}.",
    ], lines


def test_markdown_gives_the_restarts_a_paragraph_with_each_group_as_code() -> None:
    report = _restarted(Restart("crafting/grid", NO_ANSWER), Restart("blocks/door", NO_ANSWER))
    assert render_markdown(report) == (
        "# Running tests against pumpkin\n"
        "\n"
        "- ✓ `crafting/grid/a`\n"
        "\n"
        f"Restarted pumpkin after `crafting/grid`, because it {NO_ANSWER}.\\\n"
        f"Restarted pumpkin after `blocks/door`, because it {NO_ANSWER}.\n"
        "\n"
        "1 passed, 0 failed. (100%)\\\n"
        "Took 41 s\n"
    )


def test_markdown_shows_server_text_as_it_is() -> None:
    field = replace(divergent_field("new.field"), reference="`a``b`", candidate=b"")
    failed = Divergence("joiner", 0, "failed", "", None, ABSENT, "closed: <b>*now*</b> [x]_\\", "")
    report = report_of(
        group_result(report_verdict(field)),
        group_result(report_verdict(failed, group_id="join/basic")),
    )
    text = render_markdown(report, verbose=True)
    assert '  - vanilla sends ```"`a``b`"```, pumpkin sends bytes ``\n' in text, text
    assert (
        "- ✗ `join/basic` Candidate failed: closed: \\<b\\>\\*now\\*\\</b\\> \\[x\\]\\_\\\\\n"
        in text
    ), text


def test_markdown_shows_a_line_break_in_server_text_without_breaking_the_line() -> None:
    forged = "x\n\n# pumpkin passes\r\nScore: 100%"
    failed = Divergence("joiner", 0, "failed", "", None, ABSENT, forged, "")
    text = render_markdown(report_of(group_result(report_verdict(failed, group_id="join/basic"))))
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
    field = replace(divergent_field("p[]"), path=path)
    text = render_markdown(report_of(group_result(report_verdict(field))), verbose=True)
    assert f"  - {code}: vanilla sends" in text, text


def test_colour_marks_a_pass_green_a_failure_red_an_error_yellow_and_the_rest_grey() -> None:
    error = Verdict("status/error", Outcome.ERROR, detail="failed")
    report = report_of(
        group_result(_compared("a")),
        group_result(report_verdict(divergent_field("b"), group_id="status/ping")),
        group_result(error),
        group_result(report_verdict(divergent_field("c", traffic=True), group_id="status/other")),
    )
    text = render_text(report, color=True)
    assert "\x1b[32m✓\x1b[0m status/basic/a\n" in text, text
    assert "\x1b[31m✗\x1b[0m status/ping/b\n" in text, text
    assert "\x1b[33m!\x1b[0m status/error Error: failed\n" in text, text
    assert "\x1b[90m·\x1b[0m status/other/c (network traffic only, not scored)\n" in text
    assert re.sub("\x1b\\[[0-9]+m", "", text) == render_text(report)


def test_the_report_has_no_colour_unless_asked() -> None:
    report = report_of(
        group_result(_compared("a")), group_result(report_verdict(divergent_field("b")))
    )
    assert "\x1b" not in render_text(report)
    assert "\x1b" not in render_markdown(report)


def test_verbose_shows_the_tick_each_server_sent_a_packet_on() -> None:
    # #23: a tick-exact Group's packet sent on another tick.
    late = replace(
        divergent_field("block_update"),
        packet="minecraft:block_update",
        path=TICK_PATH,
        reference=1,
        candidate=2,
    )
    text = render_text(report_of(group_result(report_verdict(late))), verbose=True)
    assert "block_update\n  (tick): vanilla sends 1, pumpkin sends 2\n" in text, text


def _distribution(name: str, tested: Difference | None, **sides: Summary) -> Divergence:
    return Divergence(
        bot="",
        index=0,
        kind="distribution",
        packet="",
        path=None,
        reference=sides["reference"],
        candidate=sides["candidate"],
        test_case=name,
        tested=tested,
    )


def test_one_sample_is_a_sample_in_the_summaries() -> None:
    one = _distribution(
        "x",
        Difference("Kolmogorov-Smirnov", "D", 0.98, 1e-27),
        reference=Spread(samples=1, median=1000.0, quartiles=(1000.0, 1000.0)),
        candidate=Shares(samples=1, shares=(("minecraft:pig", 1.0),)),
    )
    verdict = Verdict("spawn/join", Outcome.MISMATCH, (one,))

    text = render_text(report_of(group_result(verdict)), verbose=True)

    assert "vanilla 1 sample, median 1000," in text, text
    assert "pumpkin 1 sample, minecraft:pig 100%" in text, text


def test_a_count_test_summarises_samples_per_play() -> None:
    counted = _distribution(
        "mob",
        Difference("Kolmogorov-Smirnov on samples per play", "D", 1.0, 1e-27),
        reference=Spread(samples=50, median=10.0, quartiles=(10.0, 10.0)),
        candidate=Spread(samples=50, median=0.0, quartiles=(0.0, 0.0)),
    )
    verdict = Verdict("spawn/join", Outcome.MISMATCH, (counted,))

    text = render_text(report_of(group_result(verdict)), verbose=True)

    assert (
        "Kolmogorov-Smirnov on samples per play D = 1.00, p = 1e-27: vanilla 50 plays,"
        " median 10 samples per play, quartiles 10 and 10; pumpkin 50 plays,"
        " median 0 samples per play, quartiles 0 and 0\n"
    ) in text, text


def test_verbose_shows_a_distribution_s_test_and_both_sides_summaries() -> None:
    numbers = _distribution(
        "distance",
        Difference("Kolmogorov-Smirnov", "D", 0.4, 0.00058),
        reference=Spread(samples=50, median=0.16608, quartiles=(-0.39263, 0.66314)),
        candidate=Spread(samples=50, median=0.86373, quartiles=(0.02174, 1.41278)),
    )
    categories = _distribution(
        "mob",
        Difference("chi-square", "V", 0.52, 0.0031),
        reference=Shares(samples=50, shares=(("minecraft:zombie", 0.6), ("minecraft:husk", 0.4))),
        candidate=Shares(samples=40, shares=(("minecraft:zombie", 1.0),)),
    )
    untested = _distribution(
        "drop",
        None,
        reference=Shares(samples=10, shares=(("minecraft:bone", 1.0),)),
        candidate=None,
    )
    verdict = Verdict("spawn/join", Outcome.MISMATCH, (numbers, categories, untested))
    text = render_text(report_of(group_result(verdict)), verbose=True)
    assert (
        "✗ spawn/join/distance\n"
        "  Kolmogorov-Smirnov D = 0.40, p = 0.00058: vanilla 50 samples, median 0.1661,"
        " quartiles -0.3926 and 0.6631; pumpkin 50 samples, median 0.8637,"
        " quartiles 0.02174 and 1.413\n"
    ) in text, text
    assert (
        "✗ spawn/join/drop\n"
        "  not tested: vanilla 10 samples, minecraft:bone 100%; pumpkin no samples\n"
    ) in text, text
    assert (
        "✗ spawn/join/mob\n"
        "  chi-square V = 0.52, p = 0.0031: vanilla 50 samples, minecraft:zombie 60%,"
        " minecraft:husk 40%; pumpkin 40 samples, minecraft:zombie 100%\n"
    ) in text, text
