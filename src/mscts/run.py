"""Runs: Scenarios played against the Reference and a Candidate, judged into Verdicts."""

import asyncio
import contextlib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import mscts.scenarios  # noqa: F401 - importing it registers the shipped Scenarios
from mscts.adapters.base import Adapter, Installation
from mscts.bot import status_probe
from mscts.codec.packets import CodecError
from mscts.compare import ABSENT, Divergence, Outcome, Verdict, compare
from mscts.net import Endpoint, ProtocolError
from mscts.runner import free_endpoint, running
from mscts.scenario import Scenario, ScenarioContext, ScenarioKind, resolve
from mscts.spec import ServerSpec
from mscts.target import TARGET
from mscts.transcript import Transcript

SCENARIO_TIMEOUT_S = 10.0
"""How long each Bot operation of a Scenario may take (Bot's `timeout_s`)."""

READY_TIMEOUT_S = 120.0
"""How long an Instance may take to become ready: a cold vanilla boot unpacks and makes a world."""

STOP_TIMEOUT_S = 30.0
"""How long each step of stopping an Instance may take (runner.running's `stop_timeout`)."""

CANDIDATE_FAILURES: tuple[type[Exception], ...] = (
    CodecError,  # a frame that did not decode (recorded first, with its decode_error)
    ProtocolError,  # an answer that breaks the protocol's sequence or content
    TimeoutError,  # no answer in time
    ConnectionError,  # the connection was closed, reset or refused
)
"""What a Scenario raises when the Candidate caused it: a `mismatch`, never `error`."""

_SPEC_KEY_ENDPOINT = Endpoint(host="127.0.0.1", port=1)
"""The Endpoint a Scenario's `spec` is applied to only to tell which specs are equal."""


class ScenarioError(Exception):
    """A Scenario raised against one Instance. Its cause is what it raised.

    Attributes:
        transcript: Everything recorded until it raised.
    """

    def __init__(self, transcript: Transcript, description: str) -> None:
        """Record that the Scenario of `transcript` failed, as `description` says."""
        super().__init__(description)
        self.transcript = transcript


@dataclass(frozen=True, slots=True)
class Server:
    """One side of a Run: an Adapter with its Installation, from which Instances launch."""

    adapter: Adapter
    installation: Installation

    @property
    def name(self) -> str:
        """The Adapter's name, as the Transcripts record it."""
        return self.adapter.name


async def run_scenario(
    scenario: Scenario, endpoint: Endpoint, *, server: str, timeout_s: float = SCENARIO_TIMEOUT_S
) -> Transcript:
    """Play `scenario` against the Instance at `endpoint`, and return its Transcript.

    `server` is the Adapter's name, for the Transcript. Every Bot is closed at the end.

    Raises:
        ScenarioError: The Scenario raised; the error holds the Transcript so far.
    """
    transcript = Transcript(scenario_id=scenario.id, server=server)
    context = ScenarioContext(endpoint, transcript, timeout_s=timeout_s)
    try:
        await scenario.run(context)
    except Exception as exc:
        raise ScenarioError(transcript, _describe(exc, timeout_s)) from exc
    finally:
        await context.close()
    return transcript


def judge(
    scenario: Scenario,
    reference: Transcript | ScenarioError,
    candidate: Transcript | ScenarioError,
) -> Verdict:
    """The Verdict on `scenario`, from what it gave on the Reference and on the Candidate.

    What `compare` finds, with the Scenario's Masks, except:

    - The Candidate failed in a way it caused (`CANDIDATE_FAILURES`: its output did not
      decode, broke the protocol, never came, or its connection closed or was refused):
      `mismatch`, led by a `failed` Divergence that says what happened, then whatever
      the Comparison of the Transcripts so far finds. Never `error`, which a
      compliance score leaves out (audit H3).
    - The Reference failed, the Scenario raised anything else on the Candidate, or the
      Comparison itself raised: `error`, the harness or the Reference having failed.
    """
    if isinstance(reference, ScenarioError):
        return _error(scenario, f"the Reference failed: {reference}")
    if isinstance(candidate, ScenarioError) and not isinstance(
        candidate.__cause__, CANDIDATE_FAILURES
    ):
        return _error(scenario, f"the harness failed on the Candidate: {candidate}")
    transcript = candidate.transcript if isinstance(candidate, ScenarioError) else candidate
    try:
        verdict = compare(reference, transcript, scenario.masks)
    except (TypeError, ValueError) as exc:
        return _error(scenario, f"the Comparison failed: {type(exc).__name__}: {exc}")
    if not isinstance(candidate, ScenarioError):
        return verdict
    failed = Divergence(
        bot="",
        index=0,
        kind="failed",
        packet="",
        path=None,
        reference=ABSENT,
        candidate=str(candidate),
    )
    return Verdict(
        scenario_id=scenario.id,
        outcome=Outcome.MISMATCH,
        divergences=(failed, *verdict.divergences),
        detail=f"the Candidate failed: {candidate}",
    )


def blocked(scenario: Scenario, verdicts: Mapping[str, Verdict]) -> Verdict | None:
    """A `blocked` Verdict if a prerequisite of `scenario` has no `match` in `verdicts`."""
    for prerequisite in scenario.requires:
        verdict = verdicts.get(prerequisite)
        if verdict is None:
            detail = f"prerequisite {prerequisite} was not run"
        elif verdict.outcome is not Outcome.MATCH:
            detail = f"prerequisite {prerequisite} was {verdict.outcome}"
        else:
            continue
        return Verdict(scenario_id=scenario.id, outcome=Outcome.BLOCKED, detail=detail)
    return None


