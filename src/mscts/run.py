"""Runs: Groups played against the Reference and a Candidate, judged into Verdicts."""

import asyncio
import contextlib
import dataclasses
import json
import logging
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from time import perf_counter

import mscts.compare
import mscts.groups  # importing it registers the shipped Groups
from mscts.adapters.base import Adapter, Installation
from mscts.bot import status_probe
from mscts.compare import ABSENT, Divergence, Outcome, Verdict, compare
from mscts.group import CommandMissing, Group, GroupContext, GroupKind, resolve
from mscts.measure import Measurement, measurements
from mscts.net import Endpoint
from mscts.runner import free_endpoint, running
from mscts.settle import SETTLE_TIMEOUT_S, PlayersStillOnline, until_no_player_online
from mscts.spec import ServerSpec
from mscts.target import TARGET
from mscts.transcript import Transcript

GROUP_TIMEOUT_S = 10.0
"""How long each Bot operation of a Group may take (Bot's `timeout_s`)."""

READY_TIMEOUT_S = 120.0
"""How long an Instance may take to become ready: a cold vanilla boot unpacks and makes a world."""

STOP_TIMEOUT_S = 30.0
"""How long each step of stopping an Instance may take (runner.running's `stop_timeout`)."""

LOG = logging.getLogger("mscts.run")
"""Where a Run says what it is doing (INFO): the Instances it starts, the Group it plays."""

_STATUS_RESPONSE = "minecraft:status_response"

_NS_PER_MS = 1_000_000

_SPEC_KEY_ENDPOINT = Endpoint(host="127.0.0.1", port=1)
"""The Endpoint a Group's `spec` is applied to only to tell which specs are equal."""


class GroupError(Exception):
    """A Group raised against one Instance. Its cause is what it raised.

    Attributes:
        transcript: Everything recorded until it raised.
        bot: The name of the Bot it came out of, or "" if none raised it.
        left_frozen: The Group froze the world and it could not be unfrozen
            (`GroupContext.left_frozen`): the Instance is unusable (#228).
    """

    def __init__(
        self, transcript: Transcript, description: str, *, bot: str = "", left_frozen: bool = False
    ) -> None:
        """Record that the Group of `transcript` failed, as `description` says."""
        super().__init__(description)
        self.transcript = transcript
        self.bot = bot
        self.left_frozen = left_frozen


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
    Groups whose `spec` gives `spec` (host and port aside); `run` refuses any other.

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
class GroupResult:
    """What one Group gave in a Run, one entry per repetition, in order.

    Attributes:
        group_id: The Group, e.g. `status/ping`.
        verdicts: Its Verdict in each repetition.
        reference: The Reference's Measurements in each repetition (none if it did
            not play the Group there).
        candidate: The Candidate's Measurements in each repetition, likewise.
        elapsed_s: Seconds playing both sides and comparing, per repetition, or the
            Reference alone where the Candidate was not played; zero where neither
            was. Instance startup and shutdown are excluded.
        transcripts: The Reference's and the Candidate's Transcript in each repetition
            whose Verdict is not `match`, if the Run was asked to keep them
            (`keep_transcripts`), to diagnose it (#162); None in the others, in one where
            the Candidate was not played, and in every one otherwise. No Report shows
            them, `report.json` does not hold them, and equality ignores them.
    """

    group_id: str
    verdicts: tuple[Verdict, ...]
    reference: tuple[tuple[Measurement, ...], ...]
    candidate: tuple[tuple[Measurement, ...], ...]
    elapsed_s: tuple[float, ...] = ()
    transcripts: tuple[tuple[Transcript, Transcript] | None, ...] = dataclasses.field(
        default=(), compare=False, repr=False
    )


@dataclasses.dataclass(frozen=True, slots=True)
class SideSummary:
    """What a Run learned about one of its sides.

    Attributes:
        name: Its Adapter's name.
        version: The `version.name` of the first status_response it sent, or None if
            none was a status JSON naming a version.
        startup: One `instance.startup` Measurement per Instance the Run launched for
            it, launch to ready; none for an Attached side.
        installed_version: Its Installation's Build and short sha256, else its sha256; None for
            an Attached side or an Installation without recorded provenance.
    """

    name: str
    version: str | None
    startup: tuple[Measurement, ...]
    installed_version: str | None = None


