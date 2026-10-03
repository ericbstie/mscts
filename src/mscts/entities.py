"""The entities a Bot's server has told it about, tracked as the 26.3 client tracks them.

`ClientPacketListener` (javap, docs/research/2026-10-03-bot-entities.md) adds an entity on
`add_entity` and changes it on the entity packets that name its id. The tracker keeps what the
server last said: each entity's type, position and data. It keeps no rotation, and does not move
an entity between packets as the client does.
"""

import math
import uuid
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import cast, override

from mscts.codec.registry_names import registry_names
from mscts.net import ProtocolError
from mscts.target import TARGET


@dataclass(frozen=True, slots=True)
class Entity:
    """One entity, as the server last described it.

    Attributes:
        id: Its entity id, which differs from server to server.
        uuid: Its UUID.
        type: Its type's name, e.g. `minecraft:zombie`; `#<id>` for an id outside the registry.
        x: Its x, in blocks.
        y: Its y, in blocks.
        z: Its z, in blocks.
        data: Its entity data so far, by index (`set_entity_data`).
    """

    id: int
    uuid: uuid.UUID
    type: str
    x: float
    y: float
    z: float
    data: Mapping[int, object] = field(default_factory=dict)


type _Vec = tuple[float, float, float]

_DELTA_SCALE = 4096.0
"""`VecDeltaCodec.TRUNCATION_STEPS`: a move delta counts 4096ths of a block."""

_RELATIVE_X, _RELATIVE_Y, _RELATIVE_Z = 0x01, 0x02, 0x04
"""The Teleport Flags bits that make an axis of `teleport_entity` add to the position."""


@dataclass(slots=True)
class _Tracked:
    """An entity as the tracker holds it, with its base for move deltas (`VecDeltaCodec`)."""

    id: int
    uuid: uuid.UUID
    type: str
    position: _Vec
    base: _Vec
    data: dict[int, object]

    def snapshot(self) -> Entity:
        x, y, z = self.position
        data = MappingProxyType(dict(self.data))
        return Entity(id=self.id, uuid=self.uuid, type=self.type, x=x, y=y, z=z, data=data)


class Entities(Mapping[int, Entity]):
    """A read-only view of the tracked entities, by entity id (`Bot.entities`)."""

    def __init__(self, tracked: Mapping[int, _Tracked]) -> None:
        """View `tracked`, which the tracker goes on changing."""
        self._tracked = tracked

    @override
    def __getitem__(self, entity_id: int) -> Entity:
        """The entity with `entity_id`, as it is now."""
        return self._tracked[entity_id].snapshot()

    @override
    def __iter__(self) -> Iterator[int]:
        """The entity ids, as they are now."""
        return iter(list(self._tracked))

    @override
    def __len__(self) -> int:
        """How many entities are tracked."""
        return len(self._tracked)


class EntityTracker:
    """Follows the entity packets a Bot receives, as `ClientPacketListener` does.

    Attributes:
        entities: The read-only view of what it tracks.
    """

    def __init__(self) -> None:
        """Track no entities yet."""
        self._tracked: dict[int, _Tracked] = {}
        self.entities = Entities(self._tracked)

    def follow(self, name: str, fields: Mapping[str, object]) -> None:
        """Apply one clientbound play packet's decoded `fields`; other packets change nothing.

        A packet for an entity id it does not track changes nothing either, as the client
        ignores one for an id its level does not have.
        """
        if name == "minecraft:add_entity":
            self._add(fields)
            return
        if name == "minecraft:remove_entities":
            for entity_id in _get(fields, "entity_ids", list):
                self._tracked.pop(entity_id, None)
            return
        change = _CHANGES.get(name)
        tracked = self._tracked.get(_int(fields, "entity_id")) if change else None
        if change is not None and tracked is not None:
            change(tracked, fields)

    def _add(self, fields: Mapping[str, object]) -> None:
        entity_id = _int(fields, "entity_id")
        at = (_float(fields, "x"), _float(fields, "y"), _float(fields, "z"))
        self._tracked[entity_id] = _Tracked(
            id=entity_id,
            uuid=_get(fields, "entity_uuid", uuid.UUID),
            type=_type_name(_int(fields, "type")),
            position=at,
            base=at,
            data={},
        )


