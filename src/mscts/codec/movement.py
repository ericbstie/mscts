"""Field types of the entity movement packets, read from the 26.3 jar with `javap`.

Both hold a value whose shape depends on a discriminator that sits inside it (the number of
steps of a move delta, the type of a position path), so each is one wire type that owns the
discriminator. A decoded value names the variant by its key, exactly one of `linear` and
`stepped`, so a Comparison reports `movement.stepped[0].x` or `position.linear.y`.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from mscts.codec.schema import BOOL, DOUBLE, SHORT, VAR_INT, PrefixedArray, Schema, WireType
from mscts.codec.wire import Reader, WireError, Writer

_INT_MASK = 0xFFFF_FFFF
_ON_GROUND = 1
_MIN_STEP_BYTES = 7
"""A step of a move delta takes at least a one-byte VarInt and three shorts."""

_LINEAR_PATH = 0
_STEPPED_PATH = 1


def _variant(value: object) -> str:
    """Which of `linear` and `stepped` `value` holds; it must hold exactly one of them."""
    if not isinstance(value, Mapping):
        msg = f"expected a mapping, got {type(value).__name__}"
        raise WireError(msg)
    present = [name for name in ("linear", "stepped") if name in value]
    if len(present) != 1:
        msg = "expected exactly one of linear, stepped"
        raise WireError(msg)
    return present[0]


def _field(value: object, name: str) -> object:
    return value.get(name) if isinstance(value, Mapping) else None


def _steps(value: object) -> Sequence[object]:
    """The steps of a stepped value that has already been checked as a list of steps."""
    steps = _field(value, "stepped")
    if not isinstance(steps, Sequence) or not steps:
        msg = "stepped: expected at least one step"
        raise WireError(msg)
    return steps


_DELTA = Schema(x=SHORT, y=SHORT, z=SHORT)
_DELTA_STEP = Schema(ticks=VAR_INT, x=SHORT, y=SHORT, z=SHORT)
_DELTA_CHECKS = {
    "linear": Schema(on_ground=BOOL, linear=_DELTA),
    "stepped": Schema(on_ground=BOOL, stepped=PrefixedArray(_DELTA_STEP)),
}


@dataclass(frozen=True, slots=True)
class _MoveDelta:
    def read(self, reader: Reader) -> dict[str, object]:
        properties = reader.var_int() & _INT_MASK
        on_ground = bool(properties & _ON_GROUND)
        count = properties >> 1
        if count == 0:
            return {"on_ground": on_ground, "linear": _DELTA.read(reader)}
        if count * _MIN_STEP_BYTES > reader.remaining:
            msg = (
                f"truncated: {count} step(s) of at least {_MIN_STEP_BYTES} bytes, "
                f"{reader.remaining} left"
            )
            raise WireError(msg)
        return {
            "on_ground": on_ground,
            "stepped": [_DELTA_STEP.read(reader) for _ in range(count)],
        }

    def write(self, writer: Writer, value: object) -> None:
        variant = _variant(value)
        _DELTA_CHECKS[variant].write(Writer(), value)
        on_ground = int(bool(_field(value, "on_ground")))
        if variant == "linear":
            writer.var_int(on_ground)
            _DELTA.write(writer, _field(value, "linear"))
            return
        steps = _steps(value)
        writer.var_int(on_ground | len(steps) << 1)
        for step in steps:
            _DELTA_STEP.write(writer, step)


MOVE_DELTA: WireType[dict[str, object]] = _MoveDelta()
"""A move delta: `{on_ground, linear: {x, y, z}}` or `{on_ground, stepped: [{ticks, x, y, z}]}`.

On the wire a VarInt of properties (bit 0 is on ground, the rest the number of steps) comes
first; with no steps three shorts follow, else each step's ticks and three shorts. A short is a
change of position in 1/4096 of a block, kept as the integer.
"""

_PATH_LINEAR = Schema(x=DOUBLE, y=DOUBLE, z=DOUBLE)
_PATH_STEPS = PrefixedArray(Schema(x=DOUBLE, y=DOUBLE, z=DOUBLE, tick_offset=VAR_INT))
_PATH_CHECKS = {
    "linear": Schema(linear=_PATH_LINEAR),
    "stepped": Schema(stepped=_PATH_STEPS),
}


@dataclass(frozen=True, slots=True)
class _PositionPath:
    def read(self, reader: Reader) -> dict[str, object]:
        path_type = reader.var_int()
        if path_type == _LINEAR_PATH:
            return {"linear": _PATH_LINEAR.read(reader)}
        if path_type == _STEPPED_PATH:
            steps = _PATH_STEPS.read(reader)
            if not steps:
                msg = "stepped: expected at least one step"
                raise WireError(msg)
            return {"stepped": steps}
        msg = f"position path: unknown type {path_type}"
        raise WireError(msg)

    def write(self, writer: Writer, value: object) -> None:
        variant = _variant(value)
        _PATH_CHECKS[variant].write(Writer(), value)
        if variant == "linear":
            writer.var_int(_LINEAR_PATH)
            _PATH_LINEAR.write(writer, _field(value, "linear"))
            return
        _steps(value)
        writer.var_int(_STEPPED_PATH)
        _PATH_STEPS.write(writer, _field(value, "stepped"))


POSITION_PATH: WireType[dict[str, object]] = _PositionPath()
"""A position path: `{linear: {x, y, z}}` or `{stepped: [{x, y, z, tick_offset}]}`.

On the wire a VarInt type (0 linear, 1 stepped) comes first, then the end position as three
Doubles, or a VarInt count of steps, each a position and a VarInt tick offset. A stepped path
ends at its last step, so it needs one. The client reads an unknown type as linear; here it is
an error.
"""
