"""Entity packets: spawn, movement, metadata, attributes, events and removal.

Field layouts: minecraft.wiki `Java_Edition_protocol/Packets`, revision 3790659
(2026-09-23, "26.3, protocol 777"), raw wikitext, checked against the 26.3 jar with `javap` on
each packet's `STREAM_CODEC`; where the two differ the jar is right. Every entity id is an
`ENTITY_ID` (or a variant of it), so a Comparison finds them by type.
"""

from collections.abc import Mapping

from mscts.codec.schema import (
    BYTE,
    DOUBLE,
    ENTITY_ID,
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
    "minecraft:remove_entities": Schema(entity_ids=PrefixedArray(ENTITY_ID)),  # Remove Entities
}