@dataclasses.dataclass(frozen=True, slots=True)
class RunResult:
    """What a Run gave: a GroupResult per Group, in the order played, and each side."""

    results: tuple[GroupResult, ...]
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
    """One Group played once: its Verdict, each side's Measurements, and its Transcripts.

    The Transcripts (the Reference's, then the Candidate's) are kept only when the
    Verdict is not `match`.
    """

    verdict: Verdict
    reference: tuple[Measurement, ...] = ()
    candidate: tuple[Measurement, ...] = ()
    elapsed_s: float = 0.0
    transcripts: tuple[Transcript, Transcript] | None = None


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


async def run_group(
    group: Group, endpoint: Endpoint, *, server: str, timeout_s: float = GROUP_TIMEOUT_S
) -> Transcript:
    """Play `group` against the Instance at `endpoint`, and return its Transcript.

    `server` is the Adapter's name, for the Transcript. Every Bot is closed at the end,
    once a disconnect still queued for any of them has failed it (`GroupContext.end`).

    Raises:
        GroupError: The Group raised, or a Bot had a disconnect nothing took; the error
            holds the Transcript so far.
    """
    transcript = Transcript(group_id=group.id, server=server)
    context = GroupContext(endpoint, transcript, timeout_s=timeout_s)
    try:
        await group.run(context)
        await context.end()
    except Exception as exc:
        first = _first_failure(exc)
        description = _describe(first, timeout_s)
        bot = context.raised_by(first)
        await context.close()  # first: it tries to unfreeze, and says if it could not
        raise GroupError(transcript, description, bot=bot, left_frozen=context.left_frozen) from exc
    finally:
        await context.close()
    return transcript


def _first_failure(error: Exception) -> Exception:
    """What made the Group fail first: `error`, or what each missing command was raised over.

    A Group's undo stack runs as it raises, so missing undo commands such as `fill` then
    `kill` would otherwise hide what the Group itself raised first (reviews A and B, #288).
    """
    while isinstance(error, CommandMissing) and isinstance(error.__context__, Exception):
        error = error.__context__
    return error


def judge(
    group: Group,
    reference: Transcript | GroupError,
    candidate: Transcript | GroupError,
) -> Verdict:
    """The Verdict on `group`, from what it gave on the Reference and on the Candidate.

    What `compare` finds, with the Group's Masks, except:

    - The Group raised on the Candidate and not on the Reference: `mismatch`, led by a
      `failed` Divergence that says what happened and names the Bot it came out of
      (`GroupError.bot`), then whatever the Comparison of the Transcripts so far finds.
      The Reference ran the same code without raising, so the Candidate caused it,
      whatever the exception's type: its output did not decode, broke the protocol,
      never came, its connection closed or was refused, it kept a closed Bot's player
      online past the Group's wait, or it sent a value the Group did not expect (#222).
      Never `error`, which a compliance score leaves out (audit H3).
    - The Comparison raised, but compares the Reference's Transcript with itself without
      raising: `mismatch`, led by a `failed` Divergence naming the exception, from no Bot.
      The Reference's data is fine, so the Candidate sent what made it raise (#239).
    - Either `mismatch` above lists each test case of the Reference's Transcript compared
      with itself, besides what the Comparison found, so the Report fails every test case
      the Reference's play has (#262).
    - The Candidate does not have a command the Group's Control needs (`CommandMissing`),
      before or after the Group's windows: the first `mismatch` above, its `failed`
      Divergence saying `missing /tick` (#284). Like any other Candidate failure, it fails
      every test case of the Reference's play, and keeps what the windows found.
    - The Reference failed, or the Comparison raises comparing the Reference's Transcript
      with itself, which a Candidate failure always does (#262): `error`, the harness or
      the Reference having failed.
      Any exception from the Comparison is caught, whatever its type, so that one Group's
      bug does not end the Run; the detail names it, and the log keeps its traceback.
      `MemoryError` and `RecursionError` are caught too and become that Group's `error`;
      an interrupt (`KeyboardInterrupt`, `SystemExit`) still ends the Run. The Self-check
      and the reference tier fail on any `error`, and the candidate tier on any Comparison
      that raised, `error` or `mismatch`, so a harness bug still shows (#174, #239).
    """
    if isinstance(reference, GroupError):
        return _error(group, f"the Reference failed: {reference}")
    transcript = candidate.transcript if isinstance(candidate, GroupError) else candidate
    try:
        verdict = compare(reference, transcript, group.masks)
    except Exception as exc:  # any Comparison bug is this Group's error (#174)
        LOG.warning("the Comparison of %s failed", group.id, exc_info=exc)
        return _comparison_raised(group, reference, candidate, exc)
    if not isinstance(candidate, GroupError):
        return verdict
    return _group_raised(group, reference, candidate, verdict)


