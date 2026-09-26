"""Runs: Scenarios played against the Reference and a Candidate, judged into Verdicts."""

import asyncio
import contextlib
import dataclasses
import json
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

import mscts.scenarios  # noqa: F401 - importing it registers the shipped Scenarios
from mscts.adapters.base import Adapter, Installation
from mscts.bot import status_probe
from mscts.codec.packets import CodecError
from mscts.compare import ABSENT, Divergence, Outcome, Verdict, compare
from mscts.measure import Measurement, measurements
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

_STATUS_RESPONSE = "minecraft:status_response"

_NS_PER_MS = 1_000_000

_SPEC_KEY_ENDPOINT = Endpoint(host="127.0.0.1", port=1)
"""The Endpoint a Scenario's `spec` is applied to only to tell which specs are equal."""


class ScenarioError(Exception):
    """A Scenario raised against one Instance. Its cause is what it raised.

    Attributes:
        transcript: Everything recorded until it raised.
        bot: The name of the Bot it came out of, or "" if none raised it.
    """

    def __init__(self, transcript: Transcript, description: str, *, bot: str = "") -> None:
        """Record that the Scenario of `transcript` failed, as `description` says."""
        super().__init__(description)
        self.transcript = transcript
        self.bot = bot


@dataclasses.dataclass(frozen=True, slots=True)
class Server:
    """One side of a Run: an Adapter with its Installation, from which Instances launch."""

    adapter: Adapter
    installation: Installation

    @property
    def name(self) -> str:
        """The Adapter's name, as the Transcripts record it."""
        return self.adapter.name


@dataclasses.dataclass(frozen=True, slots=True)
class Attached:
    """One side of a Run: an Instance someone else launched, owns and stops.

    A Run plays against it and never starts or stops it, so it can only play the
    Scenarios whose `spec` gives `spec` (host and port aside); `run` refuses any other.

    Attributes:
        name: Its Adapter's name, as the Transcripts record it.
        spec: The ServerSpec it was launched from. Its host and port are its Endpoint.
    """

    name: str
    spec: ServerSpec

    @property
    def endpoint(self) -> Endpoint:
        """Where the Instance is reached: its ServerSpec's host and port."""
        return Endpoint(host=self.spec.host, port=self.spec.port)


type Side = Server | Attached
"""One side of a Run: Instances it launches (Server), or one it is given (Attached)."""


@dataclasses.dataclass(frozen=True, slots=True)
class ScenarioResult:
    """What one Scenario gave in a Run, one entry per repetition, in order.

    Attributes:
        scenario_id: The Scenario, e.g. `status/ping`.
        verdicts: Its Verdict in each repetition.
        reference: The Reference's Measurements in each repetition (none if the
            Scenario was blocked there).
        candidate: The Candidate's Measurements in each repetition, likewise.
    """

    scenario_id: str
    verdicts: tuple[Verdict, ...]
    reference: tuple[tuple[Measurement, ...], ...]
    candidate: tuple[tuple[Measurement, ...], ...]


@dataclasses.dataclass(frozen=True, slots=True)
class SideSummary:
    """What a Run learned about one of its sides.

    Attributes:
        name: Its Adapter's name.
        version: The `version.name` of the first status_response it sent, or None if
            none was a status JSON naming a version.
        startup: One `instance.startup` Measurement per Instance the Run launched for
            it, launch to ready; none for an Attached side.
    """

    name: str
    version: str | None
    startup: tuple[Measurement, ...]


@dataclasses.dataclass(frozen=True, slots=True)
class RunResult:
    """What a Run gave: a ScenarioResult per Scenario, in the order played, and each side."""

    results: tuple[ScenarioResult, ...]
    reference: SideSummary
    candidate: SideSummary

    @property
    def verdicts(self) -> tuple[Verdict, ...]:
        """Every Verdict, repetition after repetition, each in the order played."""
        repeat = len(self.results[0].verdicts) if self.results else 0
        return tuple(
            result.verdicts[repetition] for repetition in range(repeat) for result in self.results
        )


@dataclasses.dataclass(frozen=True, slots=True)
class _Play:
    """One Scenario played once: its Verdict, and each side's Measurements."""

    verdict: Verdict
    reference: tuple[Measurement, ...] = ()
    candidate: tuple[Measurement, ...] = ()


