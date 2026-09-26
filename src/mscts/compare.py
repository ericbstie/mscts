"""Comparison: diff the Reference and Candidate Transcripts of one Scenario into a Verdict.

What is compared is, for every Bot, the ordered stream of the clientbound Packets it
received. Everything else is left out on purpose:

- Serverbound Packets are the Scenario's own actions and the Bot's automatic answers.
  They differ between Instances by design (the handshake names each Instance's own
  Endpoint), and any difference in them that a server caused shows up first in what
  that server sent.
- Timestamps and Marks are timing data, for Measurements. The order of a Bot's stream
  is compared; when its Packets arrived is not.
- The interleaving of different Bots' Packets is timing too, so each Bot is compared
  on its own.
"""

from array import array
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from enum import Enum, StrEnum
from typing import Literal, override

from mscts.codec.packets import Direction, Packet
from mscts.transcript import Transcript


class Outcome(StrEnum):
    """What a Verdict says about a Scenario."""

    MATCH = "match"
    MISMATCH = "mismatch"
    BLOCKED = "blocked"
    ERROR = "error"


class Absent(Enum):
    """The type of `ABSENT`."""

    ABSENT = "absent"

    @override
    def __repr__(self) -> str:
        """Read as `ABSENT`."""
        return "ABSENT"


ABSENT = Absent.ABSENT
"""A Divergence's value on the side that has no such packet (or field)."""


@dataclass(frozen=True, slots=True)
class Mask:
    """A normalization rule: a field, or a whole packet, is excluded from Comparison.

    Attributes:
        packet: The packet name, e.g. `minecraft:login`.
        path: The field path, e.g. `entity_id`, or `*` for the whole packet.
        reason: Why it is nondeterministic.
    """

    packet: str
    path: str
    reason: str


type DivergenceKind = Literal["bot", "missing", "unexpected", "field"]


@dataclass(frozen=True, slots=True)
class Divergence:
    """One difference a Comparison found for one Bot.

    A Bot's stream is the clientbound Packets it received, in order. The two streams
    are aligned: a Packet is matched with one of the same State and name on the other
    side, keeping both orders.

    Attributes:
        bot: The Bot's name.
        index: The position of the Packet in its stream, counting from 0: in the
            reference stream for `missing` and `field`, in the candidate stream for
            `unexpected`. Always 0 for `bot`.
        kind: `bot`: the Bot has Events (sent or received) in only one Transcript.
            Its stream's Divergences follow, the other side's stream being empty.
            `missing`: a reference Packet the alignment left unmatched.
            `unexpected`: a candidate Packet the alignment left unmatched.
            `field`: a difference between two matched Packets.
        packet: The packet name; "" for `bot`.
        path: Where in the matched Packets they differ, or None for their whole
            payload. Always None for `bot`, `missing` and `unexpected`.
        reference: The value in the reference, or ABSENT. For `bot`, the number of
            the Bot's Events.
        candidate: The value in the candidate, or ABSENT. For `bot`, the number of
            the Bot's Events.
    """

    bot: str
    index: int
    kind: DivergenceKind
    packet: str
    path: str | None
    reference: object
    candidate: object


@dataclass(frozen=True, slots=True)
class Verdict:
    """The result of one Scenario.

    Attributes:
        scenario_id: The Scenario, e.g. `status/basic`.
        outcome: `match` exactly when there are no divergences, from `compare`.
        divergences: Every difference, grouped by Bot in name order, then in stream
            order.
        detail: A human-readable note, e.g. why the Scenario is blocked.
    """

    scenario_id: str
    outcome: Outcome
    divergences: tuple[Divergence, ...] = ()
    detail: str = ""


def compare(
    reference: Transcript,
    candidate: Transcript,
    masks: Sequence[Mask],  # noqa: ARG001  # the PLAN signature; used once Masks land
) -> Verdict:
    """Diff the Candidate's Transcript of a Scenario against the Reference's.

    A Packet's value is its payload as hex. Each Bot's two streams are aligned on
    their packet keys (State and name), leaving as few Packets unmatched as possible;
    swapping the sides mirrors the alignment. Between two matched pairs, `missing`
    Divergences come before `unexpected` ones.

    Raises:
        ValueError: The Transcripts are of different Scenarios.
    """
    if reference.scenario_id != candidate.scenario_id:
        msg = (
            "cannot compare Transcripts of different Scenarios: "
            f"{reference.scenario_id!r} and {candidate.scenario_id!r}"
        )
        raise ValueError(msg)
    bots = sorted(_bots(reference) | _bots(candidate))
    divergences = tuple(
        divergence for bot in bots for divergence in _compare_bot(bot, reference, candidate)
    )
    return Verdict(
        scenario_id=reference.scenario_id,
        outcome=Outcome.MISMATCH if divergences else Outcome.MATCH,
        divergences=divergences,
    )


def _bots(transcript: Transcript) -> set[str]:
    return {event.bot for event in transcript.events}


