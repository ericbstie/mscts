"""Masks: what a valid one is, and what it hides from a Comparison."""

import re
from collections.abc import Mapping

import pytest

from mscts.codec.packets import Packet, State
from mscts.compare import ABSENT, MASKED, Mask, compare
from mscts.compare import test_case as case_name
from tests.compare.build import packet, transcript

REASON = "nondeterministic in vanilla"
AWKWARD_KEYS = ["a.b", "", 'say "hi"', "\xe9", "]", '["x"]', "1", "a b", "\\", "\n"]


def test_every_divergence_path_is_a_valid_mask_path() -> None:
    def fields(value: int) -> dict[str, object]:
        return {"m": {key: [{key: value}] for key in AWKWARD_KEYS}}

    verdict = compare(
        transcript(("alice", packet("test:p", fields=fields(1)))),
        transcript(("alice", packet("test:p", fields=fields(2)))),
        [],
    )
    paths = [d.path for d in verdict.divergences]
    assert len(paths) == len(AWKWARD_KEYS)
    for path in paths:
        assert path is not None
        assert Mask(packet="test:p", path=path, reason=REASON).path == path


@pytest.mark.parametrize(
    "path",
    [
        "*",
        "food",
        "players.sample",
        "players.sample[0].name",
        "l[10]",
        'json_response["a.b"]',
        '["weird key"].x',
        'm[""]',
        "players.sample[*].name",
        "l[*]",
        "l[*][0][*]",
        'm["a.b"][*]',
    ],
)
def test_a_mask_takes_a_field_path_or_a_star(path: str) -> None:
    assert Mask(packet="minecraft:set_health", path=path, reason=REASON).path == path


@pytest.mark.parametrize("reason", ["", "  \n"])
def test_a_mask_needs_a_reason(reason: str) -> None:
    with pytest.raises(ValueError, match="minecraft:set_health food: a Mask needs a reason"):
        Mask(packet="minecraft:set_health", path="food", reason=reason)


def test_a_mask_needs_a_packet_name() -> None:
    with pytest.raises(ValueError, match="a Mask needs a packet name"):
        Mask(packet="", path="food", reason=REASON)


@pytest.mark.parametrize(
    "path",
    [
        "",
        ".a",
        "a.",
        "a..b",
        "a b",
        "a[",
        "a[]",
        "a[01]",
        "a[-1]",
        "a[1]b",
        "[0]",
        "[0].a",
        'a["x"',
        'a["x]',
        "a[1.5]",
        "a.*",
        "**",
        "[*]",
        "[*].a",
        "a[*",
        "a[**]",
        "a[ *]",
        "a*",
    ],
)
def test_a_mask_rejects_a_malformed_path(path: str) -> None:
    error = re.escape(f"minecraft:set_health: malformed Mask path {path!r}")
    with pytest.raises(ValueError, match=error):
        Mask(packet="minecraft:set_health", path=path, reason=REASON)


@pytest.mark.parametrize(
    ("path", "canonical"),
    [
        ('["abc"]', "abc"),
        ('a["b"]', "a.b"),
        ('m["\\u00e9"]', 'm["\xe9"]'),
    ],
)
def test_a_mask_path_must_be_spelled_as_divergences_spell_it(path: str, canonical: str) -> None:
    # One spelling per path, so a path copied from a Divergence is the Mask's path.
    with pytest.raises(ValueError, match=re.escape(f"write {canonical!r}")):
        Mask(packet="minecraft:set_health", path=path, reason=REASON)


def _fields_diff(
    reference: Mapping[str, object], candidate: Mapping[str, object], *masks: Mask
) -> list[tuple[str | None, object, object]]:
    verdict = compare(
        transcript(("alice", packet("test:p", fields=reference))),
        transcript(("alice", packet("test:p", fields=candidate))),
        masks,
    )
    return [(d.path, d.reference, d.candidate) for d in verdict.divergences]


def _mask(path: str, name: str = "test:p") -> Mask:
    return Mask(packet=name, path=path, reason=REASON)


def test_a_field_mask_hides_the_field_on_both_sides() -> None:
    reference = {"entity_id": 1, "name": "a"}
    candidate = {"entity_id": 2, "name": "b"}
    assert _fields_diff(reference, candidate, _mask("entity_id")) == [("name", "a", "b")]
    assert _fields_diff({"m": {"x": 1}}, {"m": [2, 3]}, _mask("m")) == []


