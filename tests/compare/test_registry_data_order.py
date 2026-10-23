"""`registry_data` packets are compared registry by registry, in any order (#451).

The client collects each registry's packets apart and loads the registries by key at
`finish_configuration` (docs/research/2026-10-23-registry-order.md).
"""

from typing import cast

from support.registries import registry

from mscts.codec.packets import State
from mscts.compare import ABSENT, ORDER_PATH, Observability, compare
from tests.compare.build import divergence, packet, transcript

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


def test_a_registry_only_one_side_sends_is_one_divergence_and_the_rest_are_paired() -> None:
    biome, damage, enchantment = (registry(name, 3) for name in (_BIOME, _DAMAGE, _ENCHANTMENT))
    both = transcript(("alice", biome), ("alice", damage), ("alice", enchantment))
    without_damage = transcript(("alice", biome), ("alice", enchantment))

    missing = compare(both, without_damage, []).divergences
    unexpected = compare(without_damage, both, []).divergences

    assert [(d.kind, d.index, d.packet, _registry_in(d.reference)) for d in missing] == [
        ("missing", 0, _REGISTRY_DATA, _DAMAGE)
    ]
    assert [(d.kind, d.index, d.packet, _registry_in(d.candidate)) for d in unexpected] == [
        ("unexpected", 0, _REGISTRY_DATA, _DAMAGE)
    ]


def test_the_order_compared_is_that_of_the_registries_both_sides_send() -> None:
    biome, damage, enchantment = (registry(name, 3) for name in (_BIOME, _DAMAGE, _ENCHANTMENT))

    verdict = compare(
        transcript(("alice", biome), ("alice", damage), ("alice", enchantment)),
        transcript(("alice", enchantment), ("alice", biome)),
        [],
    )

    assert [(d.kind, d.index, d.path) for d in verdict.divergences] == [
        ("missing", 0, None),
        ("field", 1, ORDER_PATH),
    ]
    missing, order = verdict.divergences
    assert _registry_in(missing.reference) == _DAMAGE
    assert (order.reference, order.candidate) == ([_BIOME, _ENCHANTMENT], [_ENCHANTMENT, _BIOME])


def test_each_configuration_has_its_own_order_divergence() -> None:
    # Review A of #451: a reconfiguration whose order alone differs is reported there.
    biome, damage = registry(_BIOME, 3), registry(_DAMAGE, 3)
    finish = packet("minecraft:finish_configuration", state=State.CONFIGURATION)
    reconfigure = packet("minecraft:start_configuration")
    first = (("alice", biome), ("alice", damage), ("alice", finish), ("alice", reconfigure))

    verdict = compare(
        transcript(*first, ("alice", biome), ("alice", damage)),
        transcript(*first, ("alice", damage), ("alice", biome)),
        [],
    )

    assert [(d.index, d.path, d.reference, d.candidate) for d in verdict.divergences] == [
        (4, ORDER_PATH, [_BIOME, _DAMAGE], [_DAMAGE, _BIOME])
    ]


def test_the_order_of_a_run_paired_across_two_of_the_other_sides_runs() -> None:
    # A registry_data the codec cannot read ends a run: it may be another of a run's registries.
    biome, damage, enchantment = (registry(name, 3) for name in (_BIOME, _DAMAGE, _ENCHANTMENT))
    unread = packet(_REGISTRY_DATA, b"\x00", state=State.CONFIGURATION)

    verdict = compare(
        transcript(("alice", damage), ("alice", enchantment), ("alice", biome)),
        transcript(("alice", enchantment), ("alice", damage), ("alice", unread), ("alice", biome)),
        [],
    )

    assert [(d.kind, d.path, d.reference, d.candidate) for d in verdict.divergences] == [
        ("field", ORDER_PATH, [_DAMAGE, _ENCHANTMENT, _BIOME], [_ENCHANTMENT, _DAMAGE, _BIOME]),
        ("unexpected", None, ABSENT, "00"),
    ]


def test_a_configuration_packet_inside_one_sides_run_leaves_the_registries_paired() -> None:
    # Review A of #451: the client handles a keep_alive the same between two registry_data.
    biome, damage, enchantment = (registry(name, 3) for name in (_BIOME, _DAMAGE, _ENCHANTMENT))
    keep_alive = packet("minecraft:keep_alive", b"\x01", state=State.CONFIGURATION)

    verdict = compare(
        transcript(
            ("alice", biome), ("alice", damage), ("alice", enchantment), ("alice", keep_alive)
        ),
        transcript(
            ("alice", biome), ("alice", keep_alive), ("alice", damage), ("alice", enchantment)
        ),
        [],
    )

    assert verdict.divergences == ()


def test_a_configuration_packet_before_the_registries_is_where_it_is_after_them() -> None:
    biome, damage = registry(_BIOME, 3), registry(_DAMAGE, 3)
    features = packet("minecraft:update_enabled_features", state=State.CONFIGURATION)

    verdict = compare(
        transcript(("alice", features), ("alice", biome), ("alice", damage)),
        transcript(("alice", biome), ("alice", damage), ("alice", features)),
        [],
    )

    assert verdict.divergences == ()


def test_a_packet_a_run_goes_across_is_compared_after_the_runs_registries() -> None:
    biome, damage = registry(_BIOME, 3), registry(_DAMAGE, 3)
    sent, answer = (
        packet("minecraft:keep_alive", payload, state=State.CONFIGURATION)
        for payload in (b"\x01", b"\x02")
    )

    verdict = compare(
        transcript(("alice", biome), ("alice", sent), ("alice", damage)),
        transcript(("alice", biome), ("alice", answer), ("alice", damage)),
        [],
    )

    assert [(d.index, d.packet) for d in verdict.divergences] == [(2, "minecraft:keep_alive")]


def test_registries_in_another_order_across_a_configuration_packet_are_one_order() -> None:
    # Review B of #451, P2c: only the order differs, as network traffic.
    biome, damage, enchantment = (registry(name, 3) for name in (_BIOME, _DAMAGE, _ENCHANTMENT))
    features = packet("minecraft:update_enabled_features", state=State.CONFIGURATION)

    verdict = compare(
        transcript(
            ("alice", biome), ("alice", damage), ("alice", enchantment), ("alice", features)
        ),
        transcript(
            ("alice", damage), ("alice", features), ("alice", biome), ("alice", enchantment)
        ),
        [],
    )

    assert [(d.path, d.reference, d.candidate) for d in verdict.divergences] == [
        (ORDER_PATH, [_BIOME, _DAMAGE, _ENCHANTMENT], [_DAMAGE, _BIOME, _ENCHANTMENT])
    ]


def test_a_run_of_registries_ends_at_a_disconnect() -> None:
    # The client handles nothing after a disconnect, so a registry sent after one is not read.
    biome, damage = registry(_BIOME, 3), registry(_DAMAGE, 3)
    disconnect = packet("minecraft:disconnect", b"\x08", state=State.CONFIGURATION)

    verdict = compare(
        transcript(("alice", biome), ("alice", damage), ("alice", disconnect)),
        transcript(("alice", damage), ("alice", disconnect), ("alice", biome)),
        [],
    )

    assert [(d.kind, d.packet) for d in verdict.gameplay] == [
        ("unexpected", "minecraft:disconnect"),
        ("missing", "minecraft:disconnect"),
    ]


def _registry_in(value: object) -> object:
    """The registry id of a `registry_data` that a Divergence shows whole; else `value`."""
    if not isinstance(value, dict):
        return value
    return cast("dict[str, object]", value)["registry_id"]


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
