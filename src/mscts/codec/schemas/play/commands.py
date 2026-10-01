"""Play-state schemas for commands: what a player sends, what the server answers, its tree.

The tree is the command tree the server sends each player.

Field layouts: minecraft.wiki `Java_Edition_protocol/Packets`, revision 3790659
(2026-09-23, "26.3, protocol 777"), raw wikitext, "Chat Command", "System Chat Message" and
"Commands"; and `Java_Edition_protocol/Command_data`, revision 3445801, for a node and each
parser's properties. Checked against the 26.3 jar with `javap`
(docs/research/2026-10-01-control.md): `ServerboundChatCommandPacket` reads its command with
`FriendlyByteBuf.readUtf()`, at most 32767; `ClientboundSystemChatPacket.STREAM_CODEC` is a
text component (`ComponentSerialization.TRUSTED_STREAM_CODEC`, network NBT) then a Boolean;
`ClientboundCommandsPacket` is a list of `Entry`, then a VarInt root index, and each
parser's properties are its `ArgumentTypeInfo`'s `serializeToNetwork`.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import cast

from mscts.codec.registry_names import registry_names
from mscts.codec.schema import (
    BOOL,
    BYTE,
    DOUBLE,
    FLOAT,
    IDENTIFIER,
    INT,
    LONG,
    NBT,
    VAR_INT,
    PrefixedArray,
    Schema,
    String,
    WireType,
)
from mscts.codec.wire import Reader, WireError, Writer
from mscts.target import TARGET

SERVERBOUND: Mapping[str, Schema] = {
    # Chat Command: a command, without its slash, run as the player (unsigned: a command
    # with no signed argument).
    "minecraft:chat_command": Schema(command=String(32767)),
}

# The command tree.

_TYPE, _REDIRECT, _SUGGESTIONS = 0x03, 0x08, 0x10
"""Node flags (`ClientboundCommandsPacket`): the node type in the low two bits, then whether
it redirects and whether it names its suggestions. EXECUTABLE (0x04) and RESTRICTED (0x20)
carry no data."""

_LITERAL, _ARGUMENT = 1, 2
"""Node types with data; 0 is the root, and 3 is never written (vanilla reads no data)."""

_HAS_MIN, _HAS_MAX = 0x01, 0x02
"""A number parser's flags (`ArgumentUtils.createNumberFlags`)."""

_NODE_FIELDS = (
    "flags",
    "children",
    "redirect_node",
    "name",
    "parser",
    "properties",
    "suggestions_type",
)
_CHILDREN = PrefixedArray(VAR_INT)

_NAME = String(32767)


def _exactly(value: object, keys: Sequence[str]) -> dict[str, object]:
    """`value` as a dict, if it is a mapping of exactly `keys`."""
    if not isinstance(value, Mapping):
        msg = f"expected a mapping of {', '.join(keys)}, got {type(value).__name__}"
        raise WireError(msg)
    given = {str(key): item for key, item in value.items()}
    missing = [key for key in keys if key not in given]
    unexpected = sorted(key for key in given if key not in keys)
    problems = []
    if missing:
        problems.append(f"missing field(s) {', '.join(missing)}")
    if unexpected:
        problems.append(f"unexpected field(s) {', '.join(unexpected)}")
    if problems:
        raise WireError("; ".join(problems))
    return given


