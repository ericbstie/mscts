"""Canonicalization: protocol equivalences compare() applies before Masks and the diff.

These tests look at the gameplay Divergences; a difference Canonicalization makes
equal is still reported, as network traffic (test_observability.py).

Status packets are built through the Target's real Codec.
"""

from collections.abc import Iterable
from typing import cast

import pytest
from support.compared import PUMPKIN_NIGHTLY, VANILLA, status
from support.play import CLIENTBOUND
from support.text_nbt import Writable, nbt, wrapped

from mscts.codec.nbt import Numeric
from mscts.codec.packets import Codec, Packet, State
from mscts.compare import ABSENT, Divergence, Mask, Observability, Verdict, compare
from tests.compare.build import divergence, packet, transcript

CODEC = Codec.load("26.3")


PUMPKIN_STYLE = (
    '{"version":{"name":"26.3","protocol":777},'
    '"players":{"max":1000,"online":0,"sample":[]},'
    '"description":{"text":"mscts"},'
    '"favicon":"data:image/png;base64,iVBORw0KGgo="}'
)
"""Shaped like Pumpkin nightly's status (docs/research): sample [], a favicon, an object
description."""


def _diff(reference: str, candidate: str, *masks: Mask) -> list[tuple[str | None, object, object]]:
    verdict = compare(
        transcript(("alice", status(reference))), transcript(("alice", status(candidate))), masks
    )
    assert {(d.index, d.kind, d.packet) for d in verdict.divergences} <= {
        (0, "field", "minecraft:status_response")
    }
    # What a raw spelling changes is network traffic (test_observability.py); this is the rest.
    return [(d.path, d.reference, d.candidate) for d in verdict.gameplay]


def test_vanilla_against_itself_matches() -> None:
    assert _diff(VANILLA, VANILLA) == []


def test_a_pumpkin_style_status_differs_from_vanilla_only_where_a_client_could_tell() -> None:
    # Its "sample": [] is the declared default of an absent sample (ADR-0007's example).
    assert _diff(VANILLA, PUMPKIN_STYLE) == [
        ("json_response.favicon", ABSENT, "data:image/png;base64,iVBORw0KGgo="),
        ("json_response.players.max", 20, 1000),
    ]


def test_swapping_the_sides_swaps_the_values() -> None:
    assert _diff(PUMPKIN_STYLE, VANILLA) == [
        ("json_response.favicon", "data:image/png;base64,iVBORw0KGgo=", ABSENT),
        ("json_response.players.max", 1000, 20),
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
        # An explicit style value, an explicit type: not shown to be the same Component, so
        # not canonicalized.
        ('"x"', '{"text":"x","bold":false}', [("json_response.description.bold", ABSENT, False)]),
        ('"x"', '{"type":"text","text":"x"}', [("json_response.description.type", ABSENT, "text")]),
        # A list whose first element is not a text component.
        ('"x"', '[1,"x"]', [("json_response.description", {"text": "x"}, [1, {"text": "x"}])]),
    ],
)
def test_spellings_not_shown_to_read_alike_stay_significant(
    reference: str, candidate: str, divergences: list[tuple[str, object, object]]
) -> None:
    assert _diff(f'{{"description":{reference}}}', f'{{"description":{candidate}}}') == divergences


@pytest.mark.parametrize(
    ("reference", "candidate"),
    [
        ('["a","b"]', '{"text":"a","extra":["b"]}'),
        ('["a"]', '"a"'),
        ('[{"text":"a","bold":true},"b"]', '{"text":"a","bold":true,"extra":["b"]}'),
        ('[{"text":"a","extra":["x"]},"b"]', '{"text":"a","extra":["x","b"]}'),
        ('[["a","b"],"c"]', '{"text":"a","extra":["b","c"]}'),
        ('{"text":"a","extra":[["b","c"]]}', '{"text":"a","extra":[{"text":"b","extra":["c"]}]}'),
    ],
)
def test_a_list_is_its_first_component_with_the_rest_added_to_its_extra(
    reference: str, candidate: str
) -> None:
    # ComponentSerialization.createFromList: the first's copy, then append each of the rest
    # (docs/research/2026-09-26-comparison.md).
    assert _diff(f'{{"description":{reference}}}', f'{{"description":{candidate}}}') == []


