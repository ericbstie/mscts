"""compare(): which parts of two Transcripts are compared, and the Verdict it gives."""

import pytest

from mscts.codec.packets import State
from mscts.compare import ABSENT, Divergence, Outcome, Verdict, compare
from mscts.transcript import Mark
from tests.compare.build import SCENARIO, SERVERBOUND, packet, transcript

A = packet("test:a", b"\x01")
B = packet("test:b", b"\x02")
C = packet("test:c", b"\x03")


def test_identical_transcripts_match() -> None:
    events = [("alice", A), ("alice", B), ("bob", C)]
    verdict = compare(transcript(*events), transcript(*events, server="pumpkin"), [])
    assert verdict == Verdict(scenario_id=SCENARIO, outcome=Outcome.MATCH)


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
        scenario_id=SCENARIO,
        outcome=Outcome.MISMATCH,
        divergences=(
            Divergence(
                bot="alice",
                index=1,
                kind="field",
                packet="test:b",
                path=None,
                reference="0102",
                candidate="01ff",
            ),
        ),
    )


def test_a_packet_only_the_reference_received_is_missing() -> None:
    reference = transcript(("alice", A), ("alice", B))
    candidate = transcript(("alice", A))
    assert compare(reference, candidate, []).divergences == (
        Divergence(
            bot="alice",
            index=1,
            kind="missing",
            packet="test:b",
            path=None,
            reference="02",
            candidate=ABSENT,
        ),
    )


def test_a_packet_only_the_candidate_received_is_unexpected() -> None:
    reference = transcript(("alice", A))
    candidate = transcript(("alice", A), ("alice", B))
    assert compare(reference, candidate, []).divergences == (
        Divergence(
            bot="alice",
            index=1,
            kind="unexpected",
            packet="test:b",
            path=None,
            reference=ABSENT,
            candidate="02",
        ),
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
        Divergence(
            bot="bob",
            index=0,
            kind="bot",
            packet="",
            path=None,
            reference=2,
            candidate=ABSENT,
        ),
    )


def test_a_bot_only_the_candidate_has_is_a_bot_divergence_then_its_packets() -> None:
    reference = transcript(("alice", A))
    candidate = transcript(("alice", A), ("bob", B), ("bob", C))
    assert compare(reference, candidate, []).divergences == (
        Divergence(
            bot="bob",
            index=0,
            kind="bot",
            packet="",
            path=None,
            reference=ABSENT,
            candidate=2,
        ),
        Divergence(
            bot="bob",
            index=0,
            kind="unexpected",
            packet="test:b",
            path=None,
            reference=ABSENT,
            candidate="02",
        ),
        Divergence(
            bot="bob",
            index=1,
            kind="unexpected",
            packet="test:c",
            path=None,
            reference=ABSENT,
            candidate="03",
        ),
    )


def test_a_bot_that_received_nothing_is_still_present() -> None:
    sent = packet("test:hello", b"\x07", direction=SERVERBOUND)
    reference = transcript(("alice", A))
    candidate = transcript(("alice", sent))
    assert [d.kind for d in compare(reference, candidate, []).divergences] == ["missing"]


def test_transcripts_of_different_scenarios_are_not_compared() -> None:
    other = transcript(scenario_id="status/ping")
    with pytest.raises(ValueError, match="'test/scenario' and 'status/ping'"):
        compare(transcript(), other, [])


def test_absent_reads_as_absent() -> None:
    assert repr(ABSENT) == "ABSENT"
