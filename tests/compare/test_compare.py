"""compare(): which parts of two Transcripts are compared, and the Verdict it gives."""

import pytest

from mscts.codec.packets import State
from mscts.compare import ABSENT, Outcome, Verdict, compare
from mscts.transcript import Mark
from tests.compare.build import GROUP, SERVERBOUND, divergence, packet, transcript

A = packet("test:a", b"\x01")
B = packet("test:b", b"\x02")
C = packet("test:c", b"\x03")


def test_identical_transcripts_match() -> None:
    events = [("alice", A), ("alice", B), ("bob", C)]
    verdict = compare(transcript(*events), transcript(*events, server="pumpkin"), [])
    assert verdict == Verdict(
        group_id=GROUP, outcome=Outcome.MATCH, test_cases=("test:a", "test:b", "test:c")
    )


def test_empty_transcripts_match() -> None:
    assert compare(transcript(), transcript(), []).outcome is Outcome.MATCH


def test_outcomes_are_named_as_in_context() -> None:
    assert [str(outcome) for outcome in Outcome] == ["match", "mismatch", "blocked", "error"]


def test_timestamps_and_marks_are_not_compared() -> None:
    reference = transcript(("alice", A), ("alice", B))
    candidate = transcript(("alice", A))
    candidate.record("alice", B, t_ns=candidate.now_ns())
    candidate.marks.append(Mark(t_ns=5, label="status:start"))
    assert reference.events[1].t_ns != candidate.events[1].t_ns
    assert compare(reference, candidate, []).outcome is Outcome.MATCH


def test_serverbound_packets_are_not_compared() -> None:
    # Each Bot's handshake names its own Instance's port, so it differs by design.
    reference = transcript(
        ("alice", packet("minecraft:intention", b"\x63\xdd", direction=SERVERBOUND)),
        ("alice", A),
    )
    candidate = transcript(
        ("alice", packet("minecraft:intention", b"\x63\xde", direction=SERVERBOUND)),
        ("alice", A),
        ("alice", packet("test:b", b"\x02", direction=SERVERBOUND)),
    )
    assert compare(reference, candidate, []).outcome is Outcome.MATCH


def test_bots_are_compared_separately_whatever_their_interleaving() -> None:
    reference = transcript(("alice", A), ("bob", B), ("alice", C))
    candidate = transcript(("bob", B), ("alice", A), ("alice", C))
    assert compare(reference, candidate, []).outcome is Outcome.MATCH


def test_a_differing_payload_is_a_field_divergence_with_hex_values() -> None:
    reference = transcript(("alice", A), ("alice", packet("test:b", b"\x01\x02")))
    candidate = transcript(("alice", A), ("alice", packet("test:b", b"\x01\xff")))
    assert compare(reference, candidate, []) == Verdict(
        group_id=GROUP,
        outcome=Outcome.MISMATCH,
        divergences=(
            divergence(
                "field",
                index=1,
                packet="test:b",
                reference="0102",
                candidate="01ff",
                test_case="test:b",
            ),
        ),
        test_cases=("test:a", "test:b"),
    )


def test_a_long_payload_shows_its_first_256_bytes_and_counts_the_rest() -> None:
    # One refused chunk is tens of kilobytes; its whole hex would swamp a Report.
    long = bytes(range(256)) * 2
    reference = transcript(("alice", packet("test:b", b"\x01" + long)))
    candidate = transcript(("alice", packet("test:b", b"\x02" + long + b"\x03")))

    (difference,) = compare(reference, candidate, []).divergences

    assert (difference.reference, difference.candidate) == (
        f"01{bytes(range(255)).hex()} (257 more bytes)",
        f"02{bytes(range(255)).hex()} (258 more bytes)",
    )


def test_long_payloads_that_differ_late_show_bytes_from_just_before_the_difference() -> None:
    # Their first 256 bytes are the same; shown, they would read as equal.
    reference = bytearray(1000)
    candidate = bytearray(1000)
    reference[600], candidate[600] = 1, 2

    (difference,) = compare(
        transcript(("alice", packet("test:b", bytes(reference)))),
        transcript(("alice", packet("test:b", bytes(candidate)))),
        [],
    ).divergences

    # 16 bytes before the difference, 584, down to a multiple of 16: from byte 576 to 832.
    assert (difference.reference, difference.candidate) == (
        f"(576 bytes before) {reference[576:832].hex()} (168 more bytes)",
        f"(576 bytes before) {candidate[576:832].hex()} (168 more bytes)",
    )


def test_a_long_payload_that_goes_on_past_the_other_shows_where_the_other_ends() -> None:
    reference = bytes(600)
    candidate = bytes(600) + b"\x01"

    (difference,) = compare(
        transcript(("alice", packet("test:b", reference))),
        transcript(("alice", packet("test:b", candidate))),
        [],
    ).divergences

    assert (difference.reference, difference.candidate) == (
        f"(576 bytes before) {bytes(24).hex()}",
        f"(576 bytes before) {candidate[576:].hex()}",
    )


