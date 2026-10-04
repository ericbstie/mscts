"""Groups: named, deterministic scripts a Run plays against each Instance.

A Group sets the world up through Control (`GroupContext.control`), whose Bot, `control`,
is an operator on every Instance. A Group's own Bots stay non-operators unless the
mechanic it tests needs one: vanilla sends each operator's command feedback to the other
operators (`CommandSourceStack.broadcastToAdmins`, while the `send_command_feedback`
game rule is on), so an operator Bot would receive Control's answers too.
"""

import asyncio
import contextlib
import functools
import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Protocol

from mscts.bot import Bot
from mscts.codec.packets import Codec, Direction, Packet, State
from mscts.codec.schemas.play.commands import root_literals
from mscts.compare import HEARTBEAT, OBSERVE_CLOSE, OBSERVE_NO_PLAY, OBSERVE_OPEN, TICK_MARK, Mask
from mscts.net import Endpoint, ProtocolError
from mscts.spec import CONTROL_PLAYER, ServerSpec
from mscts.target import TARGET
from mscts.transcript import Mark, Transcript

LOG = logging.getLogger(__name__)


class GroupKind(StrEnum):
    """How a Group is judged (ADR-0006)."""

    EXACT = "exact"
    """Deterministic, diffed packet by packet."""
    TICK_EXACT = "tick-exact"
    """Deterministic mechanics observed tick by tick under a frozen and stepped world."""
    STATISTICAL = "statistical"
    """Random mechanics, run N times per server and compared as distributions."""


class CommandMissing(Exception):  # noqa: N818 - PLAN's name: a fact about the server, not a bug
    """The server has no command `root`, so Control did not send it.

    A Run reports a Group the Candidate raises it on as the Candidate's failure, naming the
    command (`missing /tick`); on the Reference, it is an `error`.

    Attributes:
        root: The command's first word, e.g. `tick`.
    """

    def __init__(self, root: str) -> None:
        """Say the server has no command `root`."""
        super().__init__(f"the server has no /{root} command")
        self.root = root


class Control(Protocol):
    """The channel that sets up Fixtures: by default, an Operator Bot (ADR-0001)."""

    async def run(self, command: str) -> tuple[Packet, ...]:
        """Run `command`, in vanilla command syntax, without the leading slash.

        Returns once the server has answered it, with the `system_chat`s it answered with.
        """
        ...

    async def leave(self) -> None:
        """Close Control's Bot, if it has joined.

        The next `run` joins a new Bot, and passes the barrier first, as on first use. A
        server removes a closed Bot's player a tick later, so a Group that needs the
        server empty waits with `mscts.settle.until_no_player_online`.
        """
        ...


MARKER_PREFIX = "mscts-barrier-"
"""The start of each token Control's barrier says to itself (`tellraw`)."""

_SYSTEM_CHAT = "minecraft:system_chat"
_COMMANDS = "minecraft:commands"


