"""Packets of a Target: connection states, directions and decoded frames."""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from importlib import resources
from typing import TYPE_CHECKING, Self

from mscts.codec.schema import Schema
from mscts.codec.schemas import configuration, handshake, login, play, status
from mscts.codec.wire import Reader, WireError, Writer

if TYPE_CHECKING:
    from mscts.target import Target


class State(StrEnum):
    """A connection state; values are the keys of the vanilla packet report."""

    HANDSHAKE = "handshake"
    STATUS = "status"
    LOGIN = "login"
    CONFIGURATION = "configuration"
    PLAY = "play"


class Direction(StrEnum):
    """Which way a packet travels; values are the keys of the vanilla packet report."""

    CLIENTBOUND = "clientbound"
    SERVERBOUND = "serverbound"


@dataclass(frozen=True, slots=True)
class Packet:
    """One decoded frame.

    Attributes:
        state: The connection state the frame was sent in.
        direction: Which way the frame travelled.
        name: The packet name, e.g. `minecraft:status_response`. A frame the Codec could
            not decode has the packet's name if its id is known, `unknown:<state>:0x2a`
            if not, and `corrupt:<state>` if not even a packet id could be read.
        packet_id: The packet id the frame started with, or -1 if it had none.
        payload: The bytes after the packet id (all of them if it had none).
        fields: The decoded fields, or None if the packet has no schema yet, or could not
            be decoded.
        decode_error: Why the Codec could not decode the frame, or None if it could.
    """

    state: State
    direction: Direction
    name: str
    packet_id: int
    payload: bytes
    fields: Mapping[str, object] | None
    decode_error: str | None = None


class CodecError(ValueError):
    """Packet data, a packet, or packet fields that the Codec cannot accept."""


class UnknownPacketError(CodecError):
    """A packet name or id that the Target does not define for that state and direction."""


type PacketIds = Mapping[tuple[State, Direction], Mapping[str, int]]
"""Packet ids by name, for each (state, direction) the Target defines."""

type Schemas = Mapping[tuple[State, Direction], Mapping[str, Schema]]
"""Schemas by packet name, for each (state, direction) that has any."""

_SCHEMAS: Mapping[str, Schemas] = {
    "26.3": {
        (State.HANDSHAKE, Direction.SERVERBOUND): handshake.SERVERBOUND,
        (State.STATUS, Direction.SERVERBOUND): status.SERVERBOUND,
        (State.STATUS, Direction.CLIENTBOUND): status.CLIENTBOUND,
        (State.LOGIN, Direction.SERVERBOUND): login.SERVERBOUND,
        (State.LOGIN, Direction.CLIENTBOUND): login.CLIENTBOUND,
        (State.CONFIGURATION, Direction.SERVERBOUND): configuration.SERVERBOUND,
        (State.CONFIGURATION, Direction.CLIENTBOUND): configuration.CLIENTBOUND,
        (State.PLAY, Direction.SERVERBOUND): play.SERVERBOUND,
        (State.PLAY, Direction.CLIENTBOUND): play.CLIENTBOUND,
    },
}
"""The schemas `Codec.load` attaches, by Minecraft version."""


