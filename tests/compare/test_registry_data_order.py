"""`registry_data` packets are compared registry by registry, in any order (#451).

The client collects each registry's packets apart and loads the registries by key at
`finish_configuration` (docs/research/2026-10-23-registry-order.md).
"""

from support.registries import registry

from mscts.compare import ORDER_PATH, Observability, compare
from tests.compare.build import divergence, transcript

_BIOME = "minecraft:worldgen/biome"
_DAMAGE = "minecraft:damage_type"
_ENCHANTMENT = "minecraft:enchantment"
_REGISTRY_DATA = "minecraft:registry_data"


def test_the_same_registries_sent_in_another_order_are_compared_per_registry() -> None:
    biome, damage = registry(_BIOME, 100), registry(_DAMAGE, 100)

    verdict = compare(
        transcript(("alice", biome), ("alice", damage)),
        transcript(("alice", damage), ("alice", biome)),
        [],
    )

    assert verdict.gameplay == ()


def test_registries_sent_in_another_order_are_one_network_traffic_divergence() -> None:
    biome, damage, enchantment = (registry(name, 3) for name in (_BIOME, _DAMAGE, _ENCHANTMENT))

    verdict = compare(
        transcript(("alice", biome), ("alice", damage), ("alice", enchantment)),
        transcript(("alice", damage), ("alice", enchantment), ("alice", biome)),
        [],
    )

    assert verdict.divergences == (
        divergence(
            "field",
            index=0,
            packet=_REGISTRY_DATA,
            path=ORDER_PATH,
            reference=[_BIOME, _DAMAGE, _ENCHANTMENT],
            candidate=[_DAMAGE, _ENCHANTMENT, _BIOME],
            test_case="registry_data.registry_id",
            observability=Observability.NETWORK_TRAFFIC,
        ),
    )


def test_two_packets_of_one_registry_are_compared_in_the_order_they_came() -> None:
    first, second = registry(_BIOME, 2), registry(_BIOME, 2, first=2)

    verdict = compare(
        transcript(("alice", first), ("alice", second)),
        transcript(("alice", second), ("alice", first)),
        [],
    )

    assert {(d.index, d.path) for d in verdict.gameplay} == {
        (0, "entries[0].entry_id"),
        (0, "entries[1].entry_id"),
        (1, "entries[0].entry_id"),
        (1, "entries[1].entry_id"),
    }
    assert verdict.gameplay == verdict.divergences
