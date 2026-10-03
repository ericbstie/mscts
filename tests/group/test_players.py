"""The players Groups: who joins, leaves and runs what, in which windows, and what is undone.

Every test plays a Group against a fake server and reads the Transcript for what each Bot
sent and the Marks. What a server answers is never asserted.
"""

from contextlib import suppress
from dataclasses import dataclass, field
from typing import override

import pytest

from mscts.codec.packets import Direction, State
from mscts.compare import OBSERVE_CLOSE, OBSERVE_OPEN
from mscts.group import GROUPS, GroupKind
from mscts.groups import players
from mscts.net import ProtocolError
from mscts.spec import ServerSpec
from mscts.transcript import Mark, Transcript
from tests.group.test_blocks import BlocksServer, sent
from tests.group.test_control import playing, tree
from tests.net.fakes import JoinScript, Peer, join_server

ADA, BOB, CONTROL = "ada", "bob", "control"
COMPARED = (
    "minecraft:player_info_update",
    "minecraft:player_info_remove",
    "minecraft:add_entity",
    "minecraft:set_entity_data",
    "minecraft:remove_entities",
    "minecraft:system_chat",
)
WINDOW = " ".join((OBSERVE_OPEN, *COMPARED))
"""The open Mark of every window: the tab list, the other player's body and the chat."""
SET_UP = (
    "gamerule respawn_radius 0",
    "gamerule player_movement_check false",
    "tick freeze",
)
"""Mob spawning is off in every Fixture world already (ADR-0013), so it is left alone."""
UNDO = (
    "tick unfreeze",
    "gamerule player_movement_check true",
    "gamerule respawn_radius 10",
)
"""What Control ends with: each setting put back, the last made first."""
COMMANDS = tree("gamerule", "gamemode", "tick", "tellraw")


@dataclass
class PlayersServer(BlocksServer):
    """A fake server that lets in `places` connections, refusing later ones as vanilla does.

    The ones it lets in join like vanilla and get their commands answered (`BlocksServer`).
    """

    places: int | None = None
    _connections: int = field(default=0, init=False)

    @override
    async def __call__(self, peer: Peer) -> None:
        """Serve one connection: a Handler."""
        self._connections += 1
        if self.places is not None and self._connections > self.places:
            script = JoinScript(disconnect_in=State.LOGIN)
        else:
            script = JoinScript(commands=COMMANDS, then=self._play)
        with suppress(ConnectionError):
            await join_server(self.seen, script)(peer)


async def play(group_id: str, server: PlayersServer | None = None) -> Transcript:
    """Play the Group against a fake server; return its Transcript."""
    transcript = Transcript(group_id=group_id, server="fake")
    async with playing(server or PlayersServer(), transcript) as context:
        await GROUPS[group_id].run(context)
    return transcript


def windows(transcript: Transcript) -> list[tuple[Mark, Mark]]:
    """Each window's open Mark and the Mark that closes it for every Bot."""
    opens = [mark for mark in transcript.marks if mark.label.startswith(OBSERVE_OPEN)]
    closes = [mark for mark in transcript.marks if mark.label == OBSERVE_CLOSE]
    return list(zip(opens, closes, strict=True))


def hello_at(transcript: Transcript, bot: str) -> int:
    """When `bot` sent its `hello`: when it started to join."""
    (at,) = [
        event.t_ns
        for event in transcript.events
        if event.bot == bot and event.packet.name == "minecraft:hello"
    ]
    return at


def last_at(transcript: Transcript, bot: str) -> int:
    """When `bot` sent or received its last packet."""
    return max(event.t_ns for event in transcript.events if event.bot == bot)


def test_the_four_groups_are_exact_with_no_masks_or_prerequisites() -> None:
    default = ServerSpec(host="127.0.0.1", port=25566)
    ids = [group_id for group_id in GROUPS if group_id.startswith("players/")]

    assert ids == [
        "players/join-seen",
        "players/leave-seen",
        "players/mode-seen",
        "players/server-full",
    ]
    for group_id in ids:
        group = GROUPS[group_id]
        assert group.kind is GroupKind.EXACT
        assert (group.masks, group.requires) == ((), ())
    assert GROUPS["players/join-seen"].spec(default) == default
    assert GROUPS["players/server-full"].spec(default).max_players == 1