class OperatorBot:
    """Control through a Bot called `control` (`spec.CONTROL_PLAYER`), an operator.

    Every Adapter makes `control` an operator, so it may run any command.
    """

    def __init__(
        self, connect: Callable[[str], Awaitable[Bot]], transcript: Transcript, *, timeout_s: float
    ) -> None:
        """Connect its Bot with `connect` on first use; read its tree from `transcript`."""
        self._connect = connect
        self._transcript = transcript
        self._timeout_s = timeout_s
        self._bot: Bot | None = None
        self._joined_ns = 0
        self._markers = 0

    async def run(self, command: str) -> tuple[Packet, ...]:
        """Run `command` as `control`, and return once the server has answered it.

        On first use, and the first after `leave`, a new Bot joins and passes the barrier
        (`Bot.sync`), so that nothing the join caused is taken for an answer. Each run
        then sends `command`, then a
        marker, `tellraw @s "<token>"` with a token of its own, and waits for the
        `system_chat` holding the token: vanilla runs a
        player's commands one after another, so the command has run by then. Last, the
        Bot passes the barrier, so the server has also sent what the command changed.

        Returns:
            Every `system_chat` that arrived from sending `command` to the end of the
            barrier, but the marker's answer, in order of arrival; an empty tuple if none.
            That is what the server said in answer, and it can include messages that are
            not the command's, such as a join message. Pumpkin answers a player's
            commands out of order, so its answer often comes after the marker's. It is
            evidence for the Group, not a test case: no Comparison compares it.

        Raises:
            ValueError: `command` does not start with its name (it is empty, or starts
                with a slash or a space).
            CommandMissing: The server's command tree for `control` lacks the command's
                name, or `tellraw`, which the marker needs. Nothing is sent.
            ProtocolError: The command tree is broken, or the server disconnected the Bot.
            TimeoutError: No command tree, or no answer to the marker, in time.
        """
        root = command.split(" ", 1)[0]
        if not root or root.startswith("/"):
            msg = f"a command starts with its name, without a slash: {command!r}"
            raise ValueError(msg)
        bot = await self._joined()
        commands = await self._commands(bot)
        for name in (root, "tellraw"):
            if name not in commands:
                raise CommandMissing(name)
        self._markers += 1
        token = f"{MARKER_PREFIX}{self._markers}".encode()
        since = self._transcript.now_ns()
        await bot.command(command)
        await bot.command(f'tellraw @s "{token.decode()}"')
        # Text components are not decoded yet, so the token is looked for in the raw bytes:
        # a String tag, or a compound's text, holds it as it was sent.
        marker = await bot.expect(
            _SYSTEM_CHAT, timeout_s=self._timeout_s, where=lambda packet: token in packet.payload
        )
        await bot.sync()
        return tuple(
            event.packet
            for event in self._transcript.events
            if event.bot == bot.name
            and event.t_ns >= since
            and event.packet.direction is Direction.CLIENTBOUND
            and event.packet.name == _SYSTEM_CHAT
            and event.packet is not marker
        )

    async def leave(self) -> None:
        """Close Control's Bot, if it has joined; the next `run` joins a new one.

        The new Bot passes the barrier first and reads the command tree its own join
        sent, as Control's first Bot did. A server removes a closed Bot's player later
        (vanilla on its next tick): wait with `mscts.settle.until_no_player_online` if the
        server must be empty. Calling it with no Bot joined does nothing.
        """
        if self._bot is not None:
            bot, self._bot = self._bot, None
            await bot.close()

    async def _joined(self) -> Bot:
        if self._bot is None:
            self._joined_ns = self._transcript.now_ns()
            bot = await self._connect(CONTROL_PLAYER)
            await bot.join()
            await bot.sync()
            self._bot = bot
        return self._bot

    async def _commands(self, bot: Bot) -> frozenset[str]:
        """The names of the commands the last command tree the Bot received holds."""
        trees = [
            event.packet
            for event in self._transcript.events
            if event.bot == bot.name
            and event.t_ns >= self._joined_ns  # not the tree a Bot that left was sent
            and event.packet.direction is Direction.CLIENTBOUND
            and event.packet.name == _COMMANDS
        ]
        tree = trees[-1] if trees else await bot.expect(_COMMANDS, timeout_s=self._timeout_s)
        try:
            return root_literals(tree.fields or {})
        except (KeyError, ValueError) as exc:
            error = ProtocolError(f"the command tree {bot.name} received is broken: {exc}")
            bot.failure = error
            raise error from exc


def identity(spec: ServerSpec) -> ServerSpec:
    """Leave the ServerSpec as it is: a Group's default `spec`."""
    return spec


