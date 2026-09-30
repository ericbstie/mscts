"""The equipment list of `set_equipment`: slots that each carry an item stack.

Pinned with `javap` on `ClientboundSetEquipmentPacket` (a do-while: a slot byte, whose top bit says
another follows, then an optional item stack) and on `EquipmentSlot` (the eight constants, whose
ordinals are the slot ids). The stacks are stood in for by a Byte, since the item stack codec is
#19's; `EQUIPMENT` itself refuses a stack until then.
"""

import pytest

from mscts.codec.equipment import EQUIPMENT, SLOTS, EquipmentList
from mscts.codec.schema import BYTE, WireType
from mscts.codec.wire import Reader, WireError, Writer

BYTES = EquipmentList(BYTE)


def written[T](wire_type: WireType[T], value: object) -> bytes:
    writer = Writer()
    wire_type.write(writer, value)
    return writer.to_bytes()


def read_all[T](wire_type: WireType[T], data: bytes) -> T:
    reader = Reader(data)
    value = wire_type.read(reader)
    reader.expect_end()
    return value


def test_the_slots_are_the_equipment_slots_of_26_3_in_ordinal_order() -> None:
    assert SLOTS == ("mainhand", "offhand", "feet", "legs", "chest", "head", "body", "saddle")


@pytest.mark.parametrize(("slot_id", "name"), list(enumerate(SLOTS)))
def test_a_slot_is_named_by_its_ordinal(slot_id: int, name: str) -> None:
    encoded = bytes.fromhex(f"{slot_id:02x} 07")
    assert read_all(BYTES, encoded) == [{"slot": name, "item": 7}]
    assert written(BYTES, [{"slot": name, "item": 7}]) == encoded


def test_the_top_bit_of_a_slot_byte_says_another_slot_follows() -> None:
    encoded = bytes.fromhex("80 01  05 02")
    value = [{"slot": "mainhand", "item": 1}, {"slot": "head", "item": 2}]
    assert read_all(BYTES, encoded) == value
    assert written(BYTES, value) == encoded


def test_slots_keep_their_order_and_may_repeat() -> None:
    encoded = bytes.fromhex("85 01  85 02  02 03")
    value = [
        {"slot": "head", "item": 1},
        {"slot": "head", "item": 2},
        {"slot": "feet", "item": 3},
    ]
    assert read_all(BYTES, encoded) == value
    assert written(BYTES, value) == encoded


@pytest.mark.parametrize(
    ("encoded", "error"),
    [
        ("08 01", r"^0: slot: unknown id 8$"),
        ("88 01", r"^0: slot: unknown id 8$"),
        ("80 01  ff 01", r"^1: slot: unknown id 127$"),
        ("", r"^0: slot: byte truncated$"),
        ("80 01", r"^1: slot: byte truncated$"),
        ("00", r"^0: item: byte truncated$"),
        ("80 01  05", r"^1: item: byte truncated$"),
    ],
)
def test_bad_equipment_is_refused_naming_the_slot(encoded: str, error: str) -> None:
    with pytest.raises(WireError, match=error):
        read_all(BYTES, bytes.fromhex(encoded))


@pytest.mark.parametrize(
    ("value", "error"),
    [
        ([], r"^needs at least one slot$"),
        ({"slot": "head", "item": 1}, r"^expected a list or tuple, got dict$"),
        (["head"], r"^0: expected a mapping, got str$"),
        ([{"slot": "head"}], r"^0: missing key item$"),
        ([{"item": 1}], r"^0: missing key slot$"),
        ([{"slot": "head", "item": 1, "x": 1}], r"^0: unexpected key x$"),
        ([{"x": 1}], r"^0: missing key slot; missing key item; unexpected key x$"),
        ([{"slot": "hat", "item": 1}], r"^0: slot: unknown 'hat'$"),
        ([{"slot": 5, "item": 1}], r"^0: slot: unknown 5$"),
        (
            [{"slot": "head", "item": 1}, {"slot": "feet", "item": 300}],
            r"^1: item: .*byte",
        ),
    ],
)
def test_bad_equipment_is_refused_when_writing(value: object, error: str) -> None:
    with pytest.raises(WireError, match=error):
        written(BYTES, value)


def test_equipment_is_written_from_a_list_or_tuple() -> None:
    assert written(BYTES, ({"slot": "head", "item": 1},)) == bytes.fromhex("05 01")


def test_equipment_refuses_an_item_stack_until_the_item_stack_codec_lands() -> None:
    with pytest.raises(WireError, match=r"^0: item: item stack: needs #19$"):
        read_all(EQUIPMENT, bytes.fromhex("00 00"))
    with pytest.raises(WireError, match=r"^0: item: item stack: needs #19$"):
        written(EQUIPMENT, [{"slot": "mainhand", "item": None}])