def _move(tracked: _Tracked, fields: Mapping[str, object]) -> None:
    """`handleMoveEntity`: decode the delta against the base; end there, and make it the base."""
    movement = _get(fields, "movement", Mapping)
    if "linear" in movement:
        end = _decoded(tracked.base, _get(movement, "linear", Mapping))
    else:
        end = tracked.base
        for step in _get(movement, "stepped", list):
            end = _decoded(end, step)
    tracked.position = tracked.base = end


def _sync(tracked: _Tracked, fields: Mapping[str, object]) -> None:
    """`handleEntityPositionSync`: the path's end is the position and the base."""
    path = _get(fields, "position", Mapping)
    end = _get(path, "linear", Mapping) if "linear" in path else _get(path, "stepped", list)[-1]
    tracked.position = tracked.base = (_float(end, "x"), _float(end, "y"), _float(end, "z"))


def _teleport(tracked: _Tracked, fields: Mapping[str, object]) -> None:
    """`calculateAbsolute`: a flagged axis adds to the position. The base stays."""
    flags = _int(fields, "flags")
    x, y, z = tracked.position
    tracked.position = (
        (x if flags & _RELATIVE_X else 0.0) + _float(fields, "x"),
        (y if flags & _RELATIVE_Y else 0.0) + _float(fields, "y"),
        (z if flags & _RELATIVE_Z else 0.0) + _float(fields, "z"),
    )


def _set_data(tracked: _Tracked, fields: Mapping[str, object]) -> None:
    """`SynchedEntityData.assignValues`: each entry's value by its index; the others stay."""
    for entry in _get(fields, "entries", list):
        item = cast("Mapping[str, object]", entry)
        tracked.data[_int(item, "index")] = item.get("value")


_CHANGES: dict[str, Callable[[_Tracked, Mapping[str, object]], None]] = {
    "minecraft:move_entity_pos": _move,
    "minecraft:move_entity_pos_rot": _move,
    "minecraft:entity_position_sync": _sync,
    "minecraft:teleport_entity": _teleport,
    "minecraft:set_entity_data": _set_data,
}
"""What each entity packet but `add_entity` does to the entity it names."""


def _decoded(base: _Vec, delta: object) -> _Vec:
    """`VecDeltaCodec.decode`: each axis that moved is round(base * 4096) + delta, over 4096."""
    if not isinstance(delta, Mapping):
        msg = f"expected a delta, got {delta!r}"
        raise ProtocolError(msg)
    axes = cast("Mapping[str, object]", delta)
    return (
        _axis(base[0], _int(axes, "x")),
        _axis(base[1], _int(axes, "y")),
        _axis(base[2], _int(axes, "z")),
    )


def _axis(base: float, delta: int) -> float:
    if delta == 0:
        return base
    return (_java_round(base * _DELTA_SCALE) + delta) / _DELTA_SCALE


def _java_round(value: float) -> int:
    """Java's `Math.round`: the nearest integer, a half rounded up (floor of value + 0.5, exact)."""
    floor = math.floor(value)
    return floor + 1 if value - floor >= 0.5 else floor  # noqa: PLR2004 - the half


def _type_name(type_id: int) -> str:
    names = registry_names(TARGET.minecraft_version, "minecraft:entity_type")
    return names[type_id] if 0 <= type_id < len(names) else f"#{type_id}"


def _get[T](fields: Mapping[str, object], name: str, kind: type[T]) -> T:
    """`fields[name]`, which the packet's schema guarantees is a `kind`."""
    value = fields.get(name)
    if not isinstance(value, kind):
        msg = f"expected a {kind.__name__} {name}, got {value!r}"
        raise ProtocolError(msg)
    return value


def _int(fields: Mapping[str, object], name: str) -> int:
    return _get(fields, name, int)


def _float(fields: Mapping[str, object], name: str) -> float:
    return _get(fields, name, float)
