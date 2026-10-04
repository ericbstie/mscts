"""The chunks a Bot holds: those its server sent and has not told it to forget.

As the 26.3 client keeps them in its `ClientLevel` (javap, `ClientPacketListener`): a chunk
arrives with `level_chunk_with_light`, goes with `forget_level_chunk`, and a new level (a play
login, or a respawn into another dimension) starts with none.
"""

from collections.abc import Mapping, Sequence

import pytest

from mscts.bot import Bot
from mscts.transcript import Transcript
from tests.net.fakes import (
    EMPTY_CHUNK,
    Handler,
    JoinScript,
    Peer,
    answer_each_tick,
    join_server,
    with_bot,
)
from tests.net.test_bot_move import CODEC, LOGIN, RESPAWN

type Sent = tuple[str, Mapping[str, object]]


def chunk(x: int, z: int) -> Sent:
    return ("minecraft:level_chunk_with_light", EMPTY_CHUNK | {"chunk_x": x, "chunk_z": z})


def forget(x: int, z: int) -> Sent:
    return ("minecraft:forget_level_chunk", {"chunk_x": x, "chunk_z": z})


def chunk_server(packets: Sequence[Sent]) -> Handler:
    """Join like vanilla, then send `packets` after the Bot's first tick, and answer `sync`.

    The join's first batch holds chunk (0, 0).
    """

    async def then(peer: Peer) -> None:
        requests, sent = 0, False
        async for packet in peer.packets():
            if packet.name == "minecraft:client_command":
                requests += 1
                await answer_each_tick(peer, requests)
            elif not sent and packet.name == "minecraft:client_tick_end":
                sent = True
                for name, fields in packets:
                    await peer.send(name, **fields)

    return join_server([], JoinScript(then=then))


def held(*packets: Sent) -> tuple[frozenset[tuple[int, int]], frozenset[tuple[int, int]]]:
    """What a Bot's `chunks` holds once joined, and once `packets` came after its first tick."""

    async def use(bot: Bot) -> tuple[frozenset[tuple[int, int]], frozenset[tuple[int, int]]]:
        await bot.join()
        joined = bot.chunks
        await bot.tick()
        await bot.sync()
        return joined, bot.chunks

    transcript = Transcript(group_id="test/chunks", server="fake")
    result, _ = with_bot(CODEC, transcript, chunk_server(packets), use)
    return result


def test_a_bot_holds_the_chunks_of_the_joins_first_batch() -> None:
    joined, _ = held()

    assert joined == {(0, 0)}


def test_a_bot_holds_each_chunk_sent_until_it_is_told_to_forget_it() -> None:
    _, after = held(chunk(1, 0), chunk(-2, 3), forget(0, 0), forget(5, 5))

    assert after == {(1, 0), (-2, 3)}


def test_the_chunks_a_bot_holds_are_a_copy() -> None:
    joined, after = held(chunk(1, 0))

    assert (joined, after) == ({(0, 0)}, {(0, 0), (1, 0)})


@pytest.mark.parametrize(
    ("fresh", "kept"),
    [
        (("minecraft:login", LOGIN), {(1, 0)}),
        (
            (
                "minecraft:respawn",
                {**RESPAWN, "dimension_name": "minecraft:the_end", "data_kept": 0},
            ),
            {(1, 0)},
        ),
        (("minecraft:respawn", {**RESPAWN, "data_kept": 0}), {(2, 2), (1, 0)}),
    ],
    ids=["login", "respawn-elsewhere", "respawn-here"],
)
def test_a_new_level_starts_with_no_chunks(fresh: Sent, kept: set[tuple[int, int]]) -> None:
    # The chunks belong to the ClientLevel: a new one comes with each play login, and with a
    # respawn into another dimension (ClientPacketListener.handleLogin, handleRespawn).
    _, after = held(("minecraft:login", LOGIN), chunk(2, 2), fresh, chunk(1, 0))

    assert after == kept
