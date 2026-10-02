"""Entity ids: each Bot's are named by their spawn, or numbered as it hears of them (#21, #116).

Vanilla gives entity ids from a counter and mobs random UUIDs, so two servers that send the
same entities send other numbers for them. A Comparison replaces the id of an entity whose
`add_entity` came before the window (outside the windows) by its type and spawn position,
`pig@(1.5, -60.0, 7.5)`; any other id by `#<n>`, the n-th entity in the Bot's compared
packets (without windows, its own player, from `login`, is #1); and each UUID of an entity
that is not a player by `#<n>`, the n-th such UUID. So the same entities compare equal, and
a packet about another entity is still a Divergence.
"""

import re
import uuid

import pytest

from mscts.codec.packets import Packet
from mscts.codec.registry_names import registry_names
from mscts.compare import (
    ENTITY_UUIDS,
    OBSERVE_CLOSE,
    OBSERVE_OPEN,
    Mask,
    Outcome,
    _uuid_paths,
    compare,
)
from mscts.target import TARGET
from mscts.transcript import Transcript
from tests.compare.build import divergence, packet, transcript

ENTITY_TYPES = registry_names(TARGET.minecraft_version, "minecraft:entity_type")
PLAYER, PIG = ENTITY_TYPES.index("minecraft:player"), ENTITY_TYPES.index("minecraft:pig")
COW = ENTITY_TYPES.index("minecraft:cow")


def login(entity_id: int) -> Packet:
    return packet("minecraft:login", fields={"entity_id": entity_id})


def spawn(
    entity_id: int, *, x: float = 4.5, kind: int = PIG, uuid_: uuid.UUID | None = None
) -> Packet:
    fields = {
        "entity_id": entity_id,
        "entity_uuid": uuid_ or uuid.uuid4(),
        "type": kind,
        "x": x,
        "y": -60.0,
        "z": 7.5,
    }
    return packet("minecraft:add_entity", fields=fields)


def hurt(entity_id: int) -> Packet:
    return packet("minecraft:hurt_animation", fields={"entity_id": entity_id, "yaw": 0.0})


def swing(entity_id: int) -> Packet:
    return packet("minecraft:animate", fields={"entity_id": entity_id, "action": 0})


def removed(*entity_ids: int) -> Packet:
    return packet("minecraft:remove_entities", fields={"entity_ids": list(entity_ids)})


def metadata(entity_id: int, health: float = 10.0) -> Packet:
    entries = [{"index": 9, "serializer": "float", "value": health}]
    return packet("minecraft:set_entity_data", fields={"entity_id": entity_id, "entries": entries})


def test_the_same_entities_under_other_ids_and_uuids_match() -> None:
    reference = transcript(
        ("alice", login(1)), ("alice", spawn(3)), ("alice", metadata(3)), ("alice", spawn(4))
    )
    candidate = transcript(
        ("alice", login(40)), ("alice", spawn(7)), ("alice", metadata(7)), ("alice", spawn(2))
    )
    verdict = compare(reference, candidate, [])
    assert verdict.outcome is Outcome.MATCH, verdict
    assert "add_entity.entity_id" in verdict.test_cases
    assert "add_entity.entity_uuid" in verdict.test_cases


def test_metadata_aimed_at_another_entity_is_a_divergence_that_shows_the_numbers() -> None:
    reference = transcript(
        ("alice", login(1)), ("alice", spawn(3)), ("alice", spawn(4)), ("alice", metadata(3))
    )
    candidate = transcript(
        ("alice", login(1)), ("alice", spawn(3)), ("alice", spawn(4)), ("alice", metadata(4))
    )
    verdict = compare(reference, candidate, [])
    assert verdict.divergences == (
        divergence(
            "field",
            index=3,
            packet="minecraft:set_entity_data",
            path="entity_id",
            reference="#2",
            candidate="#3",
            test_case="set_entity_data.entity_id",
        ),
    )


def test_entities_spawned_in_another_order_are_divergences() -> None:
    reference = transcript(
        ("alice", login(1)), ("alice", spawn(3, x=1.5)), ("alice", spawn(4, x=2.5))
    )
    candidate = transcript(
        ("alice", login(1)), ("alice", spawn(3, x=2.5)), ("alice", spawn(4, x=1.5))
    )
    verdict = compare(reference, candidate, [])
    assert [(d.index, d.path, d.reference, d.candidate) for d in verdict.divergences] == [
        (1, "x", 1.5, 2.5),
        (2, "x", 2.5, 1.5),
    ]


