"""Bots: the client connections Scenarios drive."""

import asyncio
import hashlib
import json
import math
import struct
import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Self

from mscts.codec.packets import Codec, Packet, State
from mscts.net import Connection, Endpoint, ProtocolError
from mscts.target import Target
from mscts.transcript import Transcript

PROBE_TIMEOUT_S = 1.0
"""How long one readiness probe attempt waits, from connecting to the status answer."""

CHUNKS_PER_TICK = 9.0
"""The rate a Bot asks for when it acknowledges a chunk batch (chunk_batch_received).

The vanilla client asks for a rate it estimates from how fast it received the batch, so
its answer depends on its timing; a Bot must not. It asks for 9 chunks per tick, the rate
vanilla's server starts at (`PlayerChunkSender.START_CHUNKS_PER_TICK`, 26.3 javap), so
acknowledging never changes the pace the server chose.
"""

_RELATIVE_X, _RELATIVE_Y, _RELATIVE_Z, _RELATIVE_YAW, _RELATIVE_PITCH = (
    1 << bit for bit in range(5)
)
"""Teleport Flags bits (wiki Data types; vanilla's `Relative`): which parts add to the pose."""

_PITCH_LIMIT = 90.0

_STATUS_INTENT, _LOGIN_INTENT = 1, 2


def offline_uuid(name: str) -> uuid.UUID:
    """The UUID an offline-mode server gives the player called `name`.

    Vanilla's `UUIDUtil.createOfflinePlayerUUID` (26.3 javap): Java's
    `UUID.nameUUIDFromBytes`, a version 3 (MD5) UUID, of `"OfflinePlayer:" + name` in UTF-8.
    """
    digest = hashlib.md5(f"OfflinePlayer:{name}".encode(), usedforsecurity=False).digest()
    return uuid.UUID(bytes=digest, version=3)


def _binary32(value: float) -> float:
    """`value` rounded to the nearest binary32, as Java's float arithmetic rounds it."""
    try:
        return float(struct.unpack(">f", struct.pack(">f", value))[0])
    except OverflowError:
        return math.copysign(math.inf, value)


@dataclass(slots=True)
class _Pose:
    """Where the Bot's player is and faces, as the vanilla client would have it."""

    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    yaw: float = 0.0
    pitch: float = 0.0

    def teleport(self, fields: Mapping[str, object]) -> None:
        """Apply a player_position, as `PositionMoveRotation.calculateAbsolute` does.

        Each flagged part adds to the current value, the others replace it; rotation is
        summed in binary32 and pitch clamped to -90..90. As in `Entity.setYRot` and
        `setXRot`, a rotation that is not finite leaves the old one.
        """
        flags = _field(fields, "flags", int)
        self.x = (self.x if flags & _RELATIVE_X else 0.0) + _field(fields, "x", float)
        self.y = (self.y if flags & _RELATIVE_Y else 0.0) + _field(fields, "y", float)
        self.z = (self.z if flags & _RELATIVE_Z else 0.0) + _field(fields, "z", float)
        yaw = _binary32((self.yaw if flags & _RELATIVE_YAW else 0.0) + _field(fields, "yaw", float))
        pitch = _binary32(
            (self.pitch if flags & _RELATIVE_PITCH else 0.0) + _field(fields, "pitch", float)
        )
        if math.isfinite(yaw):
            self.yaw = yaw
        if math.isfinite(pitch):
            self.pitch = max(-_PITCH_LIMIT, min(pitch, _PITCH_LIMIT))


class Replies:
    """What a Bot answers by itself, as each packet arrives, the way the vanilla client does.

    A Connection's answer (`Connection.open(answer=...)`): the Bot's background reader
    awaits it for every Packet, in wire order, whether or not a Scenario is reading. Per
    the 26.3 client (javap):

    - login `login_finished` → `login_acknowledged`;
    - configuration `select_known_packs` → the same packs back (the vanilla client sends
      those it knows, in the server's order: for vanilla's own offer, all of them);
    - configuration `code_of_conduct` → `accept_code_of_conduct`;
    - configuration `finish_configuration` → `finish_configuration`;
    - `keep_alive` (configuration and play) → the same id back;
    - play `player_position` → `accept_teleportation` with the pose it results in;
    - play `chunk_batch_finished` → `chunk_batch_received` at `CHUNKS_PER_TICK`;
    - play `start_configuration` → `configuration_acknowledged`.

    Every other packet gets no answer.
    """

    def __init__(self) -> None:
        """Start with the player at the origin, facing yaw 0 and pitch 0."""
        self._pose = _Pose()

    async def __call__(self, connection: Connection, packet: Packet) -> None:
        """Send `packet`'s answer, if it has one, on `connection`."""
        fields = packet.fields or {}
        match packet.state, packet.name:
            case State.LOGIN, "minecraft:login_finished":
                await connection.send("minecraft:login_acknowledged")
            case State.CONFIGURATION, "minecraft:select_known_packs":
                await connection.send(
                    "minecraft:select_known_packs", known_packs=fields.get("known_packs")
                )
            case State.CONFIGURATION, "minecraft:code_of_conduct":
                await connection.send("minecraft:accept_code_of_conduct")
            case State.CONFIGURATION, "minecraft:finish_configuration":
                await connection.send("minecraft:finish_configuration")
            case State.CONFIGURATION | State.PLAY, "minecraft:keep_alive":
                await connection.send(
                    "minecraft:keep_alive", keep_alive_id=fields.get("keep_alive_id")
                )
            case State.PLAY, "minecraft:player_position":
                self._pose.teleport(fields)
                await connection.send(
                    "minecraft:accept_teleportation",
                    teleport_id=fields.get("teleport_id"),
                    x=self._pose.x,
                    y=self._pose.y,
                    z=self._pose.z,
                    yaw=self._pose.yaw,
                    pitch=self._pose.pitch,
                )
            case State.PLAY, "minecraft:chunk_batch_finished":
                await connection.send(
                    "minecraft:chunk_batch_received", chunks_per_tick=CHUNKS_PER_TICK
                )
            case State.PLAY, "minecraft:start_configuration":
                await connection.send("minecraft:configuration_acknowledged")
            case _:
                pass


