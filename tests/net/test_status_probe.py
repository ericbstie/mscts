"""The status readiness probe, against a fake localhost server using the Target's Codec."""

import asyncio
import json

import pytest

from mscts.bot import status_probe
from mscts.codec.packets import Codec, CodecError, Direction, State
from mscts.net import Endpoint, ProtocolError
from mscts.target import TARGET
from tests.net.fakes import HOST, VANILLA_STATUS, Handler, Peer, free_port, serve, status_server


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
    async def server(peer: Peer) -> None:
        await peer.recv()
        await peer.recv()
        await peer.eof()

    async def client() -> tuple[bool, float]:
        loop = asyncio.get_running_loop()
        async with serve(codec, server) as endpoint:
            start = loop.time()
            ready = await status_probe(TARGET, timeout_s=0.05)(endpoint)
            return ready, loop.time() - start

    ready, elapsed = asyncio.run(client())
    assert ready is False
    assert elapsed < 0.5


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

    async def server(peer: Peer) -> None:
        await peer.recv()
        await peer.recv()
        await peer.eof()
        closed.append(True)

    async def client() -> None:
        async with serve(codec, server) as endpoint:

            async def run_probe() -> bool:
                return await status_probe(TARGET, timeout_s=1.0)(endpoint)

            probe = asyncio.create_task(run_probe())
            await asyncio.sleep(0.05)
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
