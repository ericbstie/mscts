"""The status readiness probe, against a fake localhost server using the Target's Codec."""

import asyncio
import gc
import json
import socket

import pytest

from mscts.bot import status_probe
from mscts.codec.packets import Codec, CodecError, Direction, State
from mscts.net import Endpoint, ProtocolError
from mscts.target import TARGET
from tests.net.fakes import (
    HANDLER_TIMEOUT_S,
    HOST,
    VANILLA_STATUS,
    Handler,
    Peer,
    free_port,
    serve,
    status_server,
)


def probe_with(codec: Codec, handler: Handler, *, timeout_s: float = 1.0) -> bool:
    async def client() -> bool:
        async with serve(codec, handler) as endpoint:
            return await status_probe(TARGET, timeout_s=timeout_s)(endpoint)

    return asyncio.run(client())


def test_the_probe_is_true_when_the_server_answers_with_the_target_protocol(
    codec: Codec,
) -> None:
    assert probe_with(codec, status_server(json.dumps(VANILLA_STATUS), [])) is True


def test_the_probe_is_false_when_nothing_listens() -> None:
    async def client() -> bool:
        return await status_probe(TARGET, timeout_s=1.0)(Endpoint(host=HOST, port=free_port()))

    assert asyncio.run(client()) is False


def test_the_probe_is_false_when_the_server_closes_without_answering(codec: Codec) -> None:
    async def server(peer: Peer) -> None:
        await peer.recv()

    assert probe_with(codec, server) is False


def test_the_probe_is_false_when_the_server_resets_the_connection(codec: Codec) -> None:
    async def server(peer: Peer) -> None:
        await peer.recv()
        await peer.reset()

    assert probe_with(codec, server) is False


def test_the_probe_is_false_soon_when_the_server_does_not_answer(codec: Codec) -> None:
    # Only the wait for the answer is timed. On a loaded host the connect can take
    # longer, and the probe may even give up while connecting, which is also False.
    asked_at: list[float] = []

    async def server(peer: Peer) -> None:
        asked_at.extend(
            [
                asyncio.get_running_loop().time()
                async for packet in peer.packets()
                if packet.name == "minecraft:status_request"
            ]
        )

    async def client() -> tuple[bool, float]:
        async with serve(codec, server) as endpoint:
            ready = await status_probe(TARGET, timeout_s=0.05)(endpoint)
            return ready, asyncio.get_running_loop().time()

    ready, returned_at = asyncio.run(client())
    assert ready is False
    assert [returned_at - at < 0.5 for at in asked_at] in ([], [True])


@pytest.mark.parametrize("turns", range(6), ids=[f"turns-{turns}" for turns in range(6)])
def test_the_fake_server_ends_when_a_client_gave_up_while_connecting(
    codec: Codec, turns: int
) -> None:
    # A probe whose connect bound expires can leave `serve` after the kernel accepted its
    # connection but before the fake did. `turns` loop iterations in, the fake is at some
    # step of accepting it (3 was the hang: accepted, handed over after the body left).
    async def server(peer: Peer) -> None:
        await peer.eof()

    async def client() -> None:
        async with asyncio.timeout(1), serve(codec, server) as endpoint:
            with socket.create_connection((endpoint.host, endpoint.port)):
                for _ in range(turns):
                    await asyncio.sleep(0)

    asyncio.run(client())
    gc.collect()  # a leaked socket warns here, in this test, not in a later one


def test_the_probe_closes_its_connection(codec: Codec) -> None:
    closed: list[bool] = []

    async def server(peer: Peer) -> None:
        await peer.recv()
        await peer.recv()
        await peer.send("minecraft:status_response", json_response=json.dumps(VANILLA_STATUS))
        await peer.eof()
        closed.append(True)

    assert probe_with(codec, server) is True
    assert closed == [True]


def test_a_cancelled_probe_closes_its_connection(codec: Codec) -> None:
    # The runner cancels a probe that is still waiting when it gives up.
    closed: list[bool] = []
    asked = asyncio.Event()  # the probe has sent both packets and is waiting for the answer

    async def server(peer: Peer) -> None:
        await peer.recv()
        await peer.recv()
        asked.set()
        await peer.eof()
        closed.append(True)

    async def client() -> None:
        async with serve(codec, server) as endpoint:

            async def run_probe() -> bool:
                return await status_probe(TARGET, timeout_s=HANDLER_TIMEOUT_S)(endpoint)

            probe = asyncio.create_task(run_probe())
            async with asyncio.timeout(HANDLER_TIMEOUT_S):
                await asked.wait()
            probe.cancel()
            with pytest.raises(asyncio.CancelledError):
                await probe

    asyncio.run(client())
    assert closed == [True]


def test_the_probe_raises_for_a_server_of_another_protocol(codec: Codec) -> None:
    other = {**VANILLA_STATUS, "version": {"name": "1.21.10", "protocol": 773}}
    with pytest.raises(
        ProtocolError, match=r"speaks protocol 773 \('1.21.10'\), not the Target's 777"
    ):
        probe_with(codec, status_server(json.dumps(other), []))


@pytest.mark.parametrize(
    "status",
    [
        {"description": "mscts"},
        {"version": "26.3"},
        {"version": {"name": "26.3"}},
        {"version": {"name": "26.3", "protocol": "777"}},
        {"version": {"name": "26.3", "protocol": True}},
    ],
)
def test_the_probe_raises_for_a_status_without_an_integer_protocol(
    codec: Codec, status: dict[str, object]
) -> None:
    with pytest.raises(ProtocolError, match=r"status has no integer version\.protocol"):
        probe_with(codec, status_server(json.dumps(status), []))


def test_the_probe_raises_for_an_answer_it_cannot_decode(codec: Codec) -> None:
    async def server(peer: Peer) -> None:
        await peer.recv()
        await peer.recv()
        data = codec.encode(
            State.STATUS,
            Direction.CLIENTBOUND,
            "minecraft:status_response",
            {"json_response": "{}"},
        )
        await peer.write(bytes([len(data) + 1]) + data + b"\x00")
        await peer.eof()

    with pytest.raises(CodecError, match="unconsumed"):
        probe_with(codec, server)
