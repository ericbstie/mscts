"""The NBT writer, from known bytes.

Hand-encoded per minecraft.wiki `NBT_format` (revision 3725656), and a file vanilla 26.3
itself wrote.
"""

import gzip
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import pytest

from mscts.adapters.nbt import (
    Byte,
    Compound,
    Double,
    Float,
    Int,
    IntArray,
    List,
    Long,
    NbtError,
    Tag,
    encode,
    gzipped,
)

DATA = Path(__file__).parent / "data"


def _named(type_id: int, payload: bytes) -> bytes:
    """A root compound {"x": <tag>}: its type, the name "x", then `payload`."""
    return b"\x0a\x00\x00" + bytes([type_id]) + b"\x00\x01x" + payload + b"\x00"


@dataclass(frozen=True, slots=True)
class Known:
    tag: Tag
    type_id: int
    payload: bytes


KNOWN = {
    "byte": Known(Byte(-2), 1, b"\xfe"),
    "int": Known(Int(-2), 3, b"\xff\xff\xff\xfe"),
    "long": Known(Long(2**63 - 1), 4, b"\x7f\xff\xff\xff\xff\xff\xff\xff"),
    "float": Known(Float(0.5), 5, b"\x3f\x00\x00\x00"),
    "double": Known(Double(-2.0), 6, b"\xc0\x00\x00\x00\x00\x00\x00\x00"),
    "string": Known("h\xe9", 8, b"\x00\x03h\xc3\xa9"),  # a u16 byte length, then UTF-8
    "list": Known(
        List((Int(1), Int(2))), 9, b"\x03\x00\x00\x00\x02\x00\x00\x00\x01\x00\x00\x00\x02"
    ),
    "empty list": Known(List(()), 9, b"\x00\x00\x00\x00\x00"),  # of TAG_End, as vanilla's
    "compound": Known({"a": Byte(1), "b": "c"}, 10, b"\x01\x00\x01a\x01\x08\x00\x01b\x00\x01c\x00"),
    "empty compound": Known({}, 10, b"\x00"),
    "int array": Known(IntArray((0, -60)), 11, b"\x00\x00\x00\x02\x00\x00\x00\x00\xff\xff\xff\xc4"),
}


@pytest.mark.parametrize("known", KNOWN.values(), ids=KNOWN.keys())
def test_each_tag_encodes_to_its_known_bytes(known: Known) -> None:
    assert encode({"x": known.tag}) == _named(known.type_id, known.payload)


def test_the_root_is_an_unnamed_compound() -> None:
    assert encode({}) == b"\x0a\x00\x00\x00"


def _vanilla_world_gen_settings() -> Compound:
    """What vanilla 26.3 wrote for the default ServerSpec, in its own key order."""
    flat = {
        "features": Byte(0),
        "biome": "minecraft:plains",
        "layers": List(
            tuple(
                {"block": f"minecraft:{block}", "height": Int(height)}
                for block, height in (("bedrock", 1), ("dirt", 2), ("grass_block", 1))
            )
        ),
        "structure_overrides": List(("minecraft:strongholds", "minecraft:villages")),
        "lakes": Byte(0),
    }
    return {
        "data": {
            "bonus_chest": Byte(0),
            "seed": Long(0),
            "generate_structures": Byte(0),
            "dimensions": {
                "minecraft:overworld": {
                    "generator": {"settings": flat, "type": "minecraft:flat"},
                    "type": "minecraft:overworld",
                },
                "minecraft:the_nether": {
                    "generator": {
                        "settings": "minecraft:nether",
                        "biome_source": {
                            "preset": "minecraft:nether",
                            "type": "minecraft:multi_noise",
                        },
                        "type": "minecraft:noise",
                    },
                    "type": "minecraft:the_nether",
                },
                "minecraft:the_end": {
                    "generator": {
                        "settings": "minecraft:end",
                        "biome_source": {"type": "minecraft:the_end"},
                        "type": "minecraft:noise",
                    },
                    "type": "minecraft:the_end",
                },
            },
        },
        "DataVersion": Int(5023),
    }


def test_it_writes_a_file_vanilla_wrote_byte_for_byte() -> None:
    # world/data/minecraft/world_gen_settings.dat of a Reference at the default ServerSpec,
    # gunzipped (docs/research/2026-09-26-pumpkin.md, "A native world save").
    written = (DATA / "vanilla-26.3-default-spec.world_gen_settings.nbt").read_bytes()
    assert encode(_vanilla_world_gen_settings()) == written


def test_gzipped_is_one_member_holding_the_encoding_and_depends_on_the_value_alone() -> None:
    root = _vanilla_world_gen_settings()
    first = gzipped(root)
    assert gzip.decompress(first) == encode(root)
    assert first[4:8] == b"\x00\x00\x00\x00"  # the gzip header's modification time
    assert gzipped(root) == first


def _untyped(value: object) -> object:
    """`value`, typed as object, so a test can cast it to a wrong type."""
    return value


BAD: dict[str, Tag] = {
    "byte above 127": Byte(128),
    "byte below -128": Byte(-129),
    "int above 2**31-1": Int(2**31),
    "int below -2**31": Int(-(2**31) - 1),
    "long above 2**63-1": Long(2**63),
    "long below -2**63": Long(-(2**63) - 1),
    "bool as a byte": Byte(True),  # noqa: FBT003 (the value under test)
    "float as a long": Long(cast("int", _untyped(1.0))),
    "int as a double": Double(1),
    "float not a binary32": Float(0.1),
    "float too large for a binary32": Float(1e300),
    "int array value above 2**31-1": IntArray((2**31,)),
    "mixed list": List((Int(1), Long(1))),
    "string with U+0000": "a\0b",
    "string outside the BMP": chr(0x1F600),
    "lone surrogate": chr(0xD800),
    "string over 65535 bytes": "x" * 65536,
    "unknown tag": cast("Tag", _untyped(1)),
}


@pytest.mark.parametrize("tag", BAD.values(), ids=BAD.keys())
def test_it_refuses_what_its_tag_cannot_hold(tag: Tag) -> None:
    with pytest.raises(NbtError):
        encode({"x": tag})


def test_it_refuses_a_bad_name() -> None:
    with pytest.raises(NbtError):
        encode({"\0": Byte(0)})


def test_the_longest_string_is_written() -> None:
    assert encode({"x": "x" * 65535})[:8] == _named(8, b"\xff\xff")[:8]