def test_a_players_uuid_is_compared_as_it_is() -> None:
    bob, other = uuid.UUID(int=1), uuid.UUID(int=2)
    reference = transcript(("alice", login(1)), ("alice", spawn(2, kind=PLAYER, uuid_=bob)))
    candidate = transcript(("alice", login(1)), ("alice", spawn(2, kind=PLAYER, uuid_=other)))
    verdict = compare(reference, candidate, [])
    assert [(d.path, d.reference, d.candidate) for d in verdict.divergences] == [
        ("entity_uuid", bob, other)
    ]


def test_a_players_uuid_takes_no_number() -> None:
    # Both hear of entity 2 first; only the reference hears of it as a player.
    reference = transcript(
        ("alice", login(1)), ("alice", spawn(2, kind=PLAYER)), ("alice", spawn(3))
    )
    candidate = transcript(("alice", login(1)), ("alice", metadata(2)), ("alice", spawn(3)))
    verdict = compare(reference, candidate, [])
    assert [(d.kind, d.index) for d in verdict.divergences] == [("missing", 1), ("unexpected", 1)]


def test_a_mob_given_a_players_uuid_is_a_divergence() -> None:
    bob = uuid.UUID(int=1)
    reference = transcript(
        ("alice", login(1)), ("alice", spawn(3)), ("alice", spawn(2, kind=PLAYER, uuid_=bob))
    )
    candidate = transcript(
        ("alice", login(1)),
        ("alice", spawn(3, uuid_=bob)),
        ("alice", spawn(2, kind=PLAYER, uuid_=bob)),
    )
    verdict = compare(reference, candidate, [])
    assert [(d.index, d.path, d.reference, d.candidate) for d in verdict.divergences] == [
        (2, "entity_uuid", bob, "#1")
    ]


def test_no_entity_takes_no_number() -> None:
    def lead(holder: int | None) -> Packet:
        fields = {"attached_entity_id": 1, "holding_entity_id": holder}
        return packet("minecraft:set_entity_link", fields=fields)

    # The pig is the second entity the reference heard of, and the third the candidate did.
    reference = transcript(("alice", login(1)), ("alice", lead(None)), ("alice", spawn(3)))
    candidate = transcript(("alice", login(1)), ("alice", lead(2)), ("alice", spawn(3)))
    verdict = compare(reference, candidate, [])
    assert [(d.path, d.reference, d.candidate) for d in verdict.divergences] == [
        ("holding_entity_id", None, "#2"),
        ("entity_id", "#2", "#3"),
    ]


def test_an_entity_first_heard_of_in_a_list_is_numbered_there() -> None:
    def riders(vehicle: int, *passengers: int) -> Packet:
        fields = {"vehicle": vehicle, "passengers": list(passengers)}
        return packet("minecraft:set_passengers", fields=fields)

    reference = transcript(
        ("alice", login(1)), ("alice", riders(1, 4, 5)), ("alice", spawn(4)), ("alice", spawn(5))
    )
    candidate = transcript(
        ("alice", login(1)), ("alice", riders(1, 7, 6)), ("alice", spawn(6)), ("alice", spawn(7))
    )
    verdict = compare(reference, candidate, [])
    assert [(d.index, d.path, d.reference, d.candidate) for d in verdict.divergences] == [
        (2, "entity_id", "#2", "#3"),
        (3, "entity_id", "#3", "#2"),
    ]


def test_a_uuid_given_to_two_entities_is_a_divergence() -> None:
    pig = uuid.UUID(int=3)
    reference = transcript(("alice", login(1)), ("alice", spawn(3)), ("alice", spawn(4)))
    candidate = transcript(
        ("alice", login(1)), ("alice", spawn(3, uuid_=pig)), ("alice", spawn(4, uuid_=pig))
    )
    verdict = compare(reference, candidate, [])
    assert [(d.index, d.path, d.reference, d.candidate) for d in verdict.divergences] == [
        (2, "entity_uuid", "#2", "#1")
    ]


