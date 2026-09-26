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

import json
import re
import struct
from array import array
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum, StrEnum
from types import MappingProxyType
from typing import Literal, NoReturn, Self, override
from uuid import UUID

from mscts.codec.packets import Direction, Packet, State
from mscts.transcript import Transcript

type _Value = bool | int | float | str | bytes | UUID | list[_Value] | dict[str, _Value] | None
"""A value of the codec value model: what decoded fields are made of."""

type _Step = str | int
"""One step of a field path: a mapping key, or a list index."""

type _Path = tuple[_Step, ...]


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


WHOLE_PACKET = "*"
"""The Mask path that drops the whole packet."""


@dataclass(frozen=True, slots=True)
class Mask:
    """A normalization rule: a field, or a whole packet, is excluded from Comparison.

    Attributes:
        packet: The packet name, e.g. `minecraft:login`, in whatever State.
        path: The field path, spelled as Divergence paths are (e.g. `entity_id`,
            `players.sample[0].name`), or `*` (WHOLE_PACKET) for the whole packet.
        reason: Why it is nondeterministic.
    """

    packet: str
    path: str
    reason: str

    def __post_init__(self) -> None:
        """Reject a Mask that could never be right.

        Raises:
            ValueError: The packet name or the reason is empty, or the path is
                malformed or not spelled as a Divergence path would be.
        """
        if not self.packet:
            msg = "a Mask needs a packet name"
            raise ValueError(msg)
        if not self.reason.strip():
            msg = f"{self.packet} {self.path}: a Mask needs a reason"
            raise ValueError(msg)
        if self.path != WHOLE_PACKET:
            _mask_steps(self)


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


def compare(reference: Transcript, candidate: Transcript, masks: Sequence[Mask]) -> Verdict:
    """Diff the Candidate's Transcript of a Scenario against the Reference's.

    Each Bot's stream is normalized first: the Packets a `*` Mask names are dropped,
    the rest are put in canonical form (`_CANONICAL`: e.g. a status response's JSON is
    parsed, and its text components written one way), and every field a Mask names
    is removed from the Packets of that name, on both sides and wherever present.
    Indices count the normalized stream, so they do not shift when a re-run has more
    or fewer dropped Packets; paths and values are those of the canonical form.

    Each Bot's two streams are aligned on their packet keys (State and name), leaving
    as few Packets unmatched as possible; swapping the sides mirrors the alignment.
    Between two matched pairs, `missing` Divergences come before `unexpected` ones.

    Two matched Packets with fields are diffed field by field (see `_diff`), giving one
    `field` Divergence per differing leaf, in path order. A path joins identifier keys
    with dots and puts list indices in brackets (`players.sample[0].name`); any other
    key is a JSON string in brackets (`m["a.b"]`). If either Packet has no fields, the
    two are compared by payload, with path None and hex values. A `missing` or
    `unexpected` Packet's value is its normalized fields, or its payload as hex.

    Raises:
        ValueError: The Transcripts are of different Scenarios.
        TypeError: A Packet's fields hold something outside the codec value model
            (int, str, bool, bytes, UUID, list, dict of str keys, None, and float).
    """
    if reference.scenario_id != candidate.scenario_id:
        msg = (
            "cannot compare Transcripts of different Scenarios: "
            f"{reference.scenario_id!r} and {candidate.scenario_id!r}"
        )
        raise ValueError(msg)
    indexed = _Masks.of(masks)
    bots = sorted(_bots(reference) | _bots(candidate))
    divergences = tuple(
        divergence
        for bot in bots
        for divergence in _compare_bot(bot, reference, candidate, indexed)
    )
    return Verdict(
        scenario_id=reference.scenario_id,
        outcome=Outcome.MISMATCH if divergences else Outcome.MATCH,
        divergences=divergences,
    )


# Bots and their streams.


@dataclass(frozen=True, slots=True)
class _Normalized:
    """A Packet of a normalized stream, with its fields as the Comparison sees them.

    Attributes:
        packet: The Packet.
        fields: A copy of its fields, in the value model, with the masked paths
            removed; None if it has none, and is then compared by payload.
    """

    packet: Packet
    fields: dict[str, _Value] | None

    @property
    def value(self) -> object:
        """What a `missing` or `unexpected` Divergence shows: fields, else payload hex."""
        return self.packet.payload.hex() if self.fields is None else self.fields