class GroupContext:
    """What a Group's script works with, against one Instance.

    Attributes:
        endpoint: Where the Instance is reached.
        left_frozen: The Group froze the world, and `end` or `close` could not unfreeze
            it: the Instance is not fit for another Group (#228).
    """

    def __init__(self, endpoint: Endpoint, transcript: Transcript, *, timeout_s: float) -> None:
        """Play against `endpoint`, recording to `transcript`, each Bot bounded by `timeout_s`."""
        self.endpoint = endpoint
        self._transcript = transcript
        self._timeout_s = timeout_s
        self._bots: dict[str, Bot] = {}
        self._unconnected: tuple[str, Exception] | None = None
        self._observing = False
        self._ticks: int | None = None  # the ticks stepped since the freeze; None: not frozen
        self.left_frozen = False
        self._control = OperatorBot(self._connect, transcript, timeout_s=timeout_s)

    @property
    def control(self) -> Control:
        """The Control channel: an Operator Bot, called `control`, that joins on first use."""
        return self._control

    async def bot(self, name: str) -> Bot:
        """Connect a Bot called `name`, recording to this Group's Transcript.

        Raises:
            ValueError: This Group already has a Bot called `name`, or `name` is
                `control`, Control's Bot.
            OSError: The connection failed.
            TimeoutError: It did not connect in time.
        """
        if name == CONTROL_PLAYER:
            msg = f"{name!r} is Control's Bot: run its commands with context.control"
            raise ValueError(msg)
        return await self._connect(name)

    async def _connect(self, name: str) -> Bot:
        previous = self._bots.get(name)
        if previous is not None and not (name == CONTROL_PLAYER and previous.closed):
            msg = f"the Group already has a Bot called {name!r}"
            raise ValueError(msg)
        try:
            bot = await Bot.connect(
                self.endpoint,
                TARGET,
                name=name,
                transcript=self._transcript,
                timeout_s=self._timeout_s,
            )
        except Exception as error:
            self._unconnected = (name, error)
            raise
        self._bots[name] = bot
        return bot

    def raised_by(self, error: BaseException) -> str:
        """The name of the Bot `error` came out of (connecting, or an operation), else ""."""
        if self._unconnected is not None and self._unconnected[1] is error:
            return self._unconnected[0]
        for name, bot in self._bots.items():
            if bot.failure is error:
                return name
        return ""

    @contextlib.asynccontextmanager
    async def span(self, name: str) -> AsyncIterator[None]:
        """Mark `<name>:start` on entry and `<name>:end` when the body completes.

        A body that raises gets no end Mark, so a failed span yields no Measurement.
        """
        self._mark(f"{name}:start")
        yield
        self._mark(f"{name}:end")

    @contextlib.asynccontextmanager
    async def observe(
        self, *names: str, until: str | None = None, bot: Bot | None = None, play: bool = True
    ) -> AsyncIterator[None]:
        """Compare only what the Bots receive inside the block: an Observation window.

        On entry, every Bot in play passes the barrier (`Bot.sync`), all at once, so what
        the setup before the window caused has arrived at every Bot, not only at Control's,
        provided the setup waited for its feedback (`Control.run` does: the server runs a
        chat command between ticks, after the barrier's pass);
        then the window gets its `observe:open` Mark, followed by `names`, each after a
        space. When the body completes, every Bot in play passes the barrier again, all at
        once. Each Bot's window ends at its own barrier: it gets the Mark `observe:close
        <Bot name>` a nanosecond after its barrier's last answer arrived, whatever the other
        Bots are still waiting for (a Bot that passes none gets it once every barrier has
        returned). Once every barrier has returned, the Mark `observe:close` ends the
        window for any Bot the Group makes later. Then every Bot not closed takes what
        has already arrived, without waiting (`Bot.drain`). A Bot whose `expect` returned
        the server's disconnect (`Bot.disconnected`, as a Group that tests a kick does)
        passes no barrier and takes nothing; a disconnect the barrier or the drain takes
        fails the Bot. A body that raises gets no barrier at its end and no close Mark:
        its window runs to the end of the Transcript.

        A barrier covers what the Bot itself sent. A window that must hold what another
        Bot's action causes at this Bot waits, in its body, for that action's feedback
        before it closes, as `OperatorBot.run` does for a command.

        With `until`, there is no barrier at the end. Every Bot not closed takes what has already
        arrived, and the window closes when the first play packet called `until` arrived
        at any Bot but Control after the window opened. Its Mark is stamped a nanosecond
        after that arrival (not after the time the Bot took the packet). So the window
        holds the packet and everything that arrived before it, and none of what arrived
        after it, not even a frame that came in the same read of the socket. The body
        must last until the packet has arrived (`Bot.join` does, for a join's packets): a
        body that ends sooner fails with the ProtocolError below.

        With `bot` too, only that Bot's `until` packet ends the window. Without it, with
        more than one Bot, where the window ends for the others is timing: each Bot's
        reader stamps a frame when it reads its own socket, and the readers run one after
        another, so a packet that reached one Bot's socket first can be stamped later.

        With `play=False`, the window compares no play packet, only the packets of the other
        States (login, configuration, status), for a Group whose play packets vary.

        Args:
            names: The only packets the window compares, e.g. `minecraft:block_update`;
                none for every packet.
            until: The name of the packet whose arrival ends the window, e.g.
                `minecraft:chunk_batch_finished`; None for a window that ends at the
                barrier.
            bot: The Bot whose `until` packet ends the window; None for any Bot but
                Control.
            play: False for a window that compares no play packet; then neither `names` nor
                `until` can be given.

        Raises:
            ValueError: A window is open already (windows do not nest), or a name (in
                `names` or `until`) is not a packet the Target's server sends in play,
                or is a heartbeat packet (`HEARTBEAT`), which no window compares; or
                `bot` is given without `until`, or is not one of this Group's Bots; or
                `play` is False and `names` or `until` is given.
            TimeoutError: A Bot's barrier got no answer in time; the Bot's `failure`.
            ProtocolError: The server disconnected a Bot, and the barrier or the drain
                took the disconnect; or no `until` packet arrived inside the window.
        """
        if self._observing:
            msg = "the Group is in an Observation window already: windows do not nest"
            raise ValueError(msg)
        if not play and (names or until is not None):
            msg = "play=False compares no play packet: give no names and no until with it"
            raise ValueError(msg)
        for name in (*names, *(() if until is None else (until,))):
            _check_observable(name)
        if bot is not None and until is None:
            msg = "bot= names the Bot whose until packet ends the window: give until too"
            raise ValueError(msg)
        if bot is not None and self._bots.get(bot.name) is not bot:
            msg = f"{bot.name!r} is not one of this Group's Bots"
            raise ValueError(msg)
        self._observing = True
        try:
            # What setup caused may still be on its way to a Bot that is not Control: the
            # barrier first, so it arrives before the window opens on every Instance.
            await self._sync()
            opened = self._mark(" ".join((OBSERVE_OPEN, *(names if play else (OBSERVE_NO_PLAY,)))))
            yield
            if until is None:
                self._mark_each(OBSERVE_CLOSE, await self._sync())
                await self._drain()
            else:
                await self._drain()
                # Compare puts a packet stamped at a Mark's time after the Mark, so the Mark
                # goes a nanosecond after the arrival. A Connection stamps the frames of one
                # read a nanosecond apart, so that is just before the next frame.
                arrival = self._arrival_of(until, since=opened, bot=bot)
                self._mark(OBSERVE_CLOSE, t_ns=arrival + 1)
        finally:
            self._observing = False

    async def freeze(self) -> None:
        """Freeze the world, through Control (`tick freeze`), for a tick-exact Group.

        Returns once the server has run the command (`Control.run`). The world stays
        frozen until the Group ends: `end` unfreezes it (`tick unfreeze`), and a failure to
        fails the Group; if the Group failed first, `close` tries. So the next Group does
        not start in a frozen world.

        Raises:
            ValueError: The Group has frozen the world already.
            CommandMissing: The server has no `/tick`.
            TimeoutError: The server did not answer in time.
        """
        if self._ticks is not None:
            msg = "the Group has frozen the world already"
            raise ValueError(msg)
        self._ticks = 0  # set first: a command that timed out may still have run
        await self._control.run("tick freeze")

    async def step(self, ticks: int = 1) -> None:
        """Move the frozen world on `ticks` ticks, one at a time, and return once they ran.

        Each tick is `tick step 1` through Control, which returns once the server has run
        the command and then passed the barrier, so the stepped tick has sent what it
        changed. Then every Bot in play passes the barrier, all at once, as at a window's
        close, and gets the Mark `tick:<k> <Bot name>` a nanosecond after its barrier's
        last answer arrived; k counts the ticks stepped since the freeze, from 1. Once
        every barrier has returned, the Mark `tick:<k>` follows, for a Bot made later.
        Vanilla sends no packet when a step ends (docs/research/2026-10-03-tick-step.md),
        so the barrier is how a step is known to have ended.

        Raises:
            ValueError: `ticks` is less than 1, or the Group has not frozen the world.
            TimeoutError: The server did not finish a step in time; that Bot's `failure`.
            ProtocolError: The server disconnected a Bot, and a barrier took it.
        """
        if ticks < 1:
            msg = f"a step moves the world on at least one tick, not {ticks}"
            raise ValueError(msg)
        if self._ticks is None:
            msg = "freeze the world first (context.freeze()): only a frozen world steps"
            raise ValueError(msg)
        for _ in range(ticks):
            await self._control.run("tick step 1")
            ends = await self._sync()
            self._ticks += 1
            self._mark_each(f"{TICK_MARK}{self._ticks}", ends)

    async def end(self) -> None:
        """Unfreeze the world if the Group froze it, then refuse a disconnect still queued.

        Called once the Group's script has completed, before the Bots close (`run_group`).
        A world left frozen would spoil every later Group on the Instance, so an unfreeze
        that fails fails the Group and sets `left_frozen`. A disconnect nothing took (it
        came after the last barrier, drain or `expect`) fails its Bot
        (`Bot.refuse_queued_disconnect`), so a Candidate that kicks a Bot late does not pass.

        Raises:
            TimeoutError: The server did not answer `tick unfreeze` in time.
            ProtocolError: The server disconnected a Bot; the Bot's `failure`.
        """
        if self._ticks is not None:
            self._ticks = None
            try:
                await self._control.run("tick unfreeze")
            except BaseException:
                self.left_frozen = True
                raise
        for bot in self._bots.values():
            await bot.refuse_queued_disconnect()

    async def close(self) -> None:
        """Unfreeze the world if it is still frozen, then close every Bot.

        The world is still frozen only if the Group failed before `end`, so a failure to
        unfreeze here is logged, not raised: the Group's own error says more, and has
        failed the Group already. It sets `left_frozen`, so the Run plays no other Group
        on the Instance. Calling it again does nothing.
        """
        if self._ticks is not None:
            self._ticks = None
            try:
                await self._control.run("tick unfreeze")
            except Exception as error:
                self.left_frozen = True
                LOG.warning("could not unfreeze the world after the Group", exc_info=error)
        for bot in self._bots.values():
            await bot.close()

    def _mark(self, label: str, *, t_ns: int | None = None) -> int:
        """Record a Mark at `t_ns`, by default now; return when it is."""
        at = self._transcript.now_ns() if t_ns is None else t_ns
        self._transcript.marks.append(Mark(t_ns=at, label=label))
        return at

    def _mark_each(self, label: str, ends: Mapping[str, int]) -> None:
        """Mark `<label> <Bot name>` for each Bot, then `label` alone, which is now.

        A Bot's Mark is a nanosecond after its barrier's last answer arrived (`ends`): a
        packet stamped at a Mark's time is after it, so the answer is before the Mark. A
        Bot that passed no barrier gets its Mark now. The Mark with no name ends the same
        span for a Bot the Group makes later.
        """
        now = self._transcript.now_ns()
        for name in self._bots:
            self._mark(f"{label} {name}", t_ns=ends[name] + 1 if name in ends else now)
        self._mark(label, t_ns=now)

    def _arrival_of(self, name: str, *, since: int, bot: Bot | None) -> int:
        """When the first play packet `name` arrived at `bot`, at or after `since`.

        With no `bot`, at any Bot but Control: Control's receipts are never compared, so
        they cannot end a window. A Bot records a frame when it takes it, so this is the
        earliest arrival over all the Bots, whatever order they were recorded in.

        Raises:
            ProtocolError: None did.
        """
        arrivals = [
            event.t_ns
            for event in self._transcript.events
            if event.t_ns >= since
            and (event.bot == bot.name if bot is not None else event.bot != CONTROL_PLAYER)
            and event.packet.name == name
            and event.packet.state is State.PLAY
            and event.packet.direction is Direction.CLIENTBOUND
        ]
        if not arrivals:
            at = "any Bot" if bot is None else bot.name
            msg = f"no {name} arrived at {at} after the Observation window opened"
            raise ProtocolError(msg)
        return min(arrivals)

    async def _drain(self) -> None:
        """Take what has already arrived at every Bot not closed, without waiting.

        A Bot whose `expect` returned the server's disconnect is skipped: the server sends
        it nothing more. A disconnect the drain takes fails the Bot (`Bot.drain`).
        """
        for bot in self._bots.values():
            if not bot.closed and not bot.disconnected:
                await bot.drain()

    async def _sync(self) -> dict[str, int]:
        """Pass the barrier on every Bot in play at once; raise the first Bot's error.

        A Bot whose `expect` returned the server's disconnect passes none: one the Group
        did not take is still queued, so that Bot's barrier takes it and fails. Returns when each
        Bot's barrier's last answer arrived, by the Bot's name.
        """

        async def barrier(bot: Bot) -> int:
            await bot.sync()
            # The last packet sync took is its last answer, the Bot's latest award_stats.
            return next(
                event.t_ns
                for event in reversed(self._transcript.events)
                if event.bot == bot.name
                and event.packet.name == _ANSWER
                and event.packet.direction is Direction.CLIENTBOUND
            )

        try:
            async with asyncio.TaskGroup() as barriers:
                tasks = {
                    name: barriers.create_task(barrier(bot))
                    for name, bot in self._bots.items()
                    if bot.in_play and not bot.disconnected
                }
        except ExceptionGroup as errors:
            raise errors.exceptions[0] from None
        return {name: task.result() for name, task in tasks.items()}


