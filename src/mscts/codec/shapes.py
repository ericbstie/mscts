"""Shared wire shapes of registry-aware types, read from `ByteBufCodecs` and `StreamCodec`.

The building blocks of the data component table (`codec/components.py`): wire types that
`schema.py` has no use for, and that more than one component shares. Pinned with `javap` on
the 26.3 server jar (docs/research/2026-09-30-item-stacks.md).
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from mscts.codec.schema import (
    BOOL,
    DOUBLE,
    FLOAT,
    IDENTIFIER,
    LONG,
    NBT,
    POSITION,
    UUID,
    VAR_INT,
    PrefixedArray,
    PrefixedOptional,
    Schema,
    SchemaError,
    String,
    Tagged,
    WireType,
)
from mscts.codec.wire import Reader, WireError, Writer

_NBT_END = 0
_TOO_DEEP = "nested too deeply"


def _integer(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        msg = f"expected an int, got {type(value).__name__}"
        raise WireError(msg)
    return value


def _one_of(value: object, first: str, second: str) -> tuple[str, object]:
    """The one key of `value` that is `first` or `second`, with its value."""
    if not isinstance(value, Mapping):
        msg = f"expected a mapping with one of {first} and {second}, got {type(value).__name__}"
        raise WireError(msg)
    keys = [str(key) for key in value]
    if sorted(keys) not in ([first], [second]):
        msg = f"expected exactly one of {first} and {second}, got {sorted(keys)}"
        raise WireError(msg)
    key = keys[0]
    return key, next(iter(value.values()))


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
class OrdinalEnum:
    """An enum by ordinal that fails past its last constant (`FriendlyByteBuf.readEnum`).

    A VarInt that indexes `getEnumConstants()`: vanilla throws on an ordinal below 0 or from `count`
    up, where `ENUM`'s `idMapper` answers a default. `writeEnum` writes `ordinal()`.

    Attributes:
        count: How many constants the enum has.
    """

    count: int

    def __post_init__(self) -> None:
        """Reject a `count` that is not a positive int.

        Raises:
            SchemaError: `count` is below 1, or not an int.
        """
        if isinstance(self.count, bool) or not isinstance(self.count, int):
            msg = f"OrdinalEnum count must be an int, got {type(self.count).__name__}"
            raise SchemaError(msg)
        if self.count < 1:
            msg = f"OrdinalEnum count {self.count} is below 1"
            raise SchemaError(msg)

    def _check(self, ordinal: int) -> int:
        if not 0 <= ordinal < self.count:
            msg = f"{ordinal} is not an ordinal of 0 to {self.count - 1}"
            raise WireError(msg)
        return ordinal

    def read(self, reader: Reader) -> int:
        """Consume one ordinal."""
        return self._check(reader.var_int())

    def write(self, writer: Writer, value: object) -> None:
        """Append `value`, an int that is an ordinal of the enum."""
        writer.var_int(self._check(_integer(value)))


SOUND_SOURCE: WireType[int] = OrdinalEnum(11)
"""A `SoundSource` category, by ordinal: MASTER 0, MUSIC 1, RECORDS 2, WEATHER 3, BLOCKS 4,
HOSTILE 5, NEUTRAL 6, PLAYERS 7, AMBIENT 8, VOICE 9, UI 10 (26.3 javap)."""


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

_NBT_COMPOUND = 10


def _require_compound(first: bytes) -> None:
    if first and first[0] != _NBT_COMPOUND:
        msg = f"NBT: the root tag must be a compound (type {_NBT_COMPOUND}), got type {first[0]}"
        raise WireError(msg)


@dataclass(frozen=True, slots=True)
class _CompoundTag:
    def read(self, reader: Reader) -> bytes:
        _require_compound(reader.peek_rest()[:1])
        return NBT.read(reader)

    def write(self, writer: Writer, value: object) -> None:
        if isinstance(value, bytes):
            _require_compound(value[:1])
        NBT.write(writer, value)


COMPOUND_TAG: WireType[bytes] = _CompoundTag()
"""An NBT root tag that must be a compound, as its exact bytes (`ByteBufCodecs.COMPOUND_TAG`).