async def run(
    scenarios: Sequence[Scenario],
    reference: Server,
    candidate: Server,
    *,
    workdir: Path,
    repeat: int = 1,
) -> list[Verdict]:
    """Play each Scenario against the Reference and the Candidate, `repeat` times.

    Returns one Verdict per Scenario per repetition, repetition after repetition, each
    in the order given. A Scenario is `blocked`, and not played, unless each of its
    prerequisites matched earlier in the same repetition (so list them first).

    Each side gets one Instance per distinct ServerSpec the Scenarios' `spec` make,
    launched in its own directory under `workdir` at an Endpoint of its own
    (`free_endpoint`) when a Scenario first needs it, and kept for every repetition.
    The Reference and Candidate Instances start together, and both are stopped at the
    end, however the Run ends.

    Raises:
        NotImplementedError: A Scenario is not `exact`: other kinds need M6a / M6b.
        ValueError: A Scenario is listed twice.
        RunnerError: An Instance could not be launched or did not become ready.
    """
    _check(scenarios)
    async with contextlib.AsyncExitStack() as stack:
        instances = _Instances(stack, reference, candidate, workdir)
        verdicts: list[Verdict] = []
        for _ in range(repeat):
            done: dict[str, Verdict] = {}
            for scenario in scenarios:
                verdict = blocked(scenario, done)
                if verdict is None:
                    verdict = await instances.play(scenario)
                done[scenario.id] = verdict
            verdicts.extend(done.values())
        return verdicts


async def selfcheck(
    scenario_ids: Sequence[str], *, reference: Server, workdir: Path, repeat: int = 20
) -> list[Verdict]:
    """Self-check the registered Scenarios `scenario_ids`: the Reference against itself.

    A `run` with `reference` on both sides, so two Instances of the Reference, each at
    an Endpoint of its own. The Scenarios' prerequisites are played too, first
    (`scenario.resolve`). Every Verdict must be `match` (G2: 20 out of 20); anything
    else is a missing Mask or a flaky Scenario, never a Reference bug.

    Raises:
        KeyError: A Scenario id is not registered; nothing was started.
    """
    scenarios = resolve(scenario_ids)
    return await run(scenarios, reference, reference, workdir=workdir, repeat=repeat)


def _check(scenarios: Sequence[Scenario]) -> None:
    seen: set[str] = set()
    for scenario in scenarios:
        if scenario.kind is not ScenarioKind.EXACT:
            msg = f"{scenario.id} is {scenario.kind}: only exact Scenarios can run before M6a/M6b"
            raise NotImplementedError(msg)
        if scenario.id in seen:
            msg = f"{scenario.id} is listed twice"
            raise ValueError(msg)
        seen.add(scenario.id)


class _Instances:
    """The Instance pairs of one Run, one per distinct ServerSpec, started on demand."""

    def __init__(
        self, stack: contextlib.AsyncExitStack, reference: Server, candidate: Server, workdir: Path
    ) -> None:
        self._stack = stack
        self._reference = reference
        self._candidate = candidate
        self._workdir = workdir
        self._pairs: dict[ServerSpec, tuple[Endpoint, Endpoint]] = {}

    async def play(self, scenario: Scenario) -> Verdict:
        """Play `scenario` on the Reference, then on the Candidate, and judge it."""
        reference, candidate = await self._pair(scenario.spec)
        return judge(
            scenario,
            await _attempt(scenario, reference, server=self._reference.name),
            await _attempt(scenario, candidate, server=self._candidate.name),
        )

    async def _pair(self, spec: Callable[[ServerSpec], ServerSpec]) -> tuple[Endpoint, Endpoint]:
        key = spec(ServerSpec(host=_SPEC_KEY_ENDPOINT.host, port=_SPEC_KEY_ENDPOINT.port))
        if key not in self._pairs:
            where = self._workdir / str(len(self._pairs))
            try:
                async with asyncio.TaskGroup() as group:
                    reference = group.create_task(
                        self._start(self._reference, spec, where / "reference")
                    )
                    candidate = group.create_task(
                        self._start(self._candidate, spec, where / "candidate")
                    )
            except ExceptionGroup as failures:
                raise failures.exceptions[0] from None
            self._pairs[key] = (reference.result(), candidate.result())
        return self._pairs[key]

    async def _start(
        self, server: Server, spec: Callable[[ServerSpec], ServerSpec], workdir: Path
    ) -> Endpoint:
        endpoint = free_endpoint()
        plan = server.adapter.prepare(
            server.installation, spec(ServerSpec(host=endpoint.host, port=endpoint.port)), workdir
        )
        instance = await self._stack.enter_async_context(
            running(
                plan,
                ready=status_probe(TARGET),
                ready_timeout=READY_TIMEOUT_S,
                stop_timeout=STOP_TIMEOUT_S,
            )
        )
        return instance.endpoint


async def _attempt(
    scenario: Scenario, endpoint: Endpoint, *, server: str
) -> Transcript | ScenarioError:
    try:
        return await run_scenario(scenario, endpoint, server=server)
    except ScenarioError as error:
        return error


def _describe(error: Exception, timeout_s: float) -> str:
    """What went wrong, for a Verdict's detail: the exception's type and message."""
    if isinstance(error, TimeoutError) and not str(error):
        return f"TimeoutError: no answer within {timeout_s} s"
    return f"{type(error).__name__}: {error}" if str(error) else type(error).__name__


def _error(scenario: Scenario, detail: str) -> Verdict:
    return Verdict(scenario_id=scenario.id, outcome=Outcome.ERROR, detail=detail)