def _comparison_raised(
    group: Group, reference: Transcript, candidate: Transcript | GroupError, exc: Exception
) -> Verdict:
    """`judge`'s Verdict when the Comparison raised `exc`: the Candidate's failure, or `error`."""
    what = _comparison_failed(exc)
    own = _itself(reference, group)
    if isinstance(own, Exception):
        return _error(group, what)
    first = _candidate_failure(candidate) if isinstance(candidate, GroupError) else what
    return Verdict(
        group_id=group.id,
        outcome=Outcome.MISMATCH,
        divergences=(*_group_failed(candidate), _failed(bot="", what=what)),
        detail=f"the Candidate failed: {first}",
        test_cases=own.test_cases,
    )


def _group_raised(
    group: Group, reference: Transcript, candidate: GroupError, verdict: Verdict
) -> Verdict:
    """`judge`'s Verdict when the Group raised on the Candidate, `verdict` the Comparison's."""
    own = _itself(reference, group)
    if isinstance(own, Exception):  # the Reference's data or mscts, as above (#262)
        return _error(group, _comparison_failed(own))
    return Verdict(
        group_id=group.id,
        outcome=Outcome.MISMATCH,
        divergences=(*_group_failed(candidate), *verdict.divergences),
        detail=f"the Candidate failed: {_candidate_failure(candidate)}",
        test_cases=tuple(sorted({*verdict.test_cases, *own.test_cases})),
    )


def prerequisite_verdict(group: Group, verdicts: Mapping[str, Verdict]) -> Verdict | None:
    """The Verdict `group` gets if a prerequisite did not pass in `verdicts`, else None.

    A prerequisite passed if it is a `match`, or a `mismatch` whose Divergences are all
    network traffic, which the Score counts as passing (ADR-0007, #221). Of those that did
    not pass, the one that decides is named (review B):

    - One is an `error`: `group` is an `error` too, played on neither side. That is the
      Reference's or mscts's fault, which the Score leaves out, so vanilla failing a
      prerequisite costs the Candidate nothing (audit L2).
    - One was not run, or is `blocked` itself: `group` is `blocked`, played on neither
      side, and fails only its own line. `run_results` never gets here: it refuses a
      Group whose prerequisites are not listed before it (`_check`).
    - Each is a `mismatch`, the Candidate's failure: `group` is a `mismatch` led by a
      `failed` Divergence naming it, as when the Candidate is left frozen (#266). The Run
      still plays it on the Reference and adds that play's test cases, which the Report
      fails like any whole-Group Candidate failure (#285).
    """
    unmet: dict[str, str] = {}
    for prerequisite in group.requires:
        verdict = verdicts.get(prerequisite)
        if verdict is None:
            unmet[prerequisite] = "not run"
        elif not _passed(verdict):
            unmet[prerequisite] = str(verdict.outcome)
    if not unmet:
        return None
    for outcome, decides in ((Outcome.ERROR, {"error"}), (Outcome.BLOCKED, {"not run", "blocked"})):
        prerequisite = next((name for name, was in unmet.items() if was in decides), None)
        if prerequisite is not None:
            detail = f"prerequisite {prerequisite} was {unmet[prerequisite]}"
            return Verdict(group_id=group.id, outcome=outcome, detail=detail)
    what = f"prerequisite {next(iter(unmet))} was mismatch"
    return Verdict(
        group_id=group.id,
        outcome=Outcome.MISMATCH,
        divergences=(_failed(bot="", what=what),),
        detail=f"the Candidate failed: {what}",
    )