@pytest.mark.parametrize(
    ("reference", "candidate", "divergences"),
    [
        (
            '["a","b"]',
            '{"text":"a","extra":["c"]}',
            [("json_response.description.extra[0].text", "b", "c")],
        ),
        (
            '["a","b"]',
            '["b","a"]',
            [
                ("json_response.description.extra[0].text", "b", "a"),
                ("json_response.description.text", "a", "b"),
            ],
        ),
        (
            '["a","b"]',
            '{"text":"a","bold":true,"extra":["b"]}',
            [("json_response.description.bold", ABSENT, True)],
        ),
        (
            '[{"text":"a"},{"text":"b","bold":true}]',
            '{"text":"a","bold":true,"extra":["b"]}',
            [
                ("json_response.description.bold", ABSENT, True),
                ("json_response.description.extra[0].bold", True, ABSENT),
            ],
        ),
    ],
)
def test_a_list_and_an_object_that_read_differently_still_differ(
    reference: str, candidate: str, divergences: list[tuple[str, object, object]]
) -> None:
    assert _diff(f'{{"description":{reference}}}', f'{{"description":{candidate}}}') == divergences


@pytest.mark.parametrize(
    "refused",
    [
        '{"text":"x","extra":[]}',
        "[]",
        '{"text":"a","extra":[{"text":"b","extra":[]}]}',
        '["a",[]]',
        '[{"text":"a","extra":[]},"b"]',
    ],
)
def test_a_description_with_an_empty_list_reads_as_no_description(refused: str) -> None:
    # ExtraCodecs.nonEmptyList refuses it, and ServerStatus.CODEC reads a description it
    # cannot decode as CommonComponents.EMPTY (docs/research/2026-09-26-comparison.md).
    assert _diff("{}", f'{{"description":{refused}}}') == []
    assert _diff('{"description":"x"}', f'{{"description":{refused}}}') == [
        ("json_response.description", {"text": "x"}, ABSENT)
    ]


def test_strings_outside_the_description_are_not_text_components() -> None:
    reference = '{"version":{"name":"26.3"},"players":{"sample":[{"name":"a"}]}}'
    candidate = '{"version":{"name":{"text":"26.3"}},"players":{"sample":[{"name":{"text":"a"}}]}}'
    assert [path for path, _, _ in _diff(reference, candidate)] == [
        "json_response.players.sample[0].name",
        "json_response.version.name",
    ]


ABSENT_DEFAULTS = '{"players":{"max":20,"online":0}}'

DECLARED_DEFAULTS = [
    ('{"players":{"max":20,"online":0,"sample":[]}}', "players.sample", []),
    ('{"players":{"max":20,"online":0},"enforcesSecureChat":false}', "enforcesSecureChat", False),
    ('{"players":{"max":20,"online":0},"description":""}', "description", ""),
    ('{"players":{"max":20,"online":0},"description":{"text":""}}', "description", {"text": ""}),
    ('{"players":{"max":20,"online":0},"description":[""]}', "description", [""]),
]


def _network_traffic(reference: str, candidate: str) -> list[tuple[str | None, object, object]]:
    verdict = compare(
        transcript(("alice", status(reference))), transcript(("alice", status(candidate))), []
    )
    return [
        (d.path, d.reference, d.candidate) for d in verdict.divergences if d not in verdict.gameplay
    ]


@pytest.mark.parametrize(
    ("candidate", "path", "sent"),
    DECLARED_DEFAULTS,
    ids=["sample", "enforcesSecureChat", "description", "description-object", "description-list"],
)
def test_a_declared_default_is_the_same_as_its_absence(
    candidate: str, path: str, sent: object
) -> None:
    # ServerStatus.CODEC reads each absent field as its default (PLAN, Comparison
    # semantics), so sending the default is a network traffic difference, at its JSON path.
    assert _diff(ABSENT_DEFAULTS, candidate) == []
    assert _diff(candidate, ABSENT_DEFAULTS) == []
    assert _network_traffic(ABSENT_DEFAULTS, candidate) == [(f"json_response.{path}", ABSENT, sent)]


