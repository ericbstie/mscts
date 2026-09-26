"""Canonicalization: protocol equivalences compare() applies before Masks and the diff.

These tests look at the observable Divergences; a difference Canonicalization makes
equal is still reported, as wire-only (test_observability.py).

Status packets are built through the Target's real Codec.
"""

import pytest

from mscts.codec.packets import Codec, Packet, State
from mscts.compare import ABSENT, Divergence, Mask, compare
from tests.compare.build import CLIENTBOUND, packet, transcript

CODEC = Codec.load("26.3")

VANILLA = (
    '{"description":"mscts","players":{"max":20,"online":0},'
    '"version":{"name":"26.3","protocol":777}}'
)
"""What vanilla 26.3 answered for the default ServerSpec (docs/research, verified)."""

PUMPKIN_STYLE = (
    '{"version":{"name":"26.3","protocol":777},'
    '"players":{"max":1000,"online":0,"sample":[]},'
    '"description":{"text":"mscts"},'
    '"favicon":"data:image/png;base64,iVBORw0KGgo="}'
)
"""Shaped like Pumpkin nightly's status (docs/research): sample [], a favicon, an object
description."""


def status(json_response: str) -> Packet:
    data = CODEC.encode(
        State.STATUS, CLIENTBOUND, "minecraft:status_response", {"json_response": json_response}
    )
    return CODEC.decode(State.STATUS, CLIENTBOUND, data)


def _diff(reference: str, candidate: str, *masks: Mask) -> list[tuple[str | None, object, object]]:
    verdict = compare(
        transcript(("alice", status(reference))), transcript(("alice", status(candidate))), masks
    )
    assert {(d.index, d.kind, d.packet) for d in verdict.divergences} <= {
        (0, "field", "minecraft:status_response")
    }
    # What a raw spelling changes is wire-only (test_observability.py); this is the rest.
    return [(d.path, d.reference, d.candidate) for d in verdict.observable]


def test_vanilla_against_itself_matches() -> None:
    assert _diff(VANILLA, VANILLA) == []


def test_a_pumpkin_style_status_differs_from_vanilla_only_where_a_client_could_tell() -> None:
    assert _diff(VANILLA, PUMPKIN_STYLE) == [
        ("json_response.favicon", ABSENT, "data:image/png;base64,iVBORw0KGgo="),
        ("json_response.players.max", 20, 1000),
        ("json_response.players.sample", ABSENT, []),
    ]


def test_swapping_the_sides_swaps_the_values() -> None:
    assert _diff(PUMPKIN_STYLE, VANILLA) == [
        ("json_response.favicon", "data:image/png;base64,iVBORw0KGgo=", ABSENT),
        ("json_response.players.max", 1000, 20),
        ("json_response.players.sample", [], ABSENT),
    ]


def test_json_key_order_whitespace_and_escapes_do_not_matter() -> None:
    reordered = (
        '{ "version" : {"protocol":777, "name":"26.\\u0033"},\n'
        '  "players": {"online":0,"max":20}, "description":"mscts" }'
    )
    assert _diff(VANILLA, reordered) == []


def test_a_json_difference_is_reported_at_its_json_path() -> None:
    changed = VANILLA.replace('"protocol":777', '"protocol":776')
    assert _diff(VANILLA, changed) == [("json_response.version.protocol", 777, 776)]


def test_a_bare_string_description_is_the_same_as_an_object_with_only_text() -> None:
    assert _diff('{"description":"mscts"}', '{"description":{"text":"mscts"}}') == []


def test_a_different_description_text_is_reported_at_its_text() -> None:
    assert _diff('{"description":"mscts"}', '{"description":{"text":"A Server"}}') == [
        ("json_response.description.text", "mscts", "A Server")
    ]


@pytest.mark.parametrize(
    ("reference", "candidate"),
    [
        ('{"text":"a","extra":["b"]}', '{"text":"a","extra":[{"text":"b"}]}'),
        (
            '{"text":"a","extra":[{"text":"b","extra":["c"]}]}',
            '{"text":"a","extra":[{"text":"b","extra":[{"text":"c"}]}]}',
        ),
        ('["a","b"]', '[{"text":"a"},{"text":"b"}]'),
        ('[["a"],"b"]', '[[{"text":"a"}],{"text":"b"}]'),
        ('"a"', '{"text":"a"}'),
    ],
)
def test_text_components_inside_a_description_are_canonical_too(
    reference: str, candidate: str
) -> None:
    assert _diff(f'{{"description":{reference}}}', f'{{"description":{candidate}}}') == []


