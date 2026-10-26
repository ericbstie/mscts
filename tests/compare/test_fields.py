"""compare() on matched Packets with fields: the recursive diff and its paths."""

import json
import math
import struct
import sys
import uuid
from collections.abc import Mapping

import pytest
from support.report_builders import group_result, report_of

from mscts.codec.packets import State
from mscts.compare import ABSENT, compare
from mscts.report import render_text
from tests.compare.build import divergence, packet, transcript


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
        ("l[→2]", ABSENT, 3),
        ("l[→3]", ABSENT, 4),
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
    assert verdict.divergences[-1] == divergence(
        "missing", packet="test:p", reference={"v": [1]}, test_case="test:p"
    )


def test_divergence_values_are_copies_of_the_fields() -> None:
    fields = {"v": [1, {"w": 2}]}
    verdict = compare(transcript(("alice", packet("test:p", fields=fields))), transcript(), [])
    value = verdict.divergences[-1].reference
    assert isinstance(value, dict)
    assert value == fields
    assert value is not fields
    assert next(item for key, item in value.items() if key == "v") is not fields["v"]


def _nested(depth: int, leaf: object) -> object:
    """`leaf` in `depth` mappings, each `{"value": ...}`; built without recursion."""
    value = leaf
    for _ in range(depth):
        value = {"value": value}
    return value


def test_a_value_nested_deeper_than_the_recursion_limit_is_a_mismatch_not_an_error() -> None:
    # A Candidate's value can nest as deep as the codec decodes it (#479).
    deep = sys.getrecursionlimit() + 1
    [(path, reference, candidate)] = _diff({"v": 1}, {"v": _nested(deep, 1)})
    assert (path, reference) == ("v", 1)
    assert candidate == _nested(
        255, "(nested deeper than 255 levels) " + json.dumps(_nested(deep - 255, 1))
    )
    assert _diff({"v": _nested(deep, 1)}, {"v": _nested(deep, 1)}) == []


def test_lists_nested_deeper_than_the_recursion_limit_are_compared_too() -> None:
    deep: object = 1
    for _ in range(sys.getrecursionlimit() + 1):
        deep = [deep]
    assert _diff({"v": deep}, {"v": deep}) == []
    assert len(_diff({"v": 1}, {"v": deep})) == 1


def test_the_report_shows_a_value_nested_deeper_than_the_recursion_limit() -> None:
    deep = sys.getrecursionlimit() + 1
    verdict = compare(
        transcript(("alice", packet("test:p", fields={"v": _nested(255, 1)}))),
        transcript(("alice", packet("test:p", fields={"v": _nested(deep, 1)}))),
        [],
    )
    shown = render_text(report_of(group_result(verdict)), verbose=True)
    # Unquoted: mscts wrote this text, no server sent it.
    assert 'sends (nested deeper than 255 levels) {"value": {"value":' in shown, shown[-300:]


def test_a_field_value_is_compared_as_one_leaf_from_its_256th_level_down() -> None:
    at_the_limit = "v" + ".value" * 255
    assert _diff({"v": _nested(255, 1)}, {"v": _nested(255, 2)}) == [(at_the_limit, 1, 2)]
    assert _diff({"v": _nested(256, 1)}, {"v": _nested(256, 2)}) == [
        (
            at_the_limit,
            '(nested deeper than 255 levels) {"value": 1}',
            '(nested deeper than 255 levels) {"value": 2}',
        )
    ]


def test_a_value_past_the_255th_level_is_written_as_report_json_writes_one() -> None:
    leaf = {
        "z": [None, True, False, -7, 1.5, -0.0],
        "s": 'it\'s "x" é',
        "b": b"\x00\x01",
        "u": uuid.UUID(int=1),
        "f": [math.inf, -math.inf, _NAN],
        "t": {"bytes": "00"},
        "e": [[], {}],
        "a": {"absent": True},
        "m": {"bytes": "00", "n": 1},
    }
    [(_, text, _)] = _diff({"v": _nested(256, leaf)}, {"v": _nested(256, 0)})
    assert text == (
        "(nested deeper than 255 levels) "
        '{"value": {"a": {"dict": {"absent": true}}, "b": {"bytes": "0001"}, "e": [[], {}], '
        '"f": [{"float": "inf"}, {"float": "-inf"}, {"float": "nan(7ff8000000000000)"}], '
        '"m": {"bytes": "00", "n": 1}, '
        '"s": "it\'s \\"x\\" é", "t": {"dict": {"bytes": "00"}}, '
        '"u": {"uuid": "00000000-0000-0000-0000-000000000001"}, '
        '"z": [null, true, false, -7, 1.5, -0.0]}}'
    )


_NAN = struct.unpack(">d", bytes.fromhex("7ff8000000000000"))[0]
_OTHER_NAN = struct.unpack(">d", bytes.fromhex("7ff8000000000001"))[0]


@pytest.mark.parametrize(
    ("reference", "candidate"),
    [
        ({"b": 1, "a": [2, None]}, {"a": [2, None], "b": 1}),
        ([1.5, _NAN, b"\x00", uuid.UUID(int=1)], [1.5, _NAN, b"\x00", uuid.UUID(int=1)]),
    ],
)
def test_values_past_the_255th_level_match_when_they_are_equal(
    reference: object, candidate: object
) -> None:
    assert _diff({"v": _nested(256, reference)}, {"v": _nested(256, candidate)}) == []


@pytest.mark.parametrize(
    ("reference", "candidate"),
    [
        (0.0, -0.0),
        (_NAN, _OTHER_NAN),
        (1, 1.0),
        (1, True),
        (b"a", "a"),
        (b"\x00", {"bytes": "00"}),
        (uuid.UUID(int=1), str(uuid.UUID(int=1))),
        (uuid.UUID(int=1), {"uuid": str(uuid.UUID(int=1))}),
        (math.inf, {"float": "inf"}),
        ({"dict": b"\x00"}, {"bytes": "00"}),
        ([1, 2], [2, 1]),
        ([1, 23], [12, 3]),
        ({"a": 1}, {"a": 1, "b": None}),
        ([], {}),
    ],
)
def test_values_past_the_255th_level_differ_when_they_do(
    reference: object, candidate: object
) -> None:
    assert len(_diff({"v": _nested(256, reference)}, {"v": _nested(256, candidate)})) == 1


def test_a_value_past_the_255th_level_never_equals_a_string_with_its_text() -> None:
    text = '(nested deeper than 255 levels) {"value": 1}'
    assert _diff({"v": _nested(256, 1)}, {"v": _nested(255, text)}) == [
        ("v" + ".value" * 255, text, text)
    ]


@pytest.mark.parametrize(
    ("leaf", "error"),
    [
        ([(1, 2)], r"test:p: v(\.value){255}: tuple is not a codec value"),
        ({1: "a"}, r"test:p: v(\.value){255}: int key 1 is not a field name"),
    ],
)
def test_values_past_the_255th_level_are_checked_against_the_codec_value_model(
    leaf: object, error: str
) -> None:
    with pytest.raises(TypeError, match=error):
        _diff({"v": 0}, {"v": _nested(255, {"deeper": leaf})})


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