def test_entities_heard_of_before_a_window_do_not_shift_the_numbers_inside_it() -> None:
    # Before a window, timing decides how many chunks, world-gen mobs and natural spawns a
    # Bot has heard of; only what the Comparison takes is numbered.
    reference = transcript(
        ("alice", login(1)),
        ("alice", spawn(5)),
        OBSERVE_OPEN,
        ("alice", spawn(9, x=1.5)),
        ("alice", metadata(9)),
        ("alice", spawn(10, x=2.5)),
        OBSERVE_CLOSE,
    )
    candidate = transcript(
        ("alice", login(1)),
        ("alice", spawn(7)),
        ("alice", spawn(6)),
        ("alice", metadata(8)),
        OBSERVE_OPEN,
        ("alice", spawn(20, x=1.5)),
        ("alice", metadata(20)),
        ("alice", spawn(21, x=2.5)),
        OBSERVE_CLOSE,
    )
    verdict = compare(reference, candidate, [])
    assert verdict.outcome is Outcome.MATCH, verdict
    assert "add_entity.entity_id" in verdict.test_cases


PIG_AT = "pig@(1.5, -60.0, 7.5)"
COW_AT = "cow@(3.5, -60.0, 7.5)"


def _farm(*hurt_ids: int) -> Transcript:
    """A pig (5) and a cow (6) spawned before the window, and each of `hurt_ids` hurt in it."""
    return transcript(
        ("alice", login(1)),
        ("alice", spawn(5, x=1.5)),
        ("alice", spawn(6, x=3.5, kind=COW)),
        OBSERVE_OPEN,
        *(("alice", hurt(entity_id)) for entity_id in hurt_ids),
        OBSERVE_CLOSE,
    )


def test_an_action_inside_a_window_on_another_entity_spawned_before_it_is_a_divergence() -> None:
    verdict = compare(_farm(5), _farm(6), [])

    assert verdict.outcome is Outcome.MISMATCH
    assert verdict.divergences == (
        divergence(
            "field",
            index=0,
            packet="minecraft:hurt_animation",
            path="entity_id",
            reference=PIG_AT,
            candidate=COW_AT,
            test_case="hurt_animation.entity_id",
        ),
    )


def test_a_missing_entity_spawned_before_the_window_shifts_no_other_entitys_name() -> None:
    # The Candidate never spawned the pig, so it never swings it; the cow is the same cow.
    reference = transcript(
        ("alice", login(1)),
        ("alice", spawn(5, x=1.5)),
        ("alice", spawn(6, x=3.5, kind=COW)),
        OBSERVE_OPEN,
        ("alice", swing(5)),
        ("alice", hurt(6)),
        OBSERVE_CLOSE,
    )
    candidate = transcript(
        ("alice", login(1)),
        ("alice", spawn(5, x=3.5, kind=COW)),
        OBSERVE_OPEN,
        ("alice", hurt(5)),
        OBSERVE_CLOSE,
    )

    verdict = compare(reference, candidate, [])

    assert [(d.kind, d.packet) for d in verdict.divergences] == [("missing", "minecraft:animate")]
    assert "hurt_animation.entity_id" not in verdict.differing  # the score counts it as the same


def test_a_remove_entities_before_the_window_ends_the_name_too() -> None:
    # The Reference's client forgot the pig before the window; the Candidate's did not.
    def pig_then_hurt(*before: Packet) -> Transcript:
        return transcript(
            ("alice", login(1)),
            ("alice", spawn(5, x=1.5)),
            *(("alice", item) for item in before),
            OBSERVE_OPEN,
            ("alice", hurt(5)),
            OBSERVE_CLOSE,
        )

    verdict = compare(pig_then_hurt(removed(5)), pig_then_hurt(), [])

    assert [(d.path, d.reference, d.candidate) for d in verdict.divergences] == [
        ("entity_id", "#1", PIG_AT)
    ]


def test_only_an_add_entity_names_an_entity() -> None:
    reference = transcript(
        ("alice", login(1)), ("alice", metadata(9)), OBSERVE_OPEN, ("alice", hurt(9)), OBSERVE_CLOSE
    )
    candidate = transcript(("alice", login(1)), OBSERVE_OPEN, ("alice", hurt(9)), OBSERVE_CLOSE)

    assert compare(reference, candidate, []).outcome is Outcome.MATCH


