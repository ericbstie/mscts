"""Entity packets: spawn, movement, metadata, attributes, events and removal.

Field layouts: minecraft.wiki `Java_Edition_protocol/Packets`, revision 3790659
(2026-09-23, "26.3, protocol 777"), raw wikitext, checked against the 26.3 jar with `javap` on
each packet's `STREAM_CODEC`; where the two differ the jar is right. Every entity id is an
`ENTITY_ID` (or a variant of it), so a Comparison finds them by type.
"""

from collections.abc import Mapping

from mscts.codec.entity_data import ENTITY_DATA
from mscts.codec.movement import MOVE_DELTA, POSITION_PATH
from mscts.codec.schema import (
    BOOL,
    BYTE,
    DOUBLE,
    ENTITY_ID,
    ENTITY_ID_INT,
    ENTITY_ID_OPTIONAL,
    FLOAT,
    IDENTIFIER,
    INT,
    LP_VEC3,
    UUID,
    VAR_INT,
    PrefixedArray,
    PrefixedOptional,
    Schema,
)

CLIENTBOUND: Mapping[str, Schema] = {
    # Entity Animation. The action is an Unsigned Byte on the wire (0 swing main arm, 2 leave
    # bed, 3 swing off hand, 4 critical hit, 5 magic critical hit); BYTE reads it signed and
    # writes the same byte back.
    "minecraft:animate": Schema(entity_id=ENTITY_ID, action=BYTE),
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
    # Damage Event: the damage type is a registry id; the entities that caused and dealt the
    # damage are written as their id plus one (0 for none), and the position is optional.
    "minecraft:damage_event": Schema(
        entity_id=ENTITY_ID,
        source_type=VAR_INT,
        source_cause_id=ENTITY_ID_OPTIONAL,
        source_direct_id=ENTITY_ID_OPTIONAL,
        source_position=PrefixedOptional(Schema(x=DOUBLE, y=DOUBLE, z=DOUBLE)),
    ),
    # Entity Event: unlike most entity packets, the entity id is an Int.
    "minecraft:entity_event": Schema(entity_id=ENTITY_ID_INT, event_id=BYTE),
    # Entity Position Sync: the position is a path (PositionPath), the angles are Floats.
    "minecraft:entity_position_sync": Schema(
        entity_id=ENTITY_ID, position=POSITION_PATH, yaw=FLOAT, pitch=FLOAT, on_ground=BOOL
    ),
    # Hurt Animation: the yaw is the direction the damage came from, in degrees.
    "minecraft:hurt_animation": Schema(entity_id=ENTITY_ID, yaw=FLOAT),
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
    # Remove Mob Effect: the effect is a registry id.
    "minecraft:remove_mob_effect": Schema(entity_id=ENTITY_ID, effect=VAR_INT),
    "minecraft:rotate_head": Schema(entity_id=ENTITY_ID, head_yaw=BYTE),  # Set Head Rotation
    # Set Entity Metadata: entries of index, serializer and value (see ENTITY_DATA).
    "minecraft:set_entity_data": Schema(entity_id=ENTITY_ID, entries=ENTITY_DATA),
    # Link Entities: both ids are Ints (not VarInts); a holder of 0 detaches the lead.
    "minecraft:set_entity_link": Schema(
        attached_entity_id=ENTITY_ID_INT, holding_entity_id=ENTITY_ID_INT
    ),
    # Set Entity Velocity
    "minecraft:set_entity_motion": Schema(entity_id=ENTITY_ID, velocity=LP_VEC3),
    # Set Experience: the bar is the progress to the next level, 0.0 to 1.0.
    "minecraft:set_experience": Schema(
        experience_bar=FLOAT, level=VAR_INT, total_experience=VAR_INT
    ),
    # Set Health
    "minecraft:set_health": Schema(health=FLOAT, food=VAR_INT, saturation=FLOAT),
    # Set Passengers: the vehicle, and every entity riding it.
    "minecraft:set_passengers": Schema(vehicle=ENTITY_ID, passengers=PrefixedArray(ENTITY_ID)),
    # Pickup Item: the collector takes `pickup_item_count` of the collected item entity.
    "minecraft:take_item_entity": Schema(
        collected_entity_id=ENTITY_ID, collector_entity_id=ENTITY_ID, pickup_item_count=VAR_INT
    ),
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
    # Update Attributes: at most 128 attributes, each a registry id, its base value and its
    # modifiers. A modifier's operation is 0 (add), 1 (add a multiple of the base) or 2 (of the
    # total); the client maps any other to 0, so it is not range checked.
    "minecraft:update_attributes": Schema(
        entity_id=ENTITY_ID,
        attributes=PrefixedArray(
            Schema(
                attribute=VAR_INT,
                base=DOUBLE,
                modifiers=PrefixedArray(
                    Schema(id=IDENTIFIER, amount=DOUBLE, operation=VAR_INT),
                ),
            ),
            max_length=128,
        ),
    ),
    # Entity Effect: the effect is a registry id, the duration is in ticks (-1 is infinite) and
    # the flags are a bit field (1 ambient, 2 visible, 4 show icon, 8 has a blend).
    "minecraft:update_mob_effect": Schema(
        entity_id=ENTITY_ID, effect=VAR_INT, amplifier=VAR_INT, duration=VAR_INT, flags=BYTE
    ),
}