def test_shown_bytes_that_reach_the_end_count_nothing_after_them() -> None:
    reference = bytes(512)
    candidate = bytes(272) + b"\x01" + bytes(239)

    (difference,) = compare(
        transcript(("alice", packet("test:b", reference))),
        transcript(("alice", packet("test:b", candidate))),
        [],
    ).divergences

    assert difference.candidate == f"(256 bytes before) {candidate[256:].hex()}"


def test_a_difference_near_the_start_of_long_payloads_shows_their_first_256_bytes() -> None:
    reference = bytes(500)
    candidate = bytes(10) + b"\x01" + bytes(489)

    (difference,) = compare(
        transcript(("alice", packet("test:b", reference))),
        transcript(("alice", packet("test:b", candidate))),
        [],
    ).divergences

    assert difference.candidate == f"{candidate[:256].hex()} (244 more bytes)"


def test_a_long_payload_against_a_short_one_shows_each_from_its_start() -> None:
    # The short one is shown whole, so the difference is in view already.
    reference = bytes(600)
    candidate = bytes(200) + b"\x01"

    (difference,) = compare(
        transcript(("alice", packet("test:b", reference))),
        transcript(("alice", packet("test:b", candidate))),
        [],
    ).divergences

    assert (difference.reference, difference.candidate) == (
        f"{bytes(256).hex()} (344 more bytes)",
        candidate.hex(),
    )


def test_a_long_payload_missing_or_unexpected_is_capped_too() -> None:
    long = packet("test:b", bytes(300))
    shown = f"{bytes(256).hex()} (44 more bytes)"

    verdict = compare(transcript(("alice", long)), transcript(("bob", long)), [])

    assert [(d.kind, d.reference, d.candidate) for d in verdict.divergences if d.kind != "bot"] == [
        ("missing", shown, ABSENT),
        ("unexpected", ABSENT, shown),
    ]


def test_a_payload_of_256_bytes_is_shown_whole() -> None:
    reference = transcript(("alice", packet("test:b", bytes(256))))
    candidate = transcript(("alice", packet("test:b", bytes(255) + b"\x01")))

    (difference,) = compare(reference, candidate, []).divergences

    assert difference.candidate == (bytes(255) + b"\x01").hex()


def test_a_packet_only_the_reference_received_is_missing() -> None:
    reference = transcript(("alice", A), ("alice", B))
    candidate = transcript(("alice", A))
    assert compare(reference, candidate, []).divergences == (
        divergence("missing", index=1, packet="test:b", reference="02", test_case="test:b"),
    )


def test_a_packet_only_the_candidate_received_is_unexpected() -> None:
    reference = transcript(("alice", A))
    candidate = transcript(("alice", A), ("alice", B))
    assert compare(reference, candidate, []).divergences == (
        divergence("unexpected", index=1, packet="test:b", candidate="02", test_case="test:b"),
    )


def test_same_named_packets_of_different_states_are_different_packets() -> None:
    reference = transcript(("alice", packet("minecraft:disconnect", state=State.LOGIN)))
    candidate = transcript(("alice", packet("minecraft:disconnect", state=State.PLAY)))
    assert [d.kind for d in compare(reference, candidate, []).divergences] == [
        "missing",
        "unexpected",
    ]


def test_divergences_are_grouped_by_bot_in_name_order() -> None:
    reference = transcript(("bob", A), ("alice", A))
    candidate = transcript(("bob", B), ("alice", B))
    assert [(d.bot, d.kind) for d in compare(reference, candidate, []).divergences] == [
        ("alice", "missing"),
        ("alice", "unexpected"),
        ("bob", "missing"),
        ("bob", "unexpected"),
    ]


def test_a_bot_only_the_reference_has_is_a_bot_divergence() -> None:
    # bob only sent: comparing received streams alone would find nothing.
    sent = packet("test:hello", b"\x07", direction=SERVERBOUND)
    reference = transcript(("alice", A), ("bob", sent), ("bob", sent))
    candidate = transcript(("alice", A))
    assert compare(reference, candidate, []).divergences == (
        divergence("bot", bot="bob", reference=2),
    )


def test_a_bot_only_the_candidate_has_is_a_bot_divergence_then_its_packets() -> None:
    reference = transcript(("alice", A))
    candidate = transcript(("alice", A), ("bob", B), ("bob", C))
    assert compare(reference, candidate, []).divergences == (
        divergence("bot", bot="bob", candidate=2),
        divergence("unexpected", bot="bob", packet="test:b", candidate="02", test_case="test:b"),
        divergence(
            "unexpected", bot="bob", index=1, packet="test:c", candidate="03", test_case="test:c"
        ),
    )


def test_a_bot_that_received_nothing_is_still_present() -> None:
    sent = packet("test:hello", b"\x07", direction=SERVERBOUND)
    reference = transcript(("alice", A))
    candidate = transcript(("alice", sent))
    assert [d.kind for d in compare(reference, candidate, []).divergences] == ["missing"]


def test_transcripts_of_different_groups_are_not_compared() -> None:
    other = transcript(group_id="status/ping")
    with pytest.raises(ValueError, match="different Groups: 'test/group' and 'status/ping'"):
        compare(transcript(), other, [])


def test_absent_reads_as_absent() -> None:
    assert repr(ABSENT) == "ABSENT"