`FriendlyByteBuf.readNbt` accepts any root but END; this one then insists on type 10.
"""


@dataclass(frozen=True, slots=True)
class FixedArray[T]:
    """Exactly `size` elements and no count (`ByteBufCodecs.fixedSizeList`). Its value is a list.

    Errors are prefixed with the element's index.

    Attributes:
        element: Each element's wire type.
        size: How many elements there always are.
    """

    element: WireType[T]
    size: int

    def __post_init__(self) -> None:
        """Reject a `size` that is not a non-negative int.

        Raises:
            SchemaError: `size` is negative, or not an int.
        """
        if isinstance(self.size, bool) or not isinstance(self.size, int):
            msg = f"FixedArray size must be an int, got {type(self.size).__name__}"
            raise SchemaError(msg)
        if self.size < 0:
            msg = f"FixedArray size {self.size} is negative"
            raise SchemaError(msg)

    def read(self, reader: Reader) -> list[T]:
        """Consume `size` elements."""
        values = []
        for index in range(self.size):
            try:
                values.append(self.element.read(reader))
            except WireError as exc:
                msg = f"{index}: {exc}"
                raise WireError(msg) from exc
        return values

    def write(self, writer: Writer, value: object) -> None:
        """Append `value`, a list or tuple of exactly `size` elements."""
        if not isinstance(value, list | tuple) or len(value) != self.size:
            got = f"{len(value)}" if isinstance(value, list | tuple) else type(value).__name__
            msg = f"expected a list of {self.size} item(s), got {got}"
            raise WireError(msg)
        for index, item in enumerate(value):
            try:
                self.element.write(writer, item)
            except WireError as exc:
                msg = f"{index}: {exc}"
                raise WireError(msg) from exc


@dataclass(frozen=True, slots=True)
class Deferred[T]:
    """A wire type named now and defined later: for a type that contains itself.

    `StreamCodec.recursive` is how vanilla ties the knot. A value nested so deeply that Python
    runs out of stack is a `WireError`, not a `RecursionError`: the bytes are the server's.

    Attributes:
        resolve: Returns the wire type; called each time it is read or written.
    """

    resolve: Callable[[], WireType[T]]

    def read(self, reader: Reader) -> T:
        """Read with the type `resolve` returns."""
        try:
            return self.resolve().read(reader)
        except RecursionError as exc:
            raise WireError(_TOO_DEEP) from exc

    def write(self, writer: Writer, value: object) -> None:
        """Write with the type `resolve` returns."""
        try:
            self.resolve().write(writer, value)
        except RecursionError as exc:
            raise WireError(_TOO_DEEP) from exc


def registry_dispatch(
    names: Sequence[str],
    layouts: Mapping[str, WireType[object] | None],
    tag_key: str = "type",
    value_key: str = "value",
) -> Tagged:
    """A `Tagged` with one variant per registry entry: its id is the entry's position in `names`.

    A layout of None is an entry that carries nothing (`StreamCodec.unit`).

    Raises:
        SchemaError: An entry has no layout, or a layout is for a name that is not an entry.
    """
    missing = [name for name in names if name not in layouts]
    if missing:
        msg = f"no layout for {', '.join(missing)}"
        raise SchemaError(msg)
    extra = sorted(name for name in layouts if name not in names)
    if extra:
        msg = f"layout for {', '.join(extra)}, which is not an entry"
        raise SchemaError(msg)
    return Tagged(tag_key, value_key, [(name, layouts[name]) for name in names])


@dataclass(frozen=True, slots=True)
class Holder:
    """A registry holder (`ByteBufCodecs.holder`): VarInt 0 and the value itself, else the id + 1.

    Its value is `{"direct": value}` or `{"reference": registry id}`.

    Attributes:
        direct: The wire type of the value written in place of a registry id.
    """

    direct: WireType[object]

    def read(self, reader: Reader) -> dict[str, object]:
        """Consume the VarInt, then the value if it is 0."""
        number = reader.var_int()
        if number < 0:
            msg = f"holder id {number} is negative"
            raise WireError(msg)
        if number > 0:
            return {"reference": number - 1}
        try:
            return {"direct": self.direct.read(reader)}
        except WireError as exc:
            msg = f"direct: {exc}"
            raise WireError(msg) from exc

    def write(self, writer: Writer, value: object) -> None:
        """Append `value`: a reference as its id + 1, a direct value behind a 0."""
        key, payload = _one_of(value, "reference", "direct")
        if key == "direct":
            writer.var_int(0)
            try:
                self.direct.write(writer, payload)
            except WireError as exc:
                msg = f"direct: {exc}"
                raise WireError(msg) from exc
            return
        registry_id = _integer(payload)
        if registry_id < 0:
            msg = f"holder id {registry_id} is negative"
            raise WireError(msg)
        writer.var_int(registry_id + 1)


@dataclass(frozen=True, slots=True)
class Either:
    """A Bool, then the left type (true) or the right (false): `ByteBufCodecs.either`.

    Its value is `{left_key: value}` or `{right_key: value}`.
    """

    left_key: str
    left: WireType[object]
    right_key: str
    right: WireType[object]

    def read(self, reader: Reader) -> dict[str, object]:
        """Consume the Bool, then the side it names."""
        key, wire_type = (
            (self.left_key, self.left) if reader.bool_() else (self.right_key, self.right)
        )
        try:
            return {key: wire_type.read(reader)}
        except WireError as exc:
            msg = f"{key}: {exc}"
            raise WireError(msg) from exc

    def write(self, writer: Writer, value: object) -> None:
        """Append `value`, the Bool of its side, then the value."""
        key, payload = _one_of(value, self.left_key, self.right_key)
        writer.bool_(value=key == self.left_key)
        try:
            (self.left if key == self.left_key else self.right).write(writer, payload)
        except WireError as exc:
            msg = f"{key}: {exc}"
            raise WireError(msg) from exc


@dataclass(frozen=True, slots=True)
class _HolderSet:
    def read(self, reader: Reader) -> dict[str, object]:
        number = reader.var_int()
        if number < 0:
            msg = f"holder set size {number} is negative"
            raise WireError(msg)
        if number == 0:
            try:
                return {"tag": IDENTIFIER.read(reader)}
            except WireError as exc:
                msg = f"tag: {exc}"
                raise WireError(msg) from exc
        count = number - 1
        if count > reader.remaining:
            msg = f"holder set of {count} id(s) exceeds the {reader.remaining} byte(s) left"
            raise WireError(msg)
        ids = []
        for index in range(count):
            try:
                ids.append(REGISTRY_ID.read(reader))
            except WireError as exc:
                msg = f"ids: {index}: {exc}"
                raise WireError(msg) from exc
        return {"ids": ids}

    def write(self, writer: Writer, value: object) -> None:
        key, payload = _one_of(value, "tag", "ids")
        if key == "tag":
            writer.var_int(0)
            try:
                IDENTIFIER.write(writer, payload)
            except WireError as exc:
                msg = f"tag: {exc}"
                raise WireError(msg) from exc
            return
        if not isinstance(payload, list | tuple):
            msg = f"ids: expected a list or tuple, got {type(payload).__name__}"
            raise WireError(msg)
        writer.var_int(len(payload) + 1)
        for index, registry_id in enumerate(payload):
            try:
                REGISTRY_ID.write(writer, registry_id)
            except WireError as exc:
                msg = f"ids: {index}: {exc}"
                raise WireError(msg) from exc


HOLDER_SET: WireType[dict[str, object]] = _HolderSet()
"""A set of registry entries (`ByteBufCodecs.holderSet`): a tag, or a list of ids.

