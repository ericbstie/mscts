"""The commands Groups: what the Bot that runs them sends, in which windows, and what is undone.

Every test plays a Group against a fake server and reads the Transcript for what each Bot sent
(its commands) and the Marks (the Observation windows). What a server answers is never asserted:
the fake only sends as many chat messages as a vanilla server does, so that each window's wait
for them ends.
"""

import asyncio
import json
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass, field, replace

import pytest
from support.control import (
    AWARD_STATS,
    CHAT_COMMAND,
    CLIENT_COMMAND,
    CONTROL,
    MARKER,
    chat,
    playing,
    tree,
)

from mscts.bot import SYNC_REQUESTS, TICK_GAP_S
from mscts.case_titles import TITLES
from mscts.codec.packets import Direction, Packet
from mscts.compare import OBSERVE_CLOSE, OBSERVE_OPEN
from mscts.group import GROUPS, GroupKind
from mscts.groups import chat as chat_groups
from mscts.groups import commands
from mscts.spec import Difficulty, ServerSpec
from mscts.transcript import Transcript
from tests.net.fakes import NO_STATISTICS, JoinScript, Peer, join_server

TICK_S = 2 * TICK_GAP_S
"""The fake's tick: just over what a barrier needs to see one pass, so a play is quick."""
LATE_S = 5 * TICK_S
"""How late a slow server's answer is: after the barrier's answers, which come a tick apart."""
SIGNED = "minecraft:chat_command_signed"
BARRIER = 'tellraw @s "mscts-barrier-'
"""The start of each marker Control says to itself: Control's own, not a Group's."""
ROOTS = (
    "setblock",
    "fill",
    "clone",
    "summon",
    "kill",
    "tp",
    "give",
    "enchant",
    "clear",
    "effect",
    "xp",
    "gamemode",
    "difficulty",
    "time",
    "weather",
    "gamerule",
    "tick",
    "seed",
    "list",
    "execute",
    "say",
    "tellraw",
    "deop",
)
"""The commands the fake's tree holds: every one Control or the Bots run."""

CHAT = ("minecraft:system_chat", "minecraft:player_chat", "minecraft:disguised_chat")
"""What every window compares of the chat."""
BLOCK, SECTION = "minecraft:block_update", "minecraft:section_blocks_update"
SLOT, ENTITY = "minecraft:container_set_slot", "minecraft:add_entity"


@dataclass(frozen=True)
class Want:
    """One window of a Group: Control's setup, the command, and what the window waits for.

    Attributes:
        command: What the Bot runs.
        setup: What Control runs before the window opens.
        answers: How many chat messages vanilla sends for the command and the `then` commands.
        effects: The packets besides the chat that the window compares.
        signed: Whether the Bot sends the command as the vanilla client does a message command.
        marker: Whether vanilla says nothing, so the Bot ends the window with a marker.
        then: What the Bot sends right after the command, without waiting.
    """

    command: str
    setup: tuple[str, ...] = ()
    answers: int = 1
    effects: tuple[str, ...] = ()
    signed: bool = False
    marker: bool = False
    then: tuple[str, ...] = ()

    @property
    def heard(self) -> int:
        """How many chat messages the Bot receives in the window: the marker's is one."""
        return self.answers + int(self.marker)


END = 'tellraw @s "mscts-end"'
"""The marker a window ends with where vanilla answers nothing."""
AREA_CLEAR = "fill 2 -60 2 14 -58 10 minecraft:air"
BIG_BOX = "0 -50 0 15 61 15"
PIG = 'minecraft:pig 12.5 -60 12.5 {NoAI:1b,Tags:["mscts"],UUID:[I;1,2,3,4]}'
TAGGED = 'minecraft:pig 12.5 -60 {z}.5 {{NoAI:1b,Tags:["mscts","mscts2"]}}'

