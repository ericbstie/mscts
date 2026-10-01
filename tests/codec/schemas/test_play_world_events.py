"""The world event packets of Target 26.3: level event, sound, particles, game event and explosion.

Layouts come from the 26.3 jar (`javap` on each packet's `STREAM_CODEC`) and the wiki (revision
3799543), which agree (docs/research/2026-10-01-block-world-events.md). The payloads are recorded
from vanilla 26.3, each named for the command that caused it, except `sound_entity`, which no
command makes vanilla send (mob AI does): that one is built by hand from the layout.
"""

import pytest
from support.play import decode_error, encode_error, round_trip

from mscts.codec.particles import PARTICLE
from mscts.codec.schema import ENTITY_ID
from mscts.codec.schemas import play
from mscts.codec.shapes import SOUND_EVENT, SOUND_SOURCE, VEC3

EXPLODE = "minecraft:explode"
LEVEL_EVENT = "minecraft:level_event"
SOUND = "minecraft:sound"
SOUND_ENTITY = "minecraft:sound_entity"
LEVEL_PARTICLES = "minecraft:level_particles"
GAME_EVENT = "minecraft:game_event"

# Level event: an Int event, a position, an Int data and a Bool. Recorded from breaking the stone
# at 1 -60 1 (event 2001, block break: the data is the block state), and from lava poured on
# water at 20 -60 20 (event 1501, the fizz; no data).


def test_breaking_a_block_decodes_its_event_position_and_block_state() -> None:
    round_trip(
        LEVEL_EVENT,
        {"event_id": 2001, "pos": {"x": 1, "y": -60, "z": 1}, "data": 1, "global_event": False},
        "000007d1 0000004000001fc4 00000001 00",
    )


def test_lava_meeting_water_decodes_to_an_event_with_no_data() -> None:
    round_trip(
        LEVEL_EVENT,
        {"event_id": 1501, "pos": {"x": 20, "y": -60, "z": 20}, "data": 0, "global_event": False},
        "000005dd 0000050000014fc4 00000000 00",
    )


def test_a_global_level_event_keeps_the_sign_of_its_ints_and_its_position() -> None:
    # Built by hand: both Ints are signed, and the Bool is the one that tells every player.
    round_trip(
        LEVEL_EVENT,
        {"event_id": -1, "pos": {"x": -1, "y": 0, "z": -1}, "data": -2, "global_event": True},
        "ffffffff fffffffffffff000 fffffffe 01",
    )


def test_a_level_event_refuses_a_bool_that_is_neither_zero_nor_one() -> None:
    error = decode_error(LEVEL_EVENT, "000007d1 0000004000001fc4 00000001 02")
    assert "global_event: invalid bool byte 0x02" in error


def test_a_level_event_writes_only_ints_for_its_event_and_data() -> None:
    fields = {"event_id": 2001, "pos": {"x": 1, "y": -60, "z": 1}, "data": 1, "global_event": False}
    assert "event_id: expected an int" in encode_error(LEVEL_EVENT, {**fields, "event_id": 2001.0})
    assert "data: int 2147483648 out of range" in encode_error(
        LEVEL_EVENT, {**fields, "data": 2**31}
    )


# Sound: a sound event (a registry id or an inline one), a category (a SoundSource ordinal), the
# position in eighths of a block as three Ints, the volume and pitch as Floats, and the Long seed
# that picks the variant of the sound. The seed is random in vanilla, so the Comparison does not
# compare it (the research note).

NOTE_BLOCK_SOUND = {
    "sound": {"reference": 1171},
    "category": 2,
    "x": 68,
    "y": -476,
    "z": 68,
    "volume": 3.0,
    "pitch": 0.5,
    "seed": 3208859991703385433,
}
NOTE_BLOCK_SOUND_HEX = "9409 02 00000044 fffffe24 00000044 40400000 3f000000 2c88292943717559"


def test_a_note_block_played_by_redstone_decodes_to_its_sound_in_the_records_category() -> None:
    # A note block at 8 -60 8, powered by a redstone block: 68 and -476 are 8.5 and -59.5 blocks.
    round_trip(SOUND, NOTE_BLOCK_SOUND, NOTE_BLOCK_SOUND_HEX)