_ANSWER = "minecraft:award_stats"
"""The barrier's answer (`Bot.sync`)."""


@functools.cache
def _play_names() -> frozenset[str]:
    """The names of the packets the Target's server sends in play."""
    return frozenset(Codec.for_target(TARGET).names(State.PLAY, Direction.CLIENTBOUND))


def _check_observable(name: str) -> None:
    """Raise ValueError unless a window can compare packet `name` (audit 2026-10-02, MD1).

    A window narrowed to, or ended by, a name the server never sends would compare
    nothing on either side, and match.
    """
    if name not in _play_names():
        msg = f"{name!r} is not a packet the server sends in play, e.g. 'minecraft:block_update'"
        raise ValueError(msg)
    if name in HEARTBEAT:
        msg = f"{name!r} is a heartbeat packet, which no window compares: {HEARTBEAT[name]}"
        raise ValueError(msg)


type Script = Callable[[GroupContext], Awaitable[None]]
"""A Group's script: what it does against one Instance."""


@dataclass(frozen=True, slots=True)
class Group:
    """A deterministic, named script that runs against one Instance.

    Attributes:
        id: The Group's name, e.g. `status/basic`.
        run: The script.
        requires: Group ids that must `match` first; otherwise this one is `blocked`.
        masks: What its Comparison excludes, each with a reason that shows it has no
            gameplay meaning (ADR-0006).
        spec: How it changes the Run's ServerSpec.
        kind: How it is judged (ADR-0006).
    """

    id: str
    run: Script
    requires: tuple[str, ...] = ()
    masks: tuple[Mask, ...] = ()
    spec: Callable[[ServerSpec], ServerSpec] = identity
    kind: GroupKind = GroupKind.EXACT