@pytest.mark.parametrize(
    ("candidate", "divergence"),
    [
        (
            '{"players":{"max":20,"online":0,"sample":[{"name":"a","id":"x"}]}}',
            ("json_response.players.sample", ABSENT, [{"name": "a", "id": "x"}]),
        ),
        (
            '{"players":{"max":20,"online":0},"enforcesSecureChat":true}',
            ("json_response.enforcesSecureChat", ABSENT, True),
        ),
        (
            '{"players":{"max":20,"online":0},"enforcesSecureChat":0}',
            ("json_response.enforcesSecureChat", ABSENT, 0),
        ),
        (
            '{"players":{"max":20,"online":0},"description":" "}',
            ("json_response.description", ABSENT, {"text": " "}),
        ),
        (
            '{"players":{"max":20,"online":0},"description":{"text":"","bold":false}}',
            ("json_response.description", ABSENT, {"text": "", "bold": False}),
        ),
        ('{"players":{"max":20,"online":0},"favicon":""}', ("json_response.favicon", ABSENT, "")),
    ],
    ids=[
        "sample-element",
        "secure-chat-true",
        "secure-chat-number",
        "description-space",
        "description-style",
        "favicon-has-no-default",
    ],
)
def test_only_the_exact_declared_default_is_its_absence(
    candidate: str, divergence: tuple[str, object, object]
) -> None:
    assert _diff('{"players":{"max":20,"online":0}}', candidate) == [divergence]


def test_pumpkin_nightlys_status_differs_from_vanillas_in_network_traffic_only() -> None:
    assert _diff(VANILLA, PUMPKIN_NIGHTLY) == []
    assert _network_traffic(VANILLA, PUMPKIN_NIGHTLY) == [
        ("json_response.description", "mscts", {"text": "mscts"}),
        ("json_response.enforceSecureChat", ABSENT, True),
        ("json_response.favicon", ABSENT, None),
        ("json_response.players.sample", ABSENT, []),
    ]


@pytest.mark.parametrize(
    ("candidate", "path", "sent"),
    [
        ('{"players":{"max":20,"online":0},"enforceSecureChat":true}', "enforceSecureChat", True),
        ('{"players":{"max":20,"online":0},"favicon":null}', "favicon", None),
        ('{"players":{"max":20,"online":0},"description":null}', "description", None),
        ('{"players":{"max":20,"online":0},"version":null}', "version", None),
        ('{"players":{"max":20,"online":0,"sample":null}}', "players.sample", None),
        ('{"players":{"max":20,"online":0,"MAX":1000}}', "players.MAX", 1000),
        ('{"players":{"max":20,"online":0},"sample":[]}', "sample", []),
    ],
    ids=[
        "misspelled-secure-chat",
        "null-favicon",
        "null-description",
        "null-version",
        "null-sample",
        "unknown-players-key",
        "sample-outside-players",
    ],
)
def test_a_member_the_client_never_reads_is_a_network_traffic_difference(
    candidate: str, path: str, sent: object
) -> None:
    # ServerStatus's record codecs look fields up by name, and JsonOps reads a JSON null
    # member as a missing one (docs/research/2026-09-26-comparison.md).
    assert _diff(ABSENT_DEFAULTS, candidate) == []
    assert _diff(candidate, ABSENT_DEFAULTS) == []
    assert _network_traffic(ABSENT_DEFAULTS, candidate) == [(f"json_response.{path}", ABSENT, sent)]


def test_the_version_ignores_a_key_it_does_not_name() -> None:
    reference = '{"version":{"name":"26.3","protocol":777}}'
    assert _diff(reference, '{"version":{"name":"26.3","protocol":777,"brand":"x"}}') == []


@pytest.mark.parametrize(
    ("candidate", "divergence"),
    [
        # Inside a text component, or a sample entry, keys and nulls stay significant: their
        # codecs are not shown to read them by name only.
        ('{"description":{"text":"a","x":1}}', ("json_response.description.x", ABSENT, 1)),
        ('{"description":{"text":"a","x":null}}', ("json_response.description.x", ABSENT, None)),
        (
            '{"description":[{"text":"a","extra":null},"b"]}',
            (
                "json_response.description",
                {"text": "a"},
                [{"text": "a", "extra": None}, {"text": "b"}],
            ),
        ),
        (
            '{"description":{"text":"a"},"players":{"sample":[{"name":"a","x":null}]}}',
            ("json_response.players.sample[0].x", ABSENT, None),
        ),
    ],
    ids=["description-key", "description-null", "description-list-null-extra", "sample-entry-null"],
)
def test_unknown_keys_and_nulls_elsewhere_stay_significant(
    candidate: str, divergence: tuple[str, object, object]
) -> None:
    reference = '{"description":{"text":"a"},"players":{"sample":[{"name":"a"}]}}'
    if "sample" not in candidate:
        reference = '{"description":{"text":"a"}}'
    assert _diff(reference, candidate) == [divergence]