def test_a_field_mask_hides_a_value_but_not_whether_it_is_there() -> None:
    """A field one side lacks, or holds None in, is a Divergence even under a Mask.

    A Mask says a value differs from run to run with no gameplay meaning; whether the
    value is there at all is gameplay (an advancement criterion obtained or not), so it is
    still compared: the Mask shows a value as MASKED, and leaves None and an absent field
    as they are.
    """
    assert _fields_diff({"a": 1}, {"a": 1, "seed": 7}, _mask("seed")) == [("seed", ABSENT, MASKED)]
    assert _fields_diff({"a": 1, "seed": 7}, {"a": 1}, _mask("seed")) == [("seed", MASKED, ABSENT)]
    assert _fields_diff({"seed": None}, {"seed": 7}, _mask("seed")) == [("seed", None, MASKED)]
    assert _fields_diff({"seed": None}, {"a": 1}, _mask("seed")) == [
        ("a", ABSENT, 1),
        ("seed", None, ABSENT),
    ]


def test_a_field_mask_reaches_into_mappings_and_lists() -> None:
    reference = {"players": {"sample": [{"id": 1, "name": "a"}]}}
    candidate = {"players": {"sample": [{"id": 2, "name": "a"}]}}
    assert _fields_diff(reference, candidate, _mask("players.sample[0].id")) == []


def test_a_field_mask_on_a_list_element_keeps_it_in_the_list() -> None:
    """The element is hidden where it stands: how long the list is still counts.

    Taking it out would close the list up, and compare each later element with the
    other side's element at another index.
    """
    assert _fields_diff({"l": [9, 1, 2]}, {"l": [8, 1, 2]}, _mask("l[0]")) == []
    assert _fields_diff({"l": [9, 1, 2]}, {"l": [1, 2]}, _mask("l[0]")) == [
        ("l[1]", 1, 2),
        ("l[2]", 2, ABSENT),
    ]


def test_a_field_mask_on_an_index_past_the_end_hides_nothing_there() -> None:
    assert _fields_diff({"l": [1, 2]}, {"l": [1, 2, 3]}, _mask("l[2]")) == [
        ("l[2]", ABSENT, MASKED)
    ]


def test_a_star_index_masks_every_element_of_a_list() -> None:
    reference = {"l": [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}], "m": [[1, 2], [3]]}
    candidate = {"l": [{"id": 3, "name": "a"}, {"id": 4, "name": "c"}], "m": [[5, 6], [7]]}
    assert _fields_diff(reference, candidate, _mask("l[*].id"), _mask("m[*][*]")) == [
        ("l[1].name", "b", "c")
    ]


def test_a_star_index_hides_values_but_not_whether_they_are_there() -> None:
    reference = {"l": [{"id": 1}, {"id": None}, {"id": 2}]}
    candidate = {"l": [{"id": 3}, {"id": 4}, {}, {"id": 5}]}
    assert _fields_diff(reference, candidate, _mask("l[*].id")) == [
        ("l[1].id", None, MASKED),
        ("l[2].id", MASKED, ABSENT),
        ("l[3]", ABSENT, {"id": MASKED}),
    ]


def test_a_star_index_masks_fields_that_are_no_test_cases() -> None:
    verdict = compare(
        transcript(("alice", packet("test:p", fields={"l": [{"id": 1, "n": "a"}]}))),
        transcript(("alice", packet("test:p", fields={"l": [{"id": 2, "n": "a"}]}))),
        [_mask("l[*].id")],
    )
    assert (verdict.divergences, verdict.test_cases) == ((), ("test:p.l[].n",))


def test_a_star_index_on_what_is_no_list_hides_nothing() -> None:
    assert _fields_diff({"l": {"a": 1}}, {"l": {"a": 2}}, _mask("l[*]")) == [("l.a", 1, 2)]


def test_a_star_index_is_a_mask_path_only() -> None:
    with pytest.raises(ValueError, match=re.escape("malformed field path 'a[*]'")):
        case_name(State.PLAY, "minecraft:set_health", "a[*]")


def test_a_mask_on_every_entity_id_of_a_list_is_refused() -> None:
    with pytest.raises(ValueError, match="an entity id needs no Mask"):
        Mask(packet="minecraft:remove_entities", path="entity_ids[*]", reason=REASON)


def test_a_field_mask_on_a_path_one_side_lacks_leaves_the_other_side_masked() -> None:
    reference = {"players": {"sample": [{"id": 1}]}}
    candidate = {"players": 5}
    assert _fields_diff(reference, candidate, _mask("players.sample")) == [
        ("players", {"sample": MASKED}, 5)
    ]


