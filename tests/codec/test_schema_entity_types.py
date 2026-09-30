"""The field types the entity packets need: each reads what it writes and refuses what it cannot."""

import pytest

from mscts.codec.schema import LP_VEC3
from mscts.codec.wire import Reader, WireError
from tests.codec.test_schema_types import read_all, written

# LpVec3 (net.minecraft.network.LpVec3, 26.3 javap). One byte 0x00 is the zero vector. Else six
# bytes: `lowest`, `middle`, then a big-endian u32 `high`; packed = high << 16 | middle << 8 |
# lowest, a 48-bit word whose bits 0-1 are the low bits of the scale, bit 2 a continuation flag,
# then x, y and z at bits 3, 18 and 33, each 15 bits (a quantized fraction of the scale:
# q * 2 / 32766 - 1, with 32767 read as 32766). With the flag set a VarInt follows, the scale
# divided by four. The value keeps those integers, so every encoding reads back byte for byte.

LP_VEC3_CASES = [
    ("00", {"scale": 0, "x": 0, "y": 0, "z": 0}),
    # Recorded from vanilla: the velocity of two dropped item entities (add_entity).
    ("09f175433331", {"scale": 1, "x": 15905, "y": 19660, "z": 15009}),
    ("010f806f3332", {"scale": 1, "x": 16864, "y": 19660, "z": 16439}),
    # Built with LpVec3.write's steps from (2.0, 0.5, -1.0), (4.0, -2.5, 0.75), (100000, -3, 0).
    ("f2ff40013fff", {"scale": 2, "x": 32766, "y": 20479, "z": 8192}),
    ("f4ff97fe600301", {"scale": 4, "x": 32766, "y": 6144, "z": 19455}),
    ("f4ff7ffeffffa8c301", {"scale": 100_000, "x": 32766, "y": 16383, "z": 16383}),
    # The largest scale: the extension is an unsigned 32-bit value, so its VarInt is a negative int.
    ("070000000000ffffffff0f", {"scale": 2**34 - 1, "x": 0, "y": 0, "z": 0}),
    # A nonzero scale with no direction is not what vanilla writes, but it is unambiguous.
    ("030000000000", {"scale": 3, "x": 0, "y": 0, "z": 0}),
]


@pytest.mark.parametrize(("encoded", "value"), LP_VEC3_CASES)
def test_lp_vec3_reads_and_writes_its_integers(encoded: str, value: dict[str, int]) -> None:
    assert read_all(LP_VEC3, bytes.fromhex(encoded)) == value
    assert written(LP_VEC3, value) == bytes.fromhex(encoded)


def test_lp_vec3_leaves_the_bytes_after_it_alone() -> None:
    reader = Reader(bytes.fromhex("00" + "ff"))
    assert LP_VEC3.read(reader) == {"scale": 0, "x": 0, "y": 0, "z": 0}
    assert reader.remaining == 1


@pytest.mark.parametrize(
    ("encoded", "error"),
    [
        ("", "truncated"),
        ("09f1", "truncated"),
        ("09f1754333", "truncated"),
        # The flag is set but the VarInt that should follow is missing.
        ("f4ff7ffeffff", "truncated"),
        # The flag is set with a zero extension: it would read as scale 0 to 3 with no flag.
        ("f4ff7ffeffff00", "continuation flag"),
        ("f5ff7ffeffff00", "continuation flag"),
    ],
)
def test_lp_vec3_refuses_what_vanilla_never_writes(encoded: str, error: str) -> None:
    with pytest.raises(WireError, match=error):
        read_all(LP_VEC3, bytes.fromhex(encoded))


@pytest.mark.parametrize(
    ("value", "error"),
    [
        ({"scale": 0, "x": 32, "y": 1, "z": 0}, "would read back as the zero vector"),
        ({"scale": 1, "x": 32768, "y": 0, "z": 0}, "x: 32768 out of range"),
        ({"scale": 1, "x": 0, "y": -1, "z": 0}, "y: -1 out of range"),
        ({"scale": -1, "x": 0, "y": 0, "z": 0}, "scale: -1 out of range"),
        ({"scale": 2**34, "x": 0, "y": 0, "z": 0}, "scale: 17179869184 out of range"),
        ({"scale": 1, "x": True, "y": 0, "z": 0}, "x: expected an int"),
        ({"scale": 1, "x": 0, "y": 0}, r"missing field\(s\) z"),
        ({"scale": 1, "x": 0, "y": 0, "z": 0, "w": 0}, r"unexpected field\(s\) w"),
        ((1.0, 2.0, 3.0), "expected a mapping"),
    ],
)
def test_lp_vec3_refuses_what_it_cannot_encode(value: object, error: str) -> None:
    with pytest.raises(WireError, match=error):
        written(LP_VEC3, value)
