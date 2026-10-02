"""The join's unordered lists are compared sorted (`UNORDERED`): their order is no difference.

Two vanilla Instances send them in another order (#30): `login.dimension_names` in an order
fixed per boot, `update_attributes.attributes` in one that changes from one join to the next.
The client reads the names into a set and applies each attribute by its id, so only which
values each key ends with matters. Packets are built through the Target's real Codec.
"""

from mscts.codec.packets import Codec, Packet, State
from mscts.compare import ABSENT, UNORDERED, Divergence, compare
from tests.compare.build import CLIENTBOUND, transcript

CODEC = Codec.load("26.3")

OVERWORLD, NETHER, END = "minecraft:overworld", "minecraft:the_nether", "minecraft:the_end"


def _play(name: str, fields: dict[str, object]) -> Packet:
    data = CODEC.encode(State.PLAY, CLIENTBOUND, name, fields)
    return CODEC.decode(State.PLAY, CLIENTBOUND, data)


def login(dimension_names: list[str]) -> Packet:
    """A play `login` with these dimension names, and the rest as vanilla sends at a join."""
    return _play(
        "minecraft:login",
        {
            "entity_id": 1,
            "is_hardcore": False,
            "dimension_names": dimension_names,
            "max_players": 20,
            "view_distance": 10,
            "simulation_distance": 10,
            "reduced_debug_info": False,
            "enable_respawn_screen": True,
            "do_limited_crafting": False,
            "dimension_type": 0,
            "dimension_name": OVERWORLD,
            "hashed_seed": 0,
            "game_mode": 0,
            "previous_game_mode": 0,
            "is_debug": False,
            "is_flat": True,
            "death_location": None,
            "portal_cooldown": 0,
            "sea_level": -63,
            "online_mode": False,
            "enforces_secure_chat": False,
        },
    )


type _Attribute = tuple[int, float, list[str]]


def update_attributes(attributes: list[_Attribute]) -> Packet:
    """An `update_attributes` of entity 1: each attribute's id, base and modifier ids."""
    return _play(
        "minecraft:update_attributes",
        {
            "entity_id": 1,
            "attributes": [
                {
                    "attribute": attribute,
                    "base": base,
                    "modifiers": [
                        {"id": modifier, "amount": 1.0, "operation": 0} for modifier in modifiers
                    ],
                }
                for attribute, base, modifiers in attributes
            ],
        },
    )


def _diff(reference: Packet, candidate: Packet) -> list[tuple[str | None, object, object]]:
    divergences: tuple[Divergence, ...] = compare(
        transcript(("alice", reference)), transcript(("alice", candidate)), []
    ).divergences
    return [(d.path, d.reference, d.candidate) for d in divergences]


def test_the_order_of_dimension_names_is_no_difference() -> None:
    assert _diff(login([OVERWORLD, NETHER, END]), login([OVERWORLD, END, NETHER])) == []
    assert _diff(login([END, OVERWORLD, NETHER]), login([NETHER, END, OVERWORLD])) == []


def test_a_missing_dimension_name_is_a_difference_at_its_sorted_path() -> None:
    assert _diff(login([OVERWORLD, NETHER, END]), login([NETHER, OVERWORLD])) == [
        ("dimension_names[1]", END, NETHER),
        ("dimension_names[2]", NETHER, ABSENT),
    ]


SPEED, ARMOR, HEALTH = (8, 0.1, []), (0, 0.0, ["minecraft:a"]), (17, 20.0, [])


def test_the_order_of_attributes_is_no_difference() -> None:
    assert (
        _diff(update_attributes([SPEED, ARMOR, HEALTH]), update_attributes([HEALTH, SPEED, ARMOR]))
        == []
    )


def test_an_attributes_modifiers_keep_their_order() -> None:
    two = (0, 0.0, ["minecraft:a", "minecraft:b"])
    swapped = (0, 0.0, ["minecraft:b", "minecraft:a"])
    assert _diff(update_attributes([SPEED, two]), update_attributes([swapped, SPEED])) == [
        ("attributes[0].modifiers[0].id", "minecraft:a", "minecraft:b"),
        ("attributes[0].modifiers[1].id", "minecraft:b", "minecraft:a"),
    ]


def test_a_repeated_attribute_keeps_its_order_since_the_last_one_wins() -> None:
    first, last = (8, 0.1, []), (8, 0.2, [])
    assert (
        _diff(update_attributes([first, ARMOR, last]), update_attributes([ARMOR, first, last]))
        == []
    )
    assert _diff(update_attributes([first, last]), update_attributes([last, first])) != []


def test_dimension_names_and_attributes_are_compared_sorted_with_their_reasons() -> None:
    assert "HashSet" in UNORDERED["minecraft:login"]
    assert "ObjectOpenHashSet" in UNORDERED["minecraft:update_attributes"]
