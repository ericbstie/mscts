"""The entities a Bot's server has told it about, tracked as the 26.3 client tracks them.

`ClientPacketListener` (javap, docs/research/2026-10-03-bot-entities.md) adds an entity on
`add_entity` and changes it on the entity packets that name its id. The tracker keeps what the
server last said: each entity's type, position and data. It keeps no rotation, and does not move
an entity between packets as the client does.
"""

import uuid
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import override

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


@dataclass(slots=True)
class _Tracked:
    """An entity as the tracker holds it, with its base for move deltas (`VecDeltaCodec`)."""

    id: int
    uuid: uuid.UUID
    type: str
    x: float
    y: float
    z: float
    data: dict[int, object]

    def snapshot(self) -> Entity:
        return Entity(
            id=self.id,
            uuid=self.uuid,
            type=self.type,
            x=self.x,
            y=self.y,
            z=self.z,
            data=MappingProxyType(dict(self.data)),
        )


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
        """Apply one clientbound play packet's decoded `fields`; other packets change nothing."""
        if name == "minecraft:add_entity":
            self._add(fields)

    def _add(self, fields: Mapping[str, object]) -> None:
        entity_id = _int(fields, "entity_id")
        self._tracked[entity_id] = _Tracked(
            id=entity_id,
            uuid=_get(fields, "entity_uuid", uuid.UUID),
            type=_type_name(_int(fields, "type")),
            x=_float(fields, "x"),
            y=_float(fields, "y"),
            z=_float(fields, "z"),
            data={},
        )


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