@pytest.mark.parametrize(
    ("candidate", "divergence"),
    [
        ('{"players":{"max":20.0}}', ("json_response.players.max", 20, 20.0)),
        ('{"players":{"max":true}}', ("json_response.players.max", 20, True)),
        ('{"players":{"max":"20"}}', ("json_response.players.max", 20, "20")),
        # A null member reads as missing (docs/research): a required one stays a difference.
        ('{"players":{"max":null}}', ("json_response.players.max", 20, ABSENT)),
    ],
)
def test_json_numbers_booleans_and_null_keep_their_types(
    candidate: str, divergence: tuple[str, object, object]
) -> None:
    assert _diff('{"players":{"max":20}}', candidate) == [divergence]


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
    assert _diff('{"favicon":"x"}', not_strict_json) == [
        ("json_response", {"favicon": "x"}, not_strict_json)
    ]


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
    assert _diff('{"favicon":"x"}', deepest) == [("json_response", {"favicon": "x"}, deepest)]


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
        divergence(
            "field",
            packet="minecraft:status_response",
            path="json_response",
            reference='{"a":1}',
            candidate='{ "a": 1 }',
            test_case="status_response.json_response",
        ),
    )


def test_canonicalization_leaves_the_transcript_untouched() -> None:
    reference = transcript(("alice", status(VANILLA)))
    compare(reference, transcript(("alice", status(PUMPKIN_STYLE))), [])
    assert reference.events[0].packet.fields == {"json_response": VANILLA}


# Text components in play (#335): each is NBT, decoded and compared as the component the client
# reads it into (docs/research/2026-09-26-comparison.md, Text components in NBT).


def _disconnect(reason: bytes) -> Packet:
    data = CODEC.encode(State.PLAY, CLIENTBOUND, "minecraft:disconnect", {"reason": reason})
    return CODEC.decode(State.PLAY, CLIENTBOUND, data)


def _compared(name: str, reference: Packet, candidate: Packet) -> Verdict:
    verdict = compare(transcript(("alice", reference)), transcript(("alice", candidate)), [])
    assert {(d.index, d.kind, d.packet) for d in verdict.divergences} <= {(0, "field", name)}
    return verdict


def _shown(divergences: Iterable[Divergence]) -> list[tuple[str | None, object, object, str]]:
    return [(d.path, d.reference, d.candidate, d.test_case) for d in divergences]


def _traffic(verdict: Verdict) -> tuple[Divergence, ...]:
    return tuple(d for d in verdict.divergences if d.observability is Observability.NETWORK_TRAFFIC)


def test_the_same_kick_reason_in_two_encodings_is_no_gameplay_divergence() -> None:
    verdict = _compared(
        "minecraft:disconnect", _disconnect(nbt("kick")), _disconnect(nbt({"text": "kick"}))
    )
    assert verdict.gameplay == ()
    assert _shown(_traffic(verdict)) == [
        ("reason", "kick", {"text": "kick"}, "play:disconnect.reason")
    ]


def test_a_kick_reason_with_another_translation_key_is_a_gameplay_divergence_at_the_key() -> None:
    verdict = _compared(
        "minecraft:disconnect",
        _disconnect(nbt({"translate": "multiplayer.disconnect.flying"})),
        _disconnect(nbt({"translate": "multiplayer.disconnect.invalid_player_movement"})),
    )
    assert _shown(verdict.gameplay) == [
        (
            "reason.translate",
            "multiplayer.disconnect.flying",
            "multiplayer.disconnect.invalid_player_movement",
            "play:disconnect.reason",
        )
    ]
    assert _traffic(verdict) == ()


def test_a_kick_reason_with_its_keys_in_another_order_is_network_traffic() -> None:
    verdict = _compared(
        "minecraft:disconnect",
        _disconnect(nbt({"translate": "k", "color": "red"})),
        _disconnect(nbt({"color": "red", "translate": "k"})),
    )
    assert verdict.gameplay == ()
    assert [(d.path, d.test_case) for d in _traffic(verdict)] == [
        ("reason", "play:disconnect.reason")
    ]


def test_a_kick_reason_as_a_list_is_its_first_component_with_the_rest_in_its_extra() -> None:
    verdict = _compared(
        "minecraft:disconnect",
        _disconnect(nbt(["a", "b"])),
        _disconnect(nbt({"text": "a", "extra": ["b"]})),
    )
    assert verdict.gameplay == ()
    assert [d.path for d in _traffic(verdict)] == ["reason"]


