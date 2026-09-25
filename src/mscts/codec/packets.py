"""Packets of a Target: connection states, directions and decoded frames."""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from importlib import resources
from typing import Self


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


class Codec:
    """Packet names, ids and schemas of one Target."""

    def __init__(self, packet_ids: PacketIds) -> None:
        """Index `packet_ids` both ways."""
        self._ids = {
            (state, direction, name): packet_id
            for (state, direction), by_name in packet_ids.items()
            for name, packet_id in by_name.items()
        }
        self._names = {
            (state, direction, packet_id): name
            for (state, direction, name), packet_id in self._ids.items()
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