def status_version(transcript: Transcript) -> str | None:
    """The `version.name` of the first status_response in `transcript`, if it names one.

    Read leniently: anything that is not a status JSON object with a string
    `version.name` (the Candidate's output, which must never crash the harness) is None.
    """
    for event in transcript.events:
        packet = event.packet
        if packet.name != _STATUS_RESPONSE or packet.fields is None:
            continue
        text = packet.fields.get("json_response")
        if not isinstance(text, str):
            return None
        try:
            status: object = json.loads(text)
        except (ValueError, RecursionError):
            return None
        version = status.get("version") if isinstance(status, dict) else None
        name = version.get("name") if isinstance(version, dict) else None
        return name if isinstance(name, str) else None
    return None


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
        description = _describe(exc, timeout_s)
        raise ScenarioError(transcript, description, bot=context.raised_by(exc)) from exc
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
      `mismatch`, led by a `failed` Divergence that says what happened and names the
      Bot it came out of (`ScenarioError.bot`), then whatever
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
        bot=candidate.bot,
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
    reference: Side,
    candidate: Side,
    *,
    workdir: Path,
    repeat: int = 1,
) -> list[Verdict]:
    """Play each Scenario against the Reference and the Candidate, `repeat` times.

    Returns one Verdict per Scenario per repetition, repetition after repetition, each
    in the order given: `run_results(...).verdicts`, which says how it is played.
    """
    result = await run_results(scenarios, reference, candidate, workdir=workdir, repeat=repeat)
    return list(result.verdicts)


async def run_results(
    scenarios: Sequence[Scenario],
    reference: Side,
    candidate: Side,
    *,
    workdir: Path,
    repeat: int = 1,
) -> RunResult:
    """Play each Scenario against the Reference and the Candidate, `repeat` times.

    Returns, for each Scenario in the order given, its Verdict and each side's
    Measurements for every repetition; and for each side its `instance.startup`
    Measurements and the version its status_response named. A Scenario is `blocked`,
    and not played (so it measures nothing), unless each of its prerequisites matched
    earlier in the same repetition (so list them first).

    A Server side gets one Instance per distinct ServerSpec the Scenarios' `spec` make,
    launched in its own directory under `workdir` at an Endpoint of its own
    (`free_endpoint`) when a Scenario first needs it, and kept for every repetition.
    The Reference and Candidate Instances start together, and both are stopped at the
    end, however the Run ends. An Attached side is played at its Endpoint as it is,
    and neither started nor stopped.

    Raises:
        NotImplementedError: A Scenario is not `exact`: other kinds need M6a / M6b.
        ValueError: A Scenario is listed twice, or needs a ServerSpec an Attached side
            was not launched from. Nothing was started.
        RunnerError: An Instance could not be launched or did not become ready.
    """
    _check(scenarios, (reference, candidate))
    plays: dict[str, list[_Play]] = {scenario.id: [] for scenario in scenarios}
    async with contextlib.AsyncExitStack() as stack:
        instances = _Instances(stack, reference, candidate, workdir)
        for _ in range(repeat):
            done: dict[str, Verdict] = {}
            for scenario in scenarios:
                verdict = blocked(scenario, done)
                play = _Play(verdict) if verdict is not None else await instances.play(scenario)
                done[scenario.id] = play.verdict
                plays[scenario.id].append(play)
        summaries = instances.summaries()
    return RunResult(
        results=tuple(
            ScenarioResult(
                scenario_id=scenario_id,
                verdicts=tuple(play.verdict for play in played),
                reference=tuple(play.reference for play in played),
                candidate=tuple(play.candidate for play in played),
            )
            for scenario_id, played in plays.items()
        ),
        reference=summaries[0],
        candidate=summaries[1],
    )


async def selfcheck(
    scenario_ids: Sequence[str],
    *,
    reference: Server,
    workdir: Path,
    repeat: int = 20,
    attached: Attached | None = None,
) -> list[Verdict]:
    """Self-check the registered Scenarios `scenario_ids`: the Reference against itself.

    A `run` with the Reference on both sides, so two Instances of the Reference, each
    at an Endpoint of its own: both launched from `reference`, or, given `attached`
    (an Instance of the same Adapter already running), that one as the Reference side
    and one launched from `reference` as the other. The Scenarios' prerequisites are
    played too, first (`scenario.resolve`). Every Verdict must be `match` (G2: 20 out
    of 20); anything else is a missing Mask or a flaky Scenario, never a Reference bug.

    Raises:
        KeyError: A Scenario id is not registered; nothing was started.
        ValueError: `attached` is not an Instance of `reference`'s Adapter, or not of a
            ServerSpec a Scenario needs; nothing was started.
    """
    scenarios = resolve(scenario_ids)
    if attached is not None and attached.name != reference.name:
        msg = (
            f"a Self-check compares the Reference with itself: the attached Instance is "
            f"{attached.name}, not {reference.name}"
        )
        raise ValueError(msg)
    side = reference if attached is None else attached
    return await run(scenarios, side, reference, workdir=workdir, repeat=repeat)


