"""Packets of a Target: connection states, directions and decoded frames."""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from importlib import resources
from typing import Self

from mscts.codec.schema import Schema
from mscts.codec.wire import Reader, WireError, Writer


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
        name: The packet name, e.g. `minecraft:status_response`.
        packet_id: The packet id the frame started with.
        payload: The bytes after the packet id.
        fields: The decoded fields, or None if the packet has no schema yet.
    """

    state: State
    direction: Direction
    name: str
    packet_id: int
    payload: bytes
    fields: Mapping[str, object] | None


class CodecError(ValueError):
    """Packet data, a packet, or packet fields that the Codec cannot accept."""


class UnknownPacketError(CodecError):
    """A packet name or id that the Target does not define for that state and direction."""


type PacketIds = Mapping[tuple[State, Direction], Mapping[str, int]]
"""Packet ids by name, for each (state, direction) the Target defines."""

type Schemas = Mapping[tuple[State, Direction], Mapping[str, Schema]]
"""Schemas by packet name, for each (state, direction) that has any."""


class Codec:
    """Packet names, ids and schemas of one Target."""

    def __init__(self, packet_ids: PacketIds, schemas: Schemas | None = None) -> None:
        """Index `packet_ids` both ways, and attach `schemas` to their packets.

        Raises:
            CodecError: Two names share an id in the same state and direction.
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
        self._schemas = {
            (state, direction, name): schema
            for (state, direction), by_name in (schemas or {}).items()
            for name, schema in by_name.items()
        }

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
        return cls(_parse_packet_report(report))

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
