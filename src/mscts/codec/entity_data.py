"""Entity metadata: the value types of `EntityDataSerializers`, and the entries that carry them.

Pinned with `javap` on the 26.3 server jar (each `STREAM_CODEC`, `forValueType` and the
`ByteBufCodecs` helpers they use). Ids of enums, registries and the block state registry
(a direction, a pose, a cat variant, a block state) are VarInts kept as they are, not
range checked: the client maps an id out of range to the first, wraps or clamps it, and
the registry ids depend on the server's data. An entity id inside a value (a firework's
shooter, a vibration source's target) is context dependent, so only a vibration's is an
`ENTITY_ID`.
"""

from collections.abc import Mapping
from dataclasses import dataclass

from mscts.codec.schema import (
    BOOL,
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


@dataclass(frozen=True, slots=True)
class _ZeroIsNone:
    """A VarInt where 0 is none and any other n is the value n minus `shift`.

    With a shift of 0 the value 0 cannot be written (it would read back as none).
    """

    shift: int

    def read(self, reader: Reader) -> int | None:
        number = reader.var_int()
        return None if number == 0 else number - self.shift

    def write(self, writer: Writer, value: object) -> None:
        if value is None:
            writer.var_int(0)
            return
        number = _integer(value) + self.shift
        if number == 0:
            msg = f"{value} would read back as none"
            raise WireError(msg)
        writer.var_int(number)


OPTIONAL_BLOCK_STATE: WireType[int | None] = _ZeroIsNone(0)
"""Optional block state: a block state id, or None (0 on the wire; air is not writable)."""

OPTIONAL_UNSIGNED_INT: WireType[int | None] = _ZeroIsNone(1)
"""Optional unsigned int: the value plus one as a VarInt, or None (0 on the wire)."""

OPTIONAL_GLOBAL_POS = PrefixedOptional(Schema(dimension=IDENTIFIER, pos=POSITION))
"""Optional global position: {dimension, pos: {x, y, z}}, or None."""


@dataclass(frozen=True, slots=True)
class _Holder:
    """A registry holder: VarInt 0 and the value itself, else the registry id plus one.

    Its value is `{"direct": value}` or `{"reference": registry id}`.
    """

    direct: WireType[object]

    def read(self, reader: Reader) -> dict[str, object]:
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


PAINTING_VARIANT = _Holder(
    Schema(
        width=VAR_INT,
        height=VAR_INT,
        asset_id=IDENTIFIER,
        title=PrefixedOptional(NBT),
        author=PrefixedOptional(NBT),
    )
)
"""Painting variant: `{"reference": id}` or `{"direct": {width, height, asset_id, ...}}`."""


@dataclass(frozen=True, slots=True)
class _Either:
    """A Boolean, then the left type (true) or the right (false).

    Its value is `{left_key: value}` or `{right_key: value}`.
    """

    left_key: str
    left: WireType[object]
    right_key: str
    right: WireType[object]

    def read(self, reader: Reader) -> dict[str, object]:
        key, wire_type = (
            (self.left_key, self.left) if reader.bool_() else (self.right_key, self.right)
        )
        try:
            return {key: wire_type.read(reader)}
        except WireError as exc:
            msg = f"{key}: {exc}"
            raise WireError(msg) from exc

    def write(self, writer: Writer, value: object) -> None:
        key, payload = _one_of(value, self.left_key, self.right_key)
        writer.bool_(value=key == self.left_key)
        try:
            (self.left if key == self.left_key else self.right).write(writer, payload)
        except WireError as exc:
            msg = f"{key}: {exc}"
            raise WireError(msg) from exc


_PROPERTIES = PrefixedArray(
    Schema(name=String(64), value=String(32767), signature=PrefixedOptional(String(1024))),
    max_length=16,
)
_PLAYER_NAME = String(16)

RESOLVABLE_PROFILE = Schema(
    profile=_Either(
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
