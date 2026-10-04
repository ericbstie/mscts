"""The chat Groups: what each Bot says, in which windows, and what Control sets up and undoes.

Every test plays a Group against a fake server and reads the Transcript for what each Bot
sent (its chat messages and commands) and the Marks (the Observation windows). What a server
answers is never asserted: the fake only sends what a vanilla server sends, so that each
window's wait for the listener's message ends.
"""

import asyncio
import json
import time
import uuid
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, field, replace

import pytest

from mscts.bot import SYNC_REQUESTS, TICK_GAP_S
from mscts.codec.packets import Direction, Packet
from mscts.compare import OBSERVE_CLOSE, OBSERVE_OPEN
from mscts.group import GROUPS, GroupKind
from mscts.groups import chat
from mscts.spec import ServerSpec
from mscts.transcript import Transcript
from tests.group.test_control import playing, text, tree
from tests.net.fakes import NO_STATISTICS, JoinScript, Peer, join_server

TICK_S = 2 * TICK_GAP_S
"""The fake's tick: just over what a barrier needs to see one pass, so a play is quick."""
CHAT, CHAT_COMMAND = "minecraft:chat", "minecraft:chat_command"
SIGNED = "minecraft:chat_command_signed"
SYSTEM_CHAT, PLAYER_CHAT = "minecraft:system_chat", "minecraft:player_chat"
CLIENT_COMMAND, AWARD_STATS = "minecraft:client_command", "minecraft:award_stats"
MARKER = "tellraw @s "
CONTROL = "control"
COMMANDS = tree("team", "tellraw", "me", "say", "msg", "teammsg")
GROUP_IDS = ("chat/player", "chat/commands", "chat/join-leave", "chat/limits")
KICK_REASON = bytes([0x08, 0x00, 0x04]) + b"kick"  # an NBT String text component
LONGEST = 256
"""The longest message vanilla reads (26.3 javap)."""
KICK_AT = 10
"""The message that gets a player who is not an operator kicked, if all arrive within a tick."""
LATE_S = 5 * TICK_S
"""How late a slow server tells the others: after a barrier's answers, which come a tick apart."""
KICK_PACKETS = ("minecraft:disconnect", SYSTEM_CHAT, "minecraft:player_info_remove")
"""What the spam kick's window compares: not the chat, whose count before the kick varies."""


def player_chat(peer: Peer, sender: str, message: str) -> bytes:
    """A player_chat frame: `sender` said `message`, unsigned, as vanilla sends it."""
    return peer.frame(
        PLAYER_CHAT,
        global_index=0,
        sender=uuid.UUID(int=0),
        index=0,
        signature=None,
        message=message[:LONGEST],
        timestamp=0,
        salt=0,
        previous_messages=[],
        unsigned_content=None,
        filter={"type": "pass_through", "bits": None},
        chat_type={"reference": 0},
        sender_name=text(sender),
        target_name=None,
    )


def disguised_chat(peer: Peer, sender: str, message: str) -> bytes:
    """A disguised_chat frame: `sender` said `message`, as Pumpkin sends a player's chat."""
    return peer.frame(
        "minecraft:disguised_chat",
        message=text(message),
        chat_type={"reference": 0},
        sender_name=text(sender),
        target_name=None,
    )


def system_chat(peer: Peer, message: str) -> bytes:
    """A system_chat frame saying `message`."""
    return peer.frame(SYSTEM_CHAT, content=text(message), overlay=False)


