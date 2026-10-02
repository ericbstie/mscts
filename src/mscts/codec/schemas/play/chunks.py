"""Chunk packets: a chunk's blocks, biomes, heightmaps and block entities, its light, and unloading.

Field layouts: the 26.3 client jar with `javap` on each packet's `STREAM_CODEC`, on
`ClientboundLevelChunkPacketData`, `ClientboundLightUpdatePacketData`, `LevelChunkSection.read` and
`PalettedContainer.read` (docs/research/2026-10-02-chunks-light.md). Field names are the wiki's
(minecraft.wiki `Java_Edition_protocol/Packets`), except `sections`, the wiki's Data byte array
decoded into its sections. The wiki's BitSet (a length in Longs) is not 26.3's:
`ByteBufCodecs.BIT_SET` is a length in bytes, then `BitSet.toByteArray()`.

A paletted container starts with a signed Byte, the bits per entry, which picks the palette
(`Strategy.getConfigurationForBitCount`): for block states (`Strategy$1`) 0 is one value, 1 to 4 a
list palette of 4 bits per entry, 5 to 8 a hash palette of that many bits, anything else the global
palette; for biomes (`Strategy$2`) 0 is one value, 1 to 3 a list palette of that many bits,
anything else the global palette. The entries are read at the palette's `bitsInMemory()`, which
for the global palette is `Mth.ceillog2` of the size of the client's registry (`Strategy.<init>`,
`Configuration$Global`), whatever the Byte says, and their Longs have no length
(`readFixedSizeLongArray`). For block states that size is the regenerated number of block states
(`registry_names.block_state_count`). For biomes it is the biome registry the server sent in
configuration, which this codec, reading one packet at a time, cannot see: a direct biome
container is read at the bits sent (the vanilla server writes its storage's bits,
`PalettedContainer$Data.write`), and the Comparison checks them against the Transcript's registry
(decided on #22).

Stricter than the client: the sections are read to the end of their byte array, where the client
reads one for each section of its level and ignores what is left; and a direct biome container
of more than 64 or fewer than 1 bits is refused.
"""

from collections.abc import Mapping
from dataclasses import dataclass

from mscts.codec.registry_names import block_state_count
from mscts.codec.schema import (
    INT,
    LONG,
    SHORT,
    UBYTE,
    VAR_INT,
    PrefixedArray,
    Schema,
    WireType,
)
from mscts.codec.shapes import COMPOUND_TAG, ENUM, REGISTRY_ID
from mscts.codec.wire import Reader, WireError, Writer
from mscts.target import TARGET

_LONG_BITS = 64
_LONG_BYTES = 8
_BYTE_MIN, _BYTE_MAX = -128, 127
_NBT_END = b"\x00"
_COORDINATE_MAX = 15
_SECTIONS_MAX_BYTES = 2_097_152
"""`ByteBufCodecs.byteArray(2097152)`: the most bytes the sections of a chunk may take."""
_LIGHT_ARRAY_BYTES = 2048
"""`byteArray(2048)`: one light level for each of a section's 4096 blocks, four bits each."""


def _integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        msg = f"{name}: expected an int, got {type(value).__name__}"
        raise WireError(msg)
    return value


@dataclass(frozen=True, slots=True)
class _ByteArray:
    """A VarInt length, then that many bytes (`FriendlyByteBuf.readByteArray`). Its value is bytes.

    Attributes:
        max_length: The most bytes allowed (`ByteBufCodecs.byteArray(max)`), or None for any.
    """

    max_length: int | None = None

    def _check(self, length: int) -> None:
        if self.max_length is not None and length > self.max_length:
            msg = f"byte array length {length} exceeds max {self.max_length}"
            raise WireError(msg)

    def read(self, reader: Reader) -> bytes:
        length = reader.var_int()
        if length < 0:
            msg = f"byte array length {length} is negative"
            raise WireError(msg)
        self._check(length)
        return reader.raw(length)

    def write(self, writer: Writer, value: object) -> None:
        if not isinstance(value, bytes):
            msg = f"expected bytes, got {type(value).__name__}"
            raise WireError(msg)
        self._check(len(value))
        writer.var_int(len(value)).raw(value)


_BIT_SET: WireType[bytes] = _ByteArray()
"""A light mask (`ByteBufCodecs.BIT_SET`): its bytes; the first byte's lowest bit is section 0.

Kept as sent, so a zero byte after the last bit (which the client ignores) re-encodes too.
"""


