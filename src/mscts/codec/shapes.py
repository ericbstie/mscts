"""Shared wire shapes of registry-aware types, read from `ByteBufCodecs` and `StreamCodec`.

The building blocks of the data component table (`codec/components.py`): wire types that
`schema.py` has no use for, and that more than one component shares. Pinned with `javap` on
the 26.3 server jar (docs/research/2026-09-30-item-stacks.md).
"""

from collections.abc import Mapping
from dataclasses import dataclass

from mscts.codec.schema import (
    BOOL,
    FLOAT,
    IDENTIFIER,
    NBT,
    POSITION,
    UUID,
    VAR_INT,
    PrefixedArray,
    PrefixedOptional,
    Schema,
    String,
    WireType,
)
from mscts.codec.wire import Reader, WireError, Writer

_NBT_END = 0


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