On the wire a VarInt: 0 and then a tag's Identifier, else the number of ids + 1 and the ids.
Its value is `{"tag": "minecraft:logs"}` or `{"ids": [registry id, ...]}`.
"""

_SECTION_FIELDS = (("x", 22, 42), ("z", 22, 20), ("y", 20, 0))
"""Each coordinate of a section position: its name, width in bits, and shift within the Long."""


@dataclass(frozen=True, slots=True)
class _SectionPosition:
    def read(self, reader: Reader) -> dict[str, int]:
        packed = reader.long() & 0xFFFF_FFFF_FFFF_FFFF
        position = {}
        for name, width, shift in _SECTION_FIELDS:
            value = (packed >> shift) & ((1 << width) - 1)
            position[name] = value - (1 << width) if value >> (width - 1) else value
        return {name: position[name] for name in ("x", "y", "z")}

    def write(self, writer: Writer, value: object) -> None:
        # Exactly the names x, y and z, each an int: the Schema says what is wrong if not.
        Schema(x=LONG, y=LONG, z=LONG).write(Writer(), value)
        given = (
            {str(key): item for key, item in value.items()} if isinstance(value, Mapping) else {}
        )
        packed = 0
        for name, width, shift in _SECTION_FIELDS:
            coordinate = _integer(given.get(name))
            if not -(1 << (width - 1)) <= coordinate < 1 << (width - 1):
                msg = f"{name}: {coordinate} out of range for {width} signed bits"
                raise WireError(msg)
            packed |= (coordinate & ((1 << width) - 1)) << shift
        writer.long(packed - (1 << 64) if packed >> 63 else packed)


SECTION_POSITION: WireType[dict[str, int]] = _SectionPosition()
"""A chunk section's position (`SectionPos.STREAM_CODEC`): `{x, y, z}` in sections, in one Long.

