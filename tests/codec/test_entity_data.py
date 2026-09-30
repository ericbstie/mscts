"""Entity metadata's value types, pinned with `javap` on the 26.3 server jar.

The hex payloads are built by hand from the `StreamCodec` layouts, not produced by the Codec.
"""

import uuid

import pytest

from mscts.codec.entity_data import (
    OPTIONAL_BLOCK_STATE,
    OPTIONAL_GLOBAL_POS,
    OPTIONAL_UNSIGNED_INT,
    PAINTING_VARIANT,
    RESOLVABLE_PROFILE,
)
from mscts.codec.schema import WireType
from mscts.codec.wire import Reader, WireError, Writer

SAMPLE_UUID = uuid.UUID("12345678-1234-5678-1234-567812345678")


def written[T](wire_type: WireType[T], value: object) -> bytes:
    writer = Writer()
    wire_type.write(writer, value)
    return writer.to_bytes()


def read_all[T](wire_type: WireType[T], data: bytes) -> T:
    reader = Reader(data)
    value = wire_type.read(reader)
    reader.expect_end()
    return value


# Optional block state: a VarInt block state id, 0 meaning none (EntityDataSerializers$2).


@pytest.mark.parametrize(("value", "encoded"), [(None, "00"), (1, "01"), (42, "2a"), (300, "ac02")])
def test_optional_block_state_is_the_id_and_zero_for_none(value: int | None, encoded: str) -> None:
    assert written(OPTIONAL_BLOCK_STATE, value) == bytes.fromhex(encoded)
    assert read_all(OPTIONAL_BLOCK_STATE, bytes.fromhex(encoded)) == value


def test_optional_block_state_refuses_zero_which_would_read_back_as_none() -> None:
    with pytest.raises(WireError, match=r"^0 would read back as none$"):
        written(OPTIONAL_BLOCK_STATE, 0)


# Optional unsigned int: a VarInt of the value plus one, 0 meaning none (EntityDataSerializers$3).


@pytest.mark.parametrize(
    ("value", "encoded"),
    [(None, "00"), (0, "01"), (41, "2a"), (299, "ac02"), (-2, "ffffffff0f")],
)
def test_optional_unsigned_int_is_the_value_plus_one_and_zero_for_none(
    value: int | None, encoded: str
) -> None:
    assert written(OPTIONAL_UNSIGNED_INT, value) == bytes.fromhex(encoded)
    assert read_all(OPTIONAL_UNSIGNED_INT, bytes.fromhex(encoded)) == value


def test_optional_unsigned_int_refuses_minus_one_which_would_read_back_as_none() -> None:
    with pytest.raises(WireError, match=r"^-1 would read back as none$"):
        written(OPTIONAL_UNSIGNED_INT, -1)


@pytest.mark.parametrize("wire_type", [OPTIONAL_BLOCK_STATE, OPTIONAL_UNSIGNED_INT])
@pytest.mark.parametrize("value", [True, 1.0, "1"])
def test_the_optional_ints_refuse_what_is_not_an_int(
    wire_type: WireType[object], value: object
) -> None:
    with pytest.raises(WireError, match="expected an int"):
        written(wire_type, value)


# Optional global pos: a Boolean, then the dimension (an Identifier) and a Position.


def test_optional_global_pos_is_a_dimension_and_a_block_position() -> None:
    encoded = bytes.fromhex("01136d696e6563726166743a6f766572776f726c640000004000003002")
    value = {"dimension": "minecraft:overworld", "pos": {"x": 1, "y": 2, "z": 3}}
    assert read_all(OPTIONAL_GLOBAL_POS, encoded) == value
    assert written(OPTIONAL_GLOBAL_POS, value) == encoded
    assert read_all(OPTIONAL_GLOBAL_POS, b"\x00") is None


# Painting variant: a Holder. VarInt 0 then the variant itself, else the registry id plus one.

DIRECT_PLAIN = "0004020f6d696e6563726166743a6b656261620000"
DIRECT_FULL = "0001010b6d696e6563726166743a780108000268690108000161"


