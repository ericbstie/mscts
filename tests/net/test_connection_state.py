"""The Connection's State machine, over a fake localhost server using the Target's Codec."""

import asyncio

import pytest

from mscts.codec.packets import Codec, Direction, Packet, State, UnknownPacketError
from mscts.codec.schema import Schema
from mscts.codec.schemas import handshake
from mscts.net import Endpoint, ProtocolError
from mscts.target import TARGET
from mscts.transcript import Transcript
from tests.net.fakes import Peer, connected, serve


def intention(endpoint: Endpoint, intent: int) -> dict[str, object]:
    return {
        "protocol_version": TARGET.protocol_version,
        "server_address": endpoint.host,
        "server_port": endpoint.port,
        "intent": intent,
    }


def test_a_connection_starts_in_the_handshake_state(codec: Codec, transcript: Transcript) -> None:
    async def server(peer: Peer) -> None:
        await peer.eof()

    async def client() -> State:
        async with (
            serve(codec, server) as endpoint,
            connected(endpoint, codec, transcript) as connection,
        ):
            return connection.state

    assert asyncio.run(client()) is State.HANDSHAKE


@pytest.mark.parametrize(
    ("intent", "state"), [(1, State.STATUS), (2, State.LOGIN), (3, State.LOGIN)]
)
def test_intention_moves_to_the_state_its_intent_names(
    codec: Codec, transcript: Transcript, intent: int, state: State
) -> None:
    server_states: list[State] = []

    async def server(peer: Peer) -> None:
        await peer.recv()
        server_states.append(peer.state)
        await peer.eof()

    async def client() -> State:
        async with (
            serve(codec, server) as endpoint,
            connected(endpoint, codec, transcript) as connection,
        ):
            await connection.send("minecraft:intention", **intention(endpoint, intent))
            return connection.state

    assert asyncio.run(client()) is state
    assert server_states == [state]
    [event] = transcript.events
    assert (event.packet.state, event.packet.name) == (State.HANDSHAKE, "minecraft:intention")


def test_after_a_status_intention_both_directions_speak_the_status_state(
    codec: Codec, transcript: Transcript
) -> None:
    received: list[Packet] = []

    async def server(peer: Peer) -> None:
        await peer.recv()
        received.append(await peer.recv())
        await peer.send("minecraft:status_response", json_response="{}")
        await peer.eof()

    async def client() -> None:
        async with (
            serve(codec, server) as endpoint,
            connected(endpoint, codec, transcript) as connection,
        ):
            await connection.send("minecraft:intention", **intention(endpoint, 1))
            await connection.send("minecraft:status_request")
            await connection.recv(timeout_s=1)

    asyncio.run(client())
    assert [(packet.state, packet.name) for packet in received] == [
        (State.STATUS, "minecraft:status_request")
    ]
    assert [
        (event.packet.state, event.packet.direction, event.packet.name)
        for event in transcript.events
    ] == [
        (State.HANDSHAKE, Direction.SERVERBOUND, "minecraft:intention"),
        (State.STATUS, Direction.SERVERBOUND, "minecraft:status_request"),
        (State.STATUS, Direction.CLIENTBOUND, "minecraft:status_response"),
    ]


@pytest.mark.parametrize("intent", [0, 4, -1])
def test_an_unknown_intent_raises_and_neither_writes_nor_records(
    codec: Codec, transcript: Transcript, intent: int
) -> None:
    received: list[Packet] = []

    async def server(peer: Peer) -> None:
        received.append(await peer.recv())
        await peer.eof()

    async def client() -> tuple[State, Endpoint]:
        async with (
            serve(codec, server) as endpoint,
            connected(endpoint, codec, transcript) as connection,
        ):
            with pytest.raises(ProtocolError, match=f"unknown intent {intent}"):
                await connection.send("minecraft:intention", **intention(endpoint, intent))
            state = connection.state
            await connection.send("minecraft:intention", **intention(endpoint, 1))
            return state, endpoint

    state, endpoint = asyncio.run(client())
    assert state is State.HANDSHAKE
    assert [packet.fields for packet in received] == [intention(endpoint, 1)]
    assert [event.packet.fields for event in transcript.events] == [intention(endpoint, 1)]


def a_login_codec(codec: Codec) -> Codec:
    """The Target's handshake, plus field-less schemas for the two later transitions.

    The Target's Codec has no schemas for login or configuration packets yet.
    """
    ids = {
        (state, Direction.SERVERBOUND): {name: codec.packet_id(state, Direction.SERVERBOUND, name)}
        for state, name in [
            (State.HANDSHAKE, "minecraft:intention"),
            (State.LOGIN, "minecraft:login_acknowledged"),
            (State.CONFIGURATION, "minecraft:finish_configuration"),
        ]
    }
    schemas = {
        (State.HANDSHAKE, Direction.SERVERBOUND): handshake.SERVERBOUND,
        (State.LOGIN, Direction.SERVERBOUND): {"minecraft:login_acknowledged": Schema()},
        (State.CONFIGURATION, Direction.SERVERBOUND): {"minecraft:finish_configuration": Schema()},
    }
    return Codec(ids, schemas)


def test_login_acknowledged_moves_to_configuration_and_finish_configuration_to_play(
    codec: Codec, transcript: Transcript
) -> None:
    login_codec = a_login_codec(codec)
    states: list[State] = []

    async def server(peer: Peer) -> None:
        await peer.recv()
        peer.state = State.LOGIN
        await peer.recv()
        peer.state = State.CONFIGURATION
        await peer.recv()
        await peer.eof()

    async def client() -> None:
        async with (
            serve(login_codec, server) as endpoint,
            connected(endpoint, login_codec, transcript) as connection,
        ):
            await connection.send("minecraft:intention", **intention(endpoint, 2))
            states.append(connection.state)
            await connection.send("minecraft:login_acknowledged")
            states.append(connection.state)
            await connection.send("minecraft:finish_configuration")
            states.append(connection.state)

    asyncio.run(client())
    assert states == [State.LOGIN, State.CONFIGURATION, State.PLAY]
    assert [(event.packet.state, event.packet.name) for event in transcript.events] == [
        (State.HANDSHAKE, "minecraft:intention"),
        (State.LOGIN, "minecraft:login_acknowledged"),
        (State.CONFIGURATION, "minecraft:finish_configuration"),
    ]


def test_a_packet_of_a_later_state_is_refused_before_the_intention(
    codec: Codec, transcript: Transcript
) -> None:
    async def server(peer: Peer) -> None:
        await peer.eof()

    async def client() -> None:
        async with (
            serve(codec, server) as endpoint,
            connected(endpoint, codec, transcript) as connection,
        ):
            with pytest.raises(UnknownPacketError, match="handshake serverbound"):
                await connection.send("minecraft:status_request")

    asyncio.run(client())
    assert transcript.events == []
