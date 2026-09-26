"""Masks: what a valid one is, and what it removes from a Comparison."""

import re
from collections.abc import Mapping

import pytest

from mscts.compare import ABSENT, Mask, compare
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
        "entity_id",
        "players.sample",
        "players.sample[0].name",
        "l[10]",
        'json_response["a.b"]',
        '["weird key"].x',
        'm[""]',
    ],
)
def test_a_mask_takes_a_field_path_or_a_star(path: str) -> None:
    assert Mask(packet="minecraft:login", path=path, reason=REASON).path == path


@pytest.mark.parametrize("reason", ["", "  \n"])
def test_a_mask_needs_a_reason(reason: str) -> None:
    with pytest.raises(ValueError, match="minecraft:login entity_id: a Mask needs a reason"):
        Mask(packet="minecraft:login", path="entity_id", reason=reason)


def test_a_mask_needs_a_packet_name() -> None:
    with pytest.raises(ValueError, match="a Mask needs a packet name"):
        Mask(packet="", path="entity_id", reason=REASON)


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
    ],
)
def test_a_mask_rejects_a_malformed_path(path: str) -> None:
    error = re.escape(f"minecraft:login: malformed Mask path {path!r}")
    with pytest.raises(ValueError, match=error):
        Mask(packet="minecraft:login", path=path, reason=REASON)


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
        Mask(packet="minecraft:login", path=path, reason=REASON)


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


def test_a_field_mask_removes_the_field_from_both_sides() -> None:
    reference = {"entity_id": 1, "name": "a"}
    candidate = {"entity_id": 2, "name": "b"}
    assert _fields_diff(reference, candidate, _mask("entity_id")) == [("name", "a", "b")]


def test_a_field_mask_ignores_whether_the_field_is_present() -> None:
    assert _fields_diff({"a": 1}, {"a": 1, "seed": 7}, _mask("seed")) == []
    assert _fields_diff({"a": 1, "seed": 7}, {"a": 1}, _mask("seed")) == []


def test_a_field_mask_reaches_into_mappings_and_lists() -> None:
    reference = {"players": {"sample": [{"id": 1, "name": "a"}]}}
    candidate = {"players": {"sample": [{"id": 2, "name": "a"}]}}
    assert _fields_diff(reference, candidate, _mask("players.sample[0].id")) == []


def test_a_field_mask_on_a_list_element_removes_it_from_the_list() -> None:
    assert _fields_diff({"l": [9, 1, 2]}, {"l": [8, 1, 2]}, _mask("l[0]")) == []


def test_a_field_mask_on_a_path_one_side_lacks_leaves_the_other_side_masked() -> None:
    reference = {"players": {"sample": [{"id": 1}]}}
    candidate = {"players": 5}
    assert _fields_diff(reference, candidate, _mask("players.sample")) == [("players", {}, 5)]


def test_a_field_mask_applies_only_to_its_packet() -> None:
    reference = {"entity_id": 1}
    candidate = {"entity_id": 2}
    assert _fields_diff(reference, candidate, _mask("entity_id", "test:other")) == [
        ("entity_id", 1, 2)
    ]


def test_a_mask_that_matches_nothing_is_not_an_error() -> None:
    masks = (_mask("no.such[3].path"), _mask("x", "test:q"))
    assert _fields_diff({"a": 1}, {"a": 1}, *masks) == []


def test_a_field_mask_leaves_a_packet_without_fields_compared_by_payload() -> None:
    verdict = compare(
        transcript(("alice", packet("test:p", b"\x01"))),
        transcript(("alice", packet("test:p", b"\x02"))),
        [_mask("entity_id")],
    )
    assert [(d.path, d.reference, d.candidate) for d in verdict.divergences] == [(None, "01", "02")]


def test_a_missing_packet_shows_its_fields_with_the_masked_ones_removed() -> None:
    verdict = compare(
        transcript(("alice", packet("test:p", fields={"entity_id": 1, "name": "a"}))),
        transcript(("alice", packet("test:other"))),
        [_mask("entity_id")],
    )
    assert [(d.kind, d.reference) for d in verdict.divergences] == [
        ("missing", {"name": "a"}),
        ("unexpected", ABSENT),
    ]


def test_masks_leave_the_transcripts_untouched() -> None:
    fields = {"entity_id": 1, "sample": [{"id": 1}]}
    reference = transcript(("alice", packet("test:p", fields=fields)))
    compare(reference, reference, [_mask("entity_id"), _mask("sample[0].id")])
    assert fields == {"entity_id": 1, "sample": [{"id": 1}]}
    assert reference.events[0].packet.fields == fields