@pytest.mark.parametrize(
    ("encoded", "value"),
    [
        ("01", {"reference": 0}),
        ("2b", {"reference": 42}),
        (
            DIRECT_PLAIN,
            {
                "direct": {
                    "width": 4,
                    "height": 2,
                    "asset_id": "minecraft:kebab",
                    "title": None,
                    "author": None,
                }
            },
        ),
        (
            DIRECT_FULL,
            {
                "direct": {
                    "width": 1,
                    "height": 1,
                    "asset_id": "minecraft:x",
                    "title": bytes.fromhex("08000268 69"),
                    "author": bytes.fromhex("0800 0161"),
                }
            },
        ),
    ],
)
def test_painting_variant_is_a_registry_reference_or_the_variant_itself(
    encoded: str, value: dict[str, object]
) -> None:
    assert read_all(PAINTING_VARIANT, bytes.fromhex(encoded)) == value
    assert written(PAINTING_VARIANT, value) == bytes.fromhex(encoded)


def test_painting_variant_refuses_a_negative_registry_id() -> None:
    with pytest.raises(WireError, match=r"^holder id -1 is negative$"):
        read_all(PAINTING_VARIANT, bytes.fromhex("ffffffff0f"))


def test_painting_variant_names_what_is_wrong_in_the_variant_itself() -> None:
    with pytest.raises(WireError, match=r"^direct: height: VarInt truncated$"):
        read_all(PAINTING_VARIANT, bytes.fromhex("0004"))
    direct = {"width": 1, "height": "2", "asset_id": "a", "title": None, "author": None}
    with pytest.raises(WireError, match=r"^direct: height: expected an int"):
        written(PAINTING_VARIANT, {"direct": direct})


@pytest.mark.parametrize(
    ("value", "error"),
    [
        ({}, "exactly one of reference and direct"),
        ({"reference": 1, "direct": {}}, "exactly one of reference and direct"),
        ({"other": 1}, "exactly one of reference and direct"),
        ([("reference", 1)], "expected a mapping"),
        ({"reference": -1}, "negative"),
        ({"reference": True}, "expected an int"),
    ],
)
def test_painting_variant_writes_only_one_of_a_reference_and_a_direct_variant(
    value: object, error: str
) -> None:
    with pytest.raises(WireError, match=error):
        written(PAINTING_VARIANT, value)


# Resolvable profile: a Boolean (true: a full game profile, false: a partial one), then a skin
# patch of four optionals (body, cape, elytra textures, and whether the model is slim).

UUID_HEX = "12345678 12345678 12345678 12345678"
# Either (true), the id, "Bob", one property with a signature; then the patch: no body, a cape,
# no elytra, a slim model.
GAME_PROFILE = (
    f"01 {UUID_HEX} 03 426f62  01 08 7465787475726573 03 616263 01 03 736967"
    "  00 01 0e 6d696e6563726166743a63617065 00 01 01"
)
# Either (false), no name, an id, no properties, an empty patch.
PARTIAL_PROFILE = f"00 00 01 {UUID_HEX} 00  00 00 00 00"
# Either (false), "Steve", no id, two properties without signatures, a wide model.
PARTIAL_NAMED = "00 01 05 5374657665 00 02 0161 0162 00 0163 0164 00  00 00 00 01 00"