def _passed(verdict: Verdict) -> bool:
    """Whether `verdict` is a `match`, or a `mismatch` only in network traffic (ADR-0007).

    The second only while network traffic passes (`NETWORK_TRAFFIC_ONLY_PASSES`), as the
    Score decides it.
    """
    if verdict.outcome is Outcome.MATCH:
        return True
    return (
        mscts.compare.NETWORK_TRAFFIC_ONLY_PASSES
        and verdict.outcome is Outcome.MISMATCH
        and bool(verdict.divergences)
        and not verdict.gameplay
    )


async def run(
    groups: Sequence[Group],
    reference: Side,
    candidate: Side,
    *,
    workdir: Path,
    repeat: int = 1,
) -> list[Verdict]:
    """Play each Group against the Reference and the Candidate, `repeat` times.

    Returns one Verdict per Group per repetition, repetition after repetition, each
    in the order given: `run_results(...).verdicts`, which says how it is played.
    """
    result = await run_results(groups, reference, candidate, workdir=workdir, repeat=repeat)
    return list(result.verdicts)


async def run_results(  # noqa: PLR0913 - the sides, then keyword-only options of one Run
    groups: Sequence[Group],
    reference: Side,
    candidate: Side,
    *,
    workdir: Path,
    repeat: int = 1,
    keep_transcripts: bool = False,
) -> RunResult:
    """Play each Group against the Reference and the Candidate, `repeat` times.

    Returns, for each Group in the order given, its Verdict and each side's
    Measurements for every repetition, and, with `keep_transcripts`, both sides'
    Transcripts of each repetition that did not match (`GroupResult.transcripts`, kept
    until the Run ends, so off by default); and for each side its `instance.startup`
    Measurements and the version its status_response named. A Group is not played on
    the Candidate unless each of its prerequisites passed earlier in the same repetition
    (`prerequisite_verdict` says what it is then). If the Candidate failed each that did
    not pass, it is still played on the Reference, and its `mismatch` lists that play's
    test cases, which the Report fails (#285); otherwise it is an `error`, played on
    neither side, and measures nothing. A Run makes no `blocked` Verdict.

    A Server side gets one Instance per distinct ServerSpec the Groups' `spec` make,
    launched in its own directory under `workdir` at an Endpoint of its own
    (`free_endpoint`) when a Group first needs it, and kept for every repetition.
    The Reference and Candidate Instances start together, and both are stopped at the
    end, however the Run ends. An Attached side is played at its Endpoint as it is,
    and neither started nor stopped.

    Raises:
        NotImplementedError: A Group is `statistical`, which needs M6b.
        ValueError: A Group is listed twice, or before a Group it requires, or a Group
            it requires is not listed (`mscts.group.resolve` adds and orders them), or a
            Group needs a ServerSpec an Attached side was not launched from. Nothing was
            started.
        RunnerError: An Instance could not be launched or did not become ready.
    """
    _check(groups, (reference, candidate))
    plays: dict[str, list[_Play]] = {group.id: [] for group in groups}
    async with contextlib.AsyncExitStack() as stack:
        instances = _Instances(
            stack, reference, candidate, workdir, keep_transcripts=keep_transcripts
        )
        for repetition in range(1, repeat + 1):
            done: dict[str, Verdict] = {}
            for group in groups:
                verdict = prerequisite_verdict(group, done)
                if verdict is None or verdict.outcome is Outcome.MISMATCH:
                    await instances.start(group)  # first, so progress reads in order
                    LOG.info("running %s (%d of %d) ...", group.id, repetition, repeat)
                    play = await instances.play(group, prerequisite_failed=verdict)
                else:
                    LOG.info(
                        "skipping %s (%d of %d): %s",
                        group.id,
                        repetition,
                        repeat,
                        verdict.detail,
                    )
                    play = _Play(verdict)
                done[group.id] = play.verdict
                plays[group.id].append(play)
        summaries = instances.summaries()
    return RunResult(
        results=tuple(
            GroupResult(
                group_id=group_id,
                verdicts=tuple(play.verdict for play in played),
                reference=tuple(play.reference for play in played),
                candidate=tuple(play.candidate for play in played),
                elapsed_s=tuple(play.elapsed_s for play in played),
                transcripts=tuple(play.transcripts for play in played),
            )
            for group_id, played in plays.items()
        ),
        reference=summaries[0],
        candidate=summaries[1],
    )


