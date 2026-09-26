"""Scenarios: named, deterministic scripts a Run plays against each Instance."""

import contextlib
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Protocol

from mscts.bot import Bot
from mscts.compare import Mask
from mscts.net import Endpoint
from mscts.spec import ServerSpec
from mscts.target import TARGET
from mscts.transcript import Mark, Transcript


class ScenarioKind(StrEnum):
    """How a Scenario is judged (ADR-0006)."""

    EXACT = "exact"
    """Deterministic, diffed packet by packet."""
    TICK_EXACT = "tick-exact"
    """Deterministic mechanics observed tick by tick under a frozen and stepped world."""
    STATISTICAL = "statistical"
    """Random mechanics, run N times per server and compared as distributions."""


class Control(Protocol):
    """The channel that sets up Fixtures: by default, an Operator Bot (ADR-0001)."""

    async def run(self, command: str) -> None:
        """Run `command`, in vanilla command syntax, without the leading slash."""
        ...


def identity(spec: ServerSpec) -> ServerSpec:
    """Leave the ServerSpec as it is: a Scenario's default `spec`."""
    return spec


class ScenarioContext:
    """What a Scenario's script works with, against one Instance.

    Attributes:
        endpoint: Where the Instance is reached.
    """

    def __init__(self, endpoint: Endpoint, transcript: Transcript, *, timeout_s: float) -> None:
        """Play against `endpoint`, recording to `transcript`, each Bot bounded by `timeout_s`."""
        self.endpoint = endpoint
        self._transcript = transcript
        self._timeout_s = timeout_s
        self._bots: dict[str, Bot] = {}
        self._unconnected: tuple[str, Exception] | None = None

    @property
    def control(self) -> Control:
        """The Control channel. Not built yet: no Scenario needs Fixtures before M5.

        Raises:
            NotImplementedError: Always, until M5 builds the Operator Bot.
        """
        msg = "Control (the Operator Bot) arrives in milestone M5"
        raise NotImplementedError(msg)

    async def bot(self, name: str) -> Bot:
        """Connect a Bot called `name`, recording to this Scenario's Transcript.

        Raises:
            ValueError: This Scenario already has a Bot called `name`.
            OSError: The connection failed.
            TimeoutError: It did not connect in time.
        """
        if name in self._bots:
            msg = f"the Scenario already has a Bot called {name!r}"
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

    async def close(self) -> None:
        """Close every Bot. Calling it again does nothing."""
        for bot in self._bots.values():
            await bot.close()

    def _mark(self, label: str) -> None:
        self._transcript.marks.append(Mark(t_ns=self._transcript.now_ns(), label=label))


type Script = Callable[[ScenarioContext], Awaitable[None]]
"""A Scenario's script: what it does against one Instance."""


@dataclass(frozen=True, slots=True)
class Scenario:
    """A deterministic, named script that runs against one Instance.

    Attributes:
        id: The Scenario's name, e.g. `status/basic`.
        run: The script.
        requires: Scenario ids that must `match` first; otherwise this one is `blocked`.
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
    kind: ScenarioKind = ScenarioKind.EXACT


_REGISTERED: dict[str, Scenario] = {}

SCENARIOS: Mapping[str, Scenario] = MappingProxyType(_REGISTERED)
"""The registered Scenarios, by id, in registration order (a read-only view).

`@scenario` registers each; mscts's own are registered as `mscts.scenarios` is imported.
"""


def scenario(
    id: str,  # noqa: A002 - the Scenario's id, as PLAN names it
    *,
    requires: tuple[str, ...] = (),
    masks: tuple[Mask, ...] = (),
    spec: Callable[[ServerSpec], ServerSpec] = identity,
    kind: ScenarioKind = ScenarioKind.EXACT,
) -> Callable[[Script], Script]:
    """Return a decorator that registers its function as the script of Scenario `id`.

    The decorator returns the function itself, and raises ValueError if a Scenario
    called `id` is registered already.
    """

    def register(run: Script) -> Script:
        if id in _REGISTERED:
            msg = f"a Scenario called {id!r} is registered already"
            raise ValueError(msg)
        _REGISTERED[id] = Scenario(
            id=id, run=run, requires=requires, masks=masks, spec=spec, kind=kind
        )
        return run

    return register


def resolve(
    scenario_ids: Iterable[str], scenarios: Mapping[str, Scenario] = SCENARIOS
) -> tuple[Scenario, ...]:
    """The Scenarios `scenario_ids` name in `scenarios`, with their prerequisites, each once.

    Every Scenario comes after its prerequisites; otherwise the order is as given.

    Raises:
        KeyError: An id, or a prerequisite, is not in `scenarios`.
        ValueError: The prerequisites form a cycle.
    """
    resolved: dict[str, Scenario] = {}
    visiting: list[str] = []

    def visit(scenario_id: str) -> None:
        if scenario_id in resolved:
            return
        if scenario_id in visiting:
            cycle = " -> ".join([*visiting[visiting.index(scenario_id) :], scenario_id])
            msg = f"the prerequisites form a cycle: {cycle}"
            raise ValueError(msg)
        if scenario_id not in scenarios:
            msg = f"no Scenario is registered as {scenario_id!r}"
            raise KeyError(msg)
        visiting.append(scenario_id)
        for prerequisite in scenarios[scenario_id].requires:
            visit(prerequisite)
        visiting.pop()
        resolved[scenario_id] = scenarios[scenario_id]

    for scenario_id in scenario_ids:
        visit(scenario_id)
    return tuple(resolved.values())
