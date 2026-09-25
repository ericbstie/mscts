"""Packets of a Target: connection states, directions and decoded frames."""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum


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