async def selfcheck(
    group_ids: Sequence[str],
    *,
    reference: Server,
    workdir: Path,
    repeat: int = 20,
    attached: Attached | None = None,
) -> list[Verdict]:
    """Self-check the registered Groups `group_ids`: the Reference against itself.

    A `run` with the Reference on both sides, so two Instances of the Reference, each
    at an Endpoint of its own: both launched from `reference`, or, given `attached`
    (an Instance of the same Adapter already running), that one as the Reference side
    and one launched from `reference` as the other. The Groups' prerequisites are
    played too, first (`group.resolve`). Every Verdict must be `match` (G2: 20 out
    of 20); anything else is a missing Mask or a flaky Group, never a Reference bug.

    Raises:
        KeyError: A Group id is not registered; nothing was started.
        ValueError: `attached` is not an Instance of `reference`'s Adapter, or not of a
            ServerSpec a Group needs; nothing was started.
    """
    groups = resolve(group_ids)
    if attached is not None and attached.name != reference.name:
        msg = (
            f"a Self-check compares the Reference with itself: the attached Instance is "
            f"{attached.name}, not {reference.name}"
        )
        raise ValueError(msg)
    side = reference if attached is None else attached
    return await run(groups, side, reference, workdir=workdir, repeat=repeat)


def _check(groups: Sequence[Group], sides: Sequence[Side]) -> None:
    seen: set[str] = set()
    for group in groups:
        if group.kind is GroupKind.STATISTICAL:
            msg = f"{group.id} is {group.kind}: only exact and tick-exact Groups can run before M6b"
            raise NotImplementedError(msg)
        if group.id in seen:
            msg = f"{group.id} is listed twice"
            raise ValueError(msg)
        for prerequisite in group.requires:
            if prerequisite not in seen:
                msg = (
                    f"{group.id} requires {prerequisite}, which is not listed before it "
                    "(mscts.group.resolve lists each Group's prerequisites first)"
                )
                raise ValueError(msg)
        seen.add(group.id)
        for side in sides:
            if isinstance(side, Attached) and _spec_key(group.spec) != _spec_key(side.spec):
                msg = (
                    f"{group.id} needs another ServerSpec than the attached {side.name} "
                    f"Instance at {side.spec.host}:{side.spec.port} was launched from: "
                    f"{_spec_key(group.spec)} is not {_spec_key(side.spec)}"
                )
                raise ValueError(msg)


def _spec_key(spec: ServerSpec | Callable[[ServerSpec], ServerSpec]) -> ServerSpec:
    """A ServerSpec with the Endpoint left out, to tell which specs are equal.

    Given a Group's `spec`, the ServerSpec it makes of the default one.
    """
    if not isinstance(spec, ServerSpec):
        return spec(ServerSpec(host=_SPEC_KEY_ENDPOINT.host, port=_SPEC_KEY_ENDPOINT.port))
    return dataclasses.replace(spec, host=_SPEC_KEY_ENDPOINT.host, port=_SPEC_KEY_ENDPOINT.port)