_REGISTERED: dict[str, Group] = {}

GROUPS: Mapping[str, Group] = MappingProxyType(_REGISTERED)
"""The registered Groups, by id, in registration order (a read-only view).

`@group` registers each; mscts's own are registered as `mscts.groups` is imported.
"""


def group(
    id: str,  # noqa: A002 - the Group's id, as PLAN names it
    *,
    requires: tuple[str, ...] = (),
    masks: tuple[Mask, ...] = (),
    spec: Callable[[ServerSpec], ServerSpec] = identity,
    kind: GroupKind = GroupKind.EXACT,
) -> Callable[[Script], Script]:
    """Return a decorator that registers its function as the script of Group `id`.

    The decorator returns the function itself, and raises ValueError if a Group
    called `id` is registered already.
    """

    def register(run: Script) -> Script:
        if id in _REGISTERED:
            msg = f"a Group called {id!r} is registered already"
            raise ValueError(msg)
        _REGISTERED[id] = Group(
            id=id, run=run, requires=requires, masks=masks, spec=spec, kind=kind
        )
        return run

    return register


def resolve(group_ids: Iterable[str], groups: Mapping[str, Group] = GROUPS) -> tuple[Group, ...]:
    """The Groups `group_ids` name in `groups`, with their prerequisites, each once.

    Every Group comes after its prerequisites; otherwise the order is as given.

    Raises:
        KeyError: An id, or a prerequisite, is not in `groups`.
        ValueError: The prerequisites form a cycle.
    """
    resolved: dict[str, Group] = {}
    visiting: list[str] = []

    def visit(group_id: str) -> None:
        if group_id in resolved:
            return
        if group_id in visiting:
            cycle = " -> ".join([*visiting[visiting.index(group_id) :], group_id])
            msg = f"the prerequisites form a cycle: {cycle}"
            raise ValueError(msg)
        if group_id not in groups:
            msg = f"no Group is registered as {group_id!r}"
            raise KeyError(msg)
        visiting.append(group_id)
        for prerequisite in groups[group_id].requires:
            visit(prerequisite)
        visiting.pop()
        resolved[group_id] = groups[group_id]

    for group_id in group_ids:
        visit(group_id)
    return tuple(resolved.values())