@dataclass(frozen=True, slots=True)
class _Masks:
    """A Comparison's Masks, by packet name.

    Attributes:
        dropped: The names of the packets dropped whole.
        paths: The field paths removed, by packet name.
    """

    dropped: frozenset[str]
    paths: Mapping[str, Sequence[_Path]]

    @classmethod
    def of(cls, masks: Sequence[Mask]) -> Self:
        """Index `masks`."""
        paths: dict[str, list[_Path]] = {}
        for mask in masks:
            if mask.path != WHOLE_PACKET:
                paths.setdefault(mask.packet, []).append(_mask_steps(mask))
        dropped = frozenset(mask.packet for mask in masks if mask.path == WHOLE_PACKET)
        return cls(dropped=dropped, paths=paths)


def _bots(transcript: Transcript) -> set[str]:
    return {event.bot for event in transcript.events}


def _compare_bot(
    bot: str, reference: Transcript, candidate: Transcript, masks: _Masks
) -> Iterator[Divergence]:
    """Compare one Bot's streams; its presence counts Events of any kind, even dropped ones."""
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
    yield from _compare_streams(bot, _stream(reference, bot, masks), _stream(candidate, bot, masks))


def _stream(transcript: Transcript, bot: str, masks: _Masks) -> list[_Normalized]:
    """Return `bot`'s normalized stream: its clientbound Packets, less the dropped ones."""
    return [
        _normalize(event.packet, masks)
        for event in transcript.events
        if event.bot == bot
        and event.packet.direction is Direction.CLIENTBOUND
        and event.packet.name not in masks.dropped
    ]


# Normalization: copies of the fields, in the value model, with Masks applied.


def _normalize(packet: Packet, masks: _Masks) -> _Normalized:
    """Copy `packet`'s fields, put them in canonical form, then apply the Masks."""
    if packet.fields is None:
        return _Normalized(packet=packet, fields=None)
    fields = _plain_mapping(packet.fields.items(), packet.name, ())
    canonical = _CANONICAL.get((packet.state, packet.name))
    if canonical is not None:
        fields = canonical(fields)
    for path in masks.paths.get(packet.name, ()):
        _remove(fields, path)
    return _Normalized(packet=packet, fields=fields)


_LEAF_TYPES: frozenset[type] = frozenset({bool, int, float, str, bytes, UUID})
"""The exact types of the model's leaves besides None; no subclasses (not an IntEnum)."""


def _plain_mapping(
    items: Iterable[tuple[object, object]], packet: str, path: _Path
) -> dict[str, _Value]:
    """Copy a mapping's `items`, checking that they are made of the value model.

    Raises:
        TypeError: A key is not a str, or a value is not in the value model.
    """
    copy: dict[str, _Value] = {}
    for key, item in items:
        if not isinstance(key, str):
            msg = f"{packet}: {_where(path)}: {type(key).__name__} key {key!r} is not a field name"
            raise TypeError(msg)
        copy[key] = _plain(item, packet, (*path, key))
    return copy


def _plain(value: object, packet: str, path: _Path) -> _Value:
    if isinstance(value, Mapping):
        return _plain_mapping(value.items(), packet, path)
    if isinstance(value, list):
        return [_plain(item, packet, (*path, index)) for index, item in enumerate(value)]
    if value is None:
        return None
    if isinstance(value, (bool, int, float, str, bytes, UUID)) and type(value) in _LEAF_TYPES:
        return value
    msg = f"{packet}: {_where(path)}: {type(value).__name__} is not a codec value"
    raise TypeError(msg)


def _remove(fields: dict[str, _Value], path: _Path) -> None:
    """Remove the value at `path` from `fields`, if there is one; a list closes up."""
    node: _Value = fields
    for step in path[:-1]:
        child = _child(node, step)
        if isinstance(child, Absent):
            return
        node = child
    last = path[-1]
    if isinstance(node, dict) and isinstance(last, str):
        node.pop(last, None)
    elif isinstance(node, list) and isinstance(last, int) and last < len(node):
        del node[last]


def _child(node: _Value, step: _Step) -> _Value | Absent:
    if isinstance(node, dict) and isinstance(step, str):
        return node.get(step, ABSENT)
    if isinstance(node, list) and isinstance(step, int) and step < len(node):
        return node[step]
    return ABSENT


# Canonicalization: protocol equivalences, applied before the Masks. It is not masking:
# a Mask says a value is nondeterministic, a canonical form says two encodings mean the
# same thing to the vanilla client. PLAN (Comparison semantics) gives the evidence for
# each entry, and the equivalences considered and not encoded.


_JSON_NESTING_LIMIT = 255
"""The deepest JSON the vanilla client reads: its Gson 2.14.0 JsonReader's default."""