def test_a_masked_field_is_a_test_case_only_where_it_diverges() -> None:
    def test_cases(
        reference: Mapping[str, object], candidate: Mapping[str, object]
    ) -> tuple[str, ...]:
        verdict = compare(
            transcript(("alice", packet("test:p", fields=reference))),
            transcript(("alice", packet("test:p", fields=candidate))),
            [_mask("seed")],
        )
        return verdict.test_cases

    assert test_cases({"a": 1, "seed": 7}, {"a": 1, "seed": 8}) == ("test:p.a",)
    assert test_cases({"a": 1, "seed": None}, {"a": 1, "seed": None}) == ("test:p.a",)
    assert test_cases({"a": 1, "seed": None}, {"a": 1, "seed": 8}) == ("test:p.a", "test:p.seed")


def test_a_field_mask_applies_only_to_its_packet() -> None:
    reference = {"entity_id": 1}
    candidate = {"entity_id": 2}
    assert _fields_diff(reference, candidate, _mask("entity_id", "test:other")) == [
        ("entity_id", 1, 2)
    ]


def test_a_mask_that_matches_nothing_is_not_an_error() -> None:
    masks = (_mask("no.such[3].path"), _mask("x", "test:q"))
    assert _fields_diff({"a": 1}, {"a": 1}, *masks) == []


def test_a_field_mask_whose_parent_is_absent_removes_nothing_else() -> None:
    assert _fields_diff({"a": 1}, {"a": 2}, _mask("absent.a")) == [("a", 1, 2)]
    assert _fields_diff({"l": [1]}, {"l": [2]}, _mask("l[5][0]")) == [("l[0]", 1, 2)]


def test_a_field_mask_leaves_a_packet_without_fields_compared_by_payload() -> None:
    verdict = compare(
        transcript(("alice", packet("test:p", b"\x01"))),
        transcript(("alice", packet("test:p", b"\x02"))),
        [_mask("entity_id")],
    )
    assert [(d.path, d.reference, d.candidate) for d in verdict.divergences] == [(None, "01", "02")]


def test_a_missing_packet_shows_its_fields_with_the_masked_ones_hidden() -> None:
    verdict = compare(
        transcript(("alice", packet("test:p", fields={"entity_id": 1, "name": "a"}))),
        transcript(("alice", packet("test:other"))),
        [_mask("entity_id")],
    )
    assert [(d.kind, d.reference) for d in verdict.divergences] == [
        ("missing", {"entity_id": MASKED, "name": "a"}),
        ("unexpected", ABSENT),
    ]


def test_masks_leave_the_transcripts_untouched() -> None:
    fields = {"entity_id": 1, "sample": [{"id": 1}]}
    reference = transcript(("alice", packet("test:p", fields=fields)))
    compare(reference, reference, [_mask("entity_id"), _mask("sample[0].id")])
    assert fields == {"entity_id": 1, "sample": [{"id": 1}]}
    assert reference.events[0].packet.fields == fields


def _stream_kinds(
    reference: list[Packet], candidate: list[Packet], *masks: Mask
) -> list[tuple[str, int, str]]:
    verdict = compare(
        transcript(*(("alice", p) for p in reference)),
        transcript(*(("alice", p) for p in candidate)),
        masks,
    )
    return [(d.kind, d.index, d.packet) for d in verdict.divergences]


KEEP_ALIVE = packet("minecraft:keep_alive", b"\x01")
A, B, X = packet("test:a"), packet("test:b"), packet("test:x")


def test_a_whole_packet_mask_drops_that_packet_from_both_streams() -> None:
    reference = [A, KEEP_ALIVE, B]
    candidate = [A, B, KEEP_ALIVE, KEEP_ALIVE]
    assert _stream_kinds(reference, candidate) == [
        ("missing", 1, "minecraft:keep_alive"),
        ("unexpected", 2, "minecraft:keep_alive"),
        ("unexpected", 3, "minecraft:keep_alive"),
    ]
    assert _stream_kinds(reference, candidate, _mask("*", "minecraft:keep_alive")) == []


def test_indices_count_the_stream_after_dropped_packets() -> None:
    reference = [KEEP_ALIVE, A, X]
    candidate = [A]
    assert _stream_kinds(reference, candidate, _mask("*", "minecraft:keep_alive")) == [
        ("missing", 1, "test:x")
    ]


def test_a_whole_packet_mask_drops_the_packet_in_every_state() -> None:
    reference = [packet("minecraft:keep_alive", state=State.CONFIGURATION), A]
    candidate = [A, packet("minecraft:keep_alive", state=State.PLAY)]
    assert _stream_kinds(reference, candidate, _mask("*", "minecraft:keep_alive")) == []


def test_a_bot_whose_packets_are_all_dropped_is_still_present() -> None:
    verdict = compare(
        transcript(("alice", A), ("bob", KEEP_ALIVE)),
        transcript(("alice", A)),
        [_mask("*", "minecraft:keep_alive")],
    )
    assert [(d.bot, d.kind) for d in verdict.divergences] == [("bob", "bot")]
