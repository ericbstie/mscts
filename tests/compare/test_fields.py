"""compare() on matched Packets with fields: the recursive diff and its paths."""

import math
import uuid
from collections.abc import Mapping

import pytest

from mscts.codec.packets import State
from mscts.compare import ABSENT, Divergence, compare
from tests.compare.build import packet, transcript


def _diff(
    reference: Mapping[str, object] | None, candidate: Mapping[str, object] | None
) -> list[tuple[str | None, object, object]]:
    """(path, reference, candidate) of each Divergence between two test:p Packets."""
    verdict = compare(
        transcript(("alice", packet("test:p", b"\x01", fields=reference))),
        transcript(("alice", packet("test:p", b"\x02", fields=candidate))),
        [],
    )
    assert {(d.bot, d.index, d.kind, d.packet) for d in verdict.divergences} <= {
        ("alice", 0, "field", "test:p")
    }
    return [(d.path, d.reference, d.candidate) for d in verdict.divergences]


def test_equal_fields_match_whatever_the_payloads() -> None:
    assert _diff({"entity_id": 7}, {"entity_id": 7}) == []


def test_a_differing_field_names_its_path_and_both_values() -> None:
    assert _diff({"entity_id": 7, "name": "a"}, {"entity_id": 8, "name": "a"}) == [
        ("entity_id", 7, 8)
    ]


def test_a_nested_field_path_joins_names_with_dots() -> None:
    assert _diff({"inner": {"port": 1}}, {"inner": {"port": 2}}) == [("inner.port", 1, 2)]


def test_a_list_element_path_has_its_index_in_brackets() -> None:
    reference = {"players": {"sample": [{"name": "a"}, {"name": "b"}]}}
    candidate = {"players": {"sample": [{"name": "a"}, {"name": "c"}]}}
    assert _diff(reference, candidate) == [("players.sample[1].name", "b", "c")]


def test_a_field_only_one_side_has_is_absent_on_the_other() -> None:
    assert _diff({"a": 1}, {"a": 1, "sample": []}) == [("sample", ABSENT, [])]
    assert _diff({"a": 1, "sample": []}, {"a": 1}) == [("sample", [], ABSENT)]


def test_elements_past_the_end_of_a_list_are_absent() -> None:
    assert _diff({"l": [1, 2]}, {"l": [1, 2, 3, 4]}) == [
        ("l[2]", ABSENT, 3),
        ("l[3]", ABSENT, 4),
    ]


@pytest.mark.parametrize(
    ("reference", "candidate"),
    [
        ({"k": 1}, [1]),
        (1, "1"),
        (True, 1),
        (1, 1.0),
        (0, False),
        (None, 0),
        (b"a", "a"),
    ],
)
def test_values_of_different_types_differ_even_when_python_calls_them_equal(
    reference: object, candidate: object
) -> None:
    assert _diff({"v": reference}, {"v": candidate}) == [("v", reference, candidate)]


def test_floats_are_compared_bit_for_bit() -> None:
    assert _diff({"v": 0.0}, {"v": -0.0}) == [("v", 0.0, -0.0)]
    assert _diff({"v": math.nan}, {"v": math.nan}) == []
    assert _diff({"v": 1.5}, {"v": 1.5}) == []


def test_uuid_and_bytes_values_are_compared_by_value() -> None:
    first, second = uuid.UUID(int=1), uuid.UUID(int=2)
    assert _diff({"id": first, "b": b"x"}, {"id": uuid.UUID(int=1), "b": b"x"}) == []
    assert _diff({"id": first}, {"id": second}) == [("id", first, second)]


@pytest.mark.parametrize(
    ("key", "path"),
    [
        ("a.b", 'm["a.b"]'),
        ("", 'm[""]'),
        ("1st", 'm["1st"]'),
        ('say "hi"', 'm["say \\"hi\\""]'),
        ("snake_case1", "m.snake_case1"),
    ],
)
def test_a_key_that_is_not_an_identifier_is_quoted_as_json_in_brackets(key: str, path: str) -> None:
    assert _diff({"m": {key: 1}}, {"m": {key: 2}}) == [(path, 1, 2)]


def test_divergences_follow_sorted_keys_whatever_the_order_of_either_side() -> None:
    reference = {"b": 1, "a": {"y": 1, "x": 1}}
    candidate = {"a": {"x": 2, "y": 2}, "b": 2}
    assert [path for path, _, _ in _diff(reference, candidate)] == ["a.x", "a.y", "b"]


def test_packets_without_fields_on_either_side_are_compared_by_payload() -> None:
    assert _diff({"v": 1}, None) == [(None, "01", "02")]
    assert _diff(None, {"v": 1}) == [(None, "01", "02")]


def test_a_missing_packet_with_fields_carries_its_fields() -> None:
    verdict = compare(
        transcript(("alice", packet("test:p", b"\x01", fields={"v": [1]}))), transcript(), []
    )
    assert verdict.divergences[-1] == Divergence(
        bot="alice",
        index=0,
        kind="missing",
        packet="test:p",
        path=None,
        reference={"v": [1]},
        candidate=ABSENT,
    )


def test_divergence_values_are_copies_of_the_fields() -> None:
    fields = {"v": [1, {"w": 2}]}
    verdict = compare(transcript(("alice", packet("test:p", fields=fields))), transcript(), [])
    value = verdict.divergences[-1].reference
    assert isinstance(value, dict)
    assert value == fields
    assert value is not fields
    assert next(item for key, item in value.items() if key == "v") is not fields["v"]


@pytest.mark.parametrize(
    ("fields", "error"),
    [
        ({"v": (1, 2)}, r"test:p: v: tuple is not a codec value"),
        # A subclass of a leaf type is not one: an enum would compare equal to its value.
        ({"v": State.PLAY}, r"test:p: v: State is not a codec value"),
        ({"v": {1: "a"}}, r"test:p: v: int key 1 is not a field name"),
        ({"v": [{"w": {1.5}}]}, r"test:p: v\[0\].w: set is not a codec value"),
    ],
)
def test_values_outside_the_codec_value_model_are_rejected(
    fields: Mapping[str, object], error: str
) -> None:
    with pytest.raises(TypeError, match=error):
        _diff({"v": 0}, fields)