def _canonical_status_response(fields: dict[str, _Value]) -> dict[str, _Value]:
    """Parse `json_response` into its JSON value, with a canonical `description`.

    It stays the raw string, and is compared as one, unless it is strict JSON (no
    repeated key in an object, no NaN or Infinity) nested at most 255 deep.
    """
    text = fields.get("json_response")
    if not isinstance(text, str):
        return fields
    status = _strict_json(text)
    if isinstance(status, Absent):
        return fields
    if isinstance(status, dict) and "description" in status:
        status = {**status, "description": _text_component(status["description"])}
    return {**fields, "json_response": status}


def _text_component(component: _Value) -> _Value:
    """Write each plain-string text component as `{"text": string}`.

    The components are `component` itself, each element of its list form, and each
    element of its `extra`, recursively. Nothing else in it changes.
    """
    if isinstance(component, str):
        return {"text": component}
    if isinstance(component, list):
        return [_text_component(element) for element in component]
    if isinstance(component, dict) and isinstance(extra := component.get("extra"), list):
        return {**component, "extra": [_text_component(element) for element in extra]}
    return component


def _strict_json(text: str) -> _Value | Absent:
    """Parse `text`, or return ABSENT if it is not strict JSON nested at most 255 deep."""
    try:
        value: object = json.loads(
            text, object_pairs_hook=_unique_keys, parse_constant=_not_a_json_number
        )
    except (ValueError, RecursionError):
        return ABSENT
    if _nesting(value) > _JSON_NESTING_LIMIT:
        return ABSENT
    return _plain(value, "json_response", ())


def _unique_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    unique = dict(pairs)
    if len(unique) != len(pairs):
        msg = "a JSON object repeats a key"
        raise ValueError(msg)
    return unique


def _not_a_json_number(name: str) -> NoReturn:
    msg = f"{name} is not a JSON number"
    raise ValueError(msg)


def _nesting(value: object) -> int:
    """How deep `value` nests lists and dicts: 0 for a scalar, 1 for `[]`. Iterative."""
    deepest = 0
    pending: list[tuple[object, int]] = [(value, 1)]
    while pending:
        node, depth = pending.pop()
        children: Iterable[object]
        if isinstance(node, dict):
            children = node.values()
        elif isinstance(node, list):
            children = node
        else:
            continue
        deepest = max(deepest, depth)
        pending.extend((child, depth + 1) for child in children)
    return deepest


_CANONICAL: Mapping[tuple[State, str], Callable[[dict[str, _Value]], dict[str, _Value]]] = (
    MappingProxyType(
        {
            (State.STATUS, "minecraft:status_response"): _canonical_status_response,
        }
    )
)
"""The canonical form of each clientbound packet that has one, by (State, name)."""


# Alignment.


type _Key = tuple[str, str]
"""What a Packet is aligned on: its State and name."""


def _key(entry: _Normalized) -> _Key:
    return (entry.packet.state.value, entry.packet.name)


