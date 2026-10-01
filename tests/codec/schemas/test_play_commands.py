"""The play schemas a command travels in, round-tripped through hand-built bytes."""

import struct

import pytest

from mscts.codec.packets import Codec, CodecError, Direction, State
from mscts.codec.schemas.play.commands import (
    PROPERTIES,
    CommandNode,
    commands_schema,
    root_literals,
)
from mscts.codec.wire import Reader, WireError, Writer

CODEC = Codec.load("26.3")
CLIENTBOUND, SERVERBOUND = Direction.CLIENTBOUND, Direction.SERVERBOUND


def test_chat_command_is_the_command_as_a_string() -> None:
    data = bytes([0x07, 0x0B]) + b"tick freeze"
    fields = {"command": "tick freeze"}

    assert CODEC.packet_id(State.PLAY, SERVERBOUND, "minecraft:chat_command") == 0x07
    assert CODEC.encode(State.PLAY, SERVERBOUND, "minecraft:chat_command", fields) == data
    packet = CODEC.decode(State.PLAY, SERVERBOUND, data)
    assert (packet.name, packet.fields) == ("minecraft:chat_command", fields)


def test_a_chat_command_holds_at_most_32767_characters() -> None:
    CODEC.encode(State.PLAY, SERVERBOUND, "minecraft:chat_command", {"command": "x" * 32767})
    with pytest.raises(CodecError, match=r"command: .*32767"):
        CODEC.encode(State.PLAY, SERVERBOUND, "minecraft:chat_command", {"command": "x" * 32768})


def test_system_chat_is_its_content_as_nbt_bytes_then_whether_it_is_an_overlay() -> None:
    content = bytes([0x08, 0x00, 0x02]) + b"hi"  # an NBT String tag: the text "hi"
    data = bytes([0x7C]) + content + bytes([0x01])
    fields = {"content": content, "overlay": True}

    assert CODEC.packet_id(State.PLAY, CLIENTBOUND, "minecraft:system_chat") == 0x7C
    assert CODEC.encode(State.PLAY, CLIENTBOUND, "minecraft:system_chat", fields) == data
    packet = CODEC.decode(State.PLAY, CLIENTBOUND, data)
    assert (packet.name, packet.fields) == ("minecraft:system_chat", fields)


# The command tree (`commands`): its nodes, with a hand-built parser list. The 26.3 list, in
# protocol order, comes from the registry (`registry_names`).

PARSERS = (
    "brigadier:bool",
    "brigadier:float",
    "brigadier:double",
    "brigadier:integer",
    "brigadier:long",
    "brigadier:string",
    "minecraft:entity",
    "minecraft:score_holder",
    "minecraft:time",
    "minecraft:resource",
)
NODE = CommandNode(PARSERS)
ROOT, LITERAL, ARGUMENT = 0x00, 0x01, 0x02
EXECUTABLE, REDIRECT, SUGGESTIONS = 0x04, 0x08, 0x10


def node(**fields: object) -> dict[str, object]:
    blank: dict[str, object] = {
        "flags": 0,
        "children": [],
        "redirect_node": None,
        "name": None,
        "parser": None,
        "properties": None,
        "suggestions_type": None,
    }
    return blank | fields


def string(text: str) -> bytes:
    return bytes([len(text)]) + text.encode()


def round_trip(data: bytes, value: dict[str, object]) -> None:
    reader = Reader(data)
    assert NODE.read(reader) == value
    reader.expect_end()
    writer = Writer()
    NODE.write(writer, value)
    assert writer.to_bytes() == data


def test_a_root_node_is_its_flags_and_children() -> None:
    round_trip(bytes([ROOT, 0x02, 0x01, 0x02]), node(children=[1, 2]))


def test_a_literal_node_has_a_name_and_may_redirect() -> None:
    flags = LITERAL | EXECUTABLE | REDIRECT
    data = bytes([flags, 0x00, 0x00]) + string("tick")
    round_trip(data, node(flags=flags, redirect_node=0, name="tick"))


def test_an_argument_node_has_a_parser_its_properties_and_suggestions() -> None:
    flags = ARGUMENT | EXECUTABLE | SUGGESTIONS
    properties = bytes([0x01]) + struct.pack(">i", 1)  # a minimum of 1, no maximum
    data = bytes([flags, 0x00]) + string("count") + bytes([3]) + properties
    data += string("minecraft:ask_server")
    value = node(
        flags=flags,
        name="count",
        parser="brigadier:integer",
        properties={"flags": 1, "min": 1, "max": None},
        suggestions_type="minecraft:ask_server",
    )
    round_trip(data, value)


PROPERTIES_CASES = {
    "float, both bounds": (
        "brigadier:float",
        bytes([0x03]) + struct.pack(">ff", 0.0, 1.0),
        {"flags": 3, "min": 0.0, "max": 1.0},
    ),
    "double, a maximum": (
        "brigadier:double",
        bytes([0x02]) + struct.pack(">d", 2.5),
        {"flags": 2, "min": None, "max": 2.5},
    ),
    "integer, no bound": (
        "brigadier:integer",
        bytes([0x00]),
        {"flags": 0, "min": None, "max": None},
    ),
    "long, both bounds": (
        "brigadier:long",
        bytes([0x03]) + struct.pack(">qq", -5, 5),
        {"flags": 3, "min": -5, "max": 5},
    ),
    "string": ("brigadier:string", bytes([0x02]), {"behavior": "GREEDY_PHRASE"}),
    "entity": ("minecraft:entity", bytes([0x03]), {"flags": 3}),
    "score holder": ("minecraft:score_holder", bytes([0x01]), {"flags": 1}),
    "time": ("minecraft:time", struct.pack(">i", 0), {"min": 0}),
    "resource": (
        "minecraft:resource",
        string("minecraft:block"),
        {"registry": "minecraft:block"},
    ),
    "no properties": ("brigadier:bool", b"", None),
}


