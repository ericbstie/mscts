"""The default Report is a list of differences and the total Run time (#9)."""

from dataclasses import replace
from uuid import UUID

import pytest

from mscts.compare import ABSENT, Divergence, DivergenceKind, Observability, Outcome, Verdict
from mscts.report import Report, render_markdown, render_text
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
        "- Server list description  status_response.description\n"
        '  vanilla sends "reference value", pumpkin sends "candidate value"\n'
        "Group times\n"
        "  status/basic not recorded\n"
        "Took 41 s\n"
    )


def test_verbose_values_are_under_their_case_and_keep_distinct_values() -> None:
    field = replace(
        _field("status_response.description"), reference="mscts", candidate={"text": "mscts"}
    )
    other = replace(field, candidate={"text": "other"})
    report = _report(_result(_verdict(field), _verdict(field, replace(field, index=3), other)))
    text = render_text(report, verbose=True)
    assert text.count("- Server list description  status_response.description\n") == 1
    assert text.count('  vanilla sends "mscts", pumpkin sends {"text": "mscts"}\n') == 1
    assert 'pumpkin sends {"text": "other"}\n' in text, text


def test_verbose_preserves_absent_null_and_bytes_without_inventing_values() -> None:
    missing = replace(_field("new.field"), reference=ABSENT, candidate=None)
    payload = replace(_field("new.payload"), reference=b"\x00\xff", candidate=b"\x01")
    text = render_text(_report(_result(_verdict(missing, payload))), verbose=True)
    assert "- new.field\n  vanilla leaves it out, pumpkin sends null\n" in text, text
    assert "- new.payload\n  vanilla sends bytes 00ff, pumpkin sends bytes 01\n" in text, text


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
    assert "No differences." not in text
    assert "Timings (ms)" not in text
    assert "Notes" not in text
    assert "How to read this" not in text


def test_default_output_leaves_group_times_to_verbose() -> None:
    result = replace(_result(_verdict()), elapsed_s=(0.25,))
    report = _report(result)
    assert render_text(report) == "Running tests against pumpkin\nNo differences.\nTook 41 s\n"


def test_verbose_renders_uuid_and_nested_binary_values() -> None:
    value = {"id": UUID("12345678-1234-5678-1234-567812345678"), "data": [b"\x00\xff"]}
    field = replace(_field("new.record"), reference=value, candidate=ABSENT)
    text = render_text(_report(_result(_verdict(field))), verbose=True)
    assert '"data": [{"bytes": "00ff"}]' in text, text
    assert '"id": "12345678-1234-5678-1234-567812345678"' in text, text


BUILT = SideSummary("pumpkin", "26.3", (), "nightly 4426d11 (sha256 b8382a8a…)")


def test_the_default_output_names_the_candidate_s_exact_build() -> None:
    report = replace(_report(_result(_verdict())), candidate=BUILT)
    assert render_text(report) == (
        "Running tests against pumpkin\n"
        "Candidate: pumpkin nightly 4426d11 (sha256 b8382a8a…)\n"
        "No differences.\n"
        "Took 41 s\n"
    )


def test_the_verbose_output_names_the_candidate_s_build_once() -> None:
    report = replace(_report(_result(_verdict())), candidate=BUILT)
    text = render_text(report, verbose=True)
    assert text.count("nightly 4426d11") == 1, text
    assert "  Candidate    pumpkin nightly 4426d11 (sha256 b8382a8a…)\n" in text, text


def test_markdown_names_the_candidate_s_exact_build_under_the_heading() -> None:
    report = replace(_report(_result(_verdict())), candidate=BUILT)
    assert render_markdown(report) == (
        "# Running tests against pumpkin\n"
        "\n"
        "Candidate: pumpkin nightly 4426d11 (sha256 b8382a8a…)\n"
        "\n"
        "No differences.\n"
        "\n"
        "Took 41 s\n"
    )


def test_markdown_is_the_default_report_with_a_heading_and_names_as_code() -> None:
    report = _report(
        _result(_verdict(_field("status_response.description"), _field("new.field"))),
        _result(Verdict("join/basic", Outcome.BLOCKED, detail="needs /tick")),
    )
    assert render_markdown(report) == (
        "# Running tests against pumpkin\n"
        "\n"
        "- Server list description `status_response.description`\n"
        "- `new.field`\n"
        "- Not tested: needs /tick `join/basic`\n"
        "\n"
        "Took 41 s\n"
    )


def test_markdown_says_no_differences_plainly() -> None:
    assert render_markdown(_report(_result(_verdict()))) == (
        "# Running tests against pumpkin\n\nNo differences.\n\nTook 41 s\n"
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
        "- `list[].name`\n"
        '  - `list[2].name`: vanilla sends `"reference value"`, pumpkin leaves it out\n'
        "\n"
        "## Group times\n"
        "\n"
        "- status/basic not recorded\n"
        "\n"
        "Took 41 s\n"
    )


def test_markdown_shows_server_text_as_it_is() -> None:
    field = replace(_field("new.field"), reference="`a``b`", candidate=b"")
    failed = Divergence("joiner", 0, "failed", "", None, ABSENT, "closed: <b>*now*</b> [x]_\\", "")
    report = _report(_result(_verdict(field)), _result(_verdict(failed, group_id="join/basic")))
    text = render_markdown(report, verbose=True)
    assert '  - vanilla sends ```"`a``b`"```, pumpkin sends bytes ``\n' in text, text
    assert (
        "- Candidate failed: closed: \\<b\\>\\*now\\*\\</b\\> \\[x\\]\\_\\\\ `join/basic`\n" in text
    ), text


@pytest.mark.parametrize(
    ("path", "code"),
    [("`p[0]`", "`` `p[0]` ``"), (" p[0] ", "`  p[0]  `"), ("p[0]", "`p[0]`")],
    ids=["backticks", "spaces", "plain"],
)
def test_markdown_code_keeps_its_edges(path: str, code: str) -> None:
    field = replace(_field("p[]"), path=path)
    text = render_markdown(_report(_result(_verdict(field))), verbose=True)
    assert f"  - {code}: vanilla sends" in text, text
