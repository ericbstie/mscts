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


def test_an_entry_id_with_no_namespace_is_the_minecraft_one() -> None:
    # PackedRegistryEntry.STREAM_CODEC reads each entry id with Identifier.parse too.
    verdict = compare(
        transcript(("alice", registry_of(_BIOME, ["minecraft:plains", "minecraft:desert"]))),
        transcript(("alice", registry_of(_BIOME, ["plains", ":desert"]))),
        [],
    )

    assert verdict.divergences == tuple(
        divergence(
            "field",
            index=0,
            packet=_REGISTRY_DATA,
            path=f"entries[{entry}].entry_id",
            reference=reference,
            candidate=candidate,
            test_case="registry_data.entries[].entry_id",
            observability=Observability.NETWORK_TRAFFIC,
        )
        for entry, reference, candidate in (
            (0, "minecraft:plains", "plains"),
            (1, "minecraft:desert", ":desert"),
        )
    )


_BOTH = transcript(("alice", registry(_DAMAGE, 3)), ("alice", registry(_BIOME, 3)))


# The last name holds every character Identifier.isValidNamespace and isValidPath allow.
@pytest.mark.parametrize("name", ["item", ":item", "a-z_0.9:a-z_0.9/a"])
def test_a_registry_the_client_never_loads_is_network_traffic_when_the_candidate_sends_it(
    name: str,
) -> None:
    # The client loads each registry of SYNCHRONIZED_REGISTRIES by Map.get, and no other.
    with_item = transcript(
        ("alice", registry(_DAMAGE, 3)),
        ("alice", registry(name, 3)),
        ("alice", registry(_BIOME, 3)),
    )

    verdict = compare(_BOTH, with_item, [])

    assert [(d.kind, d.observability) for d in verdict.divergences] == [
        ("unexpected", Observability.NETWORK_TRAFFIC)
    ]


def test_a_registry_only_the_reference_sends_is_gameplay() -> None:
    # Vanilla sends exactly the registries the client loads, so one only it sends means that
    # _SYNCHRONIZED_REGISTRIES is out of date.
    with_item = transcript(
        ("alice", registry(_DAMAGE, 3)),
        ("alice", registry("item", 3)),
        ("alice", registry(_BIOME, 3)),
    )

    verdict = compare(with_item, _BOTH, [])

    assert [(d.kind, d.index, d.observability) for d in verdict.divergences] == [
        ("missing", 1, Observability.GAMEPLAY)
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