def test_a_door_powered_by_redstone_decodes_to_its_sound_with_a_random_pitch() -> None:
    round_trip(
        SOUND,
        {
            "sound": {"reference": 1850},
            "category": 4,
            "x": 100,
            "y": -476,
            "z": 68,
            "volume": 1.0,
            "pitch": 0.9715679883956909,
            "seed": -3210500971036782204,
        },
        "bb0e 04 00000064 fffffe24 00000044 3f800000 3f78b8ae d3720260764e5184",
    )


def test_a_playsound_names_its_sound_in_the_packet_and_not_by_a_registry_id() -> None:
    round_trip(
        SOUND,
        {
            "sound": {
                "direct": {"location": "minecraft:block.note_block.harp", "fixed_range": None}
            },
            "category": 0,
            "x": 60,
            "y": -480,
            "z": -44,
            "volume": 1.0,
            "pitch": 1.0,
            "seed": -7325282947829501054,
        },
        "00 1f 6d696e6563726166743a626c6f636b2e6e6f74655f626c6f636b2e68617270 00"
        " 00 0000003c fffffe20 ffffffd4 3f800000 3f800000 9a575df84f657382",
    )


def test_a_playsound_in_the_neutral_category_decodes_its_category() -> None:
    round_trip(
        SOUND,
        {
            "sound": {"direct": {"location": "minecraft:entity.pig.ambient", "fixed_range": None}},
            "category": 6,
            "x": 60,
            "y": -480,
            "z": -44,
            "volume": 1.0,
            "pitch": 1.0,
            "seed": 460465355753578488,
        },
        "00 1c 6d696e6563726166743a656e746974792e7069672e616d6269656e74 00"
        " 06 0000003c fffffe20 ffffffd4 3f800000 3f800000 0663e6cd2910dff8",
    )


def test_a_sound_with_a_fixed_range_keeps_it() -> None:
    # Built by hand: an inline sound whose range does not grow with its volume.
    round_trip(
        SOUND,
        {
            "sound": {"direct": {"location": "a:b", "fixed_range": 16.0}},
            "category": 9,
            "x": 0,
            "y": 0,
            "z": 0,
            "volume": 1.0,
            "pitch": 1.0,
            "seed": 1,
        },
        "00 03 613a62 01 41800000 09 00000000 00000000 00000000 3f800000 3f800000 0000000000000001",
    )


def test_a_sound_refuses_a_category_past_the_last_sound_source() -> None:
    error = decode_error(SOUND, NOTE_BLOCK_SOUND_HEX.replace("9409 02", "9409 0b"))
    assert "category: 11 is not an ordinal of 0 to 10" in error


def test_a_sound_writes_only_a_category_that_is_a_sound_source() -> None:
    error = encode_error(SOUND, {**NOTE_BLOCK_SOUND, "category": 11})
    assert "category: 11 is not an ordinal of 0 to 10" in error


@pytest.mark.parametrize("field", ["x", "y", "z"])
def test_a_sound_position_is_an_int_of_eighths_of_a_block(field: str) -> None:
    assert f"{field}: int 2147483648 out of range" in encode_error(
        SOUND, {**NOTE_BLOCK_SOUND, field: 2**31}
    )
    assert f"{field}: expected an int" in encode_error(SOUND, {**NOTE_BLOCK_SOUND, field: 8.5})


@pytest.mark.parametrize("field", ["volume", "pitch"])
def test_a_sound_volume_and_pitch_are_floats(field: str) -> None:
    assert f"{field}: expected a float" in encode_error(SOUND, {**NOTE_BLOCK_SOUND, field: 1})


def test_a_sound_seed_is_a_long() -> None:
    assert "seed: long 9223372036854775808 out of range" in encode_error(
        SOUND, {**NOTE_BLOCK_SOUND, "seed": 2**63}
    )


