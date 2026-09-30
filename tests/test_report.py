from mscts.compare import ABSENT, Divergence, Observability, Outcome, Verdict
from mscts.measure import Measurement
from mscts.report import Report, render_text
from mscts.run import GroupResult, SideSummary
from mscts.target import TARGET

STATUS = "minecraft:status_response"
OBSERVABLE = "Differences a player would notice"
WIRE_ONLY = "Wire-only differences"
TIMINGS = "Timings"


def _field(path: str, reference: object, candidate: object, *, wire: bool = False) -> Divergence:
    return Divergence(
        bot="status",
        index=0,
        kind="field",
        packet=STATUS,
        path=path,
        reference=reference,
        candidate=candidate,
        observability=Observability.WIRE_ONLY if wire else Observability.OBSERVABLE,
    )


def _verdict(group_id: str, *divergences: Divergence, outcome: Outcome | None = None) -> Verdict:
    if outcome is None:
        outcome = Outcome.MISMATCH if divergences else Outcome.MATCH
    return Verdict(group_id=group_id, outcome=outcome, divergences=divergences)


def _result(*verdicts: Verdict, rtt: float | None = None) -> GroupResult:
    measured = (Measurement("status.rtt", "ms", rtt),) if rtt is not None else ()
    return GroupResult(
        group_id=verdicts[0].group_id,
        verdicts=verdicts,
        reference=tuple(measured for _ in verdicts),
        candidate=tuple(measured for _ in verdicts),
    )


def _report(*results: GroupResult) -> Report:
    return Report(
        target=TARGET,
        reference=SideSummary(
            name="vanilla", version="26.3", startup=(Measurement("instance.startup", "ms", 9000),)
        ),
        candidate=SideSummary(
            name="pumpkin",
            version="Pumpkin 26.2",
            startup=(Measurement("instance.startup", "ms", 400),),
        ),
        results=results,
        notes=("--out is not implemented yet",),
    )


def _positions(text: str, *headings: str) -> list[int]:
    return [text.index(heading) for heading in headings]


def test_the_header_names_both_servers_their_versions_the_target_and_the_repetitions() -> None:
    text = render_text(_report(_result(_verdict("status/basic"), _verdict("status/basic"))))

    header = text[: text.index(TIMINGS)]
    for expected in ("vanilla", "26.3", "pumpkin", "Pumpkin 26.2", "777", "2 "):
        assert expected in header


def test_no_divergences_is_said_plainly() -> None:
    text = render_text(_report(_result(_verdict("status/basic")), _result(_verdict("status/ping"))))

    assert "No differences from vanilla were found in the 2 scenarios run." in text
    assert OBSERVABLE not in text
    assert WIRE_ONLY not in text


def test_only_wire_only_divergences_say_plainly_a_player_would_notice_none() -> None:
    wire = _field("json_response.favicon", ABSENT, None, wire=True)
    text = render_text(_report(_result(_verdict("status/basic", wire))))

    assert "No difference a player would notice was found" in text
    assert OBSERVABLE not in text


def test_the_sections_come_in_order() -> None:
    basic = _verdict(
        "status/basic",
        _field("json_response.version.name", "26.3", "Pumpkin 26.2"),
        _field("json_response.description", '{"text":"A"}', '"A"', wire=True),
    )
    error = _verdict("join/basic", outcome=Outcome.ERROR)
    text = render_text(_report(_result(basic, rtt=1.0), _result(error)))

    positions = _positions(text, "2 scenarios", OBSERVABLE, WIRE_ONLY, "join/basic", TIMINGS)
    assert positions == sorted(positions)
    assert text.rindex("wire-only") > text.index(TIMINGS)  # the legend comes last


def test_the_summary_counts_identical_and_different_groups() -> None:
    different = _verdict("status/basic", _field("json_response.version.name", "26.3", "x"))
    text = render_text(_report(_result(different), _result(_verdict("status/ping"))))

    assert "2 scenarios: 1 identical, 1 different" in text


