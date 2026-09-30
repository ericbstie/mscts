"""The play package merges the schemas of every submodule: a packet is added by adding a module."""

from collections.abc import Mapping
from types import ModuleType

from mscts.codec.schema import INT, LONG, Schema
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
