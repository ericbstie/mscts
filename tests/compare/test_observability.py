"""Observability: a Divergence is observable, or wire-only (ADR-0007).

compare() diffs both the raw values and their canonical form. A raw difference whose
canonical values are equal is wire-only: the vanilla client reads both alike. Every
other Divergence is observable.
"""

import pytest

from mscts.codec.packets import Codec, Packet, State
from mscts.compare import (
    ABSENT,
    Divergence,
    Mask,
    Observability,
    Outcome,
    Verdict,
    compare,
)
from tests.compare.build import CLIENTBOUND, packet, transcript

CODEC = Codec.load("26.3")
WIRE_ONLY, OBSERVABLE = Observability.WIRE_ONLY, Observability.OBSERVABLE


def status(json_response: str) -> Packet:
    data = CODEC.encode(
        State.STATUS, CLIENTBOUND, "minecraft:status_response", {"json_response": json_response}
    )
    return CODEC.decode(State.STATUS, CLIENTBOUND, data)


def _verdict(reference: str, candidate: str, *masks: Mask) -> Verdict:
    return compare(
        transcript(("alice", status(reference))), transcript(("alice", status(candidate))), masks
    )


def _wire_only(reference: str, candidate: str) -> Divergence:
    return Divergence(
        bot="alice",
        index=0,
        kind="field",
        packet="minecraft:status_response",
        path="json_response",
        reference=reference,
        candidate=candidate,
        observability=WIRE_ONLY,
    )


def test_observability_values_are_the_context_terms() -> None:
    assert [member.value for member in Observability] == ["observable", "wire-only"]


def test_a_divergence_is_observable_unless_classified_otherwise() -> None:
    # So a `failed` Divergence (made by run.judge) is observable.
    failed = Divergence(
        bot="", index=0, kind="failed", packet="", path=None, reference=ABSENT, candidate="x"
    )
    assert failed.observability is OBSERVABLE


# Every canonicalization in the canonical table: raw spellings the client reads alike.
EQUIVALENT_SPELLINGS = [
    ('{"a":1,"b":2}', '{"b":2,"a":1}'),
    ('{"a":1}', '{ "a" : 1 }\n'),
    ('{"a":"3"}', '{"a":"\\u0033"}'),
    ('{"description":"x"}', '{"description":{"text":"x"}}'),
    ('{"description":["a","b"]}', '{"description":[{"text":"a"},{"text":"b"}]}'),
    (
        '{"description":{"text":"a","extra":["b"]}}',
        '{"description":{"text":"a","extra":[{"text":"b"}]}}',
    ),
]
SPELLING_IDS = ["key-order", "whitespace", "escape", "bare-text", "list-elements", "extra"]


@pytest.mark.parametrize(("reference", "candidate"), EQUIVALENT_SPELLINGS, ids=SPELLING_IDS)
def test_each_canonicalization_is_a_wire_only_divergence_at_the_raw_path(
    reference: str, candidate: str
) -> None:
    verdict = _verdict(reference, candidate)
    assert verdict.divergences == (_wire_only(reference, candidate),)
    assert verdict.observable == ()


@pytest.mark.parametrize(("reference", "candidate"), EQUIVALENT_SPELLINGS, ids=SPELLING_IDS)
def test_swapping_the_sides_swaps_a_wire_only_divergence(reference: str, candidate: str) -> None:
    assert _verdict(candidate, reference).divergences == (_wire_only(candidate, reference),)


def test_only_wire_only_divergences_is_still_a_mismatch() -> None:
    assert _verdict('{"a":1,"b":2}', '{"b":2,"a":1}').outcome is Outcome.MISMATCH


def test_identical_bytes_match_exactly() -> None:
    # A Self-check: no Divergence of either kind.
    assert _verdict('{"b":2,"a":1}', '{"b":2,"a":1}') == Verdict("test/scenario", Outcome.MATCH)


def test_a_canonical_difference_is_observable_and_not_also_wire_only() -> None:
    verdict = _verdict('{"a":1,"b":2}', '{"b":3,"a":1}')
    assert verdict.divergences == (
        Divergence(
            bot="alice",
            index=0,
            kind="field",
            packet="minecraft:status_response",
            path="json_response.b",
            reference=2,
            candidate=3,
        ),
    )
    assert verdict.observable == verdict.divergences


def test_a_raw_difference_under_a_masked_canonical_difference_is_not_reported() -> None:
    mask = Mask(
        packet="minecraft:status_response",
        path="json_response.players.sample",
        reason="who is online varies",
    )
    verdict = _verdict('{"players":{"sample":[]}}', '{"players":{"sample":[{"name":"a"}]}}', mask)
    assert verdict.divergences == ()


def test_a_mask_on_the_raw_path_hides_its_wire_only_divergence() -> None:
    mask = Mask(packet="minecraft:status_response", path="json_response", reason="a test")
    assert _verdict('{"a":1,"b":2}', '{"b":2,"a":1}', mask).divergences == ()


def test_a_packet_without_a_canonical_form_has_only_observable_divergences() -> None:
    def play(text: str) -> Packet:
        return packet("minecraft:status_response", fields={"json_response": text})

    verdict = compare(
        transcript(("alice", play('{"a":1}'))), transcript(("alice", play('{ "a": 1 }'))), []
    )
    assert [d.observability for d in verdict.divergences] == [OBSERVABLE]


def test_observable_divergences_come_before_wire_only_ones_in_a_packet() -> None:
    # Raw fields beside json_response are compared as they stand.
    def with_extra(text: str, extra: int) -> Packet:
        return Packet(
            state=State.STATUS,
            direction=CLIENTBOUND,
            name="minecraft:status_response",
            packet_id=0,
            payload=b"",
            fields={"json_response": text, "z": extra},
        )

    verdict = compare(
        transcript(("alice", with_extra('{"a":1,"b":2}', 1))),
        transcript(("alice", with_extra('{"b":2,"a":1}', 2))),
        [],
    )
    assert [(d.path, d.observability) for d in verdict.divergences] == [
        ("z", OBSERVABLE),
        ("json_response", WIRE_ONLY),
    ]
