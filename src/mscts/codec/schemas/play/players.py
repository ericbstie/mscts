"""Play-state schemas for the tab list: players added to it, changed in it and removed from it.

Field layouts: minecraft.wiki `Java_Edition_protocol/Packets`, revision 3810839 (2026-10-01,
"26.3, protocol 777"), raw wikitext, "Player Info Update" and "Player Info Remove". Checked
against the 26.3 jar with `javap` (#67): `ClientboundPlayerInfoUpdatePacket` writes its actions
with `FriendlyByteBuf.writeEnumSet`, one byte with bit n for the action of ordinal n, then a
list of entries, each a UUID followed by the data of each action it holds, in ordinal order
(`Action.writer`); `ClientboundPlayerInfoRemovePacket` is a list of UUIDs.

Field names are the snake_case of the wiki's, with three of the wiki's names made specific:
`chat_session` (the wiki's Data), `priority` (the list order) and `hat_visible` (the wiki's
Visible). `actions` reads as the names of the actions it holds, in bit order.
"""

import functools
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import override

from mscts.codec.schema import (
    BOOL,
    BYTE,
    LONG,
    NBT,
    UUID,
    VAR_INT,
    PrefixedArray,
    PrefixedOptional,
    Schema,
    String,
    WireType,
)
from mscts.codec.schemas.login import GAME_PROFILE
from mscts.codec.wire import Reader, WireError, Writer

_CHAT_SESSION = Schema(
    session_id=UUID,
    expires_at=LONG,
    public_key=PrefixedArray(BYTE, max_length=512),
    key_signature=PrefixedArray(BYTE, max_length=4096),
)
"""`RemoteChatSession.Data`: the session's id, then its public key (`ProfilePublicKey.Data`)."""

_ACTIONS: tuple[tuple[str, tuple[tuple[str, WireType[object]], ...]], ...] = (
    ("add_player", (("name", String(16)), ("properties", GAME_PROFILE.fields["properties"]))),
    ("initialize_chat", (("chat_session", PrefixedOptional(_CHAT_SESSION)),)),
    ("update_game_mode", (("game_mode", VAR_INT),)),
    ("update_listed", (("listed", BOOL),)),
    ("update_latency", (("ping", VAR_INT),)),
    ("update_display_name", (("display_name", PrefixedOptional(NBT)),)),
    ("update_list_order", (("priority", VAR_INT),)),
    ("update_hat", (("hat_visible", BOOL),)),
)
"""Each action of `player_info_update`, in bit order, with the fields it adds to an entry."""

_BITS = {name: bit for bit, (name, _) in enumerate(_ACTIONS)}


@dataclass(frozen=True, slots=True)
class _Actions:
    """One byte, bit n for the action of ordinal n; its value is their names, in bit order."""

    def read(self, reader: Reader) -> list[str]:
        bits = reader.raw(1)[0]
        return [name for bit, (name, _) in enumerate(_ACTIONS) if bits >> bit & 1]

    def write(self, writer: Writer, value: object) -> None:
        writer.raw(bytes([_bits(value)]))


def _bits(value: object) -> int:
    """The byte for `value`, a list of action names in bit order, each once."""
    if not isinstance(value, list | tuple):
        msg = f"expected a list of action names, got {type(value).__name__}"
        raise WireError(msg)
    bits, last = 0, -1
    for name in value:
        if not isinstance(name, str) or name not in _BITS:
            msg = f"unknown action {name!r}"
            raise WireError(msg)
        bit = _BITS[name]
        if bit <= last:
            msg = f"the actions must be listed once each, in the order of their bits: {value!r}"
            raise WireError(msg)
        bits, last = bits | 1 << bit, bit
    return bits


@functools.cache
def _entry(actions: tuple[str, ...]) -> Schema:
    """An entry of a packet that holds `actions`: the UUID, then each action's fields."""
    fields = dict(field for name, adds in _ACTIONS if name in actions for field in adds)
    return Schema(uuid=UUID, **fields)


class _PlayerInfoUpdate(Schema):
    """`player_info_update`: which actions it holds, then an entry per player with their data.

    Its declared fields (`fields`) list every field an entry may hold; each packet's entries
    hold the UUID and the fields of its own actions only, as the wire does.
    """

    __slots__ = ()

    def __init__(self) -> None:
        """Declare `actions`, then `players` with every field an action can add."""
        super().__init__(actions=_Actions(), players=PrefixedArray(_entry(tuple(_BITS))))

    @override
    def read(self, reader: Reader) -> dict[str, object]:
        """Consume the actions, then the entries, each with the fields of those actions."""
        actions = _field("actions", _Actions().read, reader)
        players = _field("players", PrefixedArray(_entry(tuple(actions))).read, reader)
        return {"actions": actions, "players": players}

    @override
    def write(self, writer: Writer, value: object) -> None:
        """Append `value`'s actions, then its entries, each with exactly those actions' fields."""
        if not isinstance(value, Mapping):
            msg = f"expected a mapping of actions and players, got {type(value).__name__}"
            raise WireError(msg)
        given = {str(key): item for key, item in value.items()}
        if set(given) != {"actions", "players"}:
            msg = f"expected exactly the fields actions and players, got {sorted(given)}"
            raise WireError(msg)
        try:
            bits = _bits(given["actions"])
        except WireError as exc:
            msg = f"actions: {exc}"
            raise WireError(msg) from exc
        writer.raw(bytes([bits]))
        names = tuple(name for name, _ in _ACTIONS if bits >> _BITS[name] & 1)
        try:
            PrefixedArray(_entry(names)).write(writer, given["players"])
        except WireError as exc:
            msg = f"players: {exc}"
            raise WireError(msg) from exc


def _field[T](name: str, read: Callable[[Reader], T], reader: Reader) -> T:
    """`read(reader)`, its error prefixed with the field's `name`."""
    try:
        return read(reader)
    except WireError as exc:
        msg = f"{name}: {exc}"
        raise WireError(msg) from exc


CLIENTBOUND: Mapping[str, Schema] = {
    "minecraft:player_info_update": _PlayerInfoUpdate(),
    "minecraft:player_info_remove": Schema(uuids=PrefixedArray(UUID)),
}