def test_an_entity_type_outside_the_registry_is_named_by_its_number() -> None:
    def odd(x: float) -> Transcript:
        return transcript(
            ("alice", login(1)),
            ("alice", spawn(5, x=x, kind=9999)),
            OBSERVE_OPEN,
            ("alice", hurt(5)),
            OBSERVE_CLOSE,
        )

    verdict = compare(odd(1.5), odd(2.5), [])

    assert [(d.reference, d.candidate) for d in verdict.divergences] == [
        ("9999@(1.5, -60.0, 7.5)", "9999@(2.5, -60.0, 7.5)")
    ]


def test_an_id_reused_after_remove_entities_is_a_new_entity() -> None:
    # Vanilla never reuses an id; the client reads the reuse as a new entity all the same.
    def pigs(second: int) -> Transcript:
        return transcript(
            ("alice", login(1)),
            ("alice", spawn(5)),
            ("alice", hurt(5)),
            ("alice", removed(5)),
            ("alice", spawn(second)),
            ("alice", hurt(second)),
        )

    verdict = compare(pigs(6), pigs(5), [])

    assert verdict.outcome is Outcome.MATCH, verdict


def test_remove_entities_ends_a_name_given_before_the_window() -> None:
    def farm(second: int) -> Transcript:
        return transcript(
            ("alice", login(1)),
            ("alice", spawn(5, x=1.5)),
            OBSERVE_OPEN,
            ("alice", removed(5)),
            ("alice", spawn(second, x=2.5)),
            ("alice", hurt(second)),
            OBSERVE_CLOSE,
        )

    verdict = compare(farm(6), farm(5), [])

    assert verdict.outcome is Outcome.MATCH, verdict


def test_inside_a_window_the_first_entity_spawned_in_it_is_number_one() -> None:
    # An entity spawned before the window is named (above); one spawned inside it is
    # numbered, and nothing before the window counts.
    reference = transcript(
        ("alice", login(1)),
        ("alice", spawn(3)),
        OBSERVE_OPEN,
        ("alice", spawn(5, x=1.5)),
        ("alice", spawn(6, x=2.5)),
        ("alice", metadata(5)),
        OBSERVE_CLOSE,
    )
    candidate = transcript(
        ("alice", login(1)),
        OBSERVE_OPEN,
        ("alice", spawn(8, x=1.5)),
        ("alice", spawn(9, x=2.5)),
        ("alice", metadata(9)),
        OBSERVE_CLOSE,
    )

    verdict = compare(reference, candidate, [])

    assert [(d.index, d.path, d.reference, d.candidate) for d in verdict.divergences] == [
        (2, "entity_id", "#1", "#2")
    ]


def test_each_bot_numbers_the_entities_it_hears_of_itself() -> None:
    # The interleaving of two Bots' packets is timing: each Bot's own player is its #1.
    reference = transcript(
        ("alice", login(1)), ("bob", login(2)), ("alice", spawn(2)), ("bob", spawn(1))
    )
    candidate = transcript(
        ("bob", login(6)), ("alice", login(5)), ("bob", spawn(5)), ("alice", spawn(6))
    )
    assert compare(reference, candidate, []).outcome is Outcome.MATCH


def test_a_list_of_entity_ids_is_numbered_element_by_element() -> None:
    reference = transcript(
        ("alice", login(1)), ("alice", spawn(3)), ("alice", spawn(4)), ("alice", removed(3, 4))
    )
    candidate = transcript(
        ("alice", login(1)), ("alice", spawn(8)), ("alice", spawn(9)), ("alice", removed(9, 8))
    )
    verdict = compare(reference, candidate, [])
    assert [(d.path, d.reference, d.candidate) for d in verdict.divergences] == [
        ("entity_ids[0]", "#2", "#3"),
        ("entity_ids[1]", "#3", "#2"),
    ]


def test_no_entity_stays_none() -> None:
    def lead(holder: int | None) -> Packet:
        fields = {"attached_entity_id": 3, "holding_entity_id": holder}
        return packet("minecraft:set_entity_link", fields=fields)

    reference = transcript(("alice", login(1)), ("alice", spawn(3)), ("alice", lead(None)))
    candidate = transcript(("alice", login(1)), ("alice", spawn(3)), ("alice", lead(1)))
    verdict = compare(reference, candidate, [])
    assert [(d.path, d.reference, d.candidate) for d in verdict.divergences] == [
        ("holding_entity_id", None, "#1")
    ]