@dataclass
class ChatServer:
    """A fake server that joins like vanilla and passes chat on like it.

    Each player but Control is told when another joins or leaves, and is sent what any of
    them says or runs as a message command. A marker (`tellraw @s "<token>"`) gets its token
    back; `tellraw @a` is told to every player. A player who says a message longer than
    vanilla reads, or one with a `§`, is kicked, and so is one who is not in `operators` on
    its `KICK_AT`-th message; what a kicked player sends after is ignored. With `late`, each
    thing the others are told reaches them `LATE_S` after the one before, in order, so after
    the barrier's answers (a server behind schedule). That a player joined comes late only
    with `late_joins`: vanilla tells it before the joining player has its chunks, so before
    its join returns. `left` holds when each player left, by name. With `disguised`, what
    a player says goes out as `disguised_chat`, as Pumpkin sends it; with
    `commands_as_system`, a message command's goes out as `system_chat`, as Pumpkin sends
    `/teammsg`.
    """

    operators: tuple[str, ...] = ()
    disguised: bool = False
    commands_as_system: bool = False
    late: bool = False
    late_joins: bool = False
    seen: list[Packet] = field(default_factory=list)
    left: dict[str, int] = field(default_factory=dict)
    _players: dict[str, Peer] = field(default_factory=dict, init=False)
    _kicked: set[str] = field(default_factory=set, init=False)
    _queue: asyncio.Queue[tuple[list[Peer], Callable[[Peer], bytes]]] = field(
        default_factory=asyncio.Queue, init=False
    )
    _teller: asyncio.Task[None] | None = field(default=None, init=False)

    async def __call__(self, peer: Peer) -> None:
        """Serve one connection: a Handler."""
        # A Bot that leaves with something unread resets the connection instead of closing it.
        with suppress(ConnectionError):
            await join_server(self.seen, JoinScript(commands=COMMANDS, then=self._play))(peer)

    async def _play(self, peer: Peer) -> None:
        if peer.name != CONTROL:
            await self._tell_all(
                lambda other: system_chat(other, f"{peer.name} joined"), late=self.late_joins
            )
            self._players[peer.name] = peer
        requests = messages = 0
        try:
            async for packet in peer.packets():
                self.seen.append(packet)
                fields = packet.fields or {}
                if packet.name == CLIENT_COMMAND:
                    requests += 1
                    if (requests - 1) % SYNC_REQUESTS != 0:
                        await asyncio.sleep(TICK_S)  # a barrier's answers come a tick apart
                    await peer.write(peer.raw_frame(AWARD_STATS, NO_STATISTICS))
                elif packet.name == CHAT_COMMAND:
                    await self._command(peer, str(fields["command"]))
                elif packet.name == SIGNED and self.commands_as_system:
                    command = str(fields["command"])
                    await self._tell_all(lambda other, said=command: system_chat(other, said))
                elif packet.name == SIGNED:
                    await self._say(peer, str(fields["command"]))
                elif packet.name == CHAT:
                    messages += 1
                    await self._chat(peer, str(fields["message"]), messages)
        except ConnectionError:
            pass  # the Bot left with something unread: a reset
        finally:
            await self._leave(peer)

    async def _command(self, peer: Peer, command: str) -> None:
        if command.startswith(MARKER):
            await peer.write(system_chat(peer, json.loads(command.removeprefix(MARKER))))
        elif command.startswith("tellraw @a "):
            await self._tell_all(lambda other: system_chat(other, command))

    async def _chat(self, peer: Peer, message: str, count: int) -> None:
        if peer.name in self._kicked:
            return
        if len(message) > LONGEST or "§" in message:
            await self._kick(peer)
            return
        await self._say(peer, message)
        if count >= KICK_AT and peer.name not in self.operators:
            await self._kick(peer)

    async def _say(self, peer: Peer, message: str) -> None:
        said = disguised_chat if self.disguised else player_chat
        await self._tell_all(lambda other: said(other, peer.name, message))

    async def _kick(self, peer: Peer) -> None:
        """Disconnect `peer` as vanilla does, and tell the others; it reads on until EOF."""
        self._kicked.add(peer.name)
        await peer.write(peer.frame("minecraft:disconnect", reason=KICK_REASON))
        await self._leave(peer)

    async def _leave(self, peer: Peer) -> None:
        if self._players.get(peer.name) is not peer:
            return
        del self._players[peer.name]
        self.left[peer.name] = time.monotonic_ns()
        await self._tell_all(lambda other: system_chat(other, f"{peer.name} left"))

    async def _tell_all(self, frame: Callable[[Peer], bytes], *, late: bool | None = None) -> None:
        players = list(self._players.values())
        if self.late if late is None else late:
            if self._teller is None:
                self._teller = asyncio.create_task(self._tell_late())
            self._queue.put_nowait((players, frame))
        else:
            await self._tell(players, frame)

    async def _tell_late(self) -> None:
        while True:
            players, frame = await self._queue.get()
            await asyncio.sleep(LATE_S)
            await self._tell(players, frame)

    async def _tell(self, players: list[Peer], frame: Callable[[Peer], bytes]) -> None:
        for other in players:
            with suppress(ConnectionError):  # it may be leaving
                await other.write(frame(other))


