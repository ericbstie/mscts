import json
from dataclasses import dataclass, field

import pytest

from mscts.bot import Bot
from mscts.codec.packets import Codec, Packet
from mscts.compare import OBSERVE_CLOSE, OBSERVE_OPEN
from mscts.group import GROUPS, Group, GroupContext, GroupKind, resolve
from mscts.groups import status
from mscts.net import Endpoint
from mscts.target import TARGET
from mscts.transcript import Transcript
from tests.group.test_blocks import BlocksServer
from tests.group.test_control import playing
from tests.net.fakes import VANILLA_STATUS, Peer, serve, status_server


async def _play(group: Group) -> tuple[Transcript, list[Packet]]:
    codec = Codec.for_target(TARGET)
    transcript = Transcript(group_id=group.id, server="fake")
    seen: list[Packet] = []
    async with serve(codec, status_server(json.dumps(VANILLA_STATUS), seen)) as endpoint:
        context = GroupContext(endpoint, transcript, timeout_s=1.0)
        try:
            await group.run(context)
        finally:
            await context.close()
    return transcript, seen


def _names(transcript: Transcript) -> list[str]:
    return [event.packet.name for event in transcript.events]


def test_both_status_groups_are_registered_as_exact_with_no_masks() -> None:
    basic, ping = GROUPS["status/basic"], GROUPS["status/ping"]

    assert (basic.run, ping.run) == (status.basic, status.ping)
    assert basic.kind is ping.kind is GroupKind.EXACT
    assert basic.masks == ping.masks == ()


def test_status_ping_runs_even_when_the_status_differs() -> None:
    # A Candidate whose status differs must still get a status.rtt: no prerequisite.
    assert GROUPS["status/ping"].requires == ()
    assert GROUPS["status/basic"].requires == ()
    assert [each.id for each in resolve(["status/ping"])] == ["status/ping"]


def test_status_with_player_is_registered_as_exact_with_no_masks_or_prerequisites() -> None:
    group = GROUPS["status/with-player"]

    assert group.run is status.with_player
    assert group.kind is GroupKind.EXACT
    assert (group.masks, group.requires) == ((), ())


def test_the_wait_is_the_status_cache_interval_plus_one_second() -> None:
    # STATUS_EXPIRE_TIME_NANOS is 5 seconds: docs/research/2026-10-03-status-sample.md.
    assert status.STATUS_CACHE_S == 5
    assert status.CACHE_WAIT_S == status.STATUS_CACHE_S + 1


@dataclass
class _JoinThenStatus:
    """A fake server: the first connection joins like vanilla, later ones answer the status."""

    joined: BlocksServer = field(default_factory=BlocksServer)
    status_seen: list[Packet] = field(default_factory=list)
    connections: int = 0

    async def __call__(self, peer: Peer) -> None:
        self.connections += 1
        if self.connections == 1:
            await self.joined(peer)
        else:
            await status_server(json.dumps(VANILLA_STATUS), self.status_seen)(peer)


async def _play_with_player(
    monkeypatch: pytest.MonkeyPatch, steps: list[str] | None = None
) -> tuple[Transcript, list[Endpoint]]:
    """Play the Group on the fake; return its Transcript and where it waited for no player."""
    monkeypatch.setattr(status, "CACHE_WAIT_S", 0.3)
    settled: list[Endpoint] = []

    async def until_no_player_online(endpoint: Endpoint) -> None:
        settled.append(endpoint)
        if steps is not None:
            steps.append("no player online")

    monkeypatch.setattr(status, "until_no_player_online", until_no_player_online)
    transcript = Transcript(group_id="status/with-player", server="fake")
    async with playing(_JoinThenStatus(), transcript) as context:
        await GROUPS["status/with-player"].run(context)
    return transcript, settled


@pytest.mark.asyncio
async def test_status_with_player_joins_before_the_window_and_asks_for_the_status_inside_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transcript, _ = await _play_with_player(monkeypatch)

    (opened,) = [mark for mark in transcript.marks if mark.label.startswith(OBSERVE_OPEN)]
    (closed,) = [mark for mark in transcript.marks if mark.label == OBSERVE_CLOSE]
    player = [event for event in transcript.events if event.bot == "player"]
    asked = [e for e in transcript.events if e.packet.name == "minecraft:status_request"]
    answered = [e for e in transcript.events if e.packet.name == "minecraft:status_response"]
    assert {event.bot for event in answered} == {"status"}
    assert opened.label == f"{OBSERVE_OPEN} {status.PLAY_PACKET}", "no play packet of the join"
    (login,) = [e for e in player if e.packet.name == "minecraft:login_finished"]
    assert login.t_ns < opened.t_ns
    (ask,), (answer,) = asked, answered
    assert opened.t_ns < ask.t_ns < answer.t_ns < closed.t_ns
    assert ask.t_ns - opened.t_ns >= 0.3e9, "it waits for the status cache first"


@pytest.mark.asyncio
async def test_status_with_player_lets_the_player_leave_before_the_next_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    steps: list[str] = []
    real_close = Bot.close

    async def logged_close(bot: Bot) -> None:
        if not bot.closed:
            steps.append(f"{bot.name} closes")
        await real_close(bot)

    monkeypatch.setattr(Bot, "close", logged_close)
    _, settled = await _play_with_player(monkeypatch, steps)

    assert len(settled) == 1, "once the player has gone"
    # The Group closes the player itself, before it waits: `context.close` comes too late.
    assert steps[:2] == ["player closes", "no player online"]


@pytest.mark.asyncio
async def test_status_basic_asks_for_the_status_once() -> None:
    transcript, seen = await _play(GROUPS["status/basic"])

    assert _names(transcript) == [
        "minecraft:intention",
        "minecraft:status_request",
        "minecraft:status_response",
    ]
    assert [packet.name for packet in seen] == _names(transcript)[:2]
    assert transcript.marks == []


@pytest.mark.asyncio
async def test_status_ping_pings_after_the_status_as_the_vanilla_client_does() -> None:
    transcript, _ = await _play(GROUPS["status/ping"])

    assert _names(transcript) == [
        "minecraft:intention",
        "minecraft:status_request",
        "minecraft:status_response",
        "minecraft:ping_request",
        "minecraft:pong_response",
    ]
    pong = transcript.events[-1].packet
    assert pong.fields == {"timestamp": status.PING_PAYLOAD}


@pytest.mark.asyncio
async def test_the_status_rtt_span_covers_exactly_the_ping_and_its_pong() -> None:
    transcript, _ = await _play(GROUPS["status/ping"])

    start, end = transcript.marks
    ping, pong = transcript.events[-2:]
    assert (start.label, end.label) == ("status.rtt:start", "status.rtt:end")
    assert transcript.events[-3].t_ns <= start.t_ns <= ping.t_ns
    assert pong.t_ns <= end.t_ns