def _compare_bot(bot: str, reference: Transcript, candidate: Transcript) -> Iterator[Divergence]:
    in_reference = sum(event.bot == bot for event in reference.events)
    in_candidate = sum(event.bot == bot for event in candidate.events)
    if not (in_reference and in_candidate):
        yield Divergence(
            bot=bot,
            index=0,
            kind="bot",
            packet="",
            path=None,
            reference=in_reference or ABSENT,
            candidate=in_candidate or ABSENT,
        )
    yield from _compare_streams(bot, _stream(reference, bot), _stream(candidate, bot))


def _stream(transcript: Transcript, bot: str) -> list[Packet]:
    return [
        event.packet
        for event in transcript.events
        if event.bot == bot and event.packet.direction is Direction.CLIENTBOUND
    ]


type _Key = tuple[str, str]


def _key(packet: Packet) -> _Key:
    return (packet.state.value, packet.name)


def _align(reference: Sequence[_Key], candidate: Sequence[_Key]) -> list[tuple[int, int]]:
    """Return the matched (reference index, candidate index) pairs, in order.

    The pairs are a longest common subsequence of the two key sequences: as few
    Packets as possible are left unmatched. Of the longest ones, the choice is fixed
    so that swapping the two sides mirrors it:

    1. The common prefix and the common suffix are matched.
    2. In between, a longest common subsequence is traced from the front. Equal keys
       are matched. Otherwise one key is skipped: the one whose skipping keeps the
       longer subsequence, or, if both keep as long a one, the smaller key, whichever
       side it is on.

    Between the prefix and the suffix this takes O(n·m) time and memory, and that
    part is short when the streams mostly agree.
    """
    shorter = min(len(reference), len(candidate))
    prefix = 0
    while prefix < shorter and reference[prefix] == candidate[prefix]:
        prefix += 1
    suffix = 0
    while suffix < shorter - prefix and reference[-1 - suffix] == candidate[-1 - suffix]:
        suffix += 1
    ref_stop, cand_stop = len(reference) - suffix, len(candidate) - suffix
    middle = _longest_common_subsequence(reference[prefix:ref_stop], candidate[prefix:cand_stop])
    return [
        *((index, index) for index in range(prefix)),
        *((prefix + ref_index, prefix + cand_index) for ref_index, cand_index in middle),
        *((ref_stop + offset, cand_stop + offset) for offset in range(suffix)),
    ]


def _longest_common_subsequence(
    reference: Sequence[_Key], candidate: Sequence[_Key]
) -> list[tuple[int, int]]:
    """Trace step 2 of `_align`, returning its matched pairs."""
    rows, columns = len(reference), len(candidate)
    # keeps[i][j]: the length of a longest common subsequence of reference[i:] and
    # candidate[j:].
    keeps = [array("L", [0]) * (columns + 1) for _ in range(rows + 1)]
    for i in range(rows - 1, -1, -1):
        row, below, key = keeps[i], keeps[i + 1], reference[i]
        for j in range(columns - 1, -1, -1):
            row[j] = below[j + 1] + 1 if key == candidate[j] else max(below[j], row[j + 1])
    pairs: list[tuple[int, int]] = []
    i = j = 0
    while i < rows and j < columns:
        if reference[i] == candidate[j]:
            pairs.append((i, j))
            i, j = i + 1, j + 1
        elif keeps[i + 1][j] > keeps[i][j + 1]:
            i += 1
        elif keeps[i][j + 1] > keeps[i + 1][j]:
            j += 1
        elif reference[i] < candidate[j]:
            i += 1
        else:
            j += 1
    return pairs


def _compare_streams(
    bot: str, reference: Sequence[Packet], candidate: Sequence[Packet]
) -> Iterator[Divergence]:
    pairs = _align([_key(p) for p in reference], [_key(p) for p in candidate])
    next_reference = next_candidate = 0
    for ref_index, cand_index in [*pairs, (len(reference), len(candidate))]:
        for index in range(next_reference, ref_index):
            yield _unmatched(bot, index, "missing", reference[index])
        for index in range(next_candidate, cand_index):
            yield _unmatched(bot, index, "unexpected", candidate[index])
        if ref_index < len(reference):
            yield from _diff_matched(bot, ref_index, reference[ref_index], candidate[cand_index])
        next_reference, next_candidate = ref_index + 1, cand_index + 1


def _unmatched(
    bot: str, index: int, kind: Literal["missing", "unexpected"], packet: Packet
) -> Divergence:
    value = _value(packet)
    return Divergence(
        bot=bot,
        index=index,
        kind=kind,
        packet=packet.name,
        path=None,
        reference=value if kind == "missing" else ABSENT,
        candidate=value if kind == "unexpected" else ABSENT,
    )


def _diff_matched(
    bot: str, index: int, reference: Packet, candidate: Packet
) -> Iterator[Divergence]:
    if reference.payload != candidate.payload:
        yield Divergence(
            bot=bot,
            index=index,
            kind="field",
            packet=reference.name,
            path=None,
            reference=reference.payload.hex(),
            candidate=candidate.payload.hex(),
        )


def _value(packet: Packet) -> object:
    return packet.payload.hex()