SUCCESS = (
    Want(
        "setblock 4 -60 4 minecraft:stone",
        setup=("setblock 4 -60 4 minecraft:air",),
        effects=(BLOCK,),
    ),
    Want("fill 4 -60 6 6 -58 8 minecraft:stone", setup=(AREA_CLEAR,), effects=(SECTION,)),
    Want(
        "clone 4 -60 6 6 -58 8 8 -60 6",
        setup=("fill 8 -60 6 10 -58 8 minecraft:air",),
        effects=(SECTION,),
    ),
    Want(f"summon {PIG}", effects=(ENTITY,)),
    Want("kill @e[type=minecraft:pig,tag=mscts]", effects=("minecraft:entity_event",)),
    Want(
        "kill @e[type=minecraft:pig,tag=mscts2]",
        setup=(
            f"summon {TAGGED.format(z=4)}",
            f"summon {TAGGED.format(z=6)}",
        ),
    ),
    Want("tp @s 1.5 -60 14.5", effects=("minecraft:player_position",)),
    Want("give @s minecraft:diamond_sword", effects=(SLOT,)),
    Want("enchant @s minecraft:sharpness 2", effects=(SLOT,)),
    Want("clear @s minecraft:diamond_sword", effects=(SLOT,)),
    Want("effect give @s minecraft:speed 100 1 true", effects=("minecraft:update_mob_effect",)),
    Want("xp add @s 10 points", effects=("minecraft:set_experience",)),
    Want("gamemode creative", effects=("minecraft:game_event", "minecraft:player_abilities")),
    Want("difficulty easy", effects=("minecraft:change_difficulty",)),
    Want("time set 1000"),
    Want("weather clear"),
    Want("gamerule keep_inventory true"),
    Want("tick rate 20", effects=("minecraft:ticking_state",)),
    Want("seed"),
    Want("list"),
    Want("execute if block 4 -60 4 minecraft:stone", setup=("setblock 4 -60 4 minecraft:stone",)),
    Want("say Hello from the commander", signed=True),
    Want(
        f"fill {BIG_BOX} minecraft:stone",
        setup=(f"fill {BIG_BOX} minecraft:air",),
        answers=2,
        then=('tellraw @s "after the fill"',),
    ),
)
"""`tick query` is left out: its tick times are the wall clock's."""

SUCCESS_UNDO = (
    "kill @e[type=minecraft:item]",
    "kill @e[type=minecraft:pig,tag=mscts]",
    "clear commander",
    "xp set commander 0 levels",
    "xp set commander 0 points",
    "effect clear commander",
    "gamerule keep_inventory false",
    "difficulty normal",
    "gamemode survival commander",
    AREA_CLEAR,
    f"fill {BIG_BOX} minecraft:air",
)
"""What Control runs after the last window, in order: the last undo pushed first."""

ERRORS = (
    Want("setblock 4 -60 4 minecraft:not_a_block", answers=2),
    Want("setblock 4 -60", answers=2),
    Want("notacommand", answers=2),
    Want("setblock 4 400 4 minecraft:stone"),
    Want("setblock 4 -60 4 minecraft:stone", setup=("setblock 4 -60 4 minecraft:stone",)),
    Want("fill 0 -60 0 100 -50 100 minecraft:stone"),
    Want("clone 4 -60 6 6 -58 8 5 -60 6"),
    Want("kill @e[tag=nothing]"),
    Want("tp @s @e[tag=nothing]", answers=2),
    Want("give @s minecraft:diamond 0", answers=2),
    Want("give @s minecraft:not_an_item", answers=2),
    Want("clear @s minecraft:diamond"),
    Want("effect give @s minecraft:not_an_effect", answers=2),
    Want("effect clear @s minecraft:speed"),
    Want("enchant @s minecraft:sharpness"),
    Want("xp add @s abc", answers=2),
    Want("gamemode nonsense", answers=2),
    Want("gamemode survival", answers=0, marker=True),
    Want("difficulty normal"),
    Want("time set abc"),
    Want("weather rain abc", answers=2),
    Want("gamerule not_a_rule true", answers=2),
    Want("gamerule keep_inventory maybe", answers=2),
    Want("tick rate 0", answers=2),
    Want("seed extra", answers=2),
    Want("list nonsense", answers=2),
    Want("summon minecraft:not_an_entity", answers=2),
    Want("say", answers=2),
)
"""`summon minecraft:pig 12.5 400 12.5` is left out: vanilla summons it, with a random UUID."""

