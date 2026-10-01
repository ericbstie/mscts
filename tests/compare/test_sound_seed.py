"""The seed of a sound is drawn at random by vanilla, so no Comparison compares it.

Two vanilla 26.3 runs of the same steps (a note block played by a redstone block, a door
powered by one) sent sounds that differ in the seed, and the door's also in its pitch. The
seed is a random field (ADR-0011); the pitch is not, because most sounds have a fixed pitch
and a global entry would hide real differences: a Group that plays a door masks it itself
(docs/research/2026-10-01-block-world-events.md). The payloads are recorded from the two runs.
"""

from support.play import CLIENTBOUND, CODEC, frame

from mscts.codec.packets import Packet, State
from mscts.compare import RANDOM_FIELDS, Mask, Outcome, compare
from tests.compare.build import transcript

SOUND = "minecraft:sound"
SOUND_ENTITY = "minecraft:sound_entity"

NOTE_BLOCK_RUN_1 = "9409 02 00000044 fffffe24 00000044 40400000 3f000000 2c88292943717559"
NOTE_BLOCK_RUN_2 = "9409 02 00000044 fffffe24 00000044 40400000 3f000000 dd545c2ef81d2e5a"
DOOR_RUN_1 = "bb0e 04 00000064 fffffe24 00000044 3f800000 3f78b8ae d3720260764e5184"
DOOR_RUN_2 = "bb0e 04 00000064 fffffe24 00000044 3f800000 3f78acb4 8bd7483b1d8e5875"
ENTITY_SOUND_1 = "06 06 2a 3f800000 3fc00000 0123456789abcdef"
ENTITY_SOUND_2 = "06 06 2a 3f800000 3fc00000 fedcba9876543210"


def sound(name: str, payload: str) -> Packet:
    return CODEC.decode(State.PLAY, CLIENTBOUND, frame(name, payload))


def test_a_sound_seed_and_a_sound_entity_seed_are_random_fields_with_the_reason() -> None:
    for field in ("minecraft:sound.seed", "minecraft:sound_entity.seed"):
        reason = RANDOM_FIELDS[field]
        assert "Level.playSound" in reason
        assert "soundSeedGenerator" in reason
        assert "generateUniqueSeed" in reason


def test_the_pitch_of_a_sound_is_not_a_random_field() -> None:
    assert "minecraft:sound.pitch" not in RANDOM_FIELDS
    assert "minecraft:sound_entity.pitch" not in RANDOM_FIELDS


def test_two_vanilla_runs_of_a_note_block_sound_differ_only_in_the_seed() -> None:
    run_1, run_2 = sound(SOUND, NOTE_BLOCK_RUN_1), sound(SOUND, NOTE_BLOCK_RUN_2)
    assert run_1.payload != run_2.payload
    assert {**(run_1.fields or {}), "seed": 0} == {**(run_2.fields or {}), "seed": 0}
    assert (run_1.fields or {})["seed"] != (run_2.fields or {})["seed"]

    verdict = compare(transcript(("alice", run_1)), transcript(("alice", run_2)), [])

    assert verdict.outcome is Outcome.MATCH, verdict.divergences
    assert "sound.seed" not in verdict.test_cases
    assert "sound.pitch" in verdict.test_cases


def test_two_vanilla_runs_of_an_entity_sound_differ_only_in_the_seed() -> None:
    first, second = sound(SOUND_ENTITY, ENTITY_SOUND_1), sound(SOUND_ENTITY, ENTITY_SOUND_2)

    verdict = compare(transcript(("alice", first)), transcript(("alice", second)), [])

    assert verdict.outcome is Outcome.MATCH, verdict.divergences
    assert "sound_entity.seed" not in verdict.test_cases
    assert "sound_entity.pitch" in verdict.test_cases


def test_a_random_seed_hides_only_itself() -> None:
    first = sound(SOUND, NOTE_BLOCK_RUN_1)
    louder = sound(SOUND, NOTE_BLOCK_RUN_2.replace("40400000", "40800000"))

    verdict = compare(transcript(("alice", first)), transcript(("alice", louder)), [])

    assert [d.path for d in verdict.divergences] == ["volume"], verdict.divergences


def test_two_vanilla_runs_of_a_door_sound_differ_in_the_pitch_too() -> None:
    run_1, run_2 = sound(SOUND, DOOR_RUN_1), sound(SOUND, DOOR_RUN_2)

    verdict = compare(transcript(("alice", run_1)), transcript(("alice", run_2)), [])

    assert verdict.outcome is Outcome.MISMATCH
    assert [d.path for d in verdict.divergences] == ["pitch"], verdict.divergences


def test_a_group_that_plays_a_door_masks_the_pitch_itself() -> None:
    run_1, run_2 = sound(SOUND, DOOR_RUN_1), sound(SOUND, DOOR_RUN_2)
    mask = Mask(SOUND, "pitch", reason="DoorBlock draws it as nextFloat() * 0.1 + 0.9")

    verdict = compare(transcript(("alice", run_1)), transcript(("alice", run_2)), [mask])

    assert verdict.outcome is Outcome.MATCH, verdict.divergences
    assert "sound.pitch" not in verdict.test_cases
