"""A `registry_data`'s registry, as the client reads it (#478).

The client reads the registry id with `Identifier.parse` and loads only the registries of
`RegistryDataLoader.SYNCHRONIZED_REGISTRIES` (javap on the 26.3 client).
"""

from support.registries import registry

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
