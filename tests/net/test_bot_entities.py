"""The entities a Bot tracks: what each entity packet does, as `ClientPacketListener` does it.

The rules are the 26.3 client's (javap, docs/research/2026-10-03-bot-entities.md). The tracker
is fed the decoded fields of recorded packets, as the Bot's reader feeds it.
"""

import uuid
from collections.abc import Mapping

from mscts.codec.registry_names import registry_names
from mscts.entities import Entity, EntityTracker
from mscts.target import TARGET

TYPES = registry_names(TARGET.minecraft_version, "minecraft:entity_type")
ZOMBIE = TYPES.index("minecraft:zombie")
PIG = TYPES.index("minecraft:pig")
UUID = uuid.UUID(int=7)


def added(entity_id: int, kind: int, x: float, y: float, z: float) -> tuple[str, dict[str, object]]:
    """An `add_entity` at `x, y, z` facing nowhere in particular, not moving."""
    return (
        "minecraft:add_entity",
        {
            "entity_id": entity_id,
            "entity_uuid": UUID,
            "type": kind,
            "x": x,
            "y": y,
            "z": z,
            "velocity": {"x": 0.0, "y": 0.0, "z": 0.0},
            "pitch": 0,
            "yaw": 0,
            "head_yaw": 0,
            "data": 0,
        },
    )


def tracked(*packets: tuple[str, Mapping[str, object]]) -> EntityTracker:
    tracker = EntityTracker()
    for name, fields in packets:
        tracker.follow(name, fields)
    return tracker


def test_an_added_entity_is_tracked_with_its_type_and_position() -> None:
    tracker = tracked(added(41, ZOMBIE, 1.5, -60.0, 2.5))

    assert dict(tracker.entities) == {
        41: Entity(id=41, uuid=UUID, type="minecraft:zombie", x=1.5, y=-60.0, z=2.5, data={})
    }
