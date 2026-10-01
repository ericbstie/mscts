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

from mscts.codec.items import SLOT
from mscts.codec.particles import PARTICLE
from mscts.codec.schema import (
    BOOL,
    BYTE,
    FLOAT,
    NBT,
    POSITION,
    UUID,
    VAR_INT,
    VAR_LONG,
    PrefixedArray,
    PrefixedOptional,
    Schema,
    String,
    Tagged,
    WireType,
)
from mscts.codec.shapes import GLOBAL_POS, PAINTING_VARIANT, RESOLVABLE_PROFILE
from mscts.codec.wire import Reader, WireError, Writer


def _integer(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        msg = f"expected an int, got {type(value).__name__}"
        raise WireError(msg)
    return value


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

OPTIONAL_GLOBAL_POS = PrefixedOptional(GLOBAL_POS)
"""Optional global position: {dimension, pos: {x, y, z}}, or None."""


_VECTOR3 = Schema(x=FLOAT, y=FLOAT, z=FLOAT)

SERIALIZERS = Tagged(
    "serializer",
    "value",
    (
        ("byte", BYTE),
        ("int", VAR_INT),
        ("long", VAR_LONG),
        ("float", FLOAT),
        ("string", String(32767)),
        ("component", NBT),
        ("optional_component", PrefixedOptional(NBT)),
        ("item_stack", SLOT),
        ("boolean", BOOL),
        ("rotations", _VECTOR3),
        ("block_pos", POSITION),
        ("optional_block_pos", PrefixedOptional(POSITION)),
        ("direction", VAR_INT),
        ("optional_living_entity_reference", PrefixedOptional(UUID)),
        ("block_state", VAR_INT),
        ("optional_block_state", OPTIONAL_BLOCK_STATE),
        ("particle", PARTICLE),
        ("particles", PrefixedArray(PARTICLE)),
        ("villager_data", Schema(type=VAR_INT, profession=VAR_INT, level=VAR_INT)),
        ("optional_unsigned_int", OPTIONAL_UNSIGNED_INT),
        ("pose", VAR_INT),
        ("cat_variant", VAR_INT),
        ("cat_sound_variant", VAR_INT),
        ("cow_variant", VAR_INT),
        ("cow_sound_variant", VAR_INT),
        ("wolf_variant", VAR_INT),
        ("wolf_sound_variant", VAR_INT),
        ("frog_variant", VAR_INT),
        ("pig_variant", VAR_INT),
        ("pig_sound_variant", VAR_INT),
        ("chicken_variant", VAR_INT),
        ("chicken_sound_variant", VAR_INT),
        ("zombie_nautilus_variant", VAR_INT),
        ("optional_global_pos", OPTIONAL_GLOBAL_POS),
        ("painting_variant", PAINTING_VARIANT),
        ("sniffer_state", VAR_INT),
        ("armadillo_state", VAR_INT),
        ("copper_golem_state", VAR_INT),
        ("weathering_copper_state", VAR_INT),
        ("vector3", _VECTOR3),
        ("quaternion", Schema(x=FLOAT, y=FLOAT, z=FLOAT, w=FLOAT)),
        ("resolvable_profile", RESOLVABLE_PROFILE),
        ("humanoid_arm", VAR_INT),
        ("dye_color", VAR_INT),
    ),
)
"""Every serializer of `EntityDataSerializers`, in registration order: the position is the id.

The names are the lower-case Java constants. A value is `{"serializer": name, "value": ...}`.
"""

_TERMINATOR = 0xFF
_ENTRY_KEYS = ("index", "serializer", "value")


@dataclass(frozen=True, slots=True)
class _EntityData:
    """The entries of a metadata packet: each a u8 index, a serializer id and its value.

    The list ends with an index of 0xFF, so an entry's index is 0 to 254. Its value is a list of
    `{"index": i, "serializer": name, "value": ...}`, in wire order.
    """

    def read(self, reader: Reader) -> list[dict[str, object]]:
        entries: list[dict[str, object]] = []
        while True:
            try:
                index = reader.raw(1)[0]
            except WireError as exc:
                msg = "entries end without the 0xff terminator"
                raise WireError(msg) from exc
            if index == _TERMINATOR:
                return entries
            try:
                entries.append({"index": index, **SERIALIZERS.read(reader)})
            except WireError as exc:
                msg = f"{len(entries)}: {exc}"
                raise WireError(msg) from exc

    def write(self, writer: Writer, value: object) -> None:
        if not isinstance(value, list | tuple):
            msg = f"expected a list or tuple, got {type(value).__name__}"
            raise WireError(msg)
        for position, item in enumerate(value):
            try:
                self._write_entry(writer, item)
            except WireError as exc:
                msg = f"{position}: {exc}"
                raise WireError(msg) from exc
        writer.raw(bytes([_TERMINATOR]))

    @staticmethod
    def _write_entry(writer: Writer, item: object) -> None:
        if not isinstance(item, Mapping):
            msg = f"expected a mapping, got {type(item).__name__}"
            raise WireError(msg)
        given = {str(key): entry for key, entry in item.items()}
        problems = [f"missing key {key}" for key in _ENTRY_KEYS if key not in given]
        problems += [f"unexpected key {key}" for key in sorted(given) if key not in _ENTRY_KEYS]
        if problems:
            raise WireError("; ".join(problems))
        try:
            index = _integer(given["index"])
        except WireError as exc:
            msg = f"index: {exc}"
            raise WireError(msg) from exc
        if not 0 <= index < _TERMINATOR:
            msg = f"index {index} is not in 0..{_TERMINATOR - 1}"
            raise WireError(msg)
        writer.raw(bytes([index]))
        SERIALIZERS.write(writer, {"serializer": given["serializer"], "value": given["value"]})


ENTITY_DATA: WireType[list[dict[str, object]]] = _EntityData()
"""The entries of `set_entity_data`: `[{"index": 9, "serializer": "float", "value": 10.0}]`."""