ERRORS_UNDO = (
    "kill @e[type=minecraft:item]",
    "kill @e[type=minecraft:pig,tag=mscts]",
    AREA_CLEAR,
)

PERMISSIONS = (
    Want("gamemode creative", answers=2),
    Want("op player", answers=2),
    Want("tp 0.5 -60 0.5", answers=2),
    Want("list"),
)
"""Four commands: a player who is not an operator is kicked for spam at about its 10th."""

PERMISSIONS_UNDO = ("gamemode survival player", "deop player")


@dataclass(frozen=True)
class Plan:
    """What a Group is meant to do: who runs the windows, who is in play, and the windows."""

    runner: str
    bots: tuple[str, ...]
    windows: tuple[Want, ...]
    undo: tuple[str, ...]


PLANS = {
    "commands/success": Plan(
        commands.COMMANDER, (commands.COMMANDER, commands.WITNESS), SUCCESS, SUCCESS_UNDO
    ),
    "commands/errors": Plan(commands.COMMANDER, (commands.COMMANDER,), ERRORS, ERRORS_UNDO),
    "commands/permissions": Plan(
        commands.PLAYER, (commands.PLAYER,), PERMISSIONS, PERMISSIONS_UNDO
    ),
}
GROUP_IDS = tuple(PLANS)
PLACES = {
    commands.COMMANDER: "0.5 -60 14.5",
    commands.WITNESS: "-3.5 -60 14.5",
    commands.PLAYER: "0.5 -60 14.5",
}
"""Where Control puts each Bot."""


def fixture_start(bots: tuple[str, ...]) -> tuple[str, ...]:
    """What Control runs before the first window: pin the joins, calm, place, freeze."""
    return (
        "gamerule player_movement_check false",
        "gamerule respawn_radius 0",
        "gamerule advance_weather false",
        "weather clear",
        *(f"tp {bot} {PLACES[bot]}" for bot in bots),
        "tp control 96.5 -60 96.5",
        "tick freeze",
        "gamerule random_tick_speed 0",
    )


def fixture_end(bots: tuple[str, ...]) -> tuple[str, ...]:
    """What Control runs after the Group's own undo: the fixture's, in reverse."""
    return (
        "gamerule random_tick_speed 3",
        "tick unfreeze",
        *(f"tp {bot} 0.5 -60 0.5" for bot in reversed(bots)),
        "gamerule advance_weather true",
        "gamerule respawn_radius 10",
        "gamerule player_movement_check true",
    )


@dataclass
class CommandsServer:
    """A fake server that joins like vanilla and answers a command with its chat messages.

    A marker (`tellraw @s "<token>"`) gets its token back as one message. Any other command
    gets `answers[command]` messages, one by default, and a Bot but Control gets each
    `late_s` after the one before, in order, while the server goes on answering the barrier
    (a server behind schedule). Every serverbound Packet goes into `seen`.
    """

    answers: Mapping[str, int] = field(default_factory=dict)
    late_s: float = 0.0
    seen: list[Packet] = field(default_factory=list)

    async def __call__(self, peer: Peer) -> None:
        """Serve one connection: a Handler."""
        # A Bot that leaves with something unread resets the connection instead of closing it.
        with suppress(ConnectionError):
            await join_server(self.seen, JoinScript(commands=tree(*ROOTS), then=self._play))(peer)

    async def _play(self, peer: Peer) -> None:
        told: asyncio.Queue[bytes] = asyncio.Queue()
        requests = 0
        async with asyncio.TaskGroup() as later:
            teller = later.create_task(self._tell(peer, told))
            try:
                async for packet in peer.packets():
                    self.seen.append(packet)
                    if packet.name == CLIENT_COMMAND:
                        requests += 1
                        if (requests - 1) % SYNC_REQUESTS != 0:
                            await asyncio.sleep(TICK_S)  # a barrier's answers come a tick apart
                        await peer.write(peer.raw_frame(AWARD_STATS, NO_STATISTICS))
                    elif packet.name in (CHAT_COMMAND, SIGNED):
                        command = str((packet.fields or {})["command"])
                        for message in self._messages(command):
                            told.put_nowait(chat(peer, message))
            except ConnectionError:
                pass  # the Bot left with something unread (a reset)
            finally:
                teller.cancel()

    def _messages(self, command: str) -> list[str]:
        if command.startswith(MARKER):
            return [json.loads(command.removeprefix(MARKER))]
        return [f"done: {command}"] * self.answers.get(command, 1)

    async def _tell(self, peer: Peer, told: asyncio.Queue[bytes]) -> None:
        while True:
            frame = await told.get()
            if peer.name != CONTROL:
                await asyncio.sleep(self.late_s)
            with suppress(ConnectionError):  # the Bot may have left first
                await peer.write(frame)