@pytest.mark.asyncio
async def test_bob_joins_inside_the_window_after_ada_and_with_control_gone() -> None:
    transcript = await play("players/join-seen")

    ((opened, closed),) = windows(transcript)
    assert opened.label == WINDOW
    assert hello_at(transcript, ADA) < opened.t_ns < hello_at(transcript, BOB)
    assert last_at(transcript, BOB) < closed.t_ns
    control = sent(transcript, CONTROL)
    assert [command for t, command in control if t < opened.t_ns] == list(SET_UP)
    assert [command for t, command in control if t > closed.t_ns] == list(UNDO)
    controls = [
        e for e in transcript.events if e.bot == CONTROL and e.packet.name == "minecraft:hello"
    ]
    assert len(controls) == 2, "Control leaves before bob joins, and rejoins to undo"
    assert controls[0].t_ns < hello_at(transcript, ADA)
    assert controls[1].t_ns > closed.t_ns


@pytest.mark.asyncio
async def test_bob_leaves_inside_the_window_after_both_joined() -> None:
    transcript = await play("players/leave-seen")

    ((opened, closed),) = windows(transcript)
    assert opened.label == WINDOW
    assert hello_at(transcript, BOB) < opened.t_ns
    bob_requests = [
        event.t_ns
        for event in transcript.events
        if event.bot == BOB and event.packet.name == "minecraft:client_command"
    ]
    assert bob_requests, "bob is in play when the window opens: its barrier covers him"
    assert last_at(transcript, BOB) < closed.t_ns, "bob left inside the window"
    ada_requests = [
        event.t_ns
        for event in transcript.events
        if event.bot == ADA and event.packet.name == "minecraft:client_command"
    ]
    assert max(ada_requests) > last_at(transcript, BOB), "ada's barrier is after bob left"
    control = sent(transcript, CONTROL)
    assert [command for t, command in control if t < opened.t_ns] == list(SET_UP)
    assert [command for t, command in control if t > closed.t_ns] == list(UNDO)


@pytest.mark.asyncio
async def test_control_changes_bobs_game_mode_once_in_each_window_and_puts_survival_back() -> None:
    transcript = await play("players/mode-seen")

    control = sent(transcript, CONTROL)
    played = windows(transcript)
    assert [opened.label for opened, _ in played] == [WINDOW] * 4
    inside = [
        [command for t, command in control if opened.t_ns < t < closed.t_ns]
        for opened, closed in played
    ]
    assert inside == [
        ["gamemode creative bob"],
        ["gamemode adventure bob"],
        ["gamemode spectator bob"],
        ["gamemode survival bob"],
    ]
    first_open, last_close = played[0][0].t_ns, played[-1][1].t_ns
    assert hello_at(transcript, BOB) < first_open
    assert [command for t, command in control if t < first_open] == list(SET_UP)
    assert [command for t, command in control if t > last_close] == [
        "gamemode survival bob",
        *UNDO,
    ]


@pytest.mark.asyncio
async def test_the_rules_are_put_back_when_bob_cannot_join() -> None:
    transcript = Transcript(group_id="players/mode-seen", server="fake")
    server = PlayersServer(places=2)  # Control and ada

    with pytest.raises(ProtocolError, match="disconnected bob"):
        async with playing(server, transcript) as context:
            await GROUPS["players/mode-seen"].run(context)

    assert [command for _, command in sent(transcript, CONTROL)] == [*SET_UP, *UNDO]


@pytest.mark.asyncio
async def test_bob_is_refused_inside_the_window_when_ada_has_the_only_place() -> None:
    server = PlayersServer(places=1)
    transcript = await play("players/server-full", server)

    ((opened, closed),) = windows(transcript)
    assert opened.label == WINDOW
    assert hello_at(transcript, ADA) < opened.t_ns < hello_at(transcript, BOB)
    refusals = [
        event
        for event in transcript.events
        if event.bot == BOB
        and event.packet.direction is Direction.CLIENTBOUND
        and event.packet.name == "minecraft:login_disconnect"
    ]
    assert len(refusals) == 1
    assert refusals[0].t_ns < closed.t_ns
    assert sent(transcript, CONTROL) == [], "Control would take the only place"


@pytest.mark.asyncio
async def test_bob_joining_a_server_that_lets_him_in_is_no_error() -> None:
    transcript = await play("players/server-full")

    ((_, closed),) = windows(transcript)
    assert last_at(transcript, BOB) < closed.t_ns


def test_the_groups_are_registered_by_the_groups_package() -> None:
    assert GROUPS["players/join-seen"].run is players.join_seen