def test_an_entity_id_deep_in_a_value_is_numbered_too() -> None:
    def vibration(entity_id: int) -> Packet:
        destination = {
            "type": "minecraft:entity",
            "value": {"entity_id": entity_id, "y_offset": 0.0},
        }
        particle = {
            "type": "minecraft:vibration",
            "options": {"destination": destination, "arrival_in_ticks": 5},
        }
        return packet("minecraft:level_particles", fields={"particle": particle})

    reference = transcript(("alice", login(1)), ("alice", spawn(3)), ("alice", vibration(3)))
    candidate = transcript(("alice", login(10)), ("alice", spawn(11)), ("alice", vibration(11)))
    assert compare(reference, candidate, []).outcome is Outcome.MATCH


def test_the_same_keys_under_another_variant_are_left_as_they_are() -> None:
    # Only a vibration's destination holds an entity id; a made-up dust with the same keys
    # shows that the variant is checked where ids are replaced, not only where they are found.
    def dust(entity_id: int) -> Packet:
        destination = {"type": "minecraft:entity", "value": {"entity_id": entity_id}}
        particle = {"type": "minecraft:dust", "options": {"destination": destination}}
        return packet("minecraft:level_particles", fields={"particle": particle})

    # The reference's first dust takes no number either, so both pigs are #2.
    reference = transcript(
        ("alice", login(1)), ("alice", dust(9)), ("alice", spawn(3)), ("alice", dust(3))
    )
    candidate = transcript(("alice", login(1)), ("alice", spawn(7)), ("alice", dust(7)))
    verdict = compare(reference, candidate, [])
    assert [(d.kind, d.index, d.path) for d in verdict.divergences] == [
        ("missing", 1, None),
        ("field", 3, "particle.options.destination.value.entity_id"),
    ]
    assert (verdict.divergences[1].reference, verdict.divergences[1].candidate) == (3, 7)


def test_an_entity_uuid_path_has_keys_only() -> None:
    assert _uuid_paths("minecraft:add_entity", ENTITY_UUIDS) == (("entity_uuid",),)
    assert _uuid_paths("minecraft:login", ENTITY_UUIDS) == ()
    error = re.escape("minecraft:add_entity.uuids[0]: an entity UUID's path has keys only")
    with pytest.raises(ValueError, match=error):
        _uuid_paths("minecraft:add_entity", ["minecraft:add_entity.uuids[0]"])


@pytest.mark.parametrize(
    ("name", "path"),
    [
        ("minecraft:login", "entity_id"),
        ("minecraft:add_entity", "entity_id"),
        ("minecraft:remove_entities", "entity_ids"),
        ("minecraft:remove_entities", "entity_ids[1]"),
        ("minecraft:set_entity_link", "holding_entity_id"),
        ("minecraft:level_particles", "particle.options.destination.value.entity_id"),
    ],
)
def test_a_mask_on_an_entity_id_is_refused(name: str, path: str) -> None:
    with pytest.raises(ValueError, match=re.escape(f"{name} {path}: ") + ".*#21"):
        Mask(name, path, reason="assigned per session")


@pytest.mark.parametrize(
    ("name", "path"),
    [
        ("minecraft:login", "*"),
        ("minecraft:add_entity", "x"),
        ("minecraft:set_entity_data", "entries"),
        ("minecraft:set_entity_data", "entries[*].value"),
        # A key where a list of entity ids has its elements is no entity id (mutant C7).
        ("minecraft:remove_entities", "entity_ids.count"),
        ("minecraft:level_particles", "particle"),
        ("test:entity", "entity_id"),
    ],
)
def test_a_mask_beside_or_around_an_entity_id_is_kept(name: str, path: str) -> None:
    assert Mask(name, path, reason="a test").path == path


def test_every_entity_uuid_field_has_a_reason() -> None:
    assert ENTITY_UUIDS
    for field, reason in ENTITY_UUIDS.items():
        assert field.startswith("minecraft:"), field
        assert reason.strip(), field