@dataclass(frozen=True)
class Said:
    """Something a Bot said: a chat message, or a command (signed or not)."""

    t_ns: int
    bot: str
    packet: str
    text: str


def said(transcript: Transcript) -> list[Said]:
    """What every Bot said, in order, but Control's markers."""
    out = []
    for event in transcript.events:
        packet = event.packet
        if packet.direction is not Direction.SERVERBOUND:
            continue
        fields = packet.fields or {}
        if packet.name == CHAT:
            out.append(Said(event.t_ns, event.bot, CHAT, str(fields["message"])))
        elif packet.name in (CHAT_COMMAND, SIGNED):
            command = str(fields["command"])
            if not command.startswith(MARKER):
                out.append(Said(event.t_ns, event.bot, packet.name, command))
    return out


@dataclass(frozen=True)
class Window:
    """One Observation window of a play: when it opened and closed, and what was said in it."""

    opened: int
    closed: int
    said: tuple[Said, ...]


@dataclass(frozen=True)
class Play:
    """A played Group: its windows, what was said outside them, and its Transcript."""

    windows: tuple[Window, ...]
    outside: tuple[Said, ...]
    transcript: Transcript


def read(transcript: Transcript) -> Play:
    """The windows of `transcript`, each closing where the listener's does."""
    opens = [mark for mark in transcript.marks if mark.label.startswith(OBSERVE_OPEN)]
    closes = [m for m in transcript.marks if m.label == f"{OBSERVE_CLOSE} {chat.LISTENER}"]
    assert len(opens) == len(closes), transcript.marks
    assert {mark.label for mark in opens} <= {
        f"{OBSERVE_OPEN} {' '.join(packets)}" for packets in (chat.PACKETS, KICK_PACKETS)
    }
    everything = said(transcript)
    windows = tuple(
        Window(
            opened.t_ns,
            closed.t_ns,
            tuple(s for s in everything if opened.t_ns <= s.t_ns <= closed.t_ns),
        )
        for opened, closed in zip(opens, closes, strict=True)
    )
    inside = {s for window in windows for s in window.said}
    return Play(windows, tuple(s for s in everything if s not in inside), transcript)


async def play(group_id: str, server: ChatServer | None = None) -> Play:
    """Play `group_id` against a fake server; return what was read from its Transcript."""
    transcript = Transcript(group_id=group_id, server="fake")
    async with playing(server or ChatServer(operators=operators(group_id)), transcript) as context:
        await GROUPS[group_id].run(context)
    return read(transcript)


def operators(group_id: str) -> tuple[str, ...]:
    return GROUPS[group_id].spec(ServerSpec(host="127.0.0.1", port=25566)).operators


def texts(window: Window, bot: str) -> list[str]:
    return [s.text for s in window.said if s.bot == bot]


def received(play: Play, bot: str, name: str, window: Window) -> int:
    """How many `name` packets `bot` received inside `window`."""
    return sum(
        event.bot == bot
        and event.packet.direction is Direction.CLIENTBOUND
        and event.packet.name == name
        and window.opened <= event.t_ns <= window.closed
        for event in play.transcript.events
    )


@pytest.mark.parametrize("group_id", GROUP_IDS)
def test_each_group_is_exact_and_masks_nothing(group_id: str) -> None:
    group = GROUPS[group_id]

    assert group.kind is GroupKind.EXACT
    assert group.requires == ()
    assert group.masks == ()


def test_the_speaker_of_commands_and_the_operator_of_limits_are_operators() -> None:
    default = ServerSpec(host="127.0.0.1", port=25566)

    assert {group_id: operators(group_id) for group_id in GROUP_IDS} == {
        "chat/player": (),
        "chat/commands": (chat.SPEAKER,),
        "chat/join-leave": (),
        "chat/limits": (chat.OPERATOR,),
    }
    alice = replace(default, operators=("alice",))
    assert GROUPS["chat/limits"].spec(alice).operators == ("alice", chat.OPERATOR)


