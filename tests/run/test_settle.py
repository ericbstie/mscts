"""`until_no_player_online`: poll an Instance's status until it says no player is online (#97).

A closed Bot is removed by the server later (vanilla: on its next tick), so whatever plays
after a Group that joined Bots (a Run before the next Group, a Group after its Control Bot
left) waits first. The fakes answer each status request from a script of counts.
"""

import asyncio
import contextlib
import dataclasses
import os
import stat
from pathlib import Path
from time import perf_counter

import pytest

import mscts.settle as settle_module
from mscts.net import Endpoint
from mscts.settle import PlayersStillOnline, until_no_player_online
from tests.net.fakes import HOST, Peer, free_port
from tests.net.fakes import status_server as fixed_status
from tests.run.occupancy import Occupancy, listening, named, never_answer

DEADLINE_S = 0.3
"""The deadline the tests that wait for it give: short, so they stay fast."""


@pytest.mark.asyncio
async def test_it_returns_after_the_poll_that_finds_no_players_online() -> None:
    occupancy = Occupancy(online=(1, 1, 0))
    async with listening(occupancy.handler()) as endpoint:
        await until_no_player_online(endpoint, deadline_s=DEADLINE_S)

    assert occupancy.polls == 3


@pytest.mark.asyncio
async def test_it_waits_the_interval_between_polls(monkeypatch: pytest.MonkeyPatch) -> None:
    interval_s = 0.2
    monkeypatch.setattr(settle_module, "SETTLE_INTERVAL_S", interval_s)
    async with listening(Occupancy(online=(1, 1, 0)).handler()) as endpoint:
        begun = perf_counter()
        await until_no_player_online(endpoint, deadline_s=5.0)

    assert perf_counter() - begun >= 2 * interval_s * 0.9  # two waits between the three polls


@pytest.mark.asyncio
@pytest.mark.timeout(10)  # the deadline is what ends the wait: a hang is the failure
async def test_it_raises_what_the_last_status_said_once_the_deadline_passes() -> None:
    occupancy = Occupancy(online=(2,), sample=named("watcher", "control"))
    async with listening(occupancy.handler()) as endpoint:
        with pytest.raises(PlayersStillOnline) as raised:
            await until_no_player_online(endpoint, deadline_s=DEADLINE_S)

    left = raised.value
    assert (left.online, left.names, left.deadline_s) == (2, ("watcher", "control"), DEADLINE_S)
    assert str(left) == "2 players still online after waiting 0.3 s: watcher, control"
    assert occupancy.polls > 1, "it gave up before the deadline"


@dataclasses.dataclass(frozen=True)
class Wording:
    online: int
    sample: object
    message: str


WORDINGS = {
    "one player, none named": Wording(1, None, "1 player still online after waiting 0.3 s"),
    "only the names it can read": Wording(
        3,
        [*named("a"), 5, {"name": 7, "id": "x"}, {"id": "x"}],
        "3 players still online after waiting 0.3 s: a",
    ),
    "a sample that is no list": Wording(2, 7, "2 players still online after waiting 0.3 s"),
}


@pytest.mark.asyncio
@pytest.mark.timeout(10)
@pytest.mark.parametrize("case", WORDINGS.values(), ids=WORDINGS.keys())
async def test_the_message_says_how_many_players_and_names_those_it_can_read(
    case: Wording,
) -> None:
    async with listening(Occupancy(online=(case.online,), sample=case.sample).handler()) as at:
        with pytest.raises(PlayersStillOnline) as raised:
            await until_no_player_online(at, deadline_s=DEADLINE_S)

    assert str(raised.value) == case.message


UNREADABLE = {
    "no players": "{}",
    "players that is no object": '{"players": 5}',
    "no online count": '{"players": {"max": 20}}',
    "an online count that is text": '{"players": {"online": "2"}}',
    "an online count that is a bool": '{"players": {"online": true}}',
    "not JSON": "not json",
}