def server_for(group_id: str, *, late_s: float = 0.0, silent: str | None = None) -> CommandsServer:
    """A fake that sends as many messages as vanilla does for each window of `group_id`.

    A `silent` command gets none, where vanilla sends some: a hang.
    """
    answers = {want.command: want.answers - len(want.then) for want in PLANS[group_id].windows}
    if silent is not None:
        answers[silent] = 0
    return CommandsServer(answers=answers, late_s=late_s)


@dataclass(frozen=True)
class Sent:
    """A command a Bot sent: when, who, as which packet, and what."""

    t_ns: int
    bot: str
    packet: str
    text: str


def sent(transcript: Transcript) -> list[Sent]:
    """Every command any Bot sent, in order, but Control's own markers."""
    out = []
    for event in transcript.events:
        packet = event.packet
        if packet.direction is not Direction.SERVERBOUND or packet.name not in (
            CHAT_COMMAND,
            SIGNED,
        ):
            continue
        command = str((packet.fields or {})["command"])
        if not (event.bot == CONTROL and command.startswith(BARRIER)):
            out.append(Sent(event.t_ns, event.bot, packet.name, command))
    return out


@dataclass(frozen=True)
class Window:
    """One Observation window of a play, and what the Bots did around and inside it.

    Attributes:
        label: Its open Mark's label.
        before: Control's commands since the last window closed.
        runner: What the runner sent inside it.
        others: What Control and the other Bots sent inside it.
        heard: How many chat messages the runner received inside it.
        first_heard_ns: When the runner received the first of them.
    """

    label: str
    before: tuple[str, ...]
    runner: tuple[Sent, ...]
    others: tuple[Sent, ...]
    heard: int
    first_heard_ns: int


@dataclass(frozen=True)
class Play:
    """A played Group: each window, Control's commands after the last, and the Transcript."""

    windows: tuple[Window, ...]
    after: tuple[str, ...]
    transcript: Transcript


def read(transcript: Transcript, runner: str) -> Play:
    """The windows of `transcript` (each opened and closed) and Control's commands after them.

    A window closes where the runner's does: each Bot's ends at its own barrier.
    """
    everything = sent(transcript)
    opens = [mark for mark in transcript.marks if mark.label.startswith(OBSERVE_OPEN)]
    closes = [m for m in transcript.marks if m.label == f"{OBSERVE_CLOSE} {runner}"]
    assert len(opens) == len(closes), transcript.marks
    chats = [
        event.t_ns
        for event in transcript.events
        if event.bot == runner
        and event.packet.direction is Direction.CLIENTBOUND
        and event.packet.name in CHAT
    ]
    windows = []
    previous = 0
    for opened, closed in zip(opens, closes, strict=True):
        assert opened.t_ns <= closed.t_ns
        inside = [s for s in everything if opened.t_ns <= s.t_ns <= closed.t_ns]
        heard = [t for t in chats if opened.t_ns <= t <= closed.t_ns]
        windows.append(
            Window(
                label=opened.label,
                before=tuple(
                    s.text
                    for s in everything
                    if s.bot == CONTROL and previous <= s.t_ns < opened.t_ns
                ),
                runner=tuple(s for s in inside if s.bot == runner),
                others=tuple(s for s in inside if s.bot != runner),
                heard=len(heard),
                first_heard_ns=min(heard, default=0),
            )
        )
        previous = closed.t_ns
    after = tuple(s.text for s in everything if s.bot == CONTROL and s.t_ns > previous)
    return Play(tuple(windows), after, transcript)