@pytest.mark.parametrize(
    ("reference", "candidate", "divergences"),
    [
        # The list form means "first, with the rest appended to its extra", but that
        # equivalence is not encoded (PLAN open questions).
        (
            '["a","b"]',
            '{"text":"a","extra":["b"]}',
            [
                (
                    "json_response.description",
                    [{"text": "a"}, {"text": "b"}],
                    {"text": "a", "extra": [{"text": "b"}]},
                )
            ],
        ),
        # An explicit style value, an empty extra, an explicit type: not the same Component
        # (or not valid), so not canonicalized.
        ('"x"', '{"text":"x","bold":false}', [("json_response.description.bold", ABSENT, False)]),
        ('"x"', '{"text":"x","extra":[]}', [("json_response.description.extra", ABSENT, [])]),
        ('"x"', '{"type":"text","text":"x"}', [("json_response.description.type", ABSENT, "text")]),
    ],
)
def test_only_the_bare_string_equivalence_is_encoded(
    reference: str, candidate: str, divergences: list[tuple[str, object, object]]
) -> None:
    assert _diff(f'{{"description":{reference}}}', f'{{"description":{candidate}}}') == divergences


def test_strings_outside_the_description_are_not_text_components() -> None:
    reference = '{"version":{"name":"26.3"},"players":{"sample":[{"name":"a"}]}}'
    candidate = '{"version":{"name":{"text":"26.3"}},"players":{"sample":[{"name":{"text":"a"}}]}}'
    assert [path for path, _, _ in _diff(reference, candidate)] == [
        "json_response.players.sample[0].name",
        "json_response.version.name",
    ]


@pytest.mark.parametrize(
    ("candidate", "divergence"),
    [
        (
            '{"players":{"max":20,"online":0,"sample":[]}}',
            ("json_response.players.sample", ABSENT, []),
        ),
        (
            '{"players":{"max":20,"online":0},"enforcesSecureChat":false}',
            ("json_response.enforcesSecureChat", ABSENT, False),
        ),
        (
            '{"players":{"max":20,"online":0},"description":""}',
            ("json_response.description", ABSENT, {"text": ""}),
        ),
    ],
)
def test_declared_defaults_are_not_filled_in(
    candidate: str, divergence: tuple[str, object, object]
) -> None:
    # The Reference's decoder reads each pair alike, but that class is an open question.
    assert _diff('{"players":{"max":20,"online":0}}', candidate) == [divergence]


@pytest.mark.parametrize(
    ("candidate", "divergence"),
    [
        ('{"v":20.0}', ("json_response.v", 20, 20.0)),
        ('{"v":true}', ("json_response.v", 20, True)),
        ('{"v":null}', ("json_response.v", 20, None)),
        ('{"v":"20"}', ("json_response.v", 20, "20")),
    ],
)
def test_json_numbers_booleans_and_null_keep_their_types(
    candidate: str, divergence: tuple[str, object, object]
) -> None:
    assert _diff('{"v":20}', candidate) == [divergence]


@pytest.mark.parametrize(
    "not_strict_json",
    [
        "{",
        '{"a":1}trailing',
        '{"a":1,"a":1}',
        '{"a":NaN}',
        '{"a":Infinity}',
        "{a:1}",
        "{'a':1}",
    ],
)
def test_anything_but_strict_json_is_compared_as_the_raw_string(not_strict_json: str) -> None:
    assert _diff(not_strict_json, not_strict_json) == []
    assert _diff('{"a":1}', not_strict_json) == [("json_response", {"a": 1}, not_strict_json)]


def test_json_nested_deeper_than_255_is_compared_as_the_raw_string() -> None:
    # Gson 2.14.0 (the client's) stops at 255 levels; this also bounds the recursion.
    def nested(depth: int, gap: str = "") -> str:
        return "[" * depth + gap + "]" * depth

    assert _diff(nested(255), nested(255, " ")) == []
    assert _diff(nested(256), nested(256, " ")) == [
        ("json_response", nested(256), nested(256, " "))
    ]
    assert _diff(nested(5000), nested(5000)) == []


def test_json_too_deep_for_the_json_module_is_compared_as_the_raw_string() -> None:
    # The deepest a String (32767) holds; json.loads itself raises RecursionError on it.
    deepest = "[" * 16383 + "]" * 16383
    assert _diff(deepest, deepest) == []
    assert _diff('{"a":1}', deepest) == [("json_response", {"a": 1}, deepest)]


def test_masks_apply_to_the_canonical_form() -> None:
    mask = Mask(
        packet="minecraft:status_response",
        path="json_response.description.text",
        reason="the motd is the Candidate's own",
    )
    assert _diff('{"description":"mscts"}', '{"description":{"text":"other"}}', mask) == []


def test_canonicalization_is_keyed_by_state_as_well_as_name() -> None:
    def play_status(text: str) -> Packet:
        return packet("minecraft:status_response", fields={"json_response": text})

    verdict = compare(
        transcript(("alice", play_status('{"a":1}'))),
        transcript(("alice", play_status('{ "a": 1 }'))),
        [],
    )
    assert verdict.divergences == (
        Divergence(
            bot="alice",
            index=0,
            kind="field",
            packet="minecraft:status_response",
            path="json_response",
            reference='{"a":1}',
            candidate='{ "a": 1 }',
        ),
    )


def test_canonicalization_leaves_the_transcript_untouched() -> None:
    reference = transcript(("alice", status(VANILLA)))
    compare(reference, transcript(("alice", status(PUMPKIN_STYLE))), [])
    assert reference.events[0].packet.fields == {"json_response": VANILLA}