def test_a_difference_inside_a_component_that_reads_differently_is_gameplay_alone() -> None:
    # The raw difference is at reason[0].bold, where the canonical forms hold nothing: it is
    # network traffic only if the whole component reads the same (_COVERS).
    verdict = _compared(
        "minecraft:disconnect",
        _disconnect(nbt([{"text": "a"}, {"text": "b"}])),
        _disconnect(nbt([{"text": "a", "bold": "x"}, {"text": "b"}])),
    )
    assert _shown(verdict.gameplay) == [("reason.bold", ABSENT, "x", "play:disconnect.reason")]
    assert _traffic(verdict) == ()


def test_a_list_element_wrapped_in_a_compound_with_an_empty_name_is_that_element() -> None:
    verdict = _compared(
        "minecraft:disconnect",
        _disconnect(nbt({"text": "a", "extra": ["b", "c"]})),
        _disconnect(nbt({"text": "a", "extra": wrapped("b", {"text": "c"})})),
    )
    assert verdict.gameplay == ()
    assert [d.path for d in _traffic(verdict)] == ["reason.extra[0]", "reason.extra[1]"]


def test_only_the_list_element_is_unwrapped_not_a_wrapper_inside_it() -> None:
    verdict = _compared(
        "minecraft:disconnect",
        _disconnect(nbt({"text": "a", "extra": ["b"]})),
        _disconnect(nbt({"text": "a", "extra": wrapped({"": "b"})})),
    )
    assert [d.path for d in verdict.gameplay] == ['reason.extra[0][""]', "reason.extra[0].text"]


def test_a_kick_reason_nested_as_deep_as_nbt_allows_is_compared() -> None:
    # Past 255 levels the value is one leaf (Nested), never equal to what a server sent.
    deep: Writable = "a"
    for _ in range(511):
        deep = [deep]
    verdict = _compared("minecraft:disconnect", _disconnect(nbt(deep)), _disconnect(nbt("a")))
    assert [d.test_case for d in verdict.gameplay] == ["play:disconnect.reason"]


def test_a_text_component_that_names_its_type_text_is_one_that_does_not() -> None:
    verdict = _compared(
        "minecraft:disconnect",
        _disconnect(nbt({"text": "a", "extra": ["b"]})),
        _disconnect(nbt({"type": "text", "text": "a", "extra": [{"type": "text", "text": "b"}]})),
    )
    assert verdict.gameplay == ()


@pytest.mark.parametrize(
    "typed",
    [
        pytest.param({"type": "translatable", "text": "a", "translate": "a"}, id="another-type"),
        pytest.param({"type": "text", "translate": "a"}, id="no-text"),
    ],
)
def test_a_type_other_than_text_or_a_text_type_without_text_stays(typed: Writable) -> None:
    verdict = _compared(
        "minecraft:disconnect", _disconnect(nbt({"text": "a"})), _disconnect(nbt(typed))
    )
    assert "reason.type" in [d.path for d in verdict.gameplay]


_FLAGS = ("bold", "italic", "underlined", "strikethrough", "obfuscated")


@pytest.mark.parametrize("flag", _FLAGS)
@pytest.mark.parametrize(
    ("vanilla", "sent"),
    [
        pytest.param(Numeric("byte", 1), Numeric("int", 2), id="true"),
        pytest.param(Numeric("byte", 1), Numeric("double", float("nan")), id="nan-is-true"),
        pytest.param(Numeric("byte", 0), Numeric("long", 0), id="false"),
        pytest.param(Numeric("byte", 0), Numeric("float", -0.0), id="minus-zero-is-false"),
    ],
)
def test_a_style_flag_is_true_for_any_number_but_zero(
    flag: str, vanilla: Numeric, sent: Numeric
) -> None:
    verdict = _compared(
        "minecraft:disconnect",
        _disconnect(nbt({"text": "a", flag: vanilla})),
        _disconnect(nbt({"text": "a", flag: sent})),
    )
    assert verdict.gameplay == ()


def test_a_style_flag_that_is_a_string_stays_as_it_is() -> None:
    verdict = _compared(
        "minecraft:disconnect",
        _disconnect(nbt({"text": "a", "bold": Numeric("byte", 1)})),
        _disconnect(nbt({"text": "a", "bold": "1"})),
    )
    assert _shown(verdict.gameplay) == [("reason.bold", True, "1", "play:disconnect.reason")]