# Sound entity: the same sound, category, volume, pitch and seed, but made by an entity, so it
# follows it instead of a position. Mob AI sends it (a goat ramming, a frog's tongue), and no
# command does, so this one is built by hand.

ENTITY_SOUND = {
    "sound": {"reference": 5},
    "category": 6,
    "entity_id": 42,
    "volume": 1.0,
    "pitch": 1.5,
    "seed": 0x0123456789ABCDEF,
}
ENTITY_SOUND_HEX = "06 06 2a 3f800000 3fc00000 0123456789abcdef"


def test_a_sound_made_by_an_entity_decodes_to_its_entity_id() -> None:
    round_trip(SOUND_ENTITY, ENTITY_SOUND, ENTITY_SOUND_HEX)


def test_a_sound_made_by_an_entity_names_an_inline_sound_and_a_long_entity_id() -> None:
    round_trip(
        SOUND_ENTITY,
        {
            "sound": {"direct": {"location": "a:b", "fixed_range": None}},
            "category": 10,
            "entity_id": 300,
            "volume": 0.5,
            "pitch": 2.0,
            "seed": -1,
        },
        "00 03 613a62 00 0a ac02 3f000000 40000000 ffffffffffffffff",
    )


def test_a_sound_made_by_an_entity_refuses_a_category_past_the_last_sound_source() -> None:
    error = decode_error(SOUND_ENTITY, ENTITY_SOUND_HEX.replace("06 06", "06 0b", 1))
    assert "category: 11 is not an ordinal of 0 to 10" in error


def test_a_sound_made_by_an_entity_writes_only_a_category_that_is_a_sound_source() -> None:
    error = encode_error(SOUND_ENTITY, {**ENTITY_SOUND, "category": -1})
    assert "category: -1 is not an ordinal of 0 to 10" in error


def test_the_sound_packets_use_the_shared_shapes() -> None:
    sound, sound_entity = play.CLIENTBOUND[SOUND], play.CLIENTBOUND[SOUND_ENTITY]
    assert sound.fields["sound"] is SOUND_EVENT
    assert sound_entity.fields["sound"] is SOUND_EVENT
    assert sound.fields["category"] is SOUND_SOURCE
    assert sound_entity.fields["category"] is SOUND_SOURCE
    assert sound_entity.fields["entity_id"] is ENTITY_ID


# Level particles: a particle (its type id, then its options), two Bools, the position as three
# Doubles, the spread and the maximum speed as three Floats each, the count and how the particles
# are randomized. Recorded from `particle` with the flame, a red dust and a stone block at 1.5
# -59 1.5.

FLAME = (
    "27 01 00 3ff8000000000000 c04d800000000000 3ff8000000000000"
    " 3f000000 3f000000 3f000000 3dcccccd 3dcccccd 3dcccccd 0a 00"
)
FLAME_FIELDS = {
    "particle": {"type": "minecraft:flame", "options": None},
    "override_limiter": True,
    "always_show": False,
    "x": 1.5,
    "y": -59.0,
    "z": 1.5,
    "x_dist": 0.5,
    "y_dist": 0.5,
    "z_dist": 0.5,
    "x_max_speed": 0.10000000149011612,
    "y_max_speed": 0.10000000149011612,
    "z_max_speed": 0.10000000149011612,
    "count": 10,
    "randomization_type": 0,
}
STILL = {
    "x_dist": 0.0,
    "y_dist": 0.0,
    "z_dist": 0.0,
    "x_max_speed": 0.0,
    "y_max_speed": 0.0,
    "z_max_speed": 0.0,
}
"""The fields of a particle that does not spread or move (a dust, a block)."""


def test_a_flame_particle_command_decodes_its_position_spread_and_speed() -> None:
    round_trip(LEVEL_PARTICLES, FLAME_FIELDS, FLAME)


def test_a_dust_particle_decodes_its_color_and_scale() -> None:
    round_trip(
        LEVEL_PARTICLES,
        {
            **FLAME_FIELDS,
            **STILL,
            "particle": {"type": "minecraft:dust", "options": {"color": -65536, "scale": 1.0}},
            "count": 1,
        },
        "15 ffff0000 3f800000 01 00 3ff8000000000000 c04d800000000000 3ff8000000000000"
        " 00000000 00000000 00000000 00000000 00000000 00000000 01 00",
    )


