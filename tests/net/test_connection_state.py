"""The Connection's State machine, over a fake localhost server using the Target's Codec."""

import asyncio
import uuid

import pytest

from mscts.codec.packets import Codec, Direction, Packet, State, UnknownPacketError
from mscts.net import Connection, Endpoint, ProtocolError
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


PLAYER = uuid.UUID("b50ad385-829d-3141-a216-7e7d7539ba7f")
LOGIN_FINISHED = {
    "profile": {"uuid": PLAYER, "username": "Notch", "properties": []},
    "session_id": PLAYER,
}


async def log_in(connection: Connection, endpoint: Endpoint) -> None:
    await connection.send("minecraft:intention", **intention(endpoint, 2))
    await connection.send("minecraft:hello", name="Notch", player_uuid=PLAYER)


def test_sending_the_acks_moves_what_is_sent_on(codec: Codec, transcript: Transcript) -> None:
    states: list[State] = []

    async def server(peer: Peer) -> None:
        await peer.recv()
        peer.state = State.LOGIN
        await peer.recv()
        peer.state = State.CONFIGURATION
        await peer.recv()
        peer.state = State.PLAY
        await peer.recv()
        await peer.eof()

    async def client() -> None:
        async with (
            serve(codec, server) as endpoint,
            connected(endpoint, codec, transcript) as connection,
        ):
            await connection.send("minecraft:intention", **intention(endpoint, 2))
            states.append(connection.state)
            await connection.send("minecraft:login_acknowledged")
            states.append(connection.state)
            await connection.send("minecraft:finish_configuration")
            states.append(connection.state)
            await connection.send("minecraft:configuration_acknowledged")
            states.append(connection.state)

    asyncio.run(client())
    assert states == [State.LOGIN, State.CONFIGURATION, State.PLAY, State.CONFIGURATION]
    assert [(event.packet.state, event.packet.name) for event in transcript.events] == [
        (State.HANDSHAKE, "minecraft:intention"),
        (State.LOGIN, "minecraft:login_acknowledged"),
        (State.CONFIGURATION, "minecraft:finish_configuration"),
        (State.PLAY, "minecraft:configuration_acknowledged"),
    ]


# Audit L8. The vanilla client (26.3, javap) switches what it *receives* as it handles the
# terminal packet (login_finished, finish_configuration, start_configuration: their
# isTerminal() is true), and what it *sends* only after sending the ack. So a frame right
# behind login_finished is already configuration, even before the Bot acks.


def test_login_finished_moves_what_arrives_after_it_to_configuration(
    codec: Codec, transcript: Transcript
) -> None:
    async def server(peer: Peer) -> None:
        await peer.recv()
        await peer.recv()
        first = peer.frame("minecraft:login_finished", **LOGIN_FINISHED)
        peer.state = State.CONFIGURATION
        await peer.write(first + peer.frame("minecraft:keep_alive", keep_alive_id=7))
        await peer.eof()

    async def client() -> list[tuple[State, str, State]]:
        async with (
            serve(codec, server) as endpoint,
            connected(endpoint, codec, transcript) as connection,
        ):
            await log_in(connection, endpoint)
            taken = []
            for _ in range(2):
                packet = await connection.recv(timeout_s=1)
                taken.append((packet.state, packet.name, connection.state))
            return taken

    assert asyncio.run(client()) == [
        (State.LOGIN, "minecraft:login_finished", State.LOGIN),
        (State.CONFIGURATION, "minecraft:keep_alive", State.LOGIN),  # not acked yet
    ]


def test_finish_configuration_moves_what_arrives_after_it_to_play(
    codec: Codec, transcript: Transcript
) -> None:
    async def server(peer: Peer) -> None:
        await peer.recv()
        await peer.recv()
        await peer.send("minecraft:login_finished", **LOGIN_FINISHED)
        await peer.recv()
        peer.state = State.CONFIGURATION
        first = peer.frame("minecraft:finish_configuration")
        peer.state = State.PLAY
        await peer.write(first + peer.raw_frame("minecraft:keep_alive", bytes(8)))
        await peer.eof()

    async def client() -> list[tuple[State, str]]:
        async with (
            serve(codec, server) as endpoint,
            connected(endpoint, codec, transcript) as connection,
        ):
            await log_in(connection, endpoint)
            await connection.recv(timeout_s=1)
            await connection.send("minecraft:login_acknowledged")
            return [
                ((packet := await connection.recv(timeout_s=1)).state, packet.name)
                for _ in range(2)
            ]

    assert asyncio.run(client()) == [
        (State.CONFIGURATION, "minecraft:finish_configuration"),
        (State.PLAY, "minecraft:keep_alive"),
    ]