@pytest.mark.parametrize("flag", _FLAGS)
def test_a_false_style_flag_is_not_an_absent_one(flag: str) -> None:
    verdict = _compared(
        "minecraft:disconnect",
        _disconnect(nbt({"text": "a"})),
        _disconnect(nbt({"text": "a", flag: Numeric("byte", 0)})),
    )
    assert _shown(verdict.gameplay) == [(f"reason.{flag}", ABSENT, False, "play:disconnect.reason")]


def test_a_kick_reason_that_does_not_decode_is_compared_as_its_bytes() -> None:
    no_tag, kick = b"\x00", nbt("kick")
    verdict = _compared("minecraft:disconnect", _disconnect(kick), _disconnect(no_tag))
    assert _shown(verdict.gameplay) == [
        ("reason", {"text": "kick"}, no_tag, "play:disconnect.reason")
    ]


_COMPONENTS = [
    pytest.param("minecraft:system_chat", ("content",), "system_chat.content", id="system_chat"),
    pytest.param(
        "minecraft:disguised_chat", ("message",), "disguised_chat.message", id="disguised_chat"
    ),
    pytest.param(
        "minecraft:disguised_chat",
        ("sender_name",),
        "disguised_chat.sender_name",
        id="disguised_chat-sender",
    ),
    pytest.param(
        "minecraft:disguised_chat",
        ("target_name",),
        "disguised_chat.target_name",
        id="disguised_chat-target",
    ),
    pytest.param(
        "minecraft:player_chat",
        ("unsigned_content",),
        "player_chat.unsigned_content",
        id="player_chat",
    ),
    pytest.param(
        "minecraft:player_chat",
        ("sender_name",),
        "player_chat.sender_name",
        id="player_chat-sender",
    ),
    pytest.param(
        "minecraft:player_chat",
        ("target_name",),
        "player_chat.target_name",
        id="player_chat-target",
    ),
    pytest.param(
        "minecraft:player_combat_kill",
        ("message",),
        "player_combat_kill.message",
        id="player_combat_kill",
    ),
    pytest.param(
        "minecraft:open_screen", ("window_title",), "open_screen.window_title", id="open_screen"
    ),
    pytest.param(
        "minecraft:update_advancements",
        ("advancements", 0, "display", "title"),
        "update_advancements.advancements[].display.title",
        id="advancement-title",
    ),
    pytest.param(
        "minecraft:update_advancements",
        ("advancements", 0, "display", "description"),
        "update_advancements.advancements[].display.description",
        id="advancement-description",
    ),
    pytest.param(
        "minecraft:player_info_update",
        ("players", 0, "display_name"),
        "player_info_update.players[].display_name",
        id="player_info_update",
    ),
]
"""Each other text component in play: its packet, where it is, and its test case."""


def _holding(name: str, path: tuple[str | int, ...], component: bytes) -> Packet:
    """A `name` packet with `component` at `path` (index 0 a one-element list) and nothing else."""
    value: object = component
    for step in reversed(path):
        value = [value] if isinstance(step, int) else {step: value}
    return packet(name, fields=cast("dict[str, object]", value))


def _rendered(path: tuple[str | int, ...]) -> str:
    return "".join(f"[{step}]" if isinstance(step, int) else f".{step}" for step in path)[1:]


@pytest.mark.parametrize(("name", "path", "test_case"), _COMPONENTS)
def test_every_text_component_in_play_sent_another_way_is_network_traffic(
    name: str, path: tuple[str | int, ...], test_case: str
) -> None:
    verdict = _compared(
        name, _holding(name, path, nbt("hi")), _holding(name, path, nbt({"text": "hi"}))
    )
    assert verdict.gameplay == ()
    assert [(d.path, d.test_case) for d in _traffic(verdict)] == [(_rendered(path), test_case)]


@pytest.mark.parametrize(("name", "path", "test_case"), _COMPONENTS)
def test_every_text_component_in_play_with_other_text_is_a_gameplay_divergence_at_its_text(
    name: str, path: tuple[str | int, ...], test_case: str
) -> None:
    verdict = _compared(name, _holding(name, path, nbt("hi")), _holding(name, path, nbt("ho")))
    assert _shown(verdict.gameplay) == [(f"{_rendered(path)}.text", "hi", "ho", test_case)]