class Bot:
    """One client connection driven by a Scenario.

    It speaks the Target's protocol version, and records everything it sends and
    receives to its Transcript under its name. Every operation, connecting included,
    is bounded by `timeout_s` seconds, and raises TimeoutError past it.

    Attributes:
        name: The Bot's name, as its Events record it.
    """

    def __init__(
        self,
        connection: Connection,
        endpoint: Endpoint,
        target: Target,
        *,
        name: str,
        timeout_s: float,
    ) -> None:
        """Drive an open Connection to `endpoint`. Use `connect` to make one."""
        self.name = name
        self._connection = connection
        self._endpoint = endpoint
        self._target = target
        self._timeout_s = timeout_s

    @classmethod
    async def connect(
        cls,
        endpoint: Endpoint,
        target: Target,
        *,
        name: str,
        transcript: Transcript,
        timeout_s: float,
    ) -> Self:
        """Open a Connection to `endpoint` for a Bot called `name`, speaking `target`.

        From then on, the Bot's `Replies` answer each packet as it arrives.

        Raises:
            OSError: The connection failed, e.g. ConnectionRefusedError.
            TimeoutError: It did not connect within `timeout_s`.
        """
        codec = Codec.for_target(target)
        async with asyncio.timeout(timeout_s):
            connection = await Connection.open(
                endpoint, codec, bot=name, transcript=transcript, answer=Replies()
            )
        return cls(connection, endpoint, target, name=name, timeout_s=timeout_s)

    async def status(self) -> Mapping[str, object]:
        """Ask for the server's status, and return the parsed status JSON.

        Sends the status handshake first, unless this Bot already has.

        Raises:
            ProtocolError: The answer is not a `status_response` holding a JSON object.
            TimeoutError: There was no answer within `timeout_s`.
        """
        async with asyncio.timeout(self._timeout_s):
            await self._handshake_for_status()
            await self._connection.send("minecraft:status_request")
            packet = await self._connection.recv(timeout_s=self._timeout_s)
        _expect(packet, "minecraft:status_response")
        return _json_object(packet, (packet.fields or {}).get("json_response"))

    async def ping(self, payload: int) -> None:
        """Ping the server with `payload`, a Long, and check the pong echoes it.

        Sends the status handshake first, unless this Bot already has.

        Raises:
            ProtocolError: The answer is not a `pong_response` echoing `payload`.
            TimeoutError: There was no answer within `timeout_s`.
        """
        async with asyncio.timeout(self._timeout_s):
            await self._handshake_for_status()
            await self._connection.send("minecraft:ping_request", timestamp=payload)
            packet = await self._connection.recv(timeout_s=self._timeout_s)
        _expect(packet, "minecraft:pong_response")
        echoed = (packet.fields or {}).get("timestamp")
        if echoed != payload:
            msg = f"pong_response echoed {echoed!r}, not the ping payload {payload!r}"
            raise ProtocolError(msg)

    async def join(self) -> None:
        """Join the server offline, and return once play's first chunk batch has finished.

        Sends the login handshake (intent 2) and a `hello` with the Bot's name and its
        `offline_uuid`, then takes each packet until play's first `chunk_batch_finished`.
        On the way, the Bot's Replies answer as the vanilla client does: they ack login
        and configuration, echo the known packs and any keep-alive, accept a code of
        conduct, confirm the join teleport, and acknowledge the chunk batch.

        Raises:
            ProtocolError: The Connection is not fresh (a handshake was sent), or the server
                asked for encryption (online mode) or disconnected the Bot.
            TimeoutError: The first chunk batch had not finished within `timeout_s`.
        """
        if self._connection.state is not State.HANDSHAKE:
            msg = f"join needs a fresh Connection, not one in {self._connection.state}"
            raise ProtocolError(msg)
        async with asyncio.timeout(self._timeout_s):
            await self._handshake(_LOGIN_INTENT)
            await self._connection.send(
                "minecraft:hello", name=self.name, player_uuid=offline_uuid(self.name)
            )
            await self.expect("minecraft:chunk_batch_finished", timeout_s=self._timeout_s)

    async def expect(
        self, name: str, *, timeout_s: float, where: Callable[[Packet], bool] | None = None
    ) -> Packet:
        """Take packets until one is called `name` and `where` holds for it; return it.

        Every packet taken is recorded, the ones before it included, and the Bot's
        Replies have already answered each of them.

        Raises:
            ProtocolError: The server disconnected the Bot, or asked for encryption,
                before such a packet arrived.
            TimeoutError: None arrived within `timeout_s`.
        """
        async with asyncio.timeout(timeout_s):
            while True:
                packet = await self._connection.recv(timeout_s=timeout_s)
                if packet.name == name and (where is None or where(packet)):
                    return packet
                self._refuse(packet)

    async def close(self) -> None:
        """Close the Bot's Connection. Calling it again does nothing."""
        await self._connection.close()

    async def _handshake_for_status(self) -> None:
        if self._connection.state is State.HANDSHAKE:
            await self._handshake(_STATUS_INTENT)

    async def _handshake(self, intent: int) -> None:
        await self._connection.send(
            "minecraft:intention",
            protocol_version=self._target.protocol_version,
            server_address=self._endpoint.host,
            server_port=self._endpoint.port,
            intent=intent,
        )

    def _refuse(self, packet: Packet) -> None:
        """Raise ProtocolError if `packet` ends the Bot's session: a disconnect, or encryption."""
        match packet.state, packet.name:
            case State.LOGIN, "minecraft:login_disconnect":
                reason: object = packet.payload
            case State.CONFIGURATION | State.PLAY, "minecraft:disconnect":
                reason = (packet.fields or {}).get("reason")
            case State.LOGIN, "minecraft:hello":
                msg = f"the server asks for encryption (online mode), and {self.name} is offline"
                raise ProtocolError(msg)
            case _:
                return
        msg = f"the server disconnected {self.name} in {packet.state}: {reason!r}"
        raise ProtocolError(msg)