x and z take 22 bits each and y 20, signed:
`(x & 0x3FFFFF) << 42 | (y & 0xFFFFF) | (z & 0x3FFFFF) << 20`.
"""

VEC3 = Schema(x=DOUBLE, y=DOUBLE, z=DOUBLE)
"""A vector of three Doubles (`Vec3.STREAM_CODEC`): `{x, y, z}`, in blocks."""

SOUND_EVENT = Holder(Schema(location=IDENTIFIER, fixed_range=PrefixedOptional(FLOAT)))
"""A sound event (`SoundEvent.STREAM_CODEC`): a registry id, or its Identifier and fixed range."""

GLOBAL_POS = Schema(dimension=IDENTIFIER, pos=POSITION)
"""A position in a dimension (`GlobalPos.STREAM_CODEC`): `{dimension, pos: {x, y, z}}`."""

PAINTING_VARIANT = Holder(
    Schema(
        width=VAR_INT,
        height=VAR_INT,
        asset_id=IDENTIFIER,
        title=PrefixedOptional(TEXT_COMPONENT),
        author=PrefixedOptional(TEXT_COMPONENT),
    )
)
"""Painting variant: `{"reference": id}` or `{"direct": {width, height, asset_id, ...}}`."""

_PROPERTIES = PrefixedArray(
    Schema(name=String(64), value=String(32767), signature=PrefixedOptional(String(1024))),
    max_length=16,
)
_PLAYER_NAME = String(16)

RESOLVABLE_PROFILE = Schema(
    profile=Either(
        "game_profile",
        Schema(id=UUID, name=_PLAYER_NAME, properties=_PROPERTIES),
        "partial",
        Schema(
            name=PrefixedOptional(_PLAYER_NAME),
            id=PrefixedOptional(UUID),
            properties=_PROPERTIES,
        ),
    ),
    skin_patch=Schema(
        body=PrefixedOptional(IDENTIFIER),
        cape=PrefixedOptional(IDENTIFIER),
        elytra=PrefixedOptional(IDENTIFIER),
        slim=PrefixedOptional(BOOL),
    ),
)
"""A player head's profile: a full game profile or a partial one, and the skin patch."""