async def replay(group_id: str, server: CommandsServer) -> Play:
    """Play `group_id` against `server`; return what was read from its Transcript."""
    transcript = Transcript(group_id=group_id, server="fake")
    async with playing(server, transcript) as context:
        await GROUPS[group_id].run(context)
    return read(transcript, PLANS[group_id].runner)


_PLAYS: dict[tuple[str, bool], Play] = {}
"""Each Group's play against `server_for`, on time and late; no test changes it."""


async def play(group_id: str, *, late: bool = False) -> Play:
    """The play of `group_id` against a default fake server, played the first time it is asked."""
    if (group_id, late) not in _PLAYS:
        server = server_for(group_id, late_s=LATE_S if late else 0.0)
        _PLAYS[group_id, late] = await replay(group_id, server)
    return _PLAYS[group_id, late]


@pytest.mark.asyncio
async def test_the_tests_of_a_group_share_one_play_of_it() -> None:
    """A play takes seconds (the fake's ticks are real), so a Group is played once per process."""
    assert await play(GROUP_IDS[0]) is await play(GROUP_IDS[0])


@pytest.mark.parametrize("group_id", GROUP_IDS)
def test_each_group_is_exact_with_no_prerequisites_or_masks(group_id: str) -> None:
    group = GROUPS[group_id]

    assert group.kind is GroupKind.EXACT
    assert group.requires == ()
    assert group.masks == ()


@pytest.mark.parametrize("group_id", GROUP_IDS)
def test_each_group_plays_on_normal_difficulty_with_the_operators_added(group_id: str) -> None:
    default = ServerSpec(host="127.0.0.1", port=25566)
    spec = GROUPS[group_id].spec

    assert spec(default).operators == (commands.COMMANDER, commands.WITNESS)
    assert spec(default).difficulty is Difficulty.NORMAL
    assert spec(replace(default, operators=("alice",))).operators == (
        "alice",
        commands.COMMANDER,
        commands.WITNESS,
    )
    assert spec(default) == GROUPS[GROUP_IDS[0]].spec(default)  # one Instance pair for all