def test_an_observable_divergence_reads_as_both_values_under_its_mechanic() -> None:
    different = _verdict("status/basic", _field("json_response.version.name", "26.3", "Pumpkin"))
    text = render_text(_report(_result(different)))

    section = text[text.index(OBSERVABLE) : text.index(TIMINGS)]
    assert "Server list ping (status)" in section
    assert section.index("Server list ping") < section.index("status/basic")
    line = next(line for line in section.splitlines() if "version.name" in line)
    assert "status_response" in line
    assert line.index('"26.3"') < line.index('"Pumpkin"')
    assert "vanilla" in line
    assert "pumpkin" in line


def test_divergences_are_grouped_by_mechanic_then_group() -> None:
    status = _verdict("status/basic", _field("a", 1, 2))
    join = _verdict("join/basic", _field("b", 3, 4))
    ping = _verdict("status/ping", _field("c", 5, 6))
    text = render_text(_report(_result(status), _result(join), _result(ping)))

    section = text[text.index(OBSERVABLE) : text.index(TIMINGS)]
    status_title, basic, ping_at, join_title = _positions(
        section, "Server list ping (status)", "status/basic", "status/ping", "join"
    )
    assert status_title < basic < ping_at < join_title


def test_an_unknown_mechanic_is_shown_by_its_prefix() -> None:
    text = render_text(_report(_result(_verdict("zzz/thing", _field("a", 1, 2)))))

    assert "zzz" in text[text.index(OBSERVABLE) :]


def test_a_failed_divergence_reads_as_the_candidate_failing() -> None:
    failed = Divergence(
        bot="",
        index=0,
        kind="failed",
        packet="",
        path=None,
        reference=ABSENT,
        candidate="TimeoutError: no answer within 10.0 s",
    )
    text = render_text(_report(_result(_verdict("status/basic", failed))))

    assert "the Candidate failed: TimeoutError: no answer within 10.0 s" in text


def test_a_long_value_is_truncated_with_its_full_length() -> None:
    long = "x" * 500
    text = render_text(_report(_result(_verdict("status/basic", _field("a", long, "y")))))

    assert "x" * 500 not in text
    assert "…" in text
    assert "502" in text  # the quoted value's full length


def test_wire_only_divergences_are_counted_per_packet_with_a_few_examples() -> None:
    wire = [_field(f"json_response.v{i}", i, f"{i}", wire=True) for i in range(10)]
    text = render_text(_report(_result(_verdict("status/basic", *wire))))

    section = text[text.index(WIRE_ONLY) : text.index(TIMINGS)]
    assert "10" in section
    assert "status_response" in section
    assert "json_response.v0" in section
    assert "json_response.v9" not in section
    assert "and 5 more" in section  # never hides that some were left out
    assert OBSERVABLE not in text


def test_errors_and_blocked_groups_are_listed_with_their_detail() -> None:
    error = Verdict("status/basic", Outcome.ERROR, detail="the Reference failed: boom")
    blocked = Verdict("status/ping", Outcome.BLOCKED, detail="prerequisite status/basic was error")
    text = render_text(_report(_result(error), _result(blocked)))

    assert "the Reference failed: boom" in text
    assert "prerequisite status/basic was error" in text


def test_verdicts_that_differ_between_repetitions_are_noted() -> None:
    different = _verdict("status/basic", _field("a", 1, 2))
    text = render_text(
        _report(_result(different, _verdict("status/basic"), _verdict("status/basic")))
    )

    assert "different in 1 of 3 runs" in text


def test_timings_show_each_measurement_for_both_servers_and_the_startup() -> None:
    text = render_text(_report(_result(_verdict("status/ping"), rtt=0.25)))

    timings = text[text.index(TIMINGS) :]
    assert "status.rtt" in timings
    assert "0.25" in timings
    assert "instance.startup" in timings
    assert "9000" in timings.replace(",", "")
    assert "400" in timings


def test_timings_name_the_groups_that_were_not_played() -> None:
    blocked = Verdict("status/ping", Outcome.BLOCKED, detail="prerequisite status/basic was error")
    text = render_text(_report(_result(_verdict("status/basic")), _result(blocked)))

    timings = text[text.index(TIMINGS) :]
    assert "status/ping" in timings
    assert "status/basic" not in timings


def test_the_notes_are_shown() -> None:
    text = render_text(_report(_result(_verdict("status/basic"))))

    assert "--out is not implemented yet" in text
