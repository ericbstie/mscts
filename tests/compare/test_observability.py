"""Observability: a Divergence is gameplay, or network traffic (ADR-0007).

compare() diffs both the raw values and their canonical form. A raw difference whose
canonical values are equal is network traffic: the vanilla client reads both alike. Every
other Divergence is gameplay.
"""

import pytest

from mscts.codec.packets import Codec, Packet, State
from mscts.compare import (
    ABSENT,
    Divergence,
    DivergenceKind,
    Mask,
    Observability,
    Outcome,
    Verdict,
    compare,
)
from tests.compare.build import CLIENTBOUND, divergence, packet, transcript

CODEC = Codec.load("26.3")
NETWORK_TRAFFIC, GAMEPLAY = Observability.NETWORK_TRAFFIC, Observability.GAMEPLAY


def status(json_response: str) -> Packet:
    data = CODEC.encode(
        State.STATUS, CLIENTBOUND, "minecraft:status_response", {"json_response": json_response}
    )
    return CODEC.decode(State.STATUS, CLIENTBOUND, data)


def _verdict(reference: str, candidate: str, *masks: Mask) -> Verdict:
    return compare(
        transcript(("alice", status(reference))), transcript(("alice", status(candidate))), masks
    )


def _network_traffic(reference: str, candidate: str) -> Divergence:
    return divergence(
        "field",
        packet="minecraft:status_response",
        path="json_response",
        reference=reference,
        candidate=candidate,
        test_case="status_response",
        observability=NETWORK_TRAFFIC,
    )


def test_observability_values_are_the_context_terms() -> None:
    assert [member.value for member in Observability] == ["gameplay", "network traffic"]


def test_a_divergence_is_gameplay_unless_classified_otherwise() -> None:
    # So a `failed` Divergence (made by run.judge) is gameplay.
    failed = divergence("failed", bot="", candidate="x")
    assert failed.observability is GAMEPLAY


# Every canonicalization of the JSON text alone: spellings of the same JSON value.
EQUIVALENT_SPELLINGS = [
    ('{"a":1,"b":2}', '{"b":2,"a":1}'),
    ('{"a":1}', '{ "a" : 1 }\n'),
    ('{"a":"3"}', '{"a":"\\u0033"}'),
]
SPELLING_IDS = ["key-order", "whitespace", "escape"]


@pytest.mark.parametrize(("reference", "candidate"), EQUIVALENT_SPELLINGS, ids=SPELLING_IDS)
def test_a_json_spelling_is_a_network_traffic_divergence_of_the_whole_text(
    reference: str, candidate: str
) -> None:
    verdict = _verdict(reference, candidate)
    assert verdict.divergences == (_network_traffic(reference, candidate),)
    assert verdict.gameplay == ()


@pytest.mark.parametrize(("reference", "candidate"), EQUIVALENT_SPELLINGS, ids=SPELLING_IDS)
def test_swapping_the_sides_swaps_a_network_traffic_divergence(
    reference: str, candidate: str
) -> None:
    assert _verdict(candidate, reference).divergences == (_network_traffic(candidate, reference),)


# Canonicalizations of JSON values: each is reported where the JSON values differ.
EQUIVALENT_VALUES = [
    ('{"description":"x"}', '{"description":{"text":"x"}}', [("description", "x", {"text": "x"})]),
    (
        '{"description":["a","b"]}',
        '{"description":[{"text":"a"},{"text":"b"}]}',
        [("description[0]", "a", {"text": "a"}), ("description[1]", "b", {"text": "b"})],
    ),
    (
        '{"description":{"text":"a","extra":["b"]}}',
        '{"description":{"text":"a","extra":[{"text":"b"}]}}',
        [("description.extra[0]", "b", {"text": "b"})],
    ),
    (
        '{"favicon":"x"}',
        '{"favicon":"x","enforceSecureChat":true}',
        [("enforceSecureChat", ABSENT, True)],
    ),
    ("{}", '{"favicon":null}', [("favicon", ABSENT, None)]),
    ("{}", '{"enforcesSecureChat":false}', [("enforcesSecureChat", ABSENT, False)]),
    # Key order is not reported beside a difference of value (PLAN, Comparison semantics).
    ('{"a":1,"favicon":null}', '{"favicon":2,"a":1}', []),
]
VALUE_IDS = [
    "bare-text",
    "list-elements",
    "extra",
    "unread-key",
    "null-member",
    "declared-default",
    "reordered-and-different",
]