def _check(scenarios: Sequence[Scenario], sides: Sequence[Side]) -> None:
    seen: set[str] = set()
    for scenario in scenarios:
        if scenario.kind is not ScenarioKind.EXACT:
            msg = f"{scenario.id} is {scenario.kind}: only exact Scenarios can run before M6a/M6b"
            raise NotImplementedError(msg)
        if scenario.id in seen:
            msg = f"{scenario.id} is listed twice"
            raise ValueError(msg)
        seen.add(scenario.id)
        for side in sides:
            if isinstance(side, Attached) and _spec_key(scenario.spec) != _spec_key(side.spec):
                msg = (
                    f"{scenario.id} needs another ServerSpec than the attached {side.name} "
                    f"Instance at {side.spec.host}:{side.spec.port} was launched from: "
                    f"{_spec_key(scenario.spec)} is not {_spec_key(side.spec)}"
                )
                raise ValueError(msg)


def _spec_key(spec: ServerSpec | Callable[[ServerSpec], ServerSpec]) -> ServerSpec:
    """A ServerSpec with the Endpoint left out, to tell which specs are equal.

    Given a Scenario's `spec`, the ServerSpec it makes of the default one.
    """
    if not isinstance(spec, ServerSpec):
        return spec(ServerSpec(host=_SPEC_KEY_ENDPOINT.host, port=_SPEC_KEY_ENDPOINT.port))
    return dataclasses.replace(spec, host=_SPEC_KEY_ENDPOINT.host, port=_SPEC_KEY_ENDPOINT.port)


class _Instances:
    """The Instance pairs of one Run, one per distinct ServerSpec, started on demand.

    It also keeps what the Run learns about each side: the startup Measurement of each
    Instance it launched, and the version the side's first status_response named.
    """

    def __init__(
        self, stack: contextlib.AsyncExitStack, reference: Side, candidate: Side, workdir: Path
    ) -> None:
        self._stack = stack
        self._sides = (reference, candidate)
        self._workdir = workdir
        self._pairs: dict[ServerSpec, tuple[Endpoint, Endpoint]] = {}
        self._startup: tuple[list[Measurement], list[Measurement]] = ([], [])
        self._versions: list[str | None] = [None, None]

    async def play(self, scenario: Scenario) -> _Play:
        """Play `scenario` on the Reference, then on the Candidate, and judge it."""
        endpoints = await self._pair(scenario.spec)
        attempts = [
            await _attempt(scenario, endpoint, server=side.name)
            for side, endpoint in zip(self._sides, endpoints, strict=True)
        ]
        transcripts = [
            attempt.transcript if isinstance(attempt, ScenarioError) else attempt
            for attempt in attempts
        ]
        for role, transcript in enumerate(transcripts):
            if self._versions[role] is None:
                self._versions[role] = status_version(transcript)
        reference, candidate = transcripts
        return _Play(
            judge(scenario, *attempts),
            reference=tuple(measurements(reference)),
            candidate=tuple(measurements(candidate)),
        )

    def summaries(self) -> tuple[SideSummary, SideSummary]:
        """What the Run learned about the Reference and the Candidate, in that order."""
        reference, candidate = (
            SideSummary(
                name=side.name, version=self._versions[role], startup=tuple(self._startup[role])
            )
            for role, side in enumerate(self._sides)
        )
        return reference, candidate

    async def _pair(self, spec: Callable[[ServerSpec], ServerSpec]) -> tuple[Endpoint, Endpoint]:
        key = _spec_key(spec)
        if key not in self._pairs:
            where = self._workdir / str(len(self._pairs))
            try:
                async with asyncio.TaskGroup() as group:
                    reference = group.create_task(self._start(0, spec, where / "reference"))
                    candidate = group.create_task(self._start(1, spec, where / "candidate"))
            except ExceptionGroup as failures:
                raise failures.exceptions[0] from None
            self._pairs[key] = (reference.result(), candidate.result())
        return self._pairs[key]

    async def _start(
        self, role: int, spec: Callable[[ServerSpec], ServerSpec], workdir: Path
    ) -> Endpoint:
        server = self._sides[role]
        if isinstance(server, Attached):
            return server.endpoint  # `_check` made sure it is of `spec`
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
        startup_ms = (instance.ready_ns - instance.launched_ns) / _NS_PER_MS
        self._startup[role].append(
            Measurement(name="instance.startup", unit="ms", value=startup_ms)
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
