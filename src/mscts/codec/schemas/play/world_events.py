"""World event packets: level events, sounds, particles and game events.

Field layouts: minecraft.wiki `Java_Edition_protocol/Packets`, revision 3799543 (2026-09-27,
"26.3, protocol 777"), raw wikitext, checked against the 26.3 jar with `javap` on each packet's
`STREAM_CODEC`; the two agree (docs/research/2026-10-01-block-world-events.md). A sound is a
`SOUND_EVENT`, a particle the shared `PARTICLE`, and an entity id an `ENTITY_ID`, so a Comparison
finds each by type.
"""

from collections.abc import Mapping

from mscts.codec.particles import PARTICLE
from mscts.codec.schema import (
    BOOL,
    DOUBLE,
    ENTITY_ID,
    FLOAT,
    INT,
    LONG,
    POSITION,
    UBYTE,
    VAR_INT,
    Schema,
)
from mscts.codec.shapes import ENUM, SOUND_EVENT, SOUND_SOURCE

CLIENTBOUND: Mapping[str, Schema] = {
    # Game Event: an Unsigned Byte id (0 to 13 in 26.3: begin raining, change game mode, ...) and
    # a Float whose meaning the id gives. Vanilla reads an id it has no name for into a null event
    # and ignores it, so any byte is a packet.
    "minecraft:game_event": Schema(event=UBYTE, value=FLOAT),
    # World Event: an Int event (a door's sound, a block breaking, a lava fizz), the position,
    # and an Int whose meaning the event gives (a block breaking: its block state). A global event
    # is heard by every player in the level, not only those near the position.
    "minecraft:level_event": Schema(event_id=INT, pos=POSITION, data=INT, global_event=BOOL),
    # Particle. `override_limiter` is the wiki's "Override Limiter" and `always_show` its "Always
    # Visible"; `x_dist` to `z_dist` are its "Distance" (the spread) and `x_max_speed` to
    # `z_max_speed` its "Max Speed". The randomization type is a plain VarInt: vanilla reads a
    # number it has no name for as the default.
    "minecraft:level_particles": Schema(
        particle=PARTICLE,
        override_limiter=BOOL,
        always_show=BOOL,
        x=DOUBLE,
        y=DOUBLE,
        z=DOUBLE,
        x_dist=FLOAT,
        y_dist=FLOAT,
        z_dist=FLOAT,
        x_max_speed=FLOAT,
        y_max_speed=FLOAT,
        z_max_speed=FLOAT,
        count=VAR_INT,
        randomization_type=ENUM,
    ),
    # Sound Effect. The position is in eighths of a block (an Int each); the category is a
    # `SoundSource` ordinal, and vanilla fails on one it does not have. The seed picks the
    # variant of the sound and is random in vanilla, one draw per sound (the research note).
    "minecraft:sound": Schema(
        sound=SOUND_EVENT,
        category=SOUND_SOURCE,
        x=INT,
        y=INT,
        z=INT,
        volume=FLOAT,
        pitch=FLOAT,
        seed=LONG,
    ),
    # Entity Sound Effect: the sound follows the entity instead of a position.
    "minecraft:sound_entity": Schema(
        sound=SOUND_EVENT,
        category=SOUND_SOURCE,
        entity_id=ENTITY_ID,
        volume=FLOAT,
        pitch=FLOAT,
        seed=LONG,
    ),
}
