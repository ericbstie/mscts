"""Tagged: a VarInt picks one of several named variants, each with its own payload or none."""

import pytest

from mscts.codec.schema import BYTE, FLOAT, VAR_INT, Schema, SchemaError, Tagged, WireType
from mscts.codec.wire import Reader, WireError, Writer

SHAPE = Tagged(
    "shape",
    "size",
    (
        ("dot", None),
        ("line", FLOAT),
        ("box", Schema(width=BYTE, height=BYTE)),
    ),
)


def written[T](wire_type: WireType[T], value: object) -> bytes:
    writer = Writer()
    wire_type.write(writer, value)
    return writer.to_bytes()


def read_all[T](wire_type: WireType[T], data: bytes) -> T:
    reader = Reader(data)
    value = wire_type.read(reader)
    reader.expect_end()
    return value


@pytest.mark.parametrize(
    ("value", "encoded"),
    [
        ({"shape": "dot", "size": None}, "00"),
        ({"shape": "line", "size": 1.5}, "013fc00000"),
        ({"shape": "box", "size": {"width": 2, "height": -3}}, "0202fd"),
    ],
)
def test_tagged_round_trips_each_variant_by_its_position(
    value: dict[str, object], encoded: str
) -> None:
    assert written(SHAPE, value) == bytes.fromhex(encoded)
    assert read_all(SHAPE, bytes.fromhex(encoded)) == value


def test_tagged_reads_the_tag_as_a_var_int() -> None:
    wide = Tagged("kind", "data", tuple((f"v{number}", None) for number in range(200)))
    assert written(wide, {"kind": "v150", "data": None}) == bytes.fromhex("9601")
    assert read_all(wide, bytes.fromhex("9601")) == {"kind": "v150", "data": None}


def test_tagged_refuses_a_tag_no_variant_has() -> None:
    with pytest.raises(WireError, match=r"^unknown shape id 3$"):
        read_all(SHAPE, b"\x03")
    with pytest.raises(WireError, match=r"^unknown shape id -1$"):
        read_all(SHAPE, bytes.fromhex("ffffffff0f"))


def test_tagged_names_the_variant_whose_payload_is_bad() -> None:
    with pytest.raises(WireError, match=r"^box: height: byte truncated"):
        read_all(SHAPE, bytes.fromhex("0202"))
    with pytest.raises(WireError, match=r"^box: width: expected an int"):
        written(SHAPE, {"shape": "box", "size": {"width": "2", "height": 1}})


def test_tagged_refuses_a_variant_name_it_does_not_have() -> None:
    with pytest.raises(WireError, match="unknown shape 'ball'"):
        written(SHAPE, {"shape": "ball", "size": None})


def test_tagged_refuses_a_payload_for_a_variant_that_takes_none() -> None:
    with pytest.raises(WireError, match=r"^dot: takes no size"):
        written(SHAPE, {"shape": "dot", "size": 1})


@pytest.mark.parametrize(
    ("value", "error"),
    [
        ({"shape": "dot"}, "missing key"),
        ({"size": None}, "missing key"),
        ({"shape": "dot", "size": None, "extra": 1}, "unexpected key"),
        ([("shape", "dot")], "expected a mapping"),
    ],
)
def test_tagged_writes_only_exactly_its_two_keys(value: object, error: str) -> None:
    with pytest.raises(WireError, match=error):
        written(SHAPE, value)


def test_tagged_lists_its_variant_names_in_id_order() -> None:
    assert SHAPE.names == ("dot", "line", "box")


def test_tagged_exposes_its_variants_so_a_walk_can_find_the_fields_inside() -> None:
    assert SHAPE.variants == (("dot", None), ("line", FLOAT), ("box", SHAPE.variants[2][1]))
    box = SHAPE.variants[2][1]
    assert isinstance(box, Schema)
    assert list(box.fields) == ["width", "height"]


@pytest.mark.parametrize(
    ("tag_key", "value_key", "variants", "error"),
    [
        ("a", "a", (("x", None),), "tag_key and value_key"),
        ("a", "b", (), "at least one variant"),
        ("a", "b", (("x", None), ("x", VAR_INT)), "twice"),
    ],
)
def test_tagged_refuses_a_declaration_that_can_never_be_valid(
    tag_key: str,
    value_key: str,
    variants: tuple[tuple[str, WireType[object] | None], ...],
    error: str,
) -> None:
    with pytest.raises(SchemaError, match=error):
        Tagged(tag_key, value_key, variants)
