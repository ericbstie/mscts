"""Bot.join against a live vanilla 26.3, sharing the session's one Reference.

Pins the login, configuration and play-entry layouts against the real Reference: every
packet the Codec has a schema for decodes with fields from the real bytes, the Bot's
own answers are the ones vanilla accepts, and a joined Bot is not kicked. Each test
joins with a Bot of its own name, so the player a join leaves in the world is never
another test's. Vanilla's spawn position is random per fresh world, so no test looks
at it (ADR-0006).

The join test logs how long each step took (`--log-cli-level=INFO` shows it).
"""

import logging
from collections.abc import Mapping

import pytest

from mscts.bot import Bot, offline_uuid
from mscts.codec.packets import Direction, Packet, State
from mscts.codec.schema import Schema
from mscts.codec.schemas import configuration, handshake, login, play
from mscts.runner import Instance
from mscts.target import TARGET
from mscts.transcript import Event, Transcript

pytestmark = [pytest.mark.reference, pytest.mark.asyncio(loop_scope="session")]

_TIMEOUT_S = 10.0
_KEEP_ALIVE_TIMEOUT_S = 20.0
"""Vanilla sends a keep-alive every 15 s (docs/research/2026-09-26-join.md), plus headroom."""

_NS_PER_S, _NS_PER_MS = 1_000_000_000, 1_000_000

_SCHEMAS: Mapping[tuple[State, Direction], Mapping[str, Schema]] = {
    (State.HANDSHAKE, Direction.SERVERBOUND): handshake.SERVERBOUND,
    (State.LOGIN, Direction.SERVERBOUND): login.SERVERBOUND,
    (State.LOGIN, Direction.CLIENTBOUND): login.CLIENTBOUND,
    (State.CONFIGURATION, Direction.SERVERBOUND): configuration.SERVERBOUND,
    (State.CONFIGURATION, Direction.CLIENTBOUND): configuration.CLIENTBOUND,
    (State.PLAY, Direction.SERVERBOUND): play.SERVERBOUND,
    (State.PLAY, Direction.CLIENTBOUND): play.CLIENTBOUND,
}

_log = logging.getLogger(__name__)


def _has_schema(packet: Packet) -> bool:
    return packet.name in _SCHEMAS.get((packet.state, packet.direction), {})


def _taken(transcript: Transcript) -> list[Event]:
    return [e for e in transcript.events if e.packet.direction is Direction.CLIENTBOUND]


def _first_taken(transcript: Transcript, state: State, name: str) -> Event:
    return next(e for e in _taken(transcript) if (e.packet.state, e.packet.name) == (state, name))


async def _joined(reference: Instance, transcript: Transcript, *, name: str) -> Bot:
    bot = await Bot.connect(
        reference.endpoint, TARGET, name=name, transcript=transcript, timeout_s=_TIMEOUT_S
    )
    try:
        await bot.join()
    except BaseException:
        await bot.close()
        raise
    return bot


async def test_join_reaches_play_and_the_first_chunk_batch(reference: Instance) -> None:
    transcript = Transcript(scenario_id="reference/join", server="vanilla")
    connecting_ns = transcript.now_ns()
    bot = await _joined(reference, transcript, name="join_basic")
    await bot.close()
    login_finished = _first_taken(transcript, State.LOGIN, "minecraft:login_finished")
    play_login = _first_taken(transcript, State.PLAY, "minecraft:login")
    chunk_batch = _taken(transcript)[-1]
    assert (chunk_batch.packet.state, chunk_batch.packet.name) == (
        State.PLAY,
        "minecraft:chunk_batch_finished",
    )
    # Offline, vanilla gives the player its name's offline UUID, and no properties.
    assert (login_finished.packet.fields or {}).get("profile") == {
        "uuid": offline_uuid("join_basic"),
        "username": "join_basic",
        "properties": [],
    }
    assert connecting_ns < login_finished.t_ns < play_login.t_ns < chunk_batch.t_ns
    _log.info(
        "join from connecting: login_finished %.1f ms, play login %.1f ms, "
        "first chunk batch finished %.1f ms",
        *(
            (event.t_ns - connecting_ns) / _NS_PER_MS
            for event in (login_finished, play_login, chunk_batch)
        ),
    )


async def test_every_join_packet_decodes_strictly_with_fields_where_a_schema_exists(
    reference: Instance,
) -> None:
    transcript = Transcript(scenario_id="reference/join-strict-decode", server="vanilla")
    bot = await _joined(reference, transcript, name="join_strict")
    await bot.close()
    packets = [event.packet for event in transcript.events]
    assert [p.decode_error for p in packets if p.decode_error is not None] == []
    assert [p.name for p in packets if _has_schema(p) and p.fields is None] == []
    # Through configuration, the Bot sends exactly what the vanilla client sends, and
    # every packet, either way, has a schema.
    through_configuration = [p for p in packets if p.state is not State.PLAY]
    assert [p.name for p in through_configuration if p.direction is Direction.SERVERBOUND] == [
        "minecraft:intention",
        "minecraft:hello",
        "minecraft:login_acknowledged",
        "minecraft:select_known_packs",
        "minecraft:finish_configuration",
    ]
    assert [p.name for p in through_configuration if not _has_schema(p)] == []


async def test_a_joined_bot_stays_connected_through_a_keep_alive_cycle(
    reference: Instance,
) -> None:
    transcript = Transcript(scenario_id="reference/join-keep-alive", server="vanilla")
    bot = await _joined(reference, transcript, name="join_keep_alive")
    try:
        first = await bot.expect("minecraft:keep_alive", timeout_s=_KEEP_ALIVE_TIMEOUT_S)
        second = await bot.expect("minecraft:keep_alive", timeout_s=_KEEP_ALIVE_TIMEOUT_S)
    finally:
        await bot.close()
    # Vanilla disconnects at once for a keep-alive echoing the wrong id, and 15 s later if
    # none came: so a second keep-alive means it accepted the Bot's echo of the first.
    echoes = [
        event.packet.fields
        for event in transcript.events
        if event.packet.direction is Direction.SERVERBOUND
        and (event.packet.state, event.packet.name) == (State.PLAY, "minecraft:keep_alive")
    ]
    assert echoes[0] == first.fields
    assert second.fields != first.fields
    play_login = _first_taken(transcript, State.PLAY, "minecraft:login")
    [second_event] = [event for event in _taken(transcript) if event.packet is second]
    assert second_event.t_ns - play_login.t_ns >= 20 * _NS_PER_S
