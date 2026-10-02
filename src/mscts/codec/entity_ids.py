"""Where a value holds entity ids: the paths from it to each value of an `EntityId` type.

A Comparison numbers entity ids by first appearance (#21) and refuses a Mask on one. Both
find the ids here, in the schemas, by type, so neither keeps a list of packets. A path is a
tuple of steps: a key of a mapping, `EACH` for every element of a list, or a `Variant` for
the values of a Tagged type that are one variant.
"""

from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from typing import override

from mscts.codec.entity_data import ENTITY_DATA, SERIALIZERS
from mscts.codec.schema import EntityId, PrefixedArray, PrefixedOptional, Schema, Tagged, WireType
from mscts.codec.shapes import Deferred, Either, FixedArray, Holder


@dataclass(frozen=True, slots=True)
class Each:
    """The type of `EACH`."""

    @override
    def __repr__(self) -> str:
        """Read as `EACH`."""
        return "EACH"


EACH = Each()
"""The step to every element of a list, in order."""


@dataclass(frozen=True, slots=True)
class Variant:
    """The step that goes on only where a Tagged value is one variant: its `key` is `name`.

    It stays on the same value: the variant's payload is the next step, the value key.
    """

    key: str
    name: str


type Step = str | Each | Variant
"""One step of an entity id path."""

type EntityIdPath = tuple[Step, ...]
"""The steps from a value to an entity id inside it; `()` if the value is the id."""


def inner_types(wire_type: WireType[object]) -> tuple[tuple[EntityIdPath, WireType[object]], ...]:
    """The wire types `wire_type` is made of, each with the steps from its value to theirs.

    A Schema's fields are under their names, the element of an array under `EACH`, an
    optional's value where the optional's is, each Tagged variant's payload under the variant
    and the value key, a Holder's direct value under `direct`, each side of an Either under
    its key, and a Deferred type where it is. Entity metadata (`ENTITY_DATA`) is a list of
    `SERIALIZERS` values. Any other type is made of none: it is read whole.
    """
    if isinstance(wire_type, Schema):
        return tuple(((name,), field) for name, field in wire_type.fields.items())
    if isinstance(wire_type, Tagged):
        return tuple(
            ((Variant(wire_type.tag_key, name), wire_type.value_key), payload)
            for name, payload in wire_type.variants
            if payload is not None
        )
    if isinstance(wire_type, Either):
        return (((wire_type.left_key,), wire_type.left), ((wire_type.right_key,), wire_type.right))
    wrapped = _wrapped(wire_type)
    return () if wrapped is None else (wrapped,)


def _wrapped(wire_type: WireType[object]) -> tuple[EntityIdPath, WireType[object]] | None:
    """The one wire type a wrapping type is made of, with the steps to its value; else None."""
    if isinstance(wire_type, PrefixedArray | FixedArray):
        return (EACH,), wire_type.element
    if isinstance(wire_type, PrefixedOptional):
        return (), wire_type.element
    if isinstance(wire_type, Holder):
        return ("direct",), wire_type.direct
    if isinstance(wire_type, Deferred):
        return (), wire_type.resolve()
    if isinstance(wire_type, type(ENTITY_DATA)):
        return (EACH,), SERIALIZERS
    return None


def entity_id_paths(wire_type: WireType[object]) -> tuple[EntityIdPath, ...]:
    """Every path from a value of `wire_type` to an entity id in it, in wire order.

    The value of an `EntityId` type is the id itself, or None for no entity. A Deferred type
    that contains itself is walked once.

    Raises:
        ValueError: A type contains itself and an entity id, so its paths never end.
    """
    return _paths(wire_type, frozenset(), set())


def _paths(
    wire_type: WireType[object], open_types: AbstractSet[int], cut: set[int]
) -> tuple[EntityIdPath, ...]:
    """`entity_id_paths` inside the Deferreds `open_types`; one met again joins `cut`."""
    if isinstance(wire_type, EntityId):
        return ((),)
    key = id(wire_type)
    if isinstance(wire_type, Deferred):
        if key in open_types:
            cut.add(key)
            return ()
        open_types = open_types | {key}
    found = tuple(
        (*steps, *rest)
        for steps, inner in inner_types(wire_type)
        for rest in _paths(inner, open_types, cut)
    )
    if found and key in cut:
        msg = f"{wire_type!r} contains itself and an entity id, so its paths never end"
        raise ValueError(msg)
    return found