def test_a_block_particle_decodes_its_block_state() -> None:
    round_trip(
        LEVEL_PARTICLES,
        {
            **FLAME_FIELDS,
            **STILL,
            "particle": {"type": "minecraft:block", "options": {"block_state": 1}},
            "count": 5,
        },
        "01 01 01 00 3ff8000000000000 c04d800000000000 3ff8000000000000"
        " 00000000 00000000 00000000 00000000 00000000 00000000 05 00",
    )


def test_a_particle_keeps_a_randomization_type_always_show_and_a_count_of_300() -> None:
    # Built by hand from the flame: always_show on instead of override_limiter, the randomization
    # type that has a speed, and a count that takes two bytes as a VarInt.
    round_trip(
        LEVEL_PARTICLES,
        {
            **FLAME_FIELDS,
            "override_limiter": False,
            "always_show": True,
            "count": 300,
            "randomization_type": 2,
        },
        FLAME.replace("27 01 00", "27 00 01").replace("0a 00", "ac02 02"),
    )


def test_a_randomization_type_vanilla_has_no_name_for_still_decodes() -> None:
    # Vanilla reads a number outside its three types as the default, so it is no packet to refuse.
    # 300 takes two bytes: the type is a VarInt.
    round_trip(
        LEVEL_PARTICLES,
        {**FLAME_FIELDS, "randomization_type": 300},
        FLAME.replace("0a 00", "0a ac02"),
    )


def test_a_particle_packet_uses_the_shared_particle() -> None:
    assert play.CLIENTBOUND[LEVEL_PARTICLES].fields["particle"] is PARTICLE


def test_a_particle_packet_names_the_field_that_is_bad() -> None:
    error = encode_error(LEVEL_PARTICLES, {**FLAME_FIELDS, "x_dist": 1})
    assert "x_dist: expected a float" in error


# Game event: an Unsigned Byte event and a Float. Recorded from `weather rain` (the rain level
# eases in a step per tick: event 7) and `gamemode creative` (event 3, the mode as a Float).


def test_the_rain_level_changing_decodes_to_its_event_and_value() -> None:
    round_trip(GAME_EVENT, {"event": 7, "value": 0.009999999776482582}, "07 3c23d70a")


def test_a_game_mode_change_decodes_to_its_event_and_value() -> None:
    round_trip(GAME_EVENT, {"event": 3, "value": 1.0}, "03 3f800000")


def test_a_game_event_vanilla_has_no_name_for_still_decodes() -> None:
    # Vanilla reads the id into a null event and then ignores it, so a Candidate that sends a
    # wrong one is a difference to report, not a packet to refuse.
    round_trip(GAME_EVENT, {"event": 200, "value": 0.0}, "c8 00000000")


def test_a_game_event_writes_only_an_unsigned_byte_event() -> None:
    assert "event: 256 out of range" in encode_error(GAME_EVENT, {"event": 256, "value": 0.0})
    assert "event: -1 out of range" in encode_error(GAME_EVENT, {"event": -1, "value": 0.0})


# Explode: the centre (three Doubles), the radius (a Float), how many blocks it destroyed (an
# Int), the knockback it gives the player (optional, three Doubles), the particle and sound of the
# blast, the particles of the blocks it destroyed (a weighted list: each particle with a scaling
# and a speed, then its VarInt weight), and whether to play the sound. Recorded from a TNT at 10.5
# -60 -5.5, with a Bot beside it.