@pytest.mark.asyncio
@pytest.mark.timeout(10)
@pytest.mark.parametrize("reply", UNREADABLE.values(), ids=UNREADABLE.keys())
async def test_a_status_that_cannot_be_read_counts_as_no_player_online(reply: str) -> None:
    async with listening(fixed_status(reply, [])) as endpoint:
        await until_no_player_online(endpoint, deadline_s=DEADLINE_S)


async def garble(peer: Peer) -> None:
    """Answer a status request with a status_response that does not decode."""
    async for packet in peer.packets():
        if packet.name == "minecraft:status_request":
            await peer.write(peer.raw_frame("minecraft:status_response", b"\xff"))


@pytest.mark.asyncio
@pytest.mark.timeout(10)
async def test_a_status_that_does_not_decode_counts_as_no_player_online() -> None:
    async with listening(garble) as endpoint:
        await until_no_player_online(endpoint, deadline_s=DEADLINE_S)


@pytest.mark.asyncio
@pytest.mark.timeout(10)
async def test_a_server_that_is_not_listening_counts_as_no_player_online() -> None:
    await until_no_player_online(Endpoint(host=HOST, port=free_port()), deadline_s=DEADLINE_S)


@pytest.mark.asyncio
@pytest.mark.timeout(5)  # a poll bounds itself by the deadline: this is not a 10 s Bot timeout
async def test_a_status_that_never_answers_ends_at_the_deadline() -> None:
    async with listening(never_answer) as endpoint:
        begun = perf_counter()
        await until_no_player_online(endpoint, deadline_s=DEADLINE_S)

    assert perf_counter() - begun < 3 * DEADLINE_S


TURNS_TO_A_STATUS_WAIT = 30
"""More event loop turns than a poll takes from its start to waiting for the status answer."""


def _open_sockets() -> int:
    """How many sockets this process has open (`/dev/fd`, on Linux and macOS)."""
    return sum(1 for fd in Path("/dev/fd").iterdir() if _is_socket(int(fd.name)))


def _is_socket(fd: int) -> bool:
    """Whether `fd` is an open socket; False if it is gone (the listing's own fd)."""
    try:
        return stat.S_ISSOCK(os.fstat(fd).st_mode)
    except OSError:
        return False


async def _until_sockets_open_are(count: int, *, within_s: float) -> int:
    """Wait until this process has `count` sockets open, or `within_s` passes; return the count.

    A closed transport closes its socket on a later turn of the event loop.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + within_s
    while True:
        now = _open_sockets()
        if now == count or loop.time() >= deadline:
            return now
        await asyncio.sleep(0.001)


@pytest.mark.asyncio
@pytest.mark.timeout(30)
async def test_a_poll_cancelled_at_any_turn_of_connecting_or_asking_leaves_no_socket_open() -> None:
    """#133: a Run cancelled mid settle wait cancels a poll wherever it is.

    Cancelled after 0, 1, 2 ... turns of the event loop, the poll is cut off while it
    connects, once it has, and while it waits for a status the server never sends. Each
    time, once the server has let go of what it accepted, no socket is left open.
    """
    asked = 0  # connections that sent something: the poll got as far as asking

    async def until_the_client_closes(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        nonlocal asked
        with contextlib.suppress(ConnectionError):
            if await reader.read(1024):
                asked += 1
                while await reader.read(1024):
                    pass  # and never answer
        writer.close()

    server = await asyncio.start_server(until_the_client_closes, HOST, 0)
    endpoint = Endpoint(host=HOST, port=server.sockets[0].getsockname()[1])
    before = _open_sockets()  # the listening socket included
    leaks: list[int] = []
    try:
        for turns in range(TURNS_TO_A_STATUS_WAIT):
            poll = asyncio.create_task(until_no_player_online(endpoint, deadline_s=5.0))
            for _ in range(turns):
                await asyncio.sleep(0)
            poll.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await poll
            # A leaked client socket holds its server side open too.
            if await _until_sockets_open_are(before, within_s=1.0) != before:
                leaks.append(turns)
    finally:
        server.close()
        server.abort_clients()
        await server.wait_closed()

    assert leaks == []
    assert asked > 0, "no poll got as far as asking: TURNS_TO_A_STATUS_WAIT is too few"
