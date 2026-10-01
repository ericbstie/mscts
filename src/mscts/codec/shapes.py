"""Shared wire shapes of registry-aware types, read from `ByteBufCodecs` and `StreamCodec`.

The building blocks of the data component table (`codec/components.py`): wire types that
`schema.py` has no use for, and that more than one component shares. Pinned with `javap` on
the 26.3 server jar (docs/research/2026-09-30-item-stacks.md).
"""

from dataclasses import dataclass

from mscts.codec.schema import NBT, VAR_INT, WireType
from mscts.codec.wire import Reader, WireError, Writer

_NBT_END = 0

REGISTRY_ID: WireType[int] = VAR_INT
"""An entry of a registry by protocol id (`ByteBufCodecs.registry`, `holderRegistry`).

A plain VarInt with no offset. The codec has no registries, so it cannot tell a valid id from
one past the end of the registry.
"""

ENUM: WireType[int] = VAR_INT
"""An enum by ordinal (`ByteBufCodecs.idMapper` over a `ByIdMap`): a plain VarInt.

Vanilla answers an out-of-range ordinal with the enum's default instead of failing, so every
VarInt is a valid read.
"""


@dataclass(frozen=True, slots=True)
class _Unit:
    def read(self, reader: Reader) -> None:
        del reader

    def write(self, writer: Writer, value: object) -> None:
        del writer
        if value is not None:
            msg = f"expected None, got {type(value).__name__}"
            raise WireError(msg)


UNIT: WireType[None] = _Unit()
"""A value with no bytes (`StreamCodec.unit`): it reads as None and writes only None."""


@dataclass(frozen=True, slots=True)
class _NbtTag:
    def read(self, reader: Reader) -> bytes:
        if reader.peek_rest()[:1] == bytes([_NBT_END]):
            msg = "NBT: a root tag of type END is no tag"
            raise WireError(msg)
        return NBT.read(reader)

    def write(self, writer: Writer, value: object) -> None:
        if isinstance(value, bytes) and value[:1] == bytes([_NBT_END]):
            msg = "NBT: a root tag of type END is no tag"
            raise WireError(msg)
        NBT.write(writer, value)


NBT_TAG: WireType[bytes] = _NbtTag()
"""An NBT root tag of any type but END, as its exact bytes.

The stream codecs derived from a `Codec` (`ByteBufCodecs.fromCodec*`, which a text component and
every component without a codec of its own use) read it with `FriendlyByteBuf.readNbt`, which
answers a TAG_End root with null and then fails. `schema.NBT` accepts that lone 0x00 byte.
"""

TEXT_COMPONENT: WireType[bytes] = NBT_TAG
"""A text component: `ComponentSerialization.STREAM_CODEC`, an NBT tag kept as its bytes.

Decoding the component (a string, a compound or a list of them) is out of scope.
"""