@pytest.mark.asyncio
@pytest.mark.parametrize("group_id", GROUP_IDS)
async def test_the_runner_sends_each_command_in_a_window_of_its_own(group_id: str) -> None:
    result = await play(group_id)
    plan = PLANS[group_id]

    assert [[s.text for s in window.runner] for window in result.windows] == [
        [want.command, *want.then, *([END] if want.marker else [])] for want in plan.windows
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("group_id", GROUP_IDS)
async def test_a_message_command_is_sent_signed_and_the_others_are_not(group_id: str) -> None:
    result = await play(group_id)

    kinds = [window.runner[0].packet for window in result.windows]
    assert kinds == [SIGNED if want.signed else CHAT_COMMAND for want in PLANS[group_id].windows]


@pytest.mark.asyncio
@pytest.mark.parametrize("group_id", GROUP_IDS)
async def test_each_window_compares_the_chat_and_the_effects_of_its_command(group_id: str) -> None:
    result = await play(group_id)

    assert [window.label for window in result.windows] == [
        f"{OBSERVE_OPEN} {' '.join((*CHAT, *want.effects))}" for want in PLANS[group_id].windows
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("group_id", GROUP_IDS)
async def test_control_sets_each_window_up_before_it_opens_and_runs_nothing_inside(
    group_id: str,
) -> None:
    result = await play(group_id)
    plan = PLANS[group_id]

    start = fixture_start(plan.bots)
    assert result.windows[0].before == (*start, *plan.windows[0].setup)
    assert [window.before for window in result.windows[1:]] == [
        want.setup for want in plan.windows[1:]
    ]
    assert [window.others for window in result.windows] == [()] * len(result.windows)


@pytest.mark.asyncio
@pytest.mark.parametrize("group_id", GROUP_IDS)
async def test_control_undoes_everything_after_the_last_window(group_id: str) -> None:
    result = await play(group_id)
    plan = PLANS[group_id]

    assert result.after == (*plan.undo, *fixture_end(plan.bots))


@pytest.mark.asyncio
@pytest.mark.parametrize("group_id", GROUP_IDS)
async def test_every_bot_passes_the_barrier_after_it_joins_and_before_control_moves_it(
    group_id: str,
) -> None:
    # Pumpkin kicked a Bot whose join teleport it had not handled when Control's `tp` ran.
    result = await play(group_id)
    commands_sent = sent(result.transcript)

    for bot in PLANS[group_id].bots:
        moved = min(s.t_ns for s in commands_sent if s.text.startswith(f"tp {bot} "))
        barrier = [
            event
            for event in result.transcript.events
            if event.bot == bot
            and event.t_ns < moved
            and event.packet.name == CLIENT_COMMAND
            and event.packet.direction is Direction.SERVERBOUND
        ]
        assert len(barrier) >= SYNC_REQUESTS, bot


@pytest.mark.asyncio
@pytest.mark.parametrize("group_id", GROUP_IDS)
async def test_the_bots_that_do_not_run_the_commands_send_none(group_id: str) -> None:
    result = await play(group_id)
    plan = PLANS[group_id]
    others = {s.bot for s in sent(result.transcript)} - {CONTROL, plan.runner}

    assert others == set()


@pytest.mark.asyncio
@pytest.mark.parametrize("group_id", GROUP_IDS)
async def test_each_window_waits_for_all_the_chat_it_expects_when_the_server_is_late(
    group_id: str,
) -> None:
    # The runner's barrier does not cover a chat command on a server behind schedule, so the
    # window waits, in its body, for the messages, or for the marker that follows the command.
    late = await play(group_id, late=True)

    assert [window.heard for window in late.windows] == [
        want.heard for want in PLANS[group_id].windows
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("group_id", GROUP_IDS)
async def test_a_command_that_follows_another_is_sent_before_the_first_is_answered(
    group_id: str,
) -> None:
    # Vanilla runs a player's commands one after another; Pumpkin answers each in a task of its
    # own, so the order of the answers shows only if the second leaves at once.
    late = await play(group_id, late=True)

    following = [
        (window, want)
        for window, want in zip(late.windows, PLANS[group_id].windows, strict=True)
        if want.then
    ]
    for window, _ in following:
        assert len(window.runner) == 2
        assert all(s.t_ns < window.first_heard_ns for s in window.runner)


@pytest.mark.asyncio
@pytest.mark.parametrize("group_id", GROUP_IDS)
async def test_control_undoes_its_settings_when_a_window_never_gets_its_answer(
    group_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(commands, "ANSWER_TIMEOUT_S", 0.3)
    plan = PLANS[group_id]
    hang = plan.windows[-1].command
    transcript = Transcript(group_id=group_id, server="fake")
    async with playing(server_for(group_id, silent=hang), transcript) as context:
        with pytest.raises(TimeoutError):
            await GROUPS[group_id].run(context)

    control = tuple(s.text for s in sent(transcript) if s.bot == CONTROL)
    assert control[-len(plan.undo) - len(fixture_end(plan.bots)) :] == (
        *plan.undo,
        *fixture_end(plan.bots),
    )
    runner = [s.text for s in sent(transcript) if s.bot == plan.runner]
    assert runner[-1 - len(plan.windows[-1].then)] == hang  # it did not go on past the hang


@pytest.mark.parametrize("group_id", GROUP_IDS)
def test_every_packet_a_window_compares_has_a_title(group_id: str) -> None:
    names = {name for want in PLANS[group_id].windows for name in (*CHAT, *want.effects)}
    shown = {name.removeprefix("minecraft:") for name in names}

    titled = {key.split(".")[0] for key in TITLES}
    assert sorted(shown - titled) == []


def test_permissions_runs_as_a_player_who_is_not_an_operator() -> None:
    default = ServerSpec(host="127.0.0.1", port=25566)

    assert commands.PLAYER not in GROUPS["commands/permissions"].spec(default).operators


@pytest.mark.asyncio
async def test_permissions_sends_no_more_commands_than_a_player_may_before_the_spam_kick() -> None:
    # Vanilla kicks a player who is not an operator at its 10th command in about a second.
    result = await play("commands/permissions")

    mine = [s for s in sent(result.transcript) if s.bot == commands.PLAYER]
    assert len(mine) <= chat_groups.UNDER_SPAM_MESSAGES