def _flags(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        msg = f"flags: expected an int, got {type(value).__name__}"
        raise WireError(msg)
    return value


@dataclass(frozen=True, slots=True)
class _Range:
    """A number parser's properties: flags, then the minimum and the maximum they announce."""

    number: WireType[object]

    def read(self, reader: Reader) -> dict[str, object]:
        flags = BYTE.read(reader)
        low = self.number.read(reader) if flags & _HAS_MIN else None
        high = self.number.read(reader) if flags & _HAS_MAX else None
        return {"flags": flags, "min": low, "max": high}

    def write(self, writer: Writer, value: object) -> None:
        fields = _exactly(value, ("flags", "min", "max"))
        flags = _flags(fields["flags"])
        BYTE.write(writer, flags)
        for key, bit in (("min", _HAS_MIN), ("max", _HAS_MAX)):
            announced = bool(flags & bit)
            if (fields[key] is not None) != announced:
                msg = f"{key}: present only if flags & {bit} (flags are {flags})"
                raise WireError(msg)
            if announced:
                self.number.write(writer, fields[key])


_BEHAVIORS = ("SINGLE_WORD", "QUOTABLE_PHRASE", "GREEDY_PHRASE")
"""`StringArgumentType.StringType`'s constants, by ordinal (brigadier 1.3.11)."""


@dataclass(frozen=True, slots=True)
class _Behavior:
    """A string parser's behaviour: a VarInt enum, read as its constant's name."""

    def read(self, reader: Reader) -> str:
        ordinal = reader.var_int()
        if not 0 <= ordinal < len(_BEHAVIORS):
            msg = f"unknown behavior {ordinal}"
            raise WireError(msg)
        return _BEHAVIORS[ordinal]

    def write(self, writer: Writer, value: object) -> None:
        if value not in _BEHAVIORS:
            msg = f"unknown behavior {value!r}"
            raise WireError(msg)
        writer.var_int(_BEHAVIORS.index(str(value)))


_REGISTRY = Schema(registry=IDENTIFIER)

PROPERTIES: Mapping[str, WireType[object]] = MappingProxyType(
    {
        "brigadier:float": _Range(FLOAT),
        "brigadier:double": _Range(DOUBLE),
        "brigadier:integer": _Range(INT),
        "brigadier:long": _Range(LONG),
        "brigadier:string": Schema(behavior=_Behavior()),
        "minecraft:entity": Schema(flags=BYTE),  # 1 a single entity, 2 players only
        "minecraft:score_holder": Schema(flags=BYTE),  # 1 several
        "minecraft:time": Schema(min=INT),  # the shortest time, in ticks
        "minecraft:resource_or_tag": _REGISTRY,
        "minecraft:resource_or_tag_key": _REGISTRY,
        "minecraft:resource": _REGISTRY,
        "minecraft:resource_key": _REGISTRY,
        "minecraft:resource_selector": _REGISTRY,
    }
)
"""The properties of the parsers that have some, by name. Every other parser has none."""


class CommandNode:
    """One node of a command tree, as a dict of the wiki's Node fields.

    `flags` (a Byte), `children` (node indices), `redirect_node` (an index, or None),
    `name` (literals and arguments, else None), `parser`, `properties` and
    `suggestions_type` (arguments only, else None). `parser` is the parser's name, not its
    id: the id is its place in `parsers`. `properties` is what `PROPERTIES` reads for it, or
    None for a parser that has none; `suggestions_type` is there only if flags & 0x10.

    An id `parsers` does not have is a WireError, as vanilla cannot read the node's
    properties either. Writing refuses a node whose fields disagree with its flags, since
    it would not read back.
    """

    __slots__ = ("_ids", "_parsers")

    def __init__(self, parsers: Sequence[str]) -> None:
        """Read parser ids as places in `parsers`, the parser names in protocol order."""
        self._parsers = tuple(parsers)
        self._ids = {name: number for number, name in enumerate(self._parsers)}

    def read(self, reader: Reader) -> dict[str, object]:
        """Consume one node."""
        flags = _field("flags", BYTE.read, reader)
        node: dict[str, object] = {"flags": flags}
        node["children"] = _field("children", _CHILDREN.read, reader)
        node["redirect_node"] = None
        if flags & _REDIRECT:
            node["redirect_node"] = _field("redirect_node", VAR_INT.read, reader)
        kind = flags & _TYPE
        node["name"] = None
        if kind in {_LITERAL, _ARGUMENT}:
            node["name"] = _field("name", _NAME.read, reader)
        node["parser"] = node["properties"] = node["suggestions_type"] = None
        if kind == _ARGUMENT:
            parser = node["parser"] = _field("parser", self._parser, reader)
            wire = PROPERTIES.get(parser)
            if wire is not None:
                node["properties"] = _field("properties", wire.read, reader)
            if flags & _SUGGESTIONS:
                node["suggestions_type"] = _field("suggestions_type", IDENTIFIER.read, reader)
        return node

    def write(self, writer: Writer, value: object) -> None:
        """Append `value`, a node, if its fields agree with its flags."""
        node = _exactly(value, _NODE_FIELDS)
        flags = _flags(node["flags"])
        kind = flags & _TYPE
        argument = kind == _ARGUMENT
        _expect_present(node, "redirect_node", present=bool(flags & _REDIRECT))
        _expect_present(node, "name", present=kind in {_LITERAL, _ARGUMENT})
        _expect_present(node, "parser", present=argument)
        _expect_present(node, "suggestions_type", present=argument and bool(flags & _SUGGESTIONS))
        parser = node["parser"]
        if argument and parser not in self._ids:
            msg = f"parser: unknown parser {parser!r}"
            raise WireError(msg)
        wire = PROPERTIES.get(str(parser)) if argument else None
        _expect_present(node, "properties", present=wire is not None)
        BYTE.write(writer, flags)
        _write_field("children", _CHILDREN, writer, node["children"])
        if node["redirect_node"] is not None:
            _write_field("redirect_node", VAR_INT, writer, node["redirect_node"])
        if node["name"] is not None:
            _write_field("name", _NAME, writer, node["name"])
        if not argument:
            return
        writer.var_int(self._ids[str(parser)])
        if wire is not None:
            _write_field("properties", wire, writer, node["properties"])
        if node["suggestions_type"] is not None:
            _write_field("suggestions_type", IDENTIFIER, writer, node["suggestions_type"])

    def _parser(self, reader: Reader) -> str:
        parser_id = reader.var_int()
        if not 0 <= parser_id < len(self._parsers):
            msg = f"unknown parser id {parser_id}"
            raise WireError(msg)
        return self._parsers[parser_id]


def _field[T](name: str, read: Callable[[Reader], T], reader: Reader) -> T:
    """Read one field of a node, naming it in any error."""
    try:
        return read(reader)
    except WireError as exc:
        msg = f"{name}: {exc}"
        raise WireError(msg) from exc


def _write_field(name: str, wire: WireType[object], writer: Writer, value: object) -> None:
    try:
        wire.write(writer, value)
    except WireError as exc:
        msg = f"{name}: {exc}"
        raise WireError(msg) from exc


def _expect_present(node: Mapping[str, object], key: str, *, present: bool) -> None:
    if (node[key] is not None) != present:
        state = "needs" if present else "cannot have"
        msg = f"{key}: a node with flags {node['flags']} {state} one"
        raise WireError(msg)


def commands_schema(parsers: Sequence[str]) -> Schema:
    """The `commands` packet: its nodes, then the index of the root node.

    Args:
        parsers: The parser names in protocol order: the Target's
            `minecraft:command_argument_type` registry.
    """
    return Schema(nodes=PrefixedArray(CommandNode(parsers)), root_index=VAR_INT)


CLIENTBOUND: Mapping[str, Schema] = {
    # Commands: the command tree, the commands this player may run and their arguments.
    "minecraft:commands": commands_schema(
        registry_names(TARGET.minecraft_version, "minecraft:command_argument_type")
    ),
    # System Chat Message: a message from the server, such as a command's feedback. The
    # content is a text component, kept as its NBT bytes until text components decode.
    "minecraft:system_chat": Schema(content=NBT, overlay=BOOL),
}


def root_literals(tree: Mapping[str, object]) -> frozenset[str]:
    """The names of the root's literal children: the commands a player can run.

    Args:
        tree: A decoded `commands` packet's fields (`commands_schema`).

    Raises:
        ValueError: The root index, or one of the root's children, is not a node of the
            tree, which vanilla could not build either.
    """
    nodes = cast("list[dict[str, object]]", tree["nodes"])
    root = cast("int", tree["root_index"])
    if not 0 <= root < len(nodes):
        msg = f"root_index {root} is not a node of the {len(nodes)}"
        raise ValueError(msg)
    names: set[str] = set()
    for child in cast("list[int]", nodes[root]["children"]):
        if not 0 <= child < len(nodes):
            msg = f"child {child} is not a node of the {len(nodes)}"
            raise ValueError(msg)
        if cast("int", nodes[child]["flags"]) & _TYPE == _LITERAL:
            names.add(cast("str", nodes[child]["name"]))
    return frozenset(names)