POOF = {"type": "minecraft:poof", "options": None}
SMOKE = {"type": "minecraft:smoke", "options": None}
TNT_EXPLOSION = {
    "center": {"x": 10.5, "y": -59.93874999880791, "z": -5.5},
    "radius": 4.0,
    "block_count": 667,
    "player_knockback": {"x": -0.5545357112409718, "y": 0.288127513960013, "z": 0.0},
    "explosion_particle": {"type": "minecraft:explosion_emitter", "options": None},
    "explosion_sound": {"reference": 703},
    "block_particles": [
        {"particle": POOF, "scaling": 0.5, "speed": 1.0, "weight": 1},
        {"particle": SMOKE, "scaling": 1.0, "speed": 1.0, "weight": 1},
    ],
    "play_sound": True,
}
TNT_EXPLOSION_HEX = (
    "4025000000000000 c04df828f5c00000 c016000000000000 40800000 0000029b"
    " 01 bfe1bec1ad07cf73 3fd270ae62624e78 0000000000000000"
    " 1d c005 02 45 3f000000 3f800000 01 48 3f800000 3f800000 01 01"
)


def test_a_tnt_explosion_decodes_its_centre_knockback_particles_and_sound() -> None:
    round_trip(EXPLODE, TNT_EXPLOSION, TNT_EXPLOSION_HEX)


def test_an_explosion_with_no_knockback_no_block_particles_and_no_sound_is_shorter() -> None:
    # Built by hand from the TNT: the optional knockback is a Bool 0, the list a count of 0.
    round_trip(
        EXPLODE,
        {
            **TNT_EXPLOSION,
            "player_knockback": None,
            "block_particles": [],
            "play_sound": False,
        },
        "4025000000000000 c04df828f5c00000 c016000000000000 40800000 0000029b 00 1d c005 00 00",
    )


def test_an_explosion_keeps_an_inline_sound_and_a_weight_that_takes_two_bytes() -> None:
    # Built by hand: the sound is named in the packet, and the weight 300 is a two byte VarInt.
    round_trip(
        EXPLODE,
        {
            **TNT_EXPLOSION,
            "player_knockback": None,
            "explosion_sound": {"direct": {"location": "a:b", "fixed_range": 8.0}},
            "block_particles": [{"particle": POOF, "scaling": 2.0, "speed": 0.0, "weight": 300}],
        },
        "4025000000000000 c04df828f5c00000 c016000000000000 40800000 0000029b"
        " 00 1d 00 03 613a62 01 41000000 01 45 40000000 00000000 ac02 01",
    )


def test_an_explosion_keeps_a_negative_block_count_and_a_particle_with_options() -> None:
    # Built by hand: the Int is signed, and a dust particle carries its colour and scale.
    dust = {"type": "minecraft:dust", "options": {"color": -65536, "scale": 1.0}}
    round_trip(
        EXPLODE,
        {
            **TNT_EXPLOSION,
            "block_count": -1,
            "player_knockback": None,
            "explosion_particle": dust,
            "block_particles": [],
        },
        "4025000000000000 c04df828f5c00000 c016000000000000 40800000 ffffffff"
        " 00 15 ffff0000 3f800000 c005 00 01",
    )


def test_an_explosion_names_the_block_particle_that_is_bad() -> None:
    bad = {"particle": POOF, "scaling": 1, "speed": 1.0, "weight": 1}
    error = encode_error(EXPLODE, {**TNT_EXPLOSION, "block_particles": [bad]})
    assert "block_particles: 0: scaling: expected a float" in error


def test_an_explosion_refuses_more_block_particles_than_there_are_bytes() -> None:
    # The count of 5 in the list, with only the two particles of the TNT after it.
    error = decode_error(EXPLODE, TNT_EXPLOSION_HEX.replace("c005 02", "c005 05"))
    assert "block_particles: " in error


def test_an_explosion_refuses_a_knockback_that_is_neither_present_nor_absent() -> None:
    error = decode_error(EXPLODE, TNT_EXPLOSION_HEX.replace("0000029b 01", "0000029b 02"))
    assert "player_knockback: " in error


def test_an_explosion_uses_the_shared_shapes() -> None:
    explode = play.CLIENTBOUND[EXPLODE]
    assert explode.fields["center"] is VEC3
    assert explode.fields["explosion_particle"] is PARTICLE
    assert explode.fields["explosion_sound"] is SOUND_EVENT