class _Instances:
    """The Instance pairs of one Run, one per distinct ServerSpec, started on demand.

    It also keeps what the Run learns about each side: the startup Measurement of each
    Instance it launched, and the version the side's first status_response named. With
    `keep_transcripts`, a play that does not match keeps both sides' Transcripts.
    """

    def __init__(
        self,
        stack: contextlib.AsyncExitStack,
        reference: Side,
        candidate: Side,
        workdir: Path,
        *,
        keep_transcripts: bool,
    ) -> None:
        self._stack = stack
        self._keep_transcripts = keep_transcripts
        self._sides = (reference, candidate)
        self._workdir = workdir
        self._pairs: dict[ServerSpec, tuple[Endpoint, Endpoint]] = {}
        self._startup: tuple[list[Measurement], list[Measurement]] = ([], [])
        self._versions: list[str | None] = [None, None]
        self._unusable: dict[Endpoint, str] = {}  # why no Group may play there any more

    async def start(self, group: Group) -> None:
        """Make sure the Instances `group` plays against are up."""
        await self._pair(group.spec)

    async def play(self, group: Group, *, prerequisite_failed: Verdict | None = None) -> _Play:
        """Play `group` on the Reference, then on the Candidate, and judge it.

        It waits first for each usable Instance to have no player online (the previous
        Group's Bots have left). If the Reference is unusable (`_unusable_verdict`), has
        any player online after `SETTLE_TIMEOUT_S`, or its wait raised, `group` is not
        played on either, and its Verdict is `error`, naming why (`_unsettled`). If only
        the Candidate is, or the Candidate failed a prerequisite of `group`
        (`prerequisite_failed`, from `prerequisite_verdict`), `group` is played on the
        Reference alone (`_reference_alone`); the prerequisite is named first.

        Both Instances of `group`'s ServerSpec are up either way: they launch as a pair, the
        first time a Group of that ServerSpec is played on either side.
        """
        endpoints = await self._pair(group.spec)
        unusable = self._unusable_verdict(group, endpoints)
        if unusable is not None and unusable.outcome is Outcome.ERROR:
            return _Play(unusable)
        skipped = prerequisite_failed or unusable
        reference, candidate = endpoints
        unsettled = await _unsettled(group, reference, candidate if skipped is None else None)
        not_played = unsettled or skipped  # a Reference unsettled comes first: `error`
        if not_played is None:
            return await self._both(group, endpoints)
        if not_played.outcome is Outcome.ERROR:
            return _Play(not_played)
        return await self._reference_alone(group, reference, not_played)

    async def _both(self, group: Group, endpoints: Sequence[Endpoint]) -> _Play:
        """Play `group` on the Reference, then on the Candidate, and judge it."""
        started = perf_counter()
        attempts = [
            await self._attempt(group, role, endpoint) for role, endpoint in enumerate(endpoints)
        ]
        reference, candidate = (_transcript(attempt) for attempt in attempts)
        verdict = judge(group, *attempts)
        return _Play(
            verdict,
            reference=tuple(measurements(reference)),
            candidate=tuple(measurements(candidate)),
            elapsed_s=perf_counter() - started,
            transcripts=(reference, candidate) if self._kept(verdict) else None,
        )

    async def _reference_alone(self, group: Group, endpoint: Endpoint, verdict: Verdict) -> _Play:
        """Play `group` on the Reference alone, the Candidate's side not compared (#266).

        `verdict` says why the Candidate's side is not compared. It is the Verdict, listing
        each test case of the Reference's play, which the Report then fails, so skipping the
        Candidate never scores better than sending every value wrong (`_not_compared`).
        """
        started = perf_counter()
        attempt = await self._attempt(group, 0, endpoint)
        return _Play(
            _not_compared(group, attempt, verdict),
            reference=tuple(measurements(_transcript(attempt))),
            elapsed_s=perf_counter() - started,
        )

    async def _attempt(
        self, group: Group, role: int, endpoint: Endpoint
    ) -> Transcript | GroupError:
        """Play `group` on side `role` at `endpoint`, and learn what it shows about the side.

        The version its first status_response names, and whether it left its world frozen.
        """
        attempt = await _attempt(group, endpoint, server=self._sides[role].name)
        if self._versions[role] is None:
            self._versions[role] = status_version(_transcript(attempt))
        if isinstance(attempt, GroupError) and attempt.left_frozen:
            self._unusable[endpoint] = f"{group.id} left its world frozen"
        return attempt

    def _kept(self, verdict: Verdict) -> bool:
        """Whether the play judged `verdict` keeps its Transcripts."""
        return self._keep_transcripts and verdict.outcome is not Outcome.MATCH

    def _unusable_verdict(self, group: Group, endpoints: Sequence[Endpoint]) -> Verdict | None:
        """The Verdict `group` gets if a side is unusable (#228), or None.

        A side a failed Group left frozen (`GroupError.left_frozen`) would make every later
        Group compare against a frozen world, so no later Group plays on it:

        - The Reference is unusable: `error`, "the Reference is unusable: <group> left
          its world frozen", and the same for the Candidate after a "; " if it is
          too. Neither side is played.
        - Only the Candidate is: `mismatch`, led by a `failed` Divergence saying so, as for
          any Candidate failure (`judge`), so the Score counts it: an `error`, which the
          Score leaves out, would score a Candidate that broke its world better. The
          Reference is still played, for its test cases (`_reference_alone`).
        """
        reference, candidate = (self._unusable.get(endpoint) for endpoint in endpoints)
        if reference is not None:
            detail = f"the Reference is unusable: {reference}"
            if candidate is not None:
                detail += f"; the Candidate is unusable: {candidate}"
            return _error(group, detail)
        if candidate is None:
            return None
        return Verdict(
            group_id=group.id,
            outcome=Outcome.MISMATCH,
            divergences=(_failed(bot="", what=candidate),),
            detail=f"the Candidate failed: {candidate}",
        )

    def summaries(self) -> tuple[SideSummary, SideSummary]:
        """What the Run learned about the Reference and the Candidate, in that order."""
        reference, candidate = (
            SideSummary(
                name=side.name,
                version=self._versions[role],
                startup=tuple(self._startup[role]),
                installed_version=_installed_version(side),
            )
            for role, side in enumerate(self._sides)
        )
        return reference, candidate

    async def _pair(self, spec: Callable[[ServerSpec], ServerSpec]) -> tuple[Endpoint, Endpoint]:
        key = _spec_key(spec)
        if key not in self._pairs:
            where = self._workdir / str(len(self._pairs))
            launched = [side.name for side in self._sides if isinstance(side, Server)]
            if launched:
                LOG.info("starting %s ...", " and ".join(launched))
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


