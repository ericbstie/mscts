"""Entity packets: spawn, movement, metadata, attributes, events and removal.

Field layouts: minecraft.wiki `Java_Edition_protocol/Packets`, revision 3790659
(2026-09-23, "26.3, protocol 777"), raw wikitext, checked against the 26.3 jar with `javap` on
each packet's `STREAM_CODEC`; where the two differ the jar is right. Every entity id is an
`ENTITY_ID` (or a variant of it), so a Comparison finds them by type.
"""

from collections.abc import Mapping

from mscts.codec.movement import MOVE_DELTA, POSITION_PATH
from mscts.codec.schema import (
    BOOL,
    BYTE,
    DOUBLE,
    ENTITY_ID,
    FLOAT,
    INT,
    LP_VEC3,
    UUID,
    VAR_INT,
    PrefixedArray,
    Schema,
)

CLIENTBOUND: Mapping[str, Schema] = {
    # Spawn Entity. The velocity is an LpVec3; the angles are in 1/256 of a turn. `data` is
    # the object data (a projectile's owner, a block's state, ...): its meaning depends on
    # the entity type.
    "minecraft:add_entity": Schema(
        entity_id=ENTITY_ID,
        entity_uuid=UUID,
        type=VAR_INT,
        x=DOUBLE,
        y=DOUBLE,
        z=DOUBLE,
        velocity=LP_VEC3,
        pitch=BYTE,
        yaw=BYTE,
        head_yaw=BYTE,
        data=VAR_INT,
    ),
    # Bundle Delimiter: the packets between two of them apply in the same tick.
    "minecraft:bundle_delimiter": Schema(),
    # Entity Position Sync: the position is a path (PositionPath), the angles are Floats.
    "minecraft:entity_position_sync": Schema(
        entity_id=ENTITY_ID, position=POSITION_PATH, yaw=FLOAT, pitch=FLOAT, on_ground=BOOL
    ),
    # Update Entity Position
    "minecraft:move_entity_pos": Schema(entity_id=ENTITY_ID, movement=MOVE_DELTA),
    # Update Entity Position and Rotation. The angles are 1/256 of a turn, the yaw first.
    "minecraft:move_entity_pos_rot": Schema(
        entity_id=ENTITY_ID, movement=MOVE_DELTA, yaw=BYTE, pitch=BYTE
    ),
    # Update Entity Rotation
    "minecraft:move_entity_rot": Schema(entity_id=ENTITY_ID, on_ground=BOOL, yaw=BYTE, pitch=BYTE),
    # Move Minecart Along Track. A step's yaw and pitch are one byte each.
    "minecraft:move_minecart_along_track": Schema(
        entity_id=ENTITY_ID,
        steps=PrefixedArray(
            Schema(
                x=DOUBLE,
                y=DOUBLE,
                z=DOUBLE,
                velocity_x=DOUBLE,
                velocity_y=DOUBLE,
                velocity_z=DOUBLE,
                yaw=BYTE,
                pitch=BYTE,
                weight=FLOAT,
            )
        ),
    ),
    "minecraft:remove_entities": Schema(entity_ids=PrefixedArray(ENTITY_ID)),  # Remove Entities
    "minecraft:rotate_head": Schema(entity_id=ENTITY_ID, head_yaw=BYTE),  # Set Head Rotation
    # Set Entity Velocity
    "minecraft:set_entity_motion": Schema(entity_id=ENTITY_ID, velocity=LP_VEC3),
    # Teleport Entity. Flags is the Teleport Flags bit field, as in player_position.
    "minecraft:teleport_entity": Schema(
        entity_id=ENTITY_ID,
        x=DOUBLE,
        y=DOUBLE,
        z=DOUBLE,
        velocity_x=DOUBLE,
        velocity_y=DOUBLE,
        velocity_z=DOUBLE,
        yaw=FLOAT,
        pitch=FLOAT,
        flags=INT,
        on_ground=BOOL,
    ),
}