def test_the_windows_compare_the_chat_a_kick_and_the_player_list() -> None:
    assert set(chat.PACKETS) == {
        "minecraft:player_chat",
        "minecraft:system_chat",
        "minecraft:disguised_chat",
        "minecraft:disconnect",
        "minecraft:player_info_update",
        "minecraft:player_info_remove",
    }
    assert len(chat.PACKETS) == len(set(chat.PACKETS))


@pytest.mark.asyncio
@pytest.mark.parametrize("group_id", GROUP_IDS)
async def test_the_listener_and_control_say_nothing_inside_a_window(group_id: str) -> None:
    result = await play(group_id)

    assert result.windows
    for window in result.windows:
        assert texts(window, chat.LISTENER) == []
        assert texts(window, CONTROL) == []


@pytest.mark.asyncio
async def test_player_says_a_plain_message_then_one_with_a_link_each_in_its_window() -> None:
    result = await play("chat/player")

    assert [[(s.bot, s.packet, s.text) for s in w.said] for w in result.windows] == [
        [(chat.SPEAKER, CHAT, "Hello, world!")],
        [(chat.SPEAKER, CHAT, "The rules are at https://www.minecraft.net/en-us/eula")],
    ]
    assert result.outside == ()


@pytest.mark.asyncio
async def test_commands_runs_each_command_in_its_window_signed_if_it_has_a_message() -> None:
    result = await play("chat/commands")

    assert [[(s.bot, s.packet, s.text) for s in w.said] for w in result.windows] == [
        [(chat.SPEAKER, SIGNED, "me waves to everyone")],
        [(chat.SPEAKER, SIGNED, "say Hello from the speaker")],
        [(chat.SPEAKER, SIGNED, f"msg {chat.LISTENER} This is a whisper")],
        [
            (
                chat.SPEAKER,
                CHAT_COMMAND,
                'tellraw @a {"text":"Formatted text","color":"gold","bold":true}',
            )
        ],
        [(chat.SPEAKER, SIGNED, "teammsg Hello, team")],
    ]


@pytest.mark.asyncio
async def test_commands_puts_both_bots_on_a_team_first_and_removes_it_after() -> None:
    result = await play("chat/commands")

    before = [s.text for s in result.outside if s.t_ns < result.windows[0].opened]
    after = [s.text for s in result.outside if s.t_ns > result.windows[-1].closed]
    assert before == ["team add mscts", "team join mscts speaker", "team join mscts listener"]
    assert after == ["team remove mscts"]
    assert {s.bot for s in result.outside} == {CONTROL}


@pytest.mark.asyncio
async def test_commands_removes_the_team_when_the_listener_never_hears_a_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(chat, "FEEDBACK_TIMEOUT_S", 0.3)
    monkeypatch.setattr(ChatServer, "_say", lambda *_: asyncio.sleep(0))
    transcript = Transcript(group_id="chat/commands", server="fake")
    server = ChatServer(operators=(chat.SPEAKER,))
    async with playing(server, transcript) as context:
        with pytest.raises(TimeoutError):
            await GROUPS["chat/commands"].run(context)

    control = [s.text for s in said(transcript) if s.bot == CONTROL]
    assert control[-1] == "team remove mscts"
    assert len([s for s in said(transcript) if s.bot == chat.SPEAKER]) == 1


@pytest.mark.asyncio
async def test_join_leave_joins_the_joiner_in_one_window_and_it_leaves_in_the_next() -> None:
    server = ChatServer()
    result = await play("chat/join-leave", server)

    joined, leaving = result.windows
    joiner = [event.t_ns for event in result.transcript.events if event.bot == chat.JOINER]
    assert joined.opened <= min(joiner) <= joined.closed  # it connects inside the window
    left = server.left[chat.JOINER] - result.transcript.start_ns
    assert leaving.opened <= left <= leaving.closed
    assert result.outside == ()


@pytest.mark.asyncio
async def test_limits_says_the_longest_message_then_spams_as_an_operator() -> None:
    result = await play("chat/limits")

    longest, spam = result.windows[:2]
    assert [(s.bot, s.text) for s in longest.said] == [(chat.TALKER, "x" * LONGEST)]
    assert [(s.bot, s.text) for s in spam.said] == [
        (chat.OPERATOR, f"Message {n}") for n in range(1, chat.SPAM_MESSAGES + 1)
    ]
    assert chat.OPERATOR in operators("chat/limits")