def _installed_version(side: Side) -> str | None:
    if isinstance(side, Attached) or side.installation.source is None:
        return None
    source = side.installation.source
    if source.build is not None:
        return f"{source.build} (sha256 {source.sha256[:8]}…)"
    return f"sha256 {source.sha256}"


async def _unsettled(
    group: Group, reference: Endpoint, candidate: Endpoint | None
) -> Verdict | None:
    """Wait for the Reference, and the Candidate if given, to have no player online.

    None if each does. The two are waited on at once, each wait to its end, so neither is
    left running when the Run moves on. The Candidate is not given when it will not be
    played anyway. If one still has players at the deadline (`PlayersStillOnline`), or its
    wait raised, the Verdict that says why `group` is not played there:

    - The Reference does: `error` (the Reference failed, as in `judge`), "the Reference had
      2 players still online after waiting 2 s: 'watcher', 'control'" (or "the Reference
      failed: the wait for no player online failed: RuntimeError: ..."), and the same
      for the Candidate after a "; " if it did too. Neither side is played.
    - Only the Candidate does, whatever its wait raised: `mismatch` (a Candidate failure is
      never `error`, audit H3; the Reference's wait ran the same code, #222), led by a
      `failed` Divergence that says who is still online, or what the wait raised. The
      Reference is still played, for its test cases (#266).

    Raises:
        BaseException: A wait raised one that is not an Exception (a cancellation from
            inside it, KeyboardInterrupt); raised once both waits are done.
    """
    endpoints = (reference,) if candidate is None else (reference, candidate)
    waits = (
        until_no_player_online(endpoint, deadline_s=SETTLE_TIMEOUT_S) for endpoint in endpoints
    )
    results = await asyncio.gather(*waits, return_exceptions=True)
    for result in results:
        if isinstance(result, BaseException) and not isinstance(result, Exception):
            raise result
    reference_left = results[0] if isinstance(results[0], Exception) else None
    left = results[-1] if candidate is not None and isinstance(results[-1], Exception) else None
    if reference_left is not None:
        detail = f"the Reference {_unsettled_by(reference_left)}"
        if left is not None:
            detail += f"; the Candidate {_unsettled_by(left)}"
        return _error(group, detail)
    if left is None:
        return None
    return Verdict(
        group_id=group.id,
        outcome=Outcome.MISMATCH,
        divergences=(_failed(bot="", what=_left_what(left)),),
        detail=f"the Candidate failed: {_left_what(left)}",
    )