@pytest.mark.parametrize(
    ("parser", "properties", "value"), PROPERTIES_CASES.values(), ids=PROPERTIES_CASES.keys()
)
def test_each_parser_has_its_own_properties(parser: str, properties: bytes, value: object) -> None:
    data = bytes([ARGUMENT, 0x00]) + string("x") + bytes([PARSERS.index(parser)]) + properties
    round_trip(data, node(flags=ARGUMENT, name="x", parser=parser, properties=value))


def test_the_parsers_with_properties_are_these() -> None:
    numbers = {"brigadier:float", "brigadier:double", "brigadier:integer", "brigadier:long"}
    registries = {
        "minecraft:resource_or_tag",
        "minecraft:resource_or_tag_key",
        "minecraft:resource",
        "minecraft:resource_key",
        "minecraft:resource_selector",
    }
    flags = {"minecraft:entity", "minecraft:score_holder"}
    others = {"brigadier:string", "minecraft:time"}
    assert set(PROPERTIES) == numbers | registries | flags | others


def test_the_string_behaviours_are_brigadiers() -> None:
    for behavior, name in enumerate(("SINGLE_WORD", "QUOTABLE_PHRASE", "GREEDY_PHRASE")):
        data = bytes([ARGUMENT, 0x00]) + string("x") + bytes([5, behavior])
        value = node(
            flags=ARGUMENT, name="x", parser="brigadier:string", properties={"behavior": name}
        )
        round_trip(data, value)


def test_a_literal_reads_no_suggestions_and_type_3_reads_nothing() -> None:
    # As vanilla reads them: suggestions only on an argument, and no data for type 3.
    flags = LITERAL | SUGGESTIONS
    round_trip(bytes([flags, 0x00]) + string("tick"), node(flags=flags, name="tick"))
    round_trip(bytes([0x03, 0x00]), node(flags=0x03))


@pytest.mark.parametrize(
    ("data", "error"),
    [
        (bytes([ARGUMENT, 0x00]) + string("x") + bytes([10]), "parser: unknown parser id 10"),
        (bytes([ARGUMENT, 0x00]) + string("x") + bytes([5, 3]), "properties: behavior: unknown"),
    ],
    ids=["unknown parser id", "unknown string behaviour"],
)
def test_what_vanilla_cannot_read_is_refused(data: bytes, error: str) -> None:
    with pytest.raises(WireError, match=error):
        NODE.read(Reader(data))


WRONG = {
    "a redirect flag and no redirect": (node(flags=REDIRECT | LITERAL, name="tick"), "redirect"),
    "a redirect with no flag": (node(flags=LITERAL, name="tick", redirect_node=0), "redirect"),
    "a name on a root": (node(name="tick"), "name"),
    "a literal with no name": (node(flags=LITERAL), "name"),
    "a parser on a literal": (
        node(flags=LITERAL, name="tick", parser="brigadier:bool"),
        "parser",
    ),
    "an unknown parser": (node(flags=ARGUMENT, name="x", parser="minecraft:nope"), "parser"),
    "properties for a parser that has none": (
        node(flags=ARGUMENT, name="x", parser="brigadier:bool", properties={}),
        "properties",
    ),
    "no properties for a parser that has some": (
        node(flags=ARGUMENT, name="x", parser="minecraft:time"),
        "properties",
    ),
    "a minimum the flags do not announce": (
        node(
            flags=ARGUMENT,
            name="x",
            parser="brigadier:integer",
            properties={"flags": 0, "min": 1, "max": None},
        ),
        "properties: min",
    ),
    "suggestions with no flag": (
        node(flags=ARGUMENT, name="x", parser="brigadier:bool", suggestions_type="a:b"),
        "suggestions_type",
    ),
    "a suggestions flag and no suggestions": (
        node(flags=ARGUMENT | SUGGESTIONS, name="x", parser="brigadier:bool"),
        "suggestions_type",
    ),
    "missing fields": ({"flags": 0}, "missing"),
}


@pytest.mark.parametrize(("value", "error"), WRONG.values(), ids=WRONG.keys())
def test_a_node_that_would_not_read_back_is_refused(value: dict[str, object], error: str) -> None:
    with pytest.raises(WireError, match=error):
        NODE.write(Writer(), value)


TREE = {
    "nodes": [
        node(children=[1, 2, 3]),
        node(flags=LITERAL | EXECUTABLE, name="tick", children=[4]),
        node(flags=LITERAL, name="setblock"),
        node(flags=ARGUMENT, name="x", parser="brigadier:bool"),
        node(flags=LITERAL | EXECUTABLE, name="freeze"),
    ],
    "root_index": 0,
}


def test_a_command_tree_is_its_nodes_then_the_root_index() -> None:
    schema = commands_schema(PARSERS)
    writer = Writer()
    schema.write(writer, TREE)
    data = writer.to_bytes()
    assert (data[0], data[-1]) == (5, 0)  # five nodes, the root first
    assert schema.read(Reader(data)) == TREE


def test_the_root_literals_are_the_commands_a_player_can_run() -> None:
    assert root_literals(TREE) == frozenset({"tick", "setblock"})


@pytest.mark.parametrize(
    ("tree", "error"),
    [
        ({"nodes": [node()], "root_index": 1}, "root_index 1 is not a node of the 1"),
        ({"nodes": [node(children=[7])], "root_index": 0}, "child 7 is not a node of the 1"),
    ],
)
def test_root_literals_refuses_an_index_out_of_the_tree(
    tree: dict[str, object], error: str
) -> None:
    with pytest.raises(ValueError, match=error):
        root_literals(tree)
