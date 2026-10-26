"""A `registry_data`'s registry, as the client reads it (#478).

The client reads the registry id with `Identifier.parse` and loads only the registries of
`RegistryDataLoader.SYNCHRONIZED_REGISTRIES` (javap on the 26.3 client).
"""

import pytest
from support.registries import registry, registry_of

from mscts.compare import Observability, compare
from tests.compare.build import divergence, transcript

_BIOME = "minecraft:worldgen/biome"
_DAMAGE = "minecraft:damage_type"
_REGISTRY_DATA = "minecraft:registry_data"


def test_a_registry_id_with_no_namespace_is_the_minecraft_one() -> None:
    # Identifier.parse: no `:`, or one first, is the minecraft namespace.
    verdict = compare(
        transcript(("alice", registry(_DAMAGE, 3)), ("alice", registry(_BIOME, 3))),
        transcript(
            ("alice", registry(":damage_type", 3)), ("alice", registry("worldgen/biome", 3))
        ),
        [],
    )

    assert verdict.divergences == tuple(
        divergence(
            "field",
            index=index,
            packet=_REGISTRY_DATA,
            path="registry_id",
            reference=reference,
            candidate=candidate,
            test_case="registry_data.registry_id",
            observability=Observability.NETWORK_TRAFFIC,
        )
        for index, reference, candidate in (
            (0, _DAMAGE, ":damage_type"),
            (1, _BIOME, "worldgen/biome"),
        )
    )


def test_a_registry_the_client_never_loads_is_network_traffic_on_either_side() -> None:
    # The client loads each registry of SYNCHRONIZED_REGISTRIES by Map.get, and no other.
    both = transcript(("alice", registry(_DAMAGE, 3)), ("alice", registry(_BIOME, 3)))
    with_item = transcript(
        ("alice", registry(_DAMAGE, 3)),
        ("alice", registry("item", 3)),
        ("alice", registry(_BIOME, 3)),
    )

    unexpected = compare(both, with_item, []).divergences
    missing = compare(with_item, both, []).divergences

    assert [(d.kind, d.index, d.observability) for d in (*unexpected, *missing)] == [
        ("unexpected", 1, Observability.NETWORK_TRAFFIC),
        ("missing", 1, Observability.NETWORK_TRAFFIC),
    ]


@pytest.mark.parametrize(
    "name", ["minecraft:Item", "bad id", "a:b:c", "a/b:c", "..:item", "minecraft:worldgen/biome "]
)
def test_a_registry_id_the_client_cannot_read_is_gameplay(name: str) -> None:
    # Identifier.parse throws for a namespace or path it refuses, and the client disconnects.
    verdict = compare(
        transcript(("alice", registry(_DAMAGE, 3))),
        transcript(("alice", registry(_DAMAGE, 3)), ("alice", registry(name, 3))),
        [],
    )

    assert [(d.kind, d.observability) for d in verdict.divergences] == [
        ("unexpected", Observability.GAMEPLAY)
    ]


def test_a_registry_with_an_entry_id_the_client_cannot_read_is_gameplay() -> None:
    # Each entry id is read with Identifier.STREAM_CODEC too (PackedRegistryEntry.STREAM_CODEC).
    verdict = compare(
        transcript(("alice", registry(_DAMAGE, 3))),
        transcript(
            ("alice", registry(_DAMAGE, 3)),
            ("alice", registry_of("minecraft:item", ["minecraft:a", "minecraft:Not Valid"])),
        ),
        [],
    )

    assert [(d.kind, d.observability) for d in verdict.divergences] == [
        ("unexpected", Observability.GAMEPLAY)
    ]


def test_a_synchronized_registry_only_one_side_sends_is_gameplay() -> None:
    # Its id names no namespace, so it is minecraft:damage_type, which the client loads.
    verdict = compare(
        transcript(("alice", registry(_BIOME, 3))),
        transcript(("alice", registry("damage_type", 3)), ("alice", registry(_BIOME, 3))),
        [],
    )

    assert [(d.kind, d.observability) for d in verdict.divergences] == [
        ("unexpected", Observability.GAMEPLAY)
    ]
