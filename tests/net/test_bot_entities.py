"""The entities a Bot tracks: what each entity packet does, as `ClientPacketListener` does it.

The rules are the 26.3 client's (javap, docs/research/2026-10-03-bot-entities.md). The tracker
is fed the decoded fields of recorded packets, as the Bot's reader feeds it.
"""

import uuid
from collections.abc import Mapping

import pytest

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


def data(entity_id: int, *entries: tuple[int, object]) -> tuple[str, dict[str, object]]:
    """A `set_entity_data` setting each `(index, value)`, all as floats on the wire."""
    items = [{"index": index, "serializer": "float", "value": value} for index, value in entries]
    return ("minecraft:set_entity_data", {"entity_id": entity_id, "entries": items})


def test_entity_data_sets_each_index_and_keeps_the_others() -> None:
    # SynchedEntityData.assignValues: each entry by its index.
    tracker = tracked(
        added(41, ZOMBIE, 1.5, -60.0, 2.5), data(41, (9, 20.0), (5, 1.0)), data(41, (9, 15.0))
    )

    assert tracker.entities[41].data == {9: 15.0, 5: 1.0}


def removed(*entity_ids: int) -> tuple[str, dict[str, object]]:
    return ("minecraft:remove_entities", {"entity_ids": list(entity_ids)})


def test_removed_entities_are_no_longer_tracked() -> None:
    tracker = tracked(
        added(41, ZOMBIE, 1.5, -60.0, 2.5), added(42, PIG, 0.5, -60.0, 0.5), removed(41, 99)
    )

    assert list(tracker.entities) == [42]


def test_an_add_with_a_known_id_replaces_the_entity() -> None:
    # ClientLevel.addEntity removes the entity that had the id first.
    tracker = tracked(
        added(41, ZOMBIE, 1.5, -60.0, 2.5), data(41, (9, 20.0)), added(41, PIG, 0.5, -60.0, 0.5)
    )

    assert tracker.entities[41] == Entity(
        id=41, uuid=UUID, type="minecraft:pig", x=0.5, y=-60.0, z=0.5, data={}
    )


def test_a_packet_for_an_entity_not_tracked_changes_nothing() -> None:
    tracker = tracked(
        added(41, ZOMBIE, 1.5, -60.0, 2.5),
        moved(7, 4096, 0, 0),
        synced(7, {"linear": {"x": 1.0, "y": 2.0, "z": 3.0}}),
        teleported(7, 1.0, 2.0, 3.0, 0),
        data(7, (9, 1.0)),
    )

    assert dict(tracker.entities) == {
        41: Entity(id=41, uuid=UUID, type="minecraft:zombie", x=1.5, y=-60.0, z=2.5, data={})
    }


def test_an_entity_taken_from_the_view_does_not_change_later() -> None:
    tracker = tracked(added(41, ZOMBIE, 1.5, -60.0, 2.5))
    before = tracker.entities[41]
    tracker.follow(*moved(41, 4096, 0, 0))
    tracker.follow(*data(41, (9, 1.0)))

    assert (before.x, dict(before.data)) == (1.5, {})


def test_find_returns_the_only_entity_of_a_type() -> None:
    tracker = tracked(added(41, ZOMBIE, 1.5, -60.0, 2.5), added(42, PIG, 0.5, -60.0, 0.5))

    assert tracker.entities.find("minecraft:zombie").id == 41
    assert tracker.entities.find("pig").id == 42


def test_find_near_a_point_returns_the_nearest_of_the_type() -> None:
    tracker = tracked(
        added(41, ZOMBIE, 1.5, -60.0, 2.5),
        added(42, ZOMBIE, 9.5, -60.0, 9.5),
        added(43, PIG, 9.5, -60.0, 9.0),
    )

    assert tracker.entities.find("zombie", near=(10.0, -60.0, 10.0)).id == 42


def test_find_names_what_was_there_when_no_entity_has_the_type() -> None:
    tracker = tracked(added(42, PIG, 0.5, -60.0, 0.5), added(43, PIG, 1.5, -60.0, 0.5))

    with pytest.raises(LookupError, match=r"no minecraft:zombie among 2 entities: 2 minecraft:pig"):
        tracker.entities.find("zombie")


def test_find_without_near_refuses_two_of_the_type() -> None:
    tracker = tracked(added(41, ZOMBIE, 1.5, -60.0, 2.5), added(42, ZOMBIE, 9.5, -60.0, 9.5))

    message = r"2 minecraft:zombie, at \(1.5, -60.0, 2.5\) and \(9.5, -60.0, 9.5\): give near="
    with pytest.raises(LookupError, match=message):
        tracker.entities.find("zombie")


def test_find_near_refuses_two_of_the_type_at_the_same_distance() -> None:
    # Which is first differs from server to server (the ids do), so neither is picked.
    tracker = tracked(added(41, ZOMBIE, 1.0, -60.0, 0.0), added(42, ZOMBIE, -1.0, -60.0, 0.0))

    with pytest.raises(LookupError, match=r"2 minecraft:zombie are nearest to \(0.0, -60.0, 0.0\)"):
        tracker.entities.find("zombie", near=(0.0, -60.0, 0.0))


def test_a_type_id_outside_the_registry_is_named_by_its_number() -> None:
    tracker = tracked(added(41, len(TYPES), 1.5, -60.0, 2.5))

    assert tracker.entities[41].type == f"#{len(TYPES)}"
