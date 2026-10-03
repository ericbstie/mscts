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


def moved(entity_id: int, x: int, y: int, z: int) -> tuple[str, dict[str, object]]:
    """A `move_entity_pos` by `x, y, z` 4096ths of a block."""
    delta = {"on_ground": True, "linear": {"x": x, "y": y, "z": z}}
    return ("minecraft:move_entity_pos", {"entity_id": entity_id, "movement": delta})


def position(tracker: EntityTracker, entity_id: int) -> tuple[float, float, float]:
    entity = tracker.entities[entity_id]
    return (entity.x, entity.y, entity.z)


def test_a_move_decodes_each_axis_against_the_base_and_keeps_an_axis_that_did_not_move() -> None:
    # VecDeltaCodec.decode: round(base * 4096) + delta, over 4096; a 0 delta keeps the base's
    # value exactly. 0.1 is 409.6 4096ths, which rounds to 410.
    tracker = tracked(added(41, ZOMBIE, 0.1, 0.1, 0.1), moved(41, 4096, 0, 1))

    assert position(tracker, 41) == (4506 / 4096, 0.1, 411 / 4096)


def test_a_move_after_a_move_decodes_against_where_the_first_ended() -> None:
    tracker = tracked(
        added(41, ZOMBIE, 1.5, -60.0, 2.5), moved(41, 2048, 0, 0), moved(41, 2048, 0, 0)
    )

    assert position(tracker, 41) == (2.5, -60.0, 2.5)


def test_a_stepped_move_ends_at_its_last_step() -> None:
    # VecDelta$Stepped.decode: each step against the one before it.
    steps = [{"ticks": 1, "x": 4096, "y": 0, "z": 0}, {"ticks": 2, "x": 4096, "y": 4096, "z": 0}]
    delta = {"on_ground": True, "stepped": steps}
    fields = {"entity_id": 41, "movement": delta, "yaw": 3, "pitch": 4}
    move = ("minecraft:move_entity_pos_rot", fields)
    tracker = tracked(added(41, ZOMBIE, 1.5, -60.0, 2.5), move, moved(41, 4096, 0, 0))

    assert position(tracker, 41) == (4.5, -59.0, 2.5)


def synced(entity_id: int, path: Mapping[str, object]) -> tuple[str, dict[str, object]]:
    """An `entity_position_sync` along `path`."""
    fields = {"entity_id": entity_id, "position": path, "yaw": 0.0, "pitch": 0.0}
    return ("minecraft:entity_position_sync", {**fields, "on_ground": True})


def test_a_position_sync_puts_the_entity_at_the_path_end_and_moves_the_base() -> None:
    linear = synced(41, {"linear": {"x": 10.0, "y": -59.0, "z": 3.0}})
    tracker = tracked(added(41, ZOMBIE, 1.5, -60.0, 2.5), linear)
    assert position(tracker, 41) == (10.0, -59.0, 3.0)

    steps = [
        {"x": 11.0, "y": -59.0, "z": 3.0, "tick_offset": 1},
        {"x": 12.0, "y": -58.0, "z": 3.0, "tick_offset": 2},
    ]
    tracker.follow(*synced(41, {"stepped": steps}))
    tracker.follow(*moved(41, 4096, 0, 0))
    assert position(tracker, 41) == (13.0, -58.0, 3.0)


RELATIVE_X = 0x01


def teleported(
    entity_id: int, x: float, y: float, z: float, flags: int
) -> tuple[str, dict[str, object]]:
    """A `teleport_entity` to `x, y, z` with the Teleport Flags `flags`, not moving or turning."""
    velocity = {"velocity_x": 0.0, "velocity_y": 0.0, "velocity_z": 0.0}
    rotation = {"yaw": 0.0, "pitch": 0.0}
    fields: dict[str, object] = {"entity_id": entity_id, "x": x, "y": y, "z": z}
    fields |= velocity | rotation
    return ("minecraft:teleport_entity", {**fields, "flags": flags, "on_ground": True})


def test_a_teleport_adds_a_flagged_axis_and_replaces_the_others() -> None:
    teleport = teleported(41, 2.0, -50.0, 7.0, RELATIVE_X)
    tracker = tracked(added(41, ZOMBIE, 1.5, -60.0, 2.5), teleport)

    assert position(tracker, 41) == (3.5, -50.0, 7.0)


def test_a_teleport_leaves_the_base_so_a_later_move_decodes_against_the_old_one() -> None:
    # handleTeleportEntity never sets the position codec's base: only moves and syncs do.
    tracker = tracked(
        added(41, ZOMBIE, 1.5, -60.0, 2.5),
        teleported(41, 100.0, -50.0, 100.0, 0),
        moved(41, 4096, 0, 0),
    )

    assert position(tracker, 41) == (2.5, -60.0, 2.5)