@dataclass(frozen=True, slots=True)
class PalettedContainer:
    """A paletted container (`PalettedContainer.read`): its value is `{bits, palette, data}`.

    `bits` is the signed Byte sent; `palette` the one id of a single value, the ids of a list or
    hash palette, or None for the global palette; `data` the bytes of the packed Longs.

    Attributes:
        name: What it holds, for messages: "block state" or "biome".
        entries: How many entries: 4096 block states or 64 biome cells, x fastest, then z, then y
            (`Strategy.getIndex`).
        list_max: The most bits sent that still read a list or hash palette.
        linear_max: The most bits sent whose list palette holds at most `1 << width` ids
            (`LinearPalette`); above it, up to `list_max`, a hash palette holds any number.
        min_width: The fewest bits per entry a list palette is read at.
        id_count: The size of the registry, if known: it sets the global palette's width and
            bounds each palette id (`byIdOrThrow`). None reads the global palette at the bits sent.
    """

    name: str
    entries: int
    list_max: int
    linear_max: int
    min_width: int
    id_count: int | None

    def _layout(self, bits: int) -> tuple[str, int]:
        """The palette ("single", "list" or "global") for `bits` sent, and the entries' width."""
        if bits == 0:
            return "single", 0
        if 1 <= bits <= self.list_max:
            return "list", max(bits, self.min_width)
        if self.id_count is not None:
            return "global", (self.id_count - 1).bit_length()  # Mth.ceillog2
        if not 1 <= bits <= _LONG_BITS:
            msg = f"a direct {self.name} container of {bits} bits per entry cannot be read"
            raise WireError(msg)
        return "global", bits

    def _longs(self, width: int) -> int:
        return 0 if width == 0 else -(-self.entries // (_LONG_BITS // width))

    def _id(self, value: int) -> int:
        if value < 0 or (self.id_count is not None and value >= self.id_count):
            last = "" if self.id_count is None else f" to {self.id_count - 1}"
            msg = f"{self.name} {value} is not an id of 0{last}"
            raise WireError(msg)
        return value

    def _check_list(self, bits: int, width: int, count: int) -> None:
        if bits <= self.linear_max and count > 1 << width:
            msg = f"a list palette of {count} ids, more than {1 << width}"
            raise WireError(msg)

    def read(self, reader: Reader) -> dict[str, object]:
        """Consume the bits per entry, the palette and the packed Longs."""
        bits = reader.byte()
        kind, width = self._layout(bits)
        palette: int | list[int] | None = None
        if kind == "single":
            palette = self._id(reader.var_int())
        elif kind == "list":
            count = reader.var_int()
            if count < 0 or count > reader.remaining:
                msg = f"palette length {count} is negative or exceeds the {reader.remaining} left"
                raise WireError(msg)
            self._check_list(bits, width, count)
            palette = [self._id(reader.var_int()) for _ in range(count)]
        data = reader.raw(_LONG_BYTES * self._longs(width))
        return {"bits": bits, "palette": palette, "data": data}

    def write(self, writer: Writer, value: object) -> None:
        """Append `value`, a mapping of exactly bits, palette and data that fit each other."""
        given = (
            {str(key): item for key, item in value.items()} if isinstance(value, Mapping) else {}
        )
        if sorted(given) != ["bits", "data", "palette"]:
            msg = "expected a mapping of exactly bits, palette and data"
            raise WireError(msg)
        bits = _integer(given["bits"], "bits")
        if not _BYTE_MIN <= bits <= _BYTE_MAX:
            msg = f"bits: {bits} out of range for a Byte"
            raise WireError(msg)
        kind, width = self._layout(bits)
        palette, data = given["palette"], given["data"]
        out = Writer().byte(bits)
        if kind == "single":
            out.var_int(self._id(_integer(palette, "palette")))
        elif kind == "list":
            if not isinstance(palette, list | tuple):
                msg = (
                    f"palette: expected a list of ids for {bits} bits, got {type(palette).__name__}"
                )
                raise WireError(msg)
            self._check_list(bits, width, len(palette))
            out.var_int(len(palette))
            for item in palette:
                out.var_int(self._id(_integer(item, "palette")))
        elif palette is not None:
            msg = f"palette: expected None for the global palette, got {type(palette).__name__}"
            raise WireError(msg)
        size = _LONG_BYTES * self._longs(width)
        if not isinstance(data, bytes) or len(data) != size:
            got = f"{len(data)} bytes" if isinstance(data, bytes) else type(data).__name__
            msg = f"data: expected {size} bytes for {bits} bits, got {got}"
            raise WireError(msg)
        writer.raw(out.raw(data).to_bytes())

    def values(self, value: Mapping[str, object]) -> tuple[int | None, ...]:
        """The id at each entry of a container this type read, in entry order.

        An entry that indexes past its palette has None: the client reads it, and fails only
        when it looks it up (`valueFor`).
        """
        bits = _integer(value["bits"], "bits")
        palette, data = value["palette"], value["data"]
        kind, width = self._layout(bits)
        if kind == "single":
            return (_integer(palette, "palette"),) * self.entries
        if not isinstance(data, bytes):
            msg = f"data: expected bytes, got {type(data).__name__}"
            raise WireError(msg)
        indexes = _unpacked(data, width, self.entries)
        if kind == "global":
            return tuple(indexes)
        listed = palette if isinstance(palette, list | tuple) else []
        ids = [_integer(item, "palette") for item in listed]
        return tuple(ids[index] if index < len(ids) else None for index in indexes)


def _unpacked(data: bytes, width: int, entries: int) -> list[int]:
    """The first `entries` values of `width` bits packed into big-endian Longs, lowest bits first.

    No value is split across two Longs (`SimpleBitStorage`): the high bits left over are unused.
    """
    per_long, mask = _LONG_BITS // width, (1 << width) - 1
    values: list[int] = []
    for start in range(0, len(data), _LONG_BYTES):
        word = int.from_bytes(data[start : start + _LONG_BYTES], "big")
        values.extend(word >> (slot * width) & mask for slot in range(per_long))
    return values[:entries]


BLOCK_STATES = PalettedContainer(
    "block state",
    entries=4096,
    list_max=8,
    linear_max=4,
    min_width=4,
    id_count=block_state_count(TARGET.minecraft_version),
)
"""A section's block states (`Strategy$1`): 16 bits per entry for the global palette in 26.3."""

BIOMES = PalettedContainer(
    "biome", entries=64, list_max=3, linear_max=3, min_width=1, id_count=None
)
"""A section's biomes, one for each 4x4x4 cell (`Strategy$2`)."""


@dataclass(frozen=True, slots=True)
class _Buffer[T]:
    """A byte array (`byteArray(2097152)`) holding `element` after `element` to its end."""

    element: WireType[T]

    def read(self, reader: Reader) -> list[T]:
        inner = Reader(_ByteArray(_SECTIONS_MAX_BYTES).read(reader))
        values: list[T] = []
        while inner.remaining:
            try:
                values.append(self.element.read(inner))
            except WireError as exc:
                msg = f"{len(values)}: {exc}"
                raise WireError(msg) from exc
        return values

    def write(self, writer: Writer, value: object) -> None:
        if not isinstance(value, list | tuple):
            msg = f"expected a list or tuple, got {type(value).__name__}"
            raise WireError(msg)
        inner = Writer()
        for index, item in enumerate(value):
            try:
                self.element.write(inner, item)
            except WireError as exc:
                msg = f"{index}: {exc}"
                raise WireError(msg) from exc
        _ByteArray(_SECTIONS_MAX_BYTES).write(writer, inner.to_bytes())


SECTION = Schema(block_count=SHORT, fluid_count=SHORT, block_states=BLOCK_STATES, biomes=BIOMES)
"""A chunk section (`LevelChunkSection.read`): the counts are kept by the client as sent."""


@dataclass(frozen=True, slots=True)
class _OptionalCompoundTag:
    """`ByteBufCodecs.OPTIONAL_COMPOUND_TAG`: a compound, or TAG_End for none (its value None)."""

    def read(self, reader: Reader) -> bytes | None:
        if reader.peek_rest()[:1] == _NBT_END:
            reader.raw(1)
            return None
        return COMPOUND_TAG.read(reader)

    def write(self, writer: Writer, value: object) -> None:
        if value is None:
            writer.raw(_NBT_END)
            return
        COMPOUND_TAG.write(writer, value)


_BLOCK_ENTITY_LAYOUT = Schema(
    packed_xz=UBYTE, y=SHORT, type=REGISTRY_ID, data=_OptionalCompoundTag()
)


@dataclass(frozen=True, slots=True)
class _BlockEntity:
    """A block entity of a chunk (`BlockEntityInfo`): `{x, z, y, type, data}`.

    x and z (0 to 15 in the chunk) share a Byte, x in the high four bits; y is the world's; the
    type is a `minecraft:block_entity_type` id, and the data a compound or None.
    """

    def read(self, reader: Reader) -> dict[str, object]:
        fields = _BLOCK_ENTITY_LAYOUT.read(reader)
        packed = _integer(fields.pop("packed_xz"), "packed_xz")
        return {"x": packed >> 4, "z": packed & _COORDINATE_MAX, **fields}

    def write(self, writer: Writer, value: object) -> None:
        # Exactly these names, each of its type: the Schema says what is wrong if not.
        Schema(x=UBYTE, z=UBYTE, y=SHORT, type=REGISTRY_ID, data=_OptionalCompoundTag()).write(
            Writer(), value
        )
        given = (
            {str(key): item for key, item in value.items()} if isinstance(value, Mapping) else {}
        )
        coordinates = {name: _integer(given[name], name) for name in ("x", "z")}
        for name, coordinate in coordinates.items():
            if coordinate > _COORDINATE_MAX:
                msg = f"{name}: {coordinate} out of range for 0 to {_COORDINATE_MAX}"
                raise WireError(msg)
        packed = coordinates["x"] << 4 | coordinates["z"]
        fields = {
            "packed_xz": packed,
            "y": given["y"],
            "type": given["type"],
            "data": given["data"],
        }
        _BLOCK_ENTITY_LAYOUT.write(writer, fields)


LIGHT_DATA = Schema(
    sky_light_mask=_BIT_SET,
    block_light_mask=_BIT_SET,
    empty_sky_light_mask=_BIT_SET,
    empty_block_light_mask=_BIT_SET,
    sky_light_arrays=PrefixedArray(_ByteArray(_LIGHT_ARRAY_BYTES)),
    block_light_arrays=PrefixedArray(_ByteArray(_LIGHT_ARRAY_BYTES)),
)
"""Light (`ClientboundLightUpdatePacketData`): four masks, then the sky and the block arrays.

Bit `i` of a mask is light section `i`: section 0 is the one below the world, and there is one
above it. The client takes the next array for each bit of a mask, makes an empty section for a
bit of an empty mask the mask lacks, and leaves a section neither names as it was.
"""

_HEIGHTMAP = Schema(type=ENUM, data=PrefixedArray(LONG))
"""A heightmap: its `Heightmap$Types` id (an unknown one reads as 0) and its packed Longs."""

CLIENTBOUND: Mapping[str, Schema] = {
    # Chunk Data and Update Light: the chunk at chunk_x, chunk_z, its sections bottom to top, its
    # block entities and its light. The client keeps heightmaps in an EnumMap by type.
    "minecraft:level_chunk_with_light": Schema(
        chunk_x=INT,
        chunk_z=INT,
        heightmaps=PrefixedArray(_HEIGHTMAP),
        sections=_Buffer(SECTION),
        block_entities=PrefixedArray(_BlockEntity()),
        light=LIGHT_DATA,
    ),
    # Update Light: new light for some sections of a chunk.
    "minecraft:light_update": Schema(chunk_x=VAR_INT, chunk_z=VAR_INT, data=LIGHT_DATA),
    # Unload Chunk: one Long (`ChunkPos.pack`), so z (its high half) comes first.
    "minecraft:forget_level_chunk": Schema(chunk_z=INT, chunk_x=INT),
    # Set Center Chunk and Set Render Distance: the client's loading area.
    "minecraft:set_chunk_cache_center": Schema(chunk_x=VAR_INT, chunk_z=VAR_INT),
    "minecraft:set_chunk_cache_radius": Schema(view_distance=VAR_INT),
    # Chunk Biomes: new biomes for loaded chunks, each section's biome container in a byte array.
    "minecraft:chunks_biomes": Schema(
        chunk_biome_data=PrefixedArray(Schema(chunk_z=INT, chunk_x=INT, biomes=_Buffer(BIOMES)))
    ),
}
