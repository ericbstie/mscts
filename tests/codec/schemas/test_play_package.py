"""The play package merges the schemas of every submodule: a packet is added by adding a module."""

from collections.abc import Mapping
from types import ModuleType

import pytest

from mscts.codec.schema import INT, LONG, VAR_INT, Schema, SchemaError
from mscts.codec.schemas.play import merge_submodules


def fake_module(name: str, **mappings: Mapping[str, Schema]) -> ModuleType:
    module = ModuleType(name)
    for attribute, schemas in mappings.items():
        setattr(module, attribute, schemas)
    return module


def test_merges_every_submodule() -> None:
    interact, add_entity, system_chat = Schema(entity_id=INT), Schema(entity_id=INT), Schema(t=LONG)
    entities = fake_module(
        "entities",
        SERVERBOUND={"minecraft:interact": interact},
        CLIENTBOUND={"minecraft:add_entity": add_entity},
    )
    # A submodule may define only one of the two mappings.
    chat = fake_module("chat", CLIENTBOUND={"minecraft:system_chat": system_chat})

    serverbound, clientbound = merge_submodules([("entities", entities), ("chat", chat)])

    assert serverbound == {"minecraft:interact": interact}
    assert clientbound == {"minecraft:add_entity": add_entity, "minecraft:system_chat": system_chat}


def test_a_packet_defined_twice_is_refused() -> None:
    first = fake_module("first", CLIENTBOUND={"minecraft:add_entity": Schema(entity_id=INT)})
    second = fake_module("second", CLIENTBOUND={"minecraft:add_entity": Schema(entity_id=VAR_INT)})

    with pytest.raises(
        SchemaError, match=r"minecraft:add_entity is in CLIENTBOUND of both first and second"
    ):
        merge_submodules([("first", first), ("second", second)])


def test_a_packet_may_be_defined_once_in_each_direction() -> None:
    keep_alive = Schema(keep_alive_id=LONG)
    both = fake_module(
        "both",
        SERVERBOUND={"minecraft:keep_alive": keep_alive},
        CLIENTBOUND={"minecraft:keep_alive": keep_alive},
    )

    serverbound, clientbound = merge_submodules([("both", both)])

    assert serverbound == clientbound == {"minecraft:keep_alive": keep_alive}