class Codec:
    """Packet names, ids and schemas of one Target."""

    def __init__(self, packet_ids: PacketIds, schemas: Schemas | None = None) -> None:
        """Index `packet_ids` both ways, and attach `schemas` to their packets.

        Raises:
            CodecError: Two names share an id in the same state and direction.
            UnknownPacketError: A schema is keyed by a packet `packet_ids` lacks.
        """
        self._ids: dict[tuple[State, Direction, str], int] = {}
        self._names: dict[tuple[State, Direction, int], str] = {}
        for (state, direction), by_name in packet_ids.items():
            for name, packet_id in by_name.items():
                other = self._names.setdefault((state, direction, packet_id), name)
                if other != name:
                    msg = f"{state} {direction}: {other} and {name} share id {packet_id:#04x}"
                    raise CodecError(msg)
                self._ids[state, direction, name] = packet_id
        self._schemas: dict[tuple[State, Direction, str], Schema] = {}
        for (state, direction), by_name in (schemas or {}).items():
            for name, schema in by_name.items():
                if (state, direction, name) not in self._ids:
                    msg = f"schema for no packet {state} {direction} {name}"
                    raise UnknownPacketError(msg)
                self._schemas[state, direction, name] = schema

    @classmethod
    def load(cls, minecraft_version: str) -> Self:
        """Load the Codec for a Minecraft version from `codec/data/<minecraft_version>/`.

        Raises:
            CodecError: There is no packet data for that version.
        """
        resource = resources.files("mscts.codec").joinpath(
            "data", minecraft_version, "packets.json"
        )
        try:
            text = resource.read_text(encoding="utf-8")
        except FileNotFoundError:
            msg = f"no packet data for Minecraft {minecraft_version}"
            raise CodecError(msg) from None
        report: object = json.loads(text)
        return cls(_parse_packet_report(report), _SCHEMAS.get(minecraft_version))

    @classmethod
    def for_target(cls, target: "Target") -> Self:
        """Load the Codec for `target`'s Minecraft version (see `load`)."""
        return cls.load(target.minecraft_version)

    def packet_id(self, state: State, direction: Direction, name: str) -> int:
        """Return the id of packet `name` in `state`, travelling `direction`.

        Raises:
            UnknownPacketError: The Target has no such packet there.
        """
        try:
            return self._ids[state, direction, name]
        except KeyError:
            msg = f"no packet {state} {direction} {name}"
            raise UnknownPacketError(msg) from None

    def packet_name(self, state: State, direction: Direction, packet_id: int) -> str:
        """Return the name of packet `packet_id` in `state`, travelling `direction`.

        Raises:
            UnknownPacketError: The Target has no such packet there.
        """
        try:
            return self._names[state, direction, packet_id]
        except KeyError:
            msg = f"no packet {state} {direction} {packet_id:#04x}"
            raise UnknownPacketError(msg) from None

    def encode(
        self, state: State, direction: Direction, name: str, fields: Mapping[str, object]
    ) -> bytes:
        """Encode packet `name` with `fields` as `VarInt packet id ‖ payload`.

        Raises:
            UnknownPacketError: The Target has no such packet there.
            CodecError: The packet has no schema, or `fields` do not fit it.
        """
        writer = Writer().var_int(self.packet_id(state, direction, name))
        schema = self._schemas.get((state, direction, name))
        if schema is None:
            msg = f"{state} {direction} {name} has no schema"
            raise CodecError(msg)
        try:
            schema.write(writer, fields)
        except WireError as exc:
            msg = f"{state} {direction} {name}: {exc}"
            raise CodecError(msg) from exc
        return writer.to_bytes()

    def decode(self, state: State, direction: Direction, data: bytes) -> Packet:
        """Decode one frame's data, `VarInt packet id ‖ payload`, seen in `state`.

        The Packet has decoded fields if the packet has a schema, else None.

        Raises:
            UnknownPacketError: The Target has no packet with that id there.
            CodecError: `data` does not start with a complete packet id, or the
                payload does not fit the packet's schema exactly (a field is invalid or
                truncated, or bytes remain after the last field).
        """
        reader = Reader(data)
        try:
            packet_id = reader.var_int()
        except WireError as exc:
            msg = f"{state} {direction} packet id: {exc}"
            raise CodecError(msg) from exc
        name = self.packet_name(state, direction, packet_id)
        payload = data[len(data) - reader.remaining :]
        fields = None
        schema = self._schemas.get((state, direction, name))
        if schema is not None:
            try:
                fields = schema.read(reader)
                reader.expect_end()
            except WireError as exc:
                msg = f"{state} {direction} {name}: {exc}"
                raise CodecError(msg) from exc
        return Packet(
            state=state,
            direction=direction,
            name=name,
            packet_id=packet_id,
            payload=payload,
            fields=fields,
        )

    def undecodable(self, state: State, direction: Direction, data: bytes, error: str) -> Packet:
        """The Packet that records frame data `decode` rejected, and why (`error`).

        It keeps the packet's name and id if the id is known in `state` and `direction`,
        names it `unknown:<state>:0x2a` if the id is not, and `corrupt:<state>` (id -1,
        every byte kept as the payload) if not even a packet id can be read.
        """
        reader = Reader(data)
        try:
            packet_id = reader.var_int()
        except WireError:
            return undecodable_frame(state, direction, data, error)
        try:
            name = self.packet_name(state, direction, packet_id)
        except UnknownPacketError:
            name = f"unknown:{state}:{packet_id:#04x}"
        return Packet(
            state=state,
            direction=direction,
            name=name,
            packet_id=packet_id,
            payload=data[len(data) - reader.remaining :],
            fields=None,
            decode_error=error,
        )


def undecodable_frame(state: State, direction: Direction, raw: bytes, error: str) -> Packet:
    """The Packet that records bytes that did not even hold a packet id, and why (`error`).

    E.g. a corrupt frame length or compressed payload: named `corrupt:<state>`, with id -1
    and `raw` as the payload.
    """
    return Packet(
        state=state,
        direction=direction,
        name=f"corrupt:{state}",
        packet_id=-1,
        payload=raw,
        fields=None,
        decode_error=error,
    )


def _parse_packet_report(report: object) -> dict[tuple[State, Direction], dict[str, int]]:
    """Read the generator's `{state: {direction: {name: {"protocol_id": id}}}}` report."""
    return {
        (State(state), Direction(direction)): {
            name: _protocol_id(entry) for name, entry in _json_object(by_name).items()
        }
        for state, by_direction in _json_object(report).items()
        for direction, by_name in _json_object(by_direction).items()
    }


def _json_object(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        msg = f"packet report: expected a JSON object, got {type(value).__name__}"
        raise CodecError(msg)
    return {str(key): item for key, item in value.items()}


def _protocol_id(entry: object) -> int:
    protocol_id = _json_object(entry).get("protocol_id")
    if not isinstance(protocol_id, int) or isinstance(protocol_id, bool):
        msg = f"packet report: expected an integer protocol_id, got {protocol_id!r}"
        raise CodecError(msg)
    return protocol_id