@pytest.mark.parametrize(
    ("encoded", "value"),
    [
        (
            GAME_PROFILE,
            {
                "profile": {
                    "game_profile": {
                        "id": SAMPLE_UUID,
                        "name": "Bob",
                        "properties": [{"name": "textures", "value": "abc", "signature": "sig"}],
                    }
                },
                "skin_patch": {
                    "body": None,
                    "cape": "minecraft:cape",
                    "elytra": None,
                    "slim": True,
                },
            },
        ),
        (
            PARTIAL_PROFILE,
            {
                "profile": {"partial": {"name": None, "id": SAMPLE_UUID, "properties": []}},
                "skin_patch": {"body": None, "cape": None, "elytra": None, "slim": None},
            },
        ),
        (
            PARTIAL_NAMED,
            {
                "profile": {
                    "partial": {
                        "name": "Steve",
                        "id": None,
                        "properties": [
                            {"name": "a", "value": "b", "signature": None},
                            {"name": "c", "value": "d", "signature": None},
                        ],
                    }
                },
                "skin_patch": {"body": None, "cape": None, "elytra": None, "slim": False},
            },
        ),
    ],
)
def test_a_resolvable_profile_is_a_game_profile_or_a_partial_one_and_a_skin_patch(
    encoded: str, value: dict[str, object]
) -> None:
    assert read_all(RESOLVABLE_PROFILE, bytes.fromhex(encoded)) == value
    assert written(RESOLVABLE_PROFILE, value) == bytes.fromhex(encoded)


def test_a_profile_has_at_most_16_properties() -> None:
    sixteen = "00 00 00 10 " + " ".join(["01 61 01 62 00"] * 16) + " 00 00 00 00"
    value = read_all(RESOLVABLE_PROFILE, bytes.fromhex(sixteen))
    assert written(RESOLVABLE_PROFILE, value) == bytes.fromhex(sixteen)
    with pytest.raises(WireError, match=r"array length 17 exceeds max 16"):
        read_all(RESOLVABLE_PROFILE, bytes.fromhex("00 00 00 11" + " 00" * 60))


def profile_with(*, name: str, prop_name: str, value: str, signature: str) -> dict[str, object]:
    return {
        "profile": {
            "game_profile": {
                "id": SAMPLE_UUID,
                "name": name,
                "properties": [{"name": prop_name, "value": value, "signature": signature}],
            }
        },
        "skin_patch": {"body": None, "cape": None, "elytra": None, "slim": None},
    }


@pytest.mark.parametrize(
    ("field", "limit"), [("name", 16), ("prop_name", 64), ("value", 32767), ("signature", 1024)]
)
def test_a_profile_string_is_at_most_as_long_as_vanilla_allows(field: str, limit: int) -> None:
    fields = {"name": "a", "prop_name": "a", "value": "a", "signature": "a"}
    written(RESOLVABLE_PROFILE, profile_with(**{**fields, field: "a" * limit}))
    with pytest.raises(WireError, match=rf"max length {limit} "):
        written(RESOLVABLE_PROFILE, profile_with(**{**fields, field: "a" * (limit + 1)}))


@pytest.mark.parametrize(
    ("encoded", "error"),
    [
        ("02", r"^profile: invalid bool byte 0x02$"),
        (f"01 {UUID_HEX} 11 " + "41" * 17, r"^profile: game_profile: name: "),
        ("00 00 00 00  00 00 00 01 02", r"^skin_patch: slim: invalid bool byte 0x02$"),
    ],
)
def test_a_resolvable_profile_refuses_bad_bytes(encoded: str, error: str) -> None:
    with pytest.raises(WireError, match=error):
        read_all(RESOLVABLE_PROFILE, bytes.fromhex(encoded))


def test_a_resolvable_profile_names_the_side_whose_value_is_bad_when_writing() -> None:
    bad = {"id": SAMPLE_UUID, "name": 5, "properties": []}
    with pytest.raises(WireError, match=r"^profile: game_profile: name: expected a str"):
        written(RESOLVABLE_PROFILE, {"profile": {"game_profile": bad}, "skin_patch": {}})


@pytest.mark.parametrize(
    ("value", "error"),
    [
        ({"profile": {}, "skin_patch": {}}, "exactly one of game_profile and partial"),
        (
            {"profile": {"game_profile": {}, "partial": {}}, "skin_patch": {}},
            "exactly one of game_profile and partial",
        ),
    ],
)
def test_a_resolvable_profile_writes_only_one_of_a_game_profile_and_a_partial(
    value: object, error: str
) -> None:
    with pytest.raises(WireError, match=error):
        written(RESOLVABLE_PROFILE, value)