def status_probe(
    target: Target, *, timeout_s: float = PROBE_TIMEOUT_S
) -> Callable[[Endpoint], Awaitable[bool]]:
    """Return a readiness probe for an Instance of `target`, for `runner.running`.

    Each call makes one short status exchange with the Endpoint. It returns True if
    the server answers with the Target's protocol version. It returns False if the
    Instance is not ready yet: the connection is refused, reset or closed, or there is
    no answer within `timeout_s` seconds. Anything else raises, because a server that
    answers wrongly is the wrong server, not a server still starting.

    The probe raises:
        ProtocolError: The status names another protocol version, or none.
        CodecError: The answer cannot be decoded.
    """

    async def probe(endpoint: Endpoint) -> bool:
        transcript = Transcript(scenario_id="readiness", server="")  # discarded
        try:
            bot = await Bot.connect(
                endpoint, target, name="probe", transcript=transcript, timeout_s=timeout_s
            )
        except (ConnectionError, TimeoutError):
            return False
        try:
            status = await bot.status()
        except (ConnectionError, TimeoutError):
            return False
        finally:
            await bot.close()
        version = _json_field(status, "version")
        protocol = _json_field(version, "protocol")
        if isinstance(protocol, bool) or not isinstance(protocol, int):
            msg = f"status has no integer version.protocol: {status!r}"
            raise ProtocolError(msg)
        if protocol != target.protocol_version:
            msg = (
                f"the server at {endpoint.host}:{endpoint.port} speaks protocol {protocol} "
                f"({_json_field(version, 'name')!r}), not the Target's {target.protocol_version}"
            )
            raise ProtocolError(msg)
        return True

    return probe


def _field[T](fields: Mapping[str, object], name: str, kind: type[T]) -> T:
    """`fields[name]`, which the packet's schema guarantees is a `kind`."""
    value = fields.get(name)
    if not isinstance(value, kind):
        msg = f"expected a {kind.__name__} {name}, got {value!r}"
        raise ProtocolError(msg)
    return value


def _json_field(value: object, key: str) -> object:
    """Return `value[key]` if `value` is a JSON object holding `key`, else None."""
    if not isinstance(value, Mapping):
        return None
    return {str(name): item for name, item in value.items()}.get(key)


def _expect(packet: Packet, name: str) -> None:
    if packet.name != name:
        msg = f"expected {name}, got {packet.name}"
        raise ProtocolError(msg)


def _json_object(packet: Packet, text: object) -> dict[str, object]:
    where = f"{packet.name.removeprefix('minecraft:')} json_response"
    if not isinstance(text, str):
        msg = f"{where} is not a string"
        raise ProtocolError(msg)
    try:
        value: object = json.loads(text)
    except json.JSONDecodeError as exc:
        msg = f"{where} is not JSON: {exc}"
        raise ProtocolError(msg) from exc
    if not isinstance(value, dict):
        msg = f"{where} is not a JSON object"
        raise ProtocolError(msg)
    return {str(key): item for key, item in value.items()}