def test_start_configuration_moves_what_arrives_after_it_back_to_configuration(
    codec: Codec, transcript: Transcript
) -> None:
    async def server(peer: Peer) -> None:
        await peer.recv()
        await peer.recv()
        await peer.send("minecraft:login_finished", **LOGIN_FINISHED)
        await peer.recv()
        peer.state = State.CONFIGURATION
        await peer.send("minecraft:finish_configuration")
        await peer.recv()
        peer.state = State.PLAY
        first = peer.frame("minecraft:start_configuration")
        peer.state = State.CONFIGURATION
        await peer.write(first + peer.frame("minecraft:keep_alive", keep_alive_id=1))
        await peer.eof()

    async def client() -> list[tuple[State, str]]:
        async with (
            serve(codec, server) as endpoint,
            connected(endpoint, codec, transcript) as connection,
        ):
            await log_in(connection, endpoint)
            await connection.recv(timeout_s=1)
            await connection.send("minecraft:login_acknowledged")
            await connection.recv(timeout_s=1)
            await connection.send("minecraft:finish_configuration")
            return [
                ((packet := await connection.recv(timeout_s=1)).state, packet.name)
                for _ in range(2)
            ]

    assert asyncio.run(client()) == [
        (State.PLAY, "minecraft:start_configuration"),
        (State.CONFIGURATION, "minecraft:keep_alive"),
    ]


# login_compression applies from the very next frame, both ways (vanilla's client handles
# it on the network thread before splitting the next frame, and compresses what it sends).


@pytest.mark.parametrize("threshold", [0, 64])
def test_login_compression_applies_from_the_next_frame_both_ways(
    codec: Codec, transcript: Transcript, threshold: int
) -> None:
    received: list[Packet] = []

    async def server(peer: Peer) -> None:
        await peer.recv()
        await peer.recv()
        first = peer.frame("minecraft:login_compression", threshold=threshold)
        peer.compress(threshold)
        await peer.write(first + peer.frame("minecraft:login_finished", **LOGIN_FINISHED))
        received.append(await peer.recv())
        await peer.eof()

    async def client() -> None:
        async with (
            serve(codec, server) as endpoint,
            connected(endpoint, codec, transcript) as connection,
        ):
            await log_in(connection, endpoint)
            assert (await connection.recv(timeout_s=1)).fields == {"threshold": threshold}
            assert (await connection.recv(timeout_s=1)).fields == LOGIN_FINISHED
            await connection.send("minecraft:login_acknowledged")

    asyncio.run(client())
    assert [packet.name for packet in received] == ["minecraft:login_acknowledged"]


def test_a_negative_login_compression_threshold_leaves_frames_uncompressed(
    codec: Codec, transcript: Transcript
) -> None:
    # Audit MD5, end to end: a Candidate may send -1 to mean "off", as vanilla's reads it.
    received: list[Packet] = []

    async def server(peer: Peer) -> None:
        await peer.recv()
        await peer.recv()
        await peer.send("minecraft:login_compression", threshold=-1)
        await peer.send("minecraft:login_finished", **LOGIN_FINISHED)
        received.append(await peer.recv())
        await peer.eof()

    async def client() -> None:
        async with (
            serve(codec, server) as endpoint,
            connected(endpoint, codec, transcript) as connection,
        ):
            await log_in(connection, endpoint)
            await connection.recv(timeout_s=1)
            assert (await connection.recv(timeout_s=1)).fields == LOGIN_FINISHED
            await connection.send("minecraft:login_acknowledged")

    asyncio.run(client())
    assert [packet.name for packet in received] == ["minecraft:login_acknowledged"]


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
