"""Bots: the client connections Scenarios drive."""

import asyncio
import json
from collections.abc import Mapping
from typing import Self

from mscts.codec.packets import Codec, Packet, State
from mscts.net import Connection, Endpoint, ProtocolError
from mscts.target import Target
from mscts.transcript import Transcript


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

        Raises:
            OSError: The connection failed, e.g. ConnectionRefusedError.
            TimeoutError: It did not connect within `timeout_s`.
        """
        codec = Codec.for_target(target)
        async with asyncio.timeout(timeout_s):
            connection = await Connection.open(endpoint, codec, bot=name, transcript=transcript)
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

    async def close(self) -> None:
        """Close the Bot's Connection. Calling it again does nothing."""
        await self._connection.close()

    async def _handshake_for_status(self) -> None:
        if self._connection.state is State.HANDSHAKE:
            await self._connection.send(
                "minecraft:intention",
                protocol_version=self._target.protocol_version,
                server_address=self._endpoint.host,
                server_port=self._endpoint.port,
                intent=1,
            )


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