@pytest.mark.asyncio
async def test_limits_ends_with_a_window_for_each_kick() -> None:
    # A Candidate may not kick at all, and the Bot then waits out its bound: the kicks last.
    result = await play("chat/limits")

    kicks = result.windows[2:]
    assert [[(s.bot, s.text) for s in w.said] for w in kicks] == [
        [(chat.LONG, "x" * (LONGEST + 1))],
        [(chat.SECTION, "§cRed text")],
        [(chat.SPAMMER, f"Message {n}") for n in range(1, chat.SPAM_MESSAGES + 1)],
    ]
    for window, bot in zip(kicks, (chat.LONG, chat.SECTION, chat.SPAMMER), strict=True):
        assert received(result, bot, "minecraft:disconnect", window) == 1
    assert chat.SPAMMER not in operators("chat/limits")
    assert all(s.t_ns < kicks[0].opened for s in result.outside)


@pytest.mark.asyncio
@pytest.mark.parametrize("group_id", GROUP_IDS)
async def test_a_server_that_sends_disguised_chat_still_gets_every_window(group_id: str) -> None:
    # Pumpkin answers a player's chat with disguised_chat, where vanilla sends player_chat:
    # the window ends on either, so the Report shows the difference and the Group goes on.
    disguised = await play(group_id, ChatServer(operators=operators(group_id), disguised=True))
    vanilla = await play(group_id)

    def cases(result: Play) -> list[list[tuple[str, str]]]:
        return [[(s.bot, s.text) for s in window.said] for window in result.windows]

    assert cases(disguised) == cases(vanilla)


@pytest.mark.asyncio
async def test_a_server_that_says_a_message_command_as_a_system_message_gets_every_window() -> None:
    # Pumpkin answers /teammsg with system_chat: a command's window ends on that too.
    server = ChatServer(operators=operators("chat/commands"), commands_as_system=True)
    result = await play("chat/commands", server)

    assert len(result.windows) == len((await play("chat/commands")).windows)


def heard(result: Play, window: Window) -> int:
    """How many chat packets the listener received inside `window`, up to its close."""
    return sum(
        event.bot == chat.LISTENER
        and event.packet.direction is Direction.CLIENTBOUND
        and event.packet.name in (PLAYER_CHAT, SYSTEM_CHAT, "minecraft:disguised_chat")
        and window.opened <= event.t_ns <= window.closed
        for event in result.transcript.events
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("group_id", GROUP_IDS)
async def test_each_window_waits_for_all_the_listener_is_told_when_the_server_is_late(
    group_id: str,
) -> None:
    # The listener sent nothing, so its barrier does not cover what the others' actions
    # send it: a window must wait for each message, or a slow server's lands after it.
    prompt = await play(group_id)
    joins = group_id == "chat/join-leave"  # the one Group that waits for a join to be told
    server = ChatServer(operators=operators(group_id), late=True, late_joins=joins)
    late = await play(group_id, server)

    counts = [heard(late, window) for window in late.windows]
    assert counts == [heard(prompt, window) for window in prompt.windows]
    assert all(counts), counts


@pytest.mark.asyncio
async def test_limits_spams_in_one_write_and_compares_only_the_kick_in_the_spammers_window() -> (
    None
):
    result = await play("chat/limits")

    for bot in (chat.OPERATOR, chat.SPAMMER):
        times = [s.t_ns for s in said(result.transcript) if s.bot == bot]
        assert len(times) == chat.SPAM_MESSAGES
        assert len(set(times)) == 1, "all in one write"
    assert chat.SPAM_MESSAGES >= KICK_AT + 5, "a tick or more inside the burst still kicks"
    opens = [m.label for m in result.transcript.marks if m.label.startswith(OBSERVE_OPEN)]
    assert opens[-1] == f"{OBSERVE_OPEN} {' '.join(KICK_PACKETS)}"
    assert set(opens[:-1]) == {f"{OBSERVE_OPEN} {' '.join(chat.PACKETS)}"}