@pytest.mark.parametrize(("reference", "candidate", "found"), EQUIVALENT_VALUES, ids=VALUE_IDS)
def test_a_canonical_value_is_a_network_traffic_divergence_at_its_json_path(
    reference: str, candidate: str, found: list[tuple[str, object, object]]
) -> None:
    network_traffic = [
        (d.path, d.reference, d.candidate)
        for d in _verdict(reference, candidate).divergences
        if d.observability is NETWORK_TRAFFIC
    ]
    assert network_traffic == [(f"json_response.{path}", ref, cand) for path, ref, cand in found]
    swapped = [
        (d.path, d.candidate, d.reference)
        for d in _verdict(candidate, reference).divergences
        if d.observability is NETWORK_TRAFFIC
    ]
    assert swapped == network_traffic


def test_only_network_traffic_divergences_is_still_a_mismatch() -> None:
    assert _verdict('{"a":1,"b":2}', '{"b":2,"a":1}').outcome is Outcome.MISMATCH


def test_identical_bytes_match_exactly() -> None:
    # A Self-check: no Divergence of either kind.
    assert _verdict('{"b":2,"a":1}', '{"b":2,"a":1}') == Verdict("test/group", Outcome.MATCH)


def test_a_canonical_difference_is_gameplay_and_not_also_network_traffic() -> None:
    verdict = _verdict('{"favicon":"a","players":2}', '{"players":3,"favicon":"a"}')
    assert verdict.divergences == (
        divergence(
            "field",
            packet="minecraft:status_response",
            path="json_response.players",
            reference=2,
            candidate=3,
            test_case="status_response.players",
        ),
    )
    assert verdict.gameplay == verdict.divergences


def test_a_raw_difference_under_a_masked_canonical_difference_is_not_reported() -> None:
    mask = Mask(
        packet="minecraft:status_response",
        path="json_response.players.sample",
        reason="who is online varies",
    )
    verdict = _verdict(
        '{"players":{"sample":[{"name":"b"}]}}',
        '{"players":{"sample":[{"name":"a"},{"name":"c"}]}}',
        mask,
    )
    assert verdict.divergences == ()


def test_a_mask_hides_a_network_traffic_difference_inside_its_value() -> None:
    """Only the description's spelling is reported: the unread member is under the Mask."""
    mask = Mask(packet="minecraft:status_response", path="json_response.players", reason="a test")
    verdict = _verdict(
        '{"description":"x","players":{"max":1,"online":0,"extra":1}}',
        '{"description":{"text":"x"},"players":{"max":1,"online":0}}',
        mask,
    )
    assert [(d.path, d.observability) for d in verdict.divergences] == [
        ("json_response.description", NETWORK_TRAFFIC)
    ]


def test_a_mask_on_the_raw_path_hides_its_network_traffic_divergence() -> None:
    mask = Mask(packet="minecraft:status_response", path="json_response", reason="a test")
    assert _verdict('{"a":1,"b":2}', '{"b":2,"a":1}', mask).divergences == ()


def test_a_packet_without_a_canonical_form_has_only_gameplay_divergences() -> None:
    def play(text: str) -> Packet:
        return packet("minecraft:status_response", fields={"json_response": text})

    verdict = compare(
        transcript(("alice", play('{"a":1}'))), transcript(("alice", play('{ "a": 1 }'))), []
    )
    assert [d.observability for d in verdict.divergences] == [GAMEPLAY]


def test_gameplay_divergences_come_before_network_traffic_ones_in_a_packet() -> None:
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
        ("z", GAMEPLAY),
        ("json_response", NETWORK_TRAFFIC),
    ]


@pytest.mark.parametrize("kind", ["bot", "failed"])
def test_a_divergence_about_the_whole_group_is_never_network_traffic(
    kind: DivergenceKind,
) -> None:
    # #221: such a Divergence gives the Group a line of its own, which always fails.
    with pytest.raises(ValueError, match=f"a {kind} Divergence is gameplay"):
        Divergence(
            bot="alice",
            index=0,
            kind=kind,
            packet="",
            path=None,
            reference=ABSENT,
            candidate="kicked",
            test_case="",
            observability=NETWORK_TRAFFIC,
        )