def _align(reference: Sequence[_Key], candidate: Sequence[_Key]) -> list[tuple[int, int]]:
    """Return the matched (reference index, candidate index) pairs, in order.

    The pairs are a longest common subsequence of the two key sequences: as few
    Packets as possible are left unmatched. Of the longest ones, the choice is fixed
    so that swapping the two sides mirrors it:

    1. The common prefix and the common suffix are matched as they stand. So of
       repeated packets, the prefix matches the earliest and the suffix the latest:
       [a] against [b, a, a] matches the last a.
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


# Diffing.


def _compare_streams(
    bot: str, reference: Sequence[_Normalized], candidate: Sequence[_Normalized]
) -> Iterator[Divergence]:
    pairs = _align([_key(entry) for entry in reference], [_key(entry) for entry in candidate])
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
    bot: str, index: int, kind: Literal["missing", "unexpected"], entry: _Normalized
) -> Divergence:
    return Divergence(
        bot=bot,
        index=index,
        kind=kind,
        packet=entry.packet.name,
        path=None,
        reference=entry.value if kind == "missing" else ABSENT,
        candidate=entry.value if kind == "unexpected" else ABSENT,
    )


def _diff_matched(
    bot: str, index: int, reference: _Normalized, candidate: _Normalized
) -> Iterator[Divergence]:
    if reference.fields is None or candidate.fields is None:
        differences = (
            []
            if reference.packet.payload == candidate.packet.payload
            else [(None, reference.packet.payload.hex(), candidate.packet.payload.hex())]
        )
    else:
        differences = [
            (_render(path), ref_value, cand_value)
            for path, ref_value, cand_value in _diff(reference.fields, candidate.fields, ())
        ]
    for path, ref_value, cand_value in differences:
        yield Divergence(
            bot=bot,
            index=index,
            kind="field",
            packet=reference.packet.name,
            path=path,
            reference=ref_value,
            candidate=cand_value,
        )


def _diff(
    reference: _Value | Absent, candidate: _Value | Absent, path: _Path
) -> Iterator[tuple[_Path, _Value | Absent, _Value | Absent]]:
    """Yield (path, reference value, candidate value) for each difference, in path order.

    Mappings are compared key by key, in sorted key order, and a key only one side has
    is ABSENT on the other. Lists are compared index by index, and elements past the
    end of the shorter one are ABSENT. Anything else is a leaf.
    """
    if isinstance(reference, dict) and isinstance(candidate, dict):
        for key in sorted(reference.keys() | candidate.keys()):
            yield from _diff(reference.get(key, ABSENT), candidate.get(key, ABSENT), (*path, key))
    elif isinstance(reference, list) and isinstance(candidate, list):
        for index in range(max(len(reference), len(candidate))):
            yield from _diff(_element(reference, index), _element(candidate, index), (*path, index))
    elif not _same(reference, candidate):
        yield path, reference, candidate


def _element(items: Sequence[_Value], index: int) -> _Value | Absent:
    return items[index] if index < len(items) else ABSENT


def _same(reference: _Value | Absent, candidate: _Value | Absent) -> bool:
    """Whether two leaves are equal: same exact type, and floats bit for bit."""
    if type(reference) is not type(candidate):
        return False
    if isinstance(reference, float) and isinstance(candidate, float):
        return struct.pack(">d", reference) == struct.pack(">d", candidate)
    return reference == candidate


# Field paths.


_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_DOTTED_KEY = re.compile(r"\.([A-Za-z_][A-Za-z0-9_]*)")
_INDEX = re.compile(r"\[(0|[1-9][0-9]*)\]")
_JSON = json.JSONDecoder()


def _render(path: _Path) -> str:
    """Write a field path: `players.sample[0].name`, or `m["not an identifier"]`.

    A key that is an identifier follows a dot (none at the start). Any other key is a
    JSON string in brackets, and a list index is a number in brackets.
    """
    parts: list[str] = []
    for step in path:
        if isinstance(step, int):
            parts.append(f"[{step}]")
        elif _IDENTIFIER.fullmatch(step):
            parts.append(f".{step}" if parts else step)
        else:
            parts.append(f"[{json.dumps(step, ensure_ascii=False)}]")
    return "".join(parts)


def _where(path: _Path) -> str:
    return _render(path) or "fields"


def _mask_steps(mask: Mask) -> _Path:
    """Return the steps of `mask`'s field path.

    Raises:
        ValueError: The path is malformed, or not spelled as a Divergence path would be.
    """
    steps = _parse_path(mask.path)
    if steps is None:
        msg = f"{mask.packet}: malformed Mask path {mask.path!r}"
        raise ValueError(msg)
    if (spelling := _render(steps)) != mask.path:
        msg = (
            f"{mask.packet}: Mask path {mask.path!r} is spelled unlike a Divergence path;"
            f" write {spelling!r}"
        )
        raise ValueError(msg)
    return steps


def _parse_path(text: str) -> _Path | None:
    """Read a field path in the syntax `_render` writes, or return None if malformed.

    A path starts with a key, bare or quoted, never with an index.
    """
    steps: list[_Step] = []
    position = 0
    while position < len(text) or not steps:
        step = _next_step(text, position, start=not steps)
        if step is None:
            return None
        steps.append(step[0])
        position = step[1]
    return tuple(steps)


def _next_step(text: str, position: int, *, start: bool) -> tuple[_Step, int] | None:
    """Read the step at `position`: return it and where the next one starts, or None."""
    if text.startswith('["', position):
        return _quoted_key(text, position)
    if start:
        match = _IDENTIFIER.match(text, position)
        return None if match is None else (str(match[0]), match.end())
    if match := _DOTTED_KEY.match(text, position):
        return str(match[1]), match.end()
    if match := _INDEX.match(text, position):
        return int(match[1]), match.end()
    return None


def _quoted_key(text: str, position: int) -> tuple[_Step, int] | None:
    """Read `["<JSON string>"]` at `position`, as `_next_step` does."""
    try:
        key, end = _JSON.raw_decode(text, position + 1)
    except json.JSONDecodeError:
        return None
    if isinstance(key, str) and text.startswith("]", end):
        return key, end + 1
    return None