def _left_what(left: Exception) -> str:
    """What a side's wait for no player online raised, as a sentence."""
    if isinstance(left, PlayersStillOnline):
        return str(left)
    return f"the wait for no player online failed: {_describe(left, SETTLE_TIMEOUT_S)}"


def _unsettled_by(left: Exception) -> str:
    """What a side did, after its name, in an `error` Verdict: "had ..." or "failed: ..."."""
    if isinstance(left, PlayersStillOnline):
        return f"had {left}"
    return f"failed: {_left_what(left)}"


async def _attempt(group: Group, endpoint: Endpoint, *, server: str) -> Transcript | GroupError:
    try:
        return await run_group(group, endpoint, server=server)
    except GroupError as error:
        return error


def _transcript(attempt: Transcript | GroupError) -> Transcript:
    """What a play recorded, whether or not the Group raised."""
    return attempt.transcript if isinstance(attempt, GroupError) else attempt


def _not_compared(group: Group, reference: Transcript | GroupError, verdict: Verdict) -> Verdict:
    """`verdict`, on a Candidate side not compared, listing each test case of `reference`.

    `verdict` says why the Candidate's side is not compared. The Report fails each test
    case it lists, as for any Candidate failure of a whole Group (#262), so skipping the
    Candidate never scores better than sending every value wrong (#266). The Reference
    raised, or the Comparison raises comparing its Transcript with itself: `error`, as in
    `judge`.
    """
    if isinstance(reference, GroupError):
        return _error(group, f"the Reference failed: {reference}")
    own = _itself(reference, group)
    if isinstance(own, Exception):
        return _error(group, _comparison_failed(own))
    return dataclasses.replace(verdict, test_cases=own.test_cases)


def _describe(error: Exception, timeout_s: float) -> str:
    """What went wrong, for a Verdict's detail: the exception's type and message."""
    if isinstance(error, TimeoutError) and not str(error):
        return f"TimeoutError: no answer within {timeout_s} s"
    return f"{type(error).__name__}: {error}" if str(error) else type(error).__name__


def _error(group: Group, detail: str) -> Verdict:
    return Verdict(group_id=group.id, outcome=Outcome.ERROR, detail=detail)


def _itself(reference: Transcript, group: Group) -> Verdict | Exception:
    """The Reference's Transcript compared with itself, or what the Comparison raised on it.

    Its test cases are each one the Reference's play has, which a Candidate that failed the
    whole Group fails (#262).
    """
    try:
        return compare(reference, reference, group.masks)
    except Exception as exc:  # raising here is the answer: the Reference's data is odd
        LOG.warning("the Comparison of %s fails on the Reference alone", group.id, exc_info=exc)
        return exc


def _comparison_failed(exc: Exception) -> str:
    """What the Comparison raised, as a Verdict's detail or a `failed` Divergence says it."""
    return f"the Comparison failed: {type(exc).__name__}: {exc}"


def _group_failed(candidate: Transcript | GroupError) -> tuple[Divergence, ...]:
    """The `failed` Divergence for the Group raising on the Candidate, if it did."""
    if isinstance(candidate, GroupError):
        return (_failed(bot=candidate.bot, what=_candidate_failure(candidate)),)
    return ()


def _candidate_failure(candidate: GroupError) -> str:
    """What the Group raising on the Candidate says it did: "missing /tick" for a command missing.

    Anything else, including a failure a missing undo command came after, is the GroupError's
    own description, such as "TimeoutError: ...".
    """
    cause = candidate.__cause__
    first = _first_failure(cause) if isinstance(cause, Exception) else cause
    return f"missing /{first.root}" if isinstance(first, CommandMissing) else str(candidate)


def _failed(*, bot: str, what: str) -> Divergence:
    """The `failed` Divergence for a Candidate failure: `what` happened, out of Bot `bot`."""
    return Divergence(
        bot=bot,
        index=0,
        kind="failed",
        packet="",
        path=None,
        reference=ABSENT,
        candidate=what,
        test_case="",
    )
