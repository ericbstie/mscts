"""Comparison: diff the Reference and Candidate Transcripts of one Group into a Verdict.

What is compared is, for every Bot, the ordered stream of the clientbound Packets it
received. If the Group has Observation windows (`GroupContext.observe`), a Bot's play
Packets are compared only inside them, less the heartbeat packets (`HEARTBEAT`); its
status, login and configuration Packets are still compared whole. Everything else is
left out on purpose:

- Serverbound Packets are the Group's own actions and the Bot's automatic answers.
  They differ between Instances by design (the handshake names each Instance's own
  Endpoint), and any difference in them that a server caused shows up first in what
  that server sent.
- Play Packets outside the windows of a Group that has some arrive while it sets the
  world up or cleans up, or on the server's clock.
- Timestamps and Marks are timing data, for Measurements, and say where the windows
  are. The order of a Bot's stream is compared; when its Packets arrived is not.
- The interleaving of different Bots' Packets is timing too, so each Bot is compared
  on its own.
- Entity ids and the random UUIDs of mobs: vanilla gives ids from a counter, so an
  entity spawned outside the windows is compared as its type and its position at its
  first add_entity there (a player as its UUID), and any
  other as the order in which it first appears in the Bot's compared Packets
  (`ENTITY_UUIDS`).
- Control's Bot (`CONTROL_PLAYER`) sets the world up, as an operator: what it receives
  is the servers' answers to that, not what the Group tests.
"""

import bisect
import dataclasses
import json
import re
import struct
from array import array
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum, StrEnum
from functools import cache
from types import MappingProxyType
from typing import Literal, NoReturn, Self, cast, override
from uuid import UUID

from mscts.codec.entity_ids import EACH, Each, EntityIdPath, Step, Variant
from mscts.codec.packets import Codec, Direction, Packet, State
from mscts.codec.registry_names import registry_names
from mscts.codec.schemas.play.chunks import BIOMES, BLOCK_STATES, PalettedContainer
from mscts.codec.wire import WireError
from mscts.spec import CONTROL_PLAYER
from mscts.target import TARGET
from mscts.transcript import Event, Transcript

type _Value = bool | int | float | str | bytes | UUID | list[_Value] | dict[str, _Value] | None
"""A value of the codec value model: what decoded fields are made of."""

type _Step = str | int
"""One step of a field path: a mapping key, or a list index."""

type _Path = tuple[_Step, ...]

type _MaskStep = _Step | Each
"""One step of a Mask's path: a key, an index, or EACH (`[*]`), every index of a list."""

type _MaskPath = tuple[_MaskStep, ...]


class Outcome(StrEnum):
    """What a Verdict says about a Group."""

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

MASKED = "<masked>"
"""What a field Mask shows in place of each value at its path, on both sides.

So two masked values are equal, while a value against None or an absent field is still a
Divergence: a Mask hides a value, never whether it is there.
"""


WHOLE_PACKET = "*"
"""The Mask path that drops the whole packet."""

_MINECRAFT = "minecraft:"
"""The namespace a test case name leaves out."""

OBSERVE_OPEN = "observe:open"
"""The label of the Mark that opens an Observation window.

A window narrowed to some packets has their names after it, each after a space:
`observe:open minecraft:block_update minecraft:system_chat`.
"""

OBSERVE_CLOSE = "observe:close"
"""The label of the Mark that closes an Observation window."""

HEARTBEAT: Mapping[str, str] = MappingProxyType(
    {
        "minecraft:keep_alive": (
            "The server sends it on a clock (every 15 s on vanilla) whatever a Group does, "
            "and its id is random."
        ),
        "minecraft:set_time": (
            "The server sends it on a clock (every 20 ticks on vanilla, even with the world "
            "frozen), so how many arrive depends on how long a window lasts."
        ),
        "minecraft:award_stats": (
            "The answer to the barrier (`Bot.sync`) that ends every window. It carries the "
            "Bot's statistics, not an effect of the Group."
        ),
    }
)
"""The play packets an Observation window never compares, each with the reason.

Evidence: docs/research/2026-09-30-observation-window.md. The barrier's request,
`client_command`, is serverbound, and nothing serverbound is compared.
"""


@dataclass(frozen=True, slots=True)
class Mask:
    """A normalization rule: a field's value, or a whole packet, is excluded from Comparison.

    Attributes:
        packet: The packet name, e.g. `minecraft:login`, in whatever State.
        path: The field path, spelled as Divergence paths are (e.g. `entity_id`,
            `players.sample[0].name`), where `[*]` is every index of a list
            (`players.sample[*].name`); or `*` (WHOLE_PACKET) for the whole packet.
            A path that is an entity id is refused, but a path to a value that holds
            one (`set_entity_data` / `entries`), or `*`, hides the id with the rest:
            its reason is the only guard that nothing a player sees is hidden with it.
        reason: Why it is nondeterministic.
    """

    packet: str
    path: str
    reason: str

    def __post_init__(self) -> None:
        """Reject a Mask that could never be right.

        Raises:
            ValueError: The packet name or the reason is empty, the path is malformed or
                not spelled as a Divergence path would be, or it is an entity id (or a
                list of them), which every Comparison names or numbers instead (#21).
        """
        if not self.packet:
            msg = "a Mask needs a packet name"
            raise ValueError(msg)
        if not self.reason.strip():
            msg = f"{self.packet} {self.path}: a Mask needs a reason"
            raise ValueError(msg)
        if self.path != WHOLE_PACKET and _is_entity_id(self.packet, _mask_steps(self)):
            msg = (
                f"{self.packet} {self.path}: an entity id needs no Mask; every Comparison "
                "names each entity by its type and where it spawned, or numbers it in the "
                "order each Bot first hears of it, so the same entities compare equal on "
                "both servers (#21)"
            )
            raise ValueError(msg)


UNORDERED: Mapping[str, str] = MappingProxyType(
    {
        "minecraft:update_tags": (
            "The client reads its registries, and the tags of each, into maps, and vanilla "
            "sends both in an order that changes from one boot to the next (hash maps). Each "
            "tag's entries keep their order."
        ),
        "minecraft:login": (
            "dimension_names, sorted by name. Vanilla sends them in an order fixed per boot: "
            "MinecraftServer.createLevels adds the overworld, then iterates "
            "MappedRegistry.byKey, a HashMap keyed by ResourceKey, which has no hashCode of its "
            "own. The client reads them into a HashSet (ClientboundLoginPacket.STREAM_CODEC: "
            "ByteBufCodecs.collection(Sets::newHashSetWithExpectedSize))."
        ),
        "minecraft:update_attributes": (
            "attributes, sorted by attribute. Vanilla sends them in an order that changes from "
            "one join to the next: AttributeMap keeps them in fastutil hash collections "
            "(attributesToSync, an ObjectOpenHashSet of AttributeInstance, which has no "
            "hashCode of its own; getSyncableAttributes iterates an Object2ObjectOpenHashMap). "
            "The client applies each to the entity's instance of its attribute "
            "(ClientPacketListener.handleUpdateAttributes: AttributeMap.getInstance, then "
            "setBaseValue, removeModifiers and each modifier), so a repeated attribute keeps "
            "the last. Each attribute's modifiers keep their order."
        ),
        "minecraft:update_recipes": (
            "property_sets, sorted by property_set_id, and each one's items, sorted by item "
            "id. Vanilla sends both in an order fixed per boot: RecipeManager collects the "
            "property sets with Collectors.toUnmodifiableMap and each one's items with "
            "Collectors.toUnmodifiableSet, whose iteration order is salted per boot. The "
            "client reads them into a HashMap of sets (ClientboundUpdateRecipesPacket"
            ".STREAM_CODEC: ByteBufCodecs.map(HashMap::new, ...); RecipePropertySet"
            ".STREAM_CODEC: Set.copyOf), so a repeated property set keeps the last. The "
            "stonecutter recipes keep their order."
        ),
        "minecraft:update_advancements": (
            "removed, sorted by id, and progress, sorted by id, with each one's criteria "
            "sorted by criterion. Vanilla sends them in hash order: PlayerAdvancements"
            ".flushDirty collects the removed ids into a HashSet and the progress into a "
            "HashMap keyed by Identifier, and AdvancementProgress keeps its criteria in a "
            "HashMap. The client reads them into a set and maps "
            "(ClientboundUpdateAdvancementsPacket.STREAM_CODEC: the removed ids into a "
            "LinkedHashSet, the progress with ByteBufCodecs.map(HashMap::new, ...); "
            "AdvancementProgress.STREAM_CODEC: the criteria the same way), so a repeated id "
            "or criterion keeps its last value. The added advancements are read into a list, "
            "and keep their order."
        ),
        "minecraft:level_chunk_with_light": (
            "heightmaps, sorted by the type the client reads (an id it does not know reads as "
            "0, WORLD_SURFACE_WG), and block_entities, sorted by position (y, z, x). Vanilla "
            "sends both in hash order: ClientboundLevelChunkPacketData collects the heightmaps "
            "with Collectors.toMap, a HashMap keyed by the Heightmap$Types enum, in an order "
            "fixed per boot, and iterates the chunk's block entities, an "
            "Object2ObjectOpenHashMap keyed by BlockPos. The client reads the heightmaps into "
            "an EnumMap (ClientboundLevelChunkPacketData.STREAM_CODEC: ByteBufCodecs.map("
            "EnumMap::new, ...)), so a type sent twice keeps the last, and keeps the block "
            "entities in a map keyed by BlockPos (LevelChunk.replaceWithPacketData), loading "
            "those sent for one position in turn."
        ),
    }
)
"""The packets, in any State, whose unordered lists every Comparison sorts, each with the
reason: the hash collection vanilla iterates to send the list, in an order the client does
not keep and that may change from one boot (or join) to the next, and the map or set the
client reads the list into. The sort key is the key of the client's map or set,
and the sort is stable, so of a key sent twice the last stays last. That order is never a
Divergence, not even a network traffic one (docs/research/2026-10-01-control.md, #30).
"""

RANDOM_FIELDS: Mapping[str, str] = MappingProxyType(
    {
        "minecraft:login_finished.session_id": (
            "Vanilla draws it at random when its first connection opens "
            "(ServerConnectionListener.getSessionId), and the client only reports it in its "
            "telemetry."
        ),
        "minecraft:sound.seed": (
            "Vanilla draws it at random for every sound: Level.playSound takes "
            "soundSeedGenerator.nextLong(), which RandomSupport.generateUniqueSeed() seeds "
            "with System.nanoTime(), not with the world seed. The client uses it to pick "
            "the sound's variant."
        ),
        "minecraft:sound_entity.seed": (
            "Vanilla draws it at random for every sound an entity makes: Level.playSound "
            "takes soundSeedGenerator.nextLong(), which RandomSupport.generateUniqueSeed() "
            "seeds with System.nanoTime(), not with the world seed. The client uses it to "
            "pick the sound's variant."
        ),
        "minecraft:update_advancements.progress[*].criteria[*].obtained": (
            "Vanilla reads it from its clock: CriterionProgress.grant sets it to "
            "Instant.now() when the player obtains the criterion, and it is sent as "
            "milliseconds since the epoch, so two runs never send the same time. Whether "
            "the criterion was obtained is still compared."
        ),
    }
)
"""The fields vanilla draws at random, or reads from its clock, on every run, as
`<packet>.<path>`, each with the reason, which says where vanilla draws or reads it. No
Comparison compares their values: two vanilla runs would differ, and their distribution
belongs to a statistical Group (ADR-0011). Whether one is there is still compared, as for
any Mask. Every Comparison masks them before its Group's own Masks, in any State.
"""

ENTITY_UUIDS: Mapping[str, str] = MappingProxyType(
    {
        "minecraft:add_entity.entity_uuid": (
            "Vanilla draws an entity's UUID at random when it creates the entity: the Entity "
            "constructor takes Mth.createInsecureUUID of a new RandomSource. A player's is "
            "its own, from its name or its account, so the add_entity of a player keeps it."
        ),
    }
)
"""The fields that hold the UUID of an entity, as `<packet>.<path>`, each with the reason.

Every Comparison numbers them as it numbers entity ids, by first appearance, but in a count
of their own: `#1` is the first such UUID in a Bot's compared Packets. A packet whose `type`
field is the player's entity type (`minecraft:player`) numbers no UUID, and keeps its own as it is
(Pumpkin's player UUIDs differ from vanilla's, and that is a Divergence), unless an entity
that is not a player has the same UUID: then it shows that entity's number.
"""


type DivergenceKind = Literal["bot", "missing", "unexpected", "field", "failed"]


class Observability(StrEnum):
    """Which kind of difference a Divergence is (ADR-0007).

    `GAMEPLAY`: a vanilla client could tell the two values apart, so a player could
    notice it. `NETWORK_TRAFFIC`: the two servers send the same thing in different
    formats, and a vanilla client ends up with the same result.
    """

    GAMEPLAY = "gameplay"
    NETWORK_TRAFFIC = "network traffic"


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
            `failed`: the Group failed on the Candidate, as `candidate` says (a
            Candidate failure, `run.judge`; never made by `compare`). `bot` and `packet`
            are "", `index` 0, `reference` ABSENT.
        packet: The packet name; "" for `bot` and `failed`.
        path: Where in the matched Packets they differ, or None for their whole
            payload. Always None for `bot`, `missing`, `unexpected` and `failed`.
        reference: The value in the reference, or ABSENT. For `bot`, the number of
            the Bot's Events. For a gameplay difference in a chunk's blocks, biomes or
            light, a text that names the chunk and the first positions that differ, with
            the reference's value at each, or says what its light section is (PLAN,
            Comparison semantics).
        candidate: The value in the candidate, or ABSENT. For `bot`, the number of
            the Bot's Events. For a chunk, as `reference` with the candidate's values.
        test_case: The test case it was found in (`test_case`): its packet's, for
            `missing`, `unexpected` and a `field` Divergence of the whole payload; its
            path's for any other `field` one, the raw path for network traffic. "" for
            `bot` and `failed`, which are about the Group, not one field.
        observability: `network traffic`: a `field` Divergence between raw values whose
            canonical forms are equal, so the vanilla client reads both alike; its path
            and values are the raw ones. `gameplay`: every other Divergence, including
            every `bot`, `missing`, `unexpected` and `failed` one.
    """

    bot: str
    index: int
    kind: DivergenceKind
    packet: str
    path: str | None
    reference: object
    candidate: object
    test_case: str
    observability: Observability = Observability.GAMEPLAY


@dataclass(frozen=True, slots=True)
class Verdict:
    """The result of one Group.

    Attributes:
        group_id: The Group, e.g. `status/basic`.
        outcome: `match` exactly when there are no divergences, from `compare`; so
            network traffic Divergences alone are still a `mismatch` (ADR-0007).
        divergences: Every difference, grouped by Bot in name order, then in stream
            order.
        detail: A human-readable note, e.g. why the Group is blocked.
        test_cases: Every test case the Comparison compared, matched or not, sorted and
            each once; none if the Verdict was made without one (`blocked`, `error`).
    """

    group_id: str
    outcome: Outcome
    divergences: tuple[Divergence, ...] = ()
    detail: str = ""
    test_cases: tuple[str, ...] = ()

    @property
    def gameplay(self) -> tuple[Divergence, ...]:
        """The gameplay Divergences, in order: what compliance scores count."""
        return tuple(
            divergence
            for divergence in self.divergences
            if divergence.observability is Observability.GAMEPLAY
        )

    @property
    def differing(self) -> dict[str, Observability]:
        """The test cases that differ, and how; every other one of `test_cases` is the same.

        A test case differs in gameplay if any of its Divergences is gameplay, and else
        in network traffic only.
        """
        found: dict[str, Observability] = {}
        for divergence in self.divergences:
            name = divergence.test_case
            if name and found.get(name) is not Observability.GAMEPLAY:
                found[name] = divergence.observability
        return found


def compare(reference: Transcript, candidate: Transcript, masks: Sequence[Mask]) -> Verdict:
    """Diff the Candidate's Transcript of a Group against the Reference's.

    Each Bot's stream is normalized first: if the Transcript has Observation windows,
    the play Packets they do not observe are left out (`_Windows.observes`); the
    Packets a `*` Mask names are dropped; the lists of the Packets `UNORDERED` names are
    sorted; the rest are put in canonical form (`_CANONICAL`: e.g. a status response's
    JSON is parsed, and its text components written one way, and a chunk's sections hold
    the id at each entry of their containers, and its light what the client applies to each
    light section; a direct biome container's width is checked against the biomes the Bot's
    configuration sent, `_Context`); each entity id whose
    `add_entity` was left out of the windows becomes its type and its position at the
    first such `add_entity` (`pig@(1.5, -60.0, 7.5)`, read after the Masks; a player's is
    `player <uuid>`), and every other entity id but one first seen in a
    `remove_entities`, and each of the `ENTITY_UUIDS` but a player's, becomes `#<n>`, the
    n-th in the Packets left in the stream, so nothing left out or dropped counts
    (`_Numbers`); and in the Packets of a Mask's name, the value at its path is MASKED on
    both sides, wherever present, unless it is None: a Mask hides a value, never whether
    it is there, so a field or a list element one side lacks is still a Divergence, and a
    masked field is no test case where it does not diverge. The Masks are one for each of
    the `RANDOM_FIELDS`, then `masks`. Indices count the normalized stream, so they do not
    shift when a re-run has more or fewer Packets left out or dropped; paths and values
    are those of the sorted, canonical, numbered form.

    Each Bot's two streams are aligned on their packet keys (State and name), leaving
    as few Packets unmatched as possible; swapping the sides mirrors the alignment.
    Between two matched pairs, `missing` Divergences come before `unexpected` ones.

    Two matched Packets with fields are diffed field by field (see `_diff`), giving one
    gameplay `field` Divergence per differing leaf, in path order. If they have a
    canonical form, their raw fields (with the Masks applied where the paths reach)
    are diffed too: a raw difference is a network traffic Divergence, with the raw path
    and values, when the unmasked canonical values at that path (for a chunk, the canonical
    value that path is part of, `_COVERS`) are equal; otherwise the
    gameplay Divergences under it (or a Mask) account for it. JSON text in a raw field
    (`_JSON_TEXT`) is diffed as its parsed value, at JSON paths, and as the whole text only
    when the parsed values are equal. A packet's network traffic
    Divergences follow its gameplay ones. A path joins identifier keys
    with dots and puts list indices in brackets (`players.sample[0].name`); any other
    key is a JSON string in brackets (`m["a.b"]`). If either Packet has no fields, the
    two are compared by payload, with path None and hex values. A `missing` or
    `unexpected` Packet's value is its normalized fields, or its payload as hex.

    Raises:
        ValueError: The Transcripts are of different Groups.
        TypeError: A Packet's fields hold something outside the codec value model
            (int, str, bool, bytes, UUID, list, dict of str keys, None, and float).
    """
    if reference.group_id != candidate.group_id:
        msg = (
            "cannot compare Transcripts of different Groups: "
            f"{reference.group_id!r} and {candidate.group_id!r}"
        )
        raise ValueError(msg)
    indexed = _Masks.of((*_RANDOM_MASKS, *masks))
    bots = sorted(_bots(reference) | _bots(candidate))
    compared: set[str] = set()
    divergences = tuple(
        divergence
        for bot in bots
        for divergence in _compare_bot(bot, reference, candidate, indexed, compared)
    )
    compared.update(divergence.test_case for divergence in divergences)
    compared.discard("")
    return Verdict(
        group_id=reference.group_id,
        outcome=Outcome.MISMATCH if divergences else Outcome.MATCH,
        divergences=divergences,
        test_cases=tuple(sorted(compared)),
    )


def test_case(state: State, packet: str, path: str | None) -> str:
    """Name the test case that compares `path` of the clientbound `packet` in `state`.

    The name is the packet name without `minecraft:`, then the path as a Divergence
    spells it, with every list index left out: `status_response.players.sample[].name`.
    So the elements of a list share one test case, and so do repeated packets. A path
    of None, for a packet compared as a whole (by payload, missing or unexpected), gives
    the packet name alone. The status response's only field, `json_response`, is JSON
    text (`_JSON_TEXT`), so its paths are named from inside the JSON:
    `status_response.description`, and `status_response` for the text as a whole. A
    packet name that the Target's clientbound packets (`packets.json`) have in more than
    one State starts with the State: `play:keep_alive.id`, `configuration:keep_alive`.

    Raises:
        ValueError: `path` is malformed, or not spelled as a Divergence path would be.
    """
    steps = () if path is None else _steps(packet, path, "field path")
    return _test_case(state, packet, cast("_Path", steps))  # no EACH: `[*]` is malformed here


def _test_case(state: State, packet: str, path: _Path) -> str:
    json_text = _JSON_TEXT.get((state, packet))
    if json_text is not None and path[:1] == (json_text,):
        path = path[1:]
    name = packet.removeprefix(_MINECRAFT)
    if _in_more_than_one_state(packet):
        name = f"{state}:{name}"
    field = _render(path, index_free=True)
    if not field or field.startswith("["):
        return name + field
    return f"{name}.{field}"


@cache
def _in_more_than_one_state(packet: str) -> bool:
    """Whether the Target's `packets.json` has the clientbound `packet` in more than one State."""
    return sum(packet in _codec().names(state, Direction.CLIENTBOUND) for state in State) > 1


@cache
def _codec() -> Codec:
    """The Target's Codec, loaded once."""
    return Codec.for_target(TARGET)


# Bots and their streams.


@dataclass(frozen=True, slots=True)
class _Normalized:
    """A Packet of a normalized stream, with its fields as the Comparison sees them.

    Attributes:
        packet: The Packet.
        fields: A copy of its fields, in the value model, in canonical form, with the
            masked values hidden (`_hidden`); None if it has none, and is then compared by
            payload.
        raw: For a Packet with a canonical form, a copy of its fields as they came,
            with the masked values hidden where the paths reach; else None.
        parsed: For a Packet with a canonical form, `raw` with any JSON text in it
            parsed but not canonical (`_JSON_TEXT`), with the masked values hidden where
            the paths reach; else None.
        unmasked: For a Packet with a canonical form, its canonical form before the
            Masks; else None.
        masked: The paths in `fields` at which a Mask found a value, None included.
    """

    packet: Packet
    fields: dict[str, _Value] | None
    raw: dict[str, _Value] | None = None
    parsed: dict[str, _Value] | None = None
    unmasked: dict[str, _Value] | None = None
    masked: frozenset[_Path] = frozenset()

    @property
    def value(self) -> object:
        """What a `missing` or `unexpected` Divergence shows: fields, else payload hex."""
        return self.packet.payload.hex() if self.fields is None else self.fields


@dataclass(frozen=True, slots=True)
class _Masks:
    """A Comparison's Masks, by packet name.

    Attributes:
        dropped: The names of the packets dropped whole.
        paths: The field paths hidden, by packet name.
    """

    dropped: frozenset[str]
    paths: Mapping[str, Sequence[_MaskPath]]

    @classmethod
    def of(cls, masks: Sequence[Mask]) -> Self:
        """Index `masks`."""
        paths: dict[str, list[_MaskPath]] = {}
        for mask in masks:
            if mask.path != WHOLE_PACKET:
                paths.setdefault(mask.packet, []).append(_mask_steps(mask))
        dropped = frozenset(mask.packet for mask in masks if mask.path == WHOLE_PACKET)
        return cls(dropped=dropped, paths=paths)


def _bots(transcript: Transcript) -> set[str]:
    """The Bots whose streams are compared: every Bot but Control's."""
    return {event.bot for event in transcript.events} - {CONTROL_PLAYER}


def _compare_bot(
    bot: str, reference: Transcript, candidate: Transcript, masks: _Masks, compared: set[str]
) -> Iterator[Divergence]:
    """Compare one Bot's streams; its presence counts Events of any kind, even dropped ones.

    Adds the test case of every pair of values it compares in matched Packets to
    `compared`; a Divergence names the test case of anything else it compares.
    """
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
            test_case="",
        )
    yield from _compare_streams(
        bot, _stream(reference, bot, masks), _stream(candidate, bot, masks), compared
    )


def _stream(transcript: Transcript, bot: str, masks: _Masks) -> list[_Normalized]:
    """Return `bot`'s normalized stream: its clientbound Packets, less the dropped ones.

    If the Transcript has Observation windows, its play Packets are only those inside
    one of them (`_Windows.observes`). Entity ids are numbered over these Packets only
    (`_Numbers.take`): how many entities a Bot heard of before a window is timing, so what
    is not compared never shifts the numbers of what is. An entity whose `add_entity` was
    left out of the windows is named by it instead (`_Numbers.spawned`), and any
    `remove_entities` ends the name or number of the ids it removes (`_Numbers.removed`).
    """
    windows = _Windows.of(transcript)
    context = _Context.of(transcript, bot)
    numbers = _Numbers(ids={}, uuids={})
    stream: list[_Normalized] = []
    for event in transcript.events:
        packet = event.packet
        if event.bot != bot or packet.direction is not Direction.CLIENTBOUND:
            continue
        if windows is not None and not windows.observes(event):
            numbers.spawned(packet, masks)
        elif packet.name not in masks.dropped:
            numbers.take(packet)
            stream.append(_normalize(packet, masks, numbers, context))
        numbers.removed(packet)
    return stream


_BIOMES_REGISTRY = "minecraft:worldgen/biome"


@dataclass(frozen=True, slots=True)
class _Context:
    """What a canonical form needs from the rest of a Bot's Transcript.

    Attributes:
        biomes: How many biomes the server sent the Bot in configuration (the entries of
            its `registry_data` for `minecraft:worldgen/biome`), or None if it sent none.
    """

    biomes: int | None

    @classmethod
    def of(cls, transcript: Transcript, bot: str) -> Self:
        """The context of `bot`'s stream, from all of its Events, compared or not."""
        counts: list[int] = []
        for event in transcript.events:
            packet = event.packet
            if (
                event.bot == bot
                and (packet.state, packet.direction, packet.name)
                == (State.CONFIGURATION, Direction.CLIENTBOUND, "minecraft:registry_data")
                and packet.fields is not None
                and packet.fields.get("registry_id") == _BIOMES_REGISTRY
                and isinstance(entries := packet.fields.get("entries"), list)
            ):
                counts.append(len(cast("list[object]", entries)))
        return cls(biomes=sum(counts) if counts else None)


@dataclass(frozen=True, slots=True)
class _Windows:
    """A Transcript's Observation windows: its `observe:` Marks, in time order.

    Attributes:
        times: When each Mark was recorded, ascending.
        names: For each Mark, None if it closes a window, else the names that narrow the
            window it opens (empty for none).
    """

    times: Sequence[int]
    names: Sequence[frozenset[str] | None]

    @classmethod
    def of(cls, transcript: Transcript) -> Self | None:
        """Index the windows of `transcript`; None if it has none."""
        times: list[int] = []
        names: list[frozenset[str] | None] = []
        for mark in sorted(transcript.marks, key=lambda mark: mark.t_ns):
            label, *narrowed = mark.label.split(" ")
            if label in {OBSERVE_OPEN, OBSERVE_CLOSE}:
                times.append(mark.t_ns)
                names.append(frozenset(narrowed) if label == OBSERVE_OPEN else None)
        return cls(times=times, names=names) if times else None

    def observes(self, event: Event) -> bool:
        """Whether the Comparison takes `event`, a clientbound Packet of this Transcript.

        A packet of any State but play is always taken. A play packet is taken if it
        arrived at or after an open Mark and before the next Mark (a window that never
        closed runs to the end), the window's names include it, if it has any, and it
        is not a heartbeat packet (`HEARTBEAT`).
        """
        packet = event.packet
        if packet.state is not State.PLAY:
            return True
        if packet.name in HEARTBEAT:
            return False
        latest = bisect.bisect_right(self.times, event.t_ns) - 1
        if latest < 0:
            return False
        narrowed = self.names[latest]
        return narrowed is not None and (not narrowed or packet.name in narrowed)


# Entity numbering (#21): each entity id in a Bot's compared Packets, and each entity UUID
# (`ENTITY_UUIDS`), becomes `#<n>` in the order it first appears there, after Canonicalization
# and before the Masks. Vanilla gives ids from a counter and mobs random UUIDs, so the same
# entities on two servers compare equal only by their order. Packets left out of the
# Comparison (outside the windows) take no number: how many arrived is timing. But an entity
# whose add_entity came outside the windows is named by its type and its position at the
# first such add_entity (#116; a player by its UUID, as where a player joins is not fixed),
# which the Group's setup fixes, so an action inside a window on the wrong one of two such
# entities is still a Divergence. The Codec says where a packet's entity ids are.


@dataclass(frozen=True, slots=True)
class _Trie:
    """Paths into a value, merged on their first steps: a walk visits each end once, in order.

    Attributes:
        here: A path ends here.
        steps: Each next step, with what goes on from it, in the order the paths came.
    """

    here: bool
    steps: tuple[tuple[Step, "_Trie"], ...]

    @classmethod
    def of(cls, paths: Iterable[EntityIdPath]) -> Self:
        """Merge `paths`."""
        here = False
        rests: dict[Step, list[EntityIdPath]] = {}
        for path in paths:
            if path:
                rests.setdefault(path[0], []).append(path[1:])
            else:
                here = True
        return cls(here=here, steps=tuple((step, cls.of(rest)) for step, rest in rests.items()))


def _found(value: object, trie: _Trie) -> Iterator[object]:
    """The values at the ends of `trie`'s paths in `value`, in wire order."""
    if trie.here:
        yield value
    for step, rest in trie.steps:
        for child in _next(value, step):
            yield from _found(child, rest)


def _next(value: object, step: Step) -> Sequence[object]:
    """What `step` leads to from `value`: nothing if the value has no such part."""
    if not isinstance(step, Variant | str):
        return value if isinstance(value, list) else ()
    if not isinstance(value, Mapping):
        return ()
    mapping = cast("Mapping[str, object]", value)  # a Packet's fields, or a value in them
    if isinstance(step, Variant):
        return (mapping,) if mapping.get(step.key) == step.name else ()
    return (mapping[step],) if step in mapping else ()


def _replaced(value: _Value, trie: _Trie, number: Callable[[_Value], _Value]) -> _Value:
    """`value` with each value at the end of `trie`'s paths replaced by `number` of it.

    Lists and mappings on the way are changed in place.
    """
    if trie.here:
        return number(value)
    for step, rest in trie.steps:
        if isinstance(step, Variant):
            if isinstance(value, dict) and value.get(step.key) == step.name:
                value = _replaced(value, rest, number)
        elif isinstance(step, str):
            if isinstance(value, dict) and step in value:
                value[step] = _replaced(value[step], rest, number)
        elif isinstance(value, list):
            value[:] = [_replaced(item, rest, number) for item in value]
    return value


@dataclass(slots=True)
class _Numbers:
    """The names of the entities in a Bot's stream so far, `_stream` feeding it in order.

    An entity spawned outside the windows is named by its `add_entity` (`spawned`); any
    other entity id, and each entity UUID, is numbered by first appearance in the compared
    Packets (`take`): `#1` is the first.

    Attributes:
        ids: Each entity id's name or number.
        uuids: Each entity UUID's number, counted on their own.
        numbered: How many entity ids have taken a number.
        names: How many entities have taken each name, before its suffix.
    """

    ids: dict[int, str]
    uuids: dict[UUID, str]
    numbered: int = 0
    names: dict[str, int] = dataclasses.field(default_factory=dict)

    def spawned(self, packet: Packet, masks: _Masks) -> None:
        """Note `packet`, one the Comparison leaves out: an `add_entity` names its entity.

        The name is the entity's type and its position at its first `add_entity` before the
        window (`pig@(1.5, -60.0, 7.5)`), which the Group's own setup fixes, however many
        other entities arrived first. A later `add_entity` for the id keeps the first name,
        unless a `remove_entities` ended it in between (`removed`): vanilla sends one again
        only after that, or after the client's world is reset. A player is named by its
        UUID instead (`player <uuid>`): where a player joins is not fixed by the Group. The
        fields go through the Group's Masks first, so a masked axis reads MASKED; a `*`
        Mask on `add_entity` names nothing, so its entities are numbered like the rest. A
        name an earlier entity already took gets a suffix, ` #2` for the second, in the
        order the Bot heard of them, so a Mask never makes two entities one.
        """
        if packet.name != _ADD_ENTITY or packet.fields is None or packet.name in masks.dropped:
            return
        entity_id = packet.fields.get("entity_id")
        if type(entity_id) is int and entity_id not in self.ids:
            fields = _copy(packet, packet.fields)
            _hide_all(fields, masks.paths.get(packet.name, ()))
            name = (
                f"player {fields.get('entity_uuid')}" if _is_player(fields) else _spawn_name(fields)
            )
            taken = self.names.get(name, 0) + 1
            self.names[name] = taken
            self.ids[entity_id] = name if taken == 1 else f"{name} #{taken}"

    def take(self, packet: Packet) -> None:
        """Number the entity ids and UUIDs in `packet`, the next compared one, not yet known.

        Without windows, the first is the Bot's own player, from `login`. An id of None (no
        entity) is not an entity, and neither is the UUID of a player (`ENTITY_UUIDS`). An id
        first seen in a `remove_entities` takes no number: the entity is gone, and a number
        would shift every later one.
        """
        if packet.fields is None or packet.name == _REMOVE_ENTITIES:
            return
        ids, uuids = _entity_tries(packet.state, packet.name)
        for found in _found(packet.fields, ids):
            if type(found) is int and found not in self.ids:
                self.numbered += 1
                self.ids[found] = f"#{self.numbered}"
        if not _is_player(packet.fields):
            for found in _found(packet.fields, uuids):
                if isinstance(found, UUID):
                    self.uuids.setdefault(found, f"#{len(self.uuids) + 1}")

    def removed(self, packet: Packet) -> None:
        """End the name or number of each id `packet` removes, if it is a `remove_entities`.

        Compared or not: the client forgets the entities either way, so a later `add_entity`
        with one of the ids is a new entity.
        """
        if packet.name != _REMOVE_ENTITIES or packet.fields is None:
            return
        ids, _ = _entity_tries(packet.state, packet.name)
        for found in _found(packet.fields, ids):
            if type(found) is int:
                self.ids.pop(found, None)

    def apply(self, packet: Packet, fields: dict[str, _Value]) -> None:
        """Replace each entity id and entity UUID in `fields`, a copy of `packet`'s fields.

        A player's UUID took no number, so it stays as it is, unless an entity that is not
        a player had it too: then it shows that entity's number. An id a `remove_entities`
        removes that the Bot never heard of shows `#?` (`_UNKNOWN_ENTITY`): its value is the
        server's counter, which is timing.
        """
        ids, uuids = _entity_tries(packet.state, packet.name)
        # `take` has given every other id of the packet a name or number already.
        _replaced(
            fields,
            ids,
            lambda value: self.ids.get(value, _UNKNOWN_ENTITY) if type(value) is int else value,
        )
        _replaced(
            fields,
            uuids,
            lambda value: self.uuids.get(value, value) if isinstance(value, UUID) else value,
        )


@cache
def _entity_tries(state: State, packet: str) -> tuple[_Trie, _Trie]:
    """Where the clientbound `packet` in `state` has entity ids, and entity UUIDs.

    Raises:
        ValueError: An `ENTITY_UUIDS` path is malformed, or has a list index.
    """
    ids = _codec().entity_id_paths(state, Direction.CLIENTBOUND, packet)
    return _Trie.of(ids), _Trie.of(_uuid_paths(packet, ENTITY_UUIDS))


def _uuid_paths(packet: str, fields: Iterable[str]) -> tuple[EntityIdPath, ...]:
    """The paths in `packet` of those `fields` (`<packet>.<path>`, as `ENTITY_UUIDS`) it has.

    Raises:
        ValueError: A path of `packet` is malformed, or has a list index.
    """
    paths: list[EntityIdPath] = []
    for field in fields:
        name, _, path = field.partition(".")
        if name == packet:
            steps = _steps(name, path, "ENTITY_UUIDS path")
            keys = tuple(step for step in steps if isinstance(step, str))
            if keys != steps:
                msg = f"{field}: an entity UUID's path has keys only"
                raise ValueError(msg)
            paths.append(keys)
    return tuple(paths)


def _is_entity_id(packet: str, path: _MaskPath) -> bool:
    """Whether `path` is an entity id of the clientbound `packet`, in any State, or a list of them.

    A list index or EACH in `path` stands for any element, and a Variant step is not in a
    path.
    """
    for state in State:
        for entity_path in _codec().entity_id_paths(state, Direction.CLIENTBOUND, packet):
            keys = tuple(step for step in entity_path if not isinstance(step, Variant))
            while True:
                if len(keys) == len(path) and all(map(_step_fits, path, keys)):
                    return True
                if not keys or not isinstance(keys[-1], Each):
                    break
                keys = keys[:-1]
    return False


def _step_fits(step: _MaskStep, key: Step) -> bool:
    """Whether a Mask path's `step` is `key`, an entity id path's: EACH is any list index."""
    if isinstance(key, Each):
        return isinstance(step, Each) or type(step) is int
    return step == key


_ADD_ENTITY = "minecraft:add_entity"
_REMOVE_ENTITIES = "minecraft:remove_entities"
_UNKNOWN_ENTITY = "#?"
"""An id a `remove_entities` removes that the Bot had not heard of: it took no number."""


def _spawn_name(fields: Mapping[str, object]) -> str:
    """An entity's name from its `add_entity` `fields`: its type and position there.

    For example `pig@(1.5, -60.0, 7.5)`. A type id outside the registry is written as the
    number, a masked axis as MASKED, and -0.0 as 0.0.
    """
    kind = fields.get("type")
    names = registry_names(TARGET.minecraft_version, "minecraft:entity_type")
    if type(kind) is int and 0 <= kind < len(names):
        kind = names[kind].removeprefix("minecraft:")
    position = ", ".join(_axis(fields.get(axis)) for axis in ("x", "y", "z"))
    return f"{kind}@({position})"


def _axis(value: object) -> str:
    """One axis of a position in a name: MASKED as is, -0.0 as 0.0, else its repr."""
    if value == MASKED:
        return MASKED
    return repr(value + 0.0) if type(value) is float else repr(value)


def _is_player(fields: Mapping[str, object]) -> bool:
    """Whether `fields` are a player's: their `type` is the player's entity type id."""
    kind = fields.get("type")
    return type(kind) is int and kind == _player_type()


@cache
def _player_type() -> int:
    """The protocol id of `minecraft:player` among the entity types: what add_entity's `type` is."""
    names = registry_names(TARGET.minecraft_version, "minecraft:entity_type")
    return names.index("minecraft:player")


# Normalization: copies of the fields, in the value model, with Masks applied.


def _normalize(packet: Packet, masks: _Masks, numbers: _Numbers, context: _Context) -> _Normalized:
    """Copy `packet`'s fields; sort, canonicalize, number the entities, and apply the Masks.

    Sorting is `UNORDERED`'s, the numbers are `numbers`', and the canonical form may use
    `context`.
    """
    if packet.fields is None:
        return _Normalized(packet=packet, fields=None)
    paths = masks.paths.get(packet.name, ())
    canonical = _CANONICAL.get((packet.state, packet.name))
    if canonical is None:
        fields = _copy(packet, packet.fields)
        numbers.apply(packet, fields)
        masked = _hide_all(fields, paths)
        return _Normalized(packet=packet, fields=fields, masked=masked)
    raw = _copy(packet, packet.fields)
    parsed = _copy(packet, packet.fields)
    if (json_text := _JSON_TEXT.get((packet.state, packet.name))) is not None:
        parsed = _parsed(parsed, json_text)
    unmasked = canonical(_copy(packet, packet.fields), context)
    fields = canonical(_copy(packet, packet.fields), context)
    for copy in (raw, parsed, unmasked, fields):
        numbers.apply(packet, copy)
    for copy in (raw, parsed):
        _hide_all(copy, paths)
    masked = _hide_all(fields, paths)
    return _Normalized(
        packet=packet, fields=fields, raw=raw, parsed=parsed, unmasked=unmasked, masked=masked
    )


def _copy(packet: Packet, fields: Mapping[str, object]) -> dict[str, _Value]:
    """A copy of `fields`, `packet`'s, in the value model, sorted if `UNORDERED` names it."""
    copy = _plain_mapping(fields.items(), packet.name, ())
    sort = _SORTS.get(packet.name)
    return copy if sort is None else sort(copy)


def _hide_all(fields: dict[str, _Value], paths: Iterable[_MaskPath]) -> frozenset[_Path]:
    """Hide the value at each of `paths` in `fields` (`_hidden`); return where one stood."""
    found: list[_Path] = []
    for path in paths:
        _hidden(fields, path, (), found)
    return frozenset(found)


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


def _hidden(value: _Value, path: _MaskPath, at: _Path, found: list[_Path]) -> _Value:
    """`value` with MASKED in place of what is at `path` in it, unless that is None.

    EACH in `path` is every element of a list. `at` is where `value` is in the fields;
    each path in the fields at which a value stands, None included, is added to `found`.
    A list keeps its length. Lists and mappings on the way are changed in place.
    """
    if not path:
        found.append(at)
        return value if value is None else MASKED
    step, rest = path[0], path[1:]
    if isinstance(value, dict) and isinstance(step, str) and step in value:
        value[step] = _hidden(value[step], rest, (*at, step), found)
    elif isinstance(value, list) and isinstance(step, Each):
        value[:] = [_hidden(item, rest, (*at, index), found) for index, item in enumerate(value)]
    elif isinstance(value, list) and isinstance(step, int) and step < len(value):
        value[step] = _hidden(value[step], rest, (*at, step), found)
    return value


def _child(node: _Value, step: _Step) -> _Value | Absent:
    if isinstance(node, dict) and isinstance(step, str):
        return node.get(step, ABSENT)
    if isinstance(node, list) and isinstance(step, int) and step < len(node):
        return node[step]
    return ABSENT


# Sorting: the lists `UNORDERED` names, sorted before anything else, so their order is no
# Divergence at all. Vanilla's own order changes from one boot to the next, so a Candidate's
# order could never be told apart from it (PLAN, Comparison semantics, step 3).


def _sorted_update_tags(fields: dict[str, _Value]) -> dict[str, _Value]:
    """Order `tagged_registries` by registry, and each one's `tags` by tag name.

    The sorts are stable, so a name sent twice keeps the order of its values: the client
    keeps the last one. A tag's `entries` keep their order.
    """
    registries = fields.get("tagged_registries")
    if not isinstance(registries, list):
        return fields
    sorted_tags = [_with_sorted(registry, "tags", "tag_name") for registry in registries]
    return {**fields, "tagged_registries": _sorted_by(sorted_tags, "registry")}


def _sorted_update_recipes(fields: dict[str, _Value]) -> dict[str, _Value]:
    """Order `property_sets` by id, and each one's `items` by item id.

    The sorts are stable, so an id sent twice keeps the order of its items: the client keeps
    the last one. The stonecutter recipes keep their order.
    """
    sets = fields.get("property_sets")
    if not isinstance(sets, list):
        return fields
    sorted_items = [_with_sorted(property_set, "items", None) for property_set in sets]
    return {**fields, "property_sets": _sorted_by(sorted_items, "property_set_id")}


def _sorted_update_advancements(fields: dict[str, _Value]) -> dict[str, _Value]:
    """Order `removed` by id, `progress` by id, and each one's `criteria` by criterion.

    The sorts are stable, so an id or a criterion sent twice keeps the order of its values:
    the client keeps the last one. The added advancements keep their order.
    """
    result = dict(fields)
    if "removed" in fields:
        result["removed"] = _sorted_by(fields["removed"], None)
    if isinstance(progress := fields.get("progress"), list):
        sorted_criteria = [_with_sorted(each, "criteria", "criterion") for each in progress]
        result["progress"] = _sorted_by(sorted_criteria, "id")
    return result


def _with_sorted(node: _Value, field: str, key: str | None) -> _Value:
    """`node` with its list `field` sorted as `_sorted_by` does with `key`."""
    if isinstance(node, dict) and field in node:
        return {**node, field: _sorted_by(node[field], key)}
    return node


def _sorted_by(items: _Value, key: str | None) -> _Value:
    """`items` stably sorted by each one's `key`, or by each one itself if `key` is None.

    Unchanged unless it is a list whose sort keys are all str, or all int.
    """
    if not isinstance(items, list):
        return items
    keys = [item if key is None else _sort_key(item, key) for item in items]
    names = [name for name in keys if isinstance(name, str)]
    numbers = [number for number in keys if type(number) is int]
    if len(names) == len(items):
        return [items[index] for index in sorted(range(len(items)), key=names.__getitem__)]
    if len(numbers) == len(items):
        return [items[index] for index in sorted(range(len(items)), key=numbers.__getitem__)]
    return items


def _sort_key(item: _Value, key: str) -> _Value:
    return item.get(key) if isinstance(item, dict) else None


_HEIGHTMAP_TYPES = 6
"""How many `Heightmap$Types` the client has: it reads any other id as the first, 0
(`ByIdMap.continuous` with `OutOfBoundsStrategy.ZERO`)."""


def _sorted_level_chunk(fields: dict[str, _Value]) -> dict[str, _Value]:
    """Order `heightmaps` by the type the client reads, and `block_entities` by position.

    The sorts are stable, so a type sent twice keeps the order of its values (the client
    keeps the last one), and so do block entities sent for one position (the client loads
    each in turn).
    """
    result = dict(fields)
    if "heightmaps" in fields:
        result["heightmaps"] = _sorted_on(fields["heightmaps"], _heightmap_type)
    if "block_entities" in fields:
        result["block_entities"] = _sorted_on(fields["block_entities"], _block_position)
    return result


def _sorted_on(items: _Value, key: Callable[[_Value], tuple[int, ...] | None]) -> _Value:
    """`items` stably sorted by `key` of each one; unchanged unless no key is None."""
    if not isinstance(items, list):
        return items
    keys = [key(item) for item in items]
    known = [each for each in keys if each is not None]
    if len(known) != len(items):
        return items
    return [items[index] for index in sorted(range(len(items)), key=known.__getitem__)]


def _heightmap_type(item: _Value) -> tuple[int, ...] | None:
    kind = item.get("type") if isinstance(item, dict) else None
    if type(kind) is not int:
        return None
    return (kind if 0 <= kind < _HEIGHTMAP_TYPES else 0,)


def _block_position(item: _Value) -> tuple[int, ...] | None:
    if not isinstance(item, dict):
        return None
    position = [item.get(axis) for axis in ("y", "z", "x")]
    numbers = [each for each in position if type(each) is int]
    return tuple(numbers) if len(numbers) == len(position) else None


def _sorting(field: str, key: str | None) -> Callable[[dict[str, _Value]], dict[str, _Value]]:
    """Sort the list `field` of a packet's fields, as `_sorted_by` does with `key`."""

    def sort(fields: dict[str, _Value]) -> dict[str, _Value]:
        return {**fields, field: _sorted_by(fields[field], key)} if field in fields else fields

    return sort


_SORTS: Mapping[str, Callable[[dict[str, _Value]], dict[str, _Value]]] = MappingProxyType(
    {
        "minecraft:update_tags": _sorted_update_tags,
        "minecraft:login": _sorting("dimension_names", None),
        "minecraft:update_attributes": _sorting("attributes", "attribute"),
        "minecraft:update_recipes": _sorted_update_recipes,
        "minecraft:update_advancements": _sorted_update_advancements,
        "minecraft:level_chunk_with_light": _sorted_level_chunk,
    }
)
"""How each packet `UNORDERED` names is sorted, by name, in any State."""


# Canonicalization: protocol equivalences, applied before the Masks. It is not masking:
# a Mask says a value is nondeterministic, a canonical form says two encodings mean the
# same thing to the vanilla client. It classifies, never erases: a raw difference it
# makes equal is a network traffic Divergence (ADR-0007). PLAN (Comparison semantics) gives
# the evidence for each entry of the canonical table, and the equivalences considered
# and not encoded.


_JSON_NESTING_LIMIT = 255
"""The deepest JSON the vanilla client reads: its Gson 2.14.0 JsonReader's default."""


def _parsed(fields: dict[str, _Value], json_text: str) -> dict[str, _Value]:
    """Parse the field `json_text` of `fields` into its JSON value, as it came.

    It stays the raw string unless it is strict JSON (no repeated key in an object, no
    NaN or Infinity) nested at most 255 deep.
    """
    text = fields.get(json_text)
    if not isinstance(text, str):
        return fields
    value = _strict_json(text)
    if isinstance(value, Absent):
        return fields
    return {**fields, json_text: value}


def _canonical_status_response(fields: dict[str, _Value], _context: _Context) -> dict[str, _Value]:
    """Parse `json_response` into its JSON value: the members the client reads, canonical.

    It stays the raw string, and is compared as one, unless it is strict JSON.
    """
    fields = _parsed(fields, "json_response")
    status = fields.get("json_response")
    if isinstance(status, dict):
        status = _as_read(status)
        if "description" in status:
            status = {**status, "description": _text_component(status["description"])}
        status = _without_declared_defaults(status)
    return {**fields, "json_response": status}


_STATUS_FIELDS: Mapping[str, frozenset[str]] = MappingProxyType(
    {
        "": frozenset({"description", "players", "version", "favicon", "enforcesSecureChat"}),
        "players": frozenset({"max", "online", "sample"}),
        "version": frozenset({"name", "protocol"}),
    }
)
"""The keys the client's record codecs read: of the status object (""), and of the
`players` and `version` objects in it (docs/research/2026-09-26-comparison.md)."""


def _as_read(status: dict[str, _Value]) -> dict[str, _Value]:
    """Keep only the members of the status (and its `players`, `version`) the client reads.

    Its record codecs look each field up by name, so a key they do not name is never
    read, and `JsonOps` reads a JSON `null` member as a missing one (PLAN, Comparison
    semantics).
    """
    result = _read_members(status, _STATUS_FIELDS[""])
    for key in ("players", "version"):
        if isinstance(inner := result.get(key), dict):
            result[key] = _read_members(inner, _STATUS_FIELDS[key])
    return result


def _read_members(value: dict[str, _Value], fields: frozenset[str]) -> dict[str, _Value]:
    return {key: item for key, item in value.items() if key in fields and item is not None}


def _without_declared_defaults(status: dict[str, _Value]) -> dict[str, _Value]:
    """Drop each field of a status that holds exactly the default the client reads for it.

    `ServerStatus.CODEC` reads an absent `description` as an empty text component,
    `enforcesSecureChat` as false, and `players.sample` as an empty list (PLAN, Comparison
    semantics). `description` is already canonical here.
    """
    result = {
        key: value
        for key, value in status.items()
        if not (key == "description" and value == {"text": ""})
        and not (key == "enforcesSecureChat" and value is False)
    }
    players = result.get("players")
    if isinstance(players, dict) and players.get("sample", ABSENT) == []:
        result["players"] = {key: value for key, value in players.items() if key != "sample"}
    return result


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


# Chunks (#22): a chunk's blocks and biomes as the vanilla client keeps them, whatever palette
# the server spelled them with (docs/research/2026-10-02-chunks-light.md).


_CONTAINERS: Mapping[str, tuple[PalettedContainer, int]] = MappingProxyType(
    {"block_states": (BLOCK_STATES, 16), "biomes": (BIOMES, 4)}
)
"""A section's paletted containers, by field, each with how many entries are on its side: a
section is 16 blocks, or 4 biome cells, wide, deep and high."""


def _canonical_level_chunk(fields: dict[str, _Value], context: _Context) -> dict[str, _Value]:
    """A chunk's sections and light as the client keeps them.

    Each section's block states and biomes become the id at each entry (`_entries`,
    `_biome_entries`), and the light what the client applies (`_canonical_light`), for two
    light sections more than sections. The client keeps the id at each position, not the
    palette that spelled it: `LevelChunkSection.read` reads each container with
    `PalettedContainer.read`, which unpacks its entries at the width the palette is read at.
    """
    sections = fields.get("sections")
    if not isinstance(sections, list):
        return fields
    result = {
        **fields,
        "sections": [_canonical_section(section, context.biomes) for section in sections],
    }
    if "light" in fields:
        result["light"] = _canonical_light(fields["light"], len(sections) + _LIGHT_MARGIN)
    return result


def _canonical_section(section: _Value, biomes: int | None) -> _Value:
    if not isinstance(section, dict):
        return section
    result = dict(section)
    if isinstance(states := section.get("block_states"), dict):
        result["block_states"] = _entries(BLOCK_STATES, states)
    if isinstance(cells := section.get("biomes"), dict):
        result["biomes"] = _biome_entries(cells, biomes)
    return result


def _biome_entries(value: dict[str, _Value], biomes: int | None) -> _Value:
    """A biome container's ids (`_entries`), or what is wrong with a direct one's width.

    The client reads a direct biome container at `Mth.ceillog2` of the biomes the server sent
    it (`Strategy.<init>`, `Configuration$Global`), whatever bits per entry are sent; the
    codec reads it at the bits sent. If the Transcript has the biomes and the bits are not
    that width, the client reads other ids than these, so the container is a value of its
    own: the bits, the width the client reads, and the data.
    """
    bits, data = value.get("bits"), value.get("data")
    if biomes is not None and value.get("palette") is None and isinstance(data, bytes):
        width = (biomes - 1).bit_length()
        if bits != width:
            return f"{bits} bits per entry where the client reads {width}: {data.hex()}"
    return _entries(BIOMES, value)


def _entries(container: PalettedContainer, value: dict[str, _Value]) -> _Value:
    """A container's ids, entry by entry: one id if every entry has it, else `_packed_ids`.

    A container `PalettedContainer.values` cannot read stays as it is.
    """
    try:
        ids = container.values(value)
    except (KeyError, WireError):
        return value
    first = ids[0]
    if first is not None and ids.count(first) == len(ids):
        return first
    return _packed_ids(ids)


def _packed_ids(ids: Sequence[int | None]) -> bytes:
    """`ids` one after the other, as bytes that are equal exactly when the ids are.

    Each is its id plus 1 (0 for an entry past its palette), in as many big-endian bytes as
    the largest one needs.
    """
    numbers = [0 if each is None else each + 1 for each in ids]
    size = max(1, -(-max(numbers).bit_length() // 8))
    return b"".join(number.to_bytes(size, "big") for number in numbers)


def _unpacked_ids(data: bytes, entries: int) -> list[int | None]:
    """The `entries` ids `_packed_ids` packed into `data`."""
    size = len(data) // entries
    numbers = (
        int.from_bytes(data[start : start + size], "big") for start in range(0, len(data), size)
    )
    return [None if number == 0 else number - 1 for number in numbers]


_LIGHT_LAYERS: Mapping[str, str] = MappingProxyType(
    {
        "sky_light_mask": "sky",
        "empty_sky_light_mask": "sky",
        "sky_light_arrays": "sky",
        "block_light_mask": "block",
        "empty_block_light_mask": "block",
        "block_light_arrays": "block",
    }
)
"""The fields of light data (`LIGHT_DATA`), each with the layer of the canonical form it
is part of."""

_LIGHT_BYTES = 2048
"""How many bytes a light array has: `new DataLayer(byte[])` refuses any other length."""

_LIGHT_MARGIN = 2
"""How many more light sections a level has than sections: one below it, one above it
(`LevelLightEngine.getLightSectionCount`)."""

_LIGHT_SECTIONS_MAX = 256
"""The most light sections a level has: `DimensionType`'s height is at most `Y_SIZE`,
`(1 << BlockPos.PACKED_Y_LENGTH) - 32`, 4064 blocks, so 254 sections, and the margin."""

_EMPTY = "empty"
"""A light section sent empty, where the client's light is not the same as an array of 0s."""


def _canonical_light(light: _Value, sections: int) -> _Value:
    """Light data as the client applies it: the light each light section gets, by layer.

    For each of the `sections` light sections, that is the next array if the mask has its bit
    (an array the client cannot take shows what is wrong), else an empty section if the empty
    mask has it, else None: the client keeps the light it had
    (`ClientPacketListener.readSectionList`). Bits from `sections` up
    are never read, and neither are the arrays past the mask's bits. An empty section is an
    array of 0s for block light, and for sky light in light section 0, below the world: no
    client code tells them apart there (docs/research/2026-10-02-chunks-light.md). Light data
    not decoded by the codec stays as it is.
    """
    if not isinstance(light, dict):
        return light
    sky, block = (_light_layer(light, layer, sections) for layer in ("sky", "block"))
    if sky is None or block is None:
        return light
    return {"sky": sky, "block": block}


def _light_layer(light: dict[str, _Value], layer: str, sections: int) -> list[_Value] | None:
    mask = light.get(f"{layer}_light_mask")
    empty = light.get(f"empty_{layer}_light_mask")
    arrays = light.get(f"{layer}_light_arrays")
    if not (isinstance(mask, bytes) and isinstance(empty, bytes) and isinstance(arrays, list)):
        return None
    sent, emptied = int.from_bytes(mask, "little"), int.from_bytes(empty, "little")
    left = iter(arrays)
    result: list[_Value] = []
    for index in range(sections):
        value: _Value = None
        if sent >> index & 1:
            value = next(left, "no array left")
            if isinstance(value, bytes) and len(value) != _LIGHT_BYTES:
                value = f"an array of {len(value)} bytes"
        elif emptied >> index & 1:
            value = bytes(_LIGHT_BYTES) if layer == "block" or index == 0 else _EMPTY
        result.append(value)
    return result


def _canonical_light_update(fields: dict[str, _Value], _context: _Context) -> dict[str, _Value]:
    """The light data as the client applies it (`_canonical_light`).

    Over as many light sections as any level has: a light update does not say how high its
    level is.
    """
    if "data" not in fields:
        return fields
    return {**fields, "data": _canonical_light(fields["data"], _LIGHT_SECTIONS_MAX)}


def _chunk_cover(path: _Path) -> _Path:
    """The path of the canonical value that the raw value at `path` is part of.

    For a chunk or a light update: a section's container, or a layer of its light.
    """
    match path:
        case ("sections", int(), "block_states" | "biomes", *_):
            return path[:3]
        case ("light" | "data", str() as key, *_) if key in _LIGHT_LAYERS:
            return (path[0], _LIGHT_LAYERS[key])
    return path


# What a gameplay Divergence of a chunk shows: the chunk, and the positions that differ.


_SECTION_BOTTOMS: Mapping[int, int] = MappingProxyType({24: -64, 16: 0})
"""The lowest y of the vanilla dimension types with that many sections: the overworld and
overworld_caves are 384 blocks high from -64, the nether and the end 256 from 0 (the 26.3
server jar's `data/minecraft/dimension_type`)."""

_SHOWN_POSITIONS = 3
"""How many differing positions a Divergence names; it counts the rest."""


@dataclass(frozen=True, slots=True)
class _Place:
    """Where a chunk is in the world, for what its Divergences show.

    Attributes:
        x: The chunk's x.
        z: The chunk's z.
        bottom: The y of its lowest block, if both sides have the section count of a vanilla
            dimension type with the same lowest y (`_SECTION_BOTTOMS`); None counts y from the
            world's bottom.
    """

    x: int
    z: int
    bottom: int | None

    @classmethod
    def of(cls, fields: tuple[dict[str, _Value], dict[str, _Value]]) -> Self | None:
        """The place of two matched chunks, from the reference's position; None if unknown."""
        x, z = fields[0].get("chunk_x"), fields[0].get("chunk_z")
        if type(x) is not int or type(z) is not int:
            return None
        bottoms = {
            _SECTION_BOTTOMS.get(len(sections))
            if isinstance(sections := side.get("sections"), list)
            else None
            for side in fields
        }
        return cls(x=x, z=z, bottom=bottoms.pop() if len(bottoms) == 1 else None)

    def label(self) -> str:
        """`chunk <x> <z>`, saying so if y counts from the world's bottom."""
        note = "" if self.bottom is not None else " (y from the world's bottom)"
        return f"chunk {self.x} {self.z}{note}"

    def position(self, section: int, entry: int, side: int) -> str:
        """`x y z` in the world of `entry` of `section`, a cube of `side` entries a side.

        An entry stands for its lowest corner: a biome cell is 4 blocks a side.
        """
        shift, scale = side.bit_length() - 1, 16 // side
        x, z, y = entry & (side - 1), entry >> shift & (side - 1), entry >> 2 * shift
        bottom = (self.bottom or 0) + 16 * section
        return f"{16 * self.x + scale * x} {bottom + scale * y} {16 * self.z + scale * z}"

    def listed(self, section: int, side: int, values: list[tuple[int, str]]) -> str:
        """The first `_SHOWN_POSITIONS` entries of `values` with their values, and a count."""
        named = ", ".join(
            f"{self.position(section, entry, side)} is {value}"
            for entry, value in values[:_SHOWN_POSITIONS]
        )
        more = len(values) - _SHOWN_POSITIONS
        return f"{self.label()}: {named}" + (f" and {more} more" if more > 0 else "")

    def summed(self, section: int, text: str) -> str:
        """`text` about the whole of `section`, after the heights it spans."""
        bottom = (self.bottom or 0) + 16 * section
        return f"{self.label()}, y {bottom} to {bottom + 15}: {text}"


type _Sides = tuple[dict[str, _Value], dict[str, _Value]]
"""The reference's and the candidate's fields of two matched Packets."""


def _shown_chunk(
    path: _Path, reference: _Value | Absent, candidate: _Value | Absent, fields: _Sides
) -> tuple[object, object]:
    """What a gameplay Divergence of a chunk, or of a light update, shows on each side.

    For a section's block states or biomes, or a light section, the first positions that
    differ, each with the side's id or light level there, and how many more differ; or, for
    a container or a light section that is not ids or an array on both sides, what each
    side's is. Anything else shows its values.
    """
    match path:
        case ("sections", int() as section, str() as field) if field in _CONTAINERS:
            return _shown_section(section, field, (reference, candidate), fields)
        case ("light" | "data", "sky" | "block", int() as index):
            return _shown_light(index - 1, (reference, candidate), fields)
    return reference, candidate


def _shown_section(
    section: int, field: str, values: tuple[_Value | Absent, _Value | Absent], fields: _Sides
) -> tuple[object, object]:
    container, side = _CONTAINERS[field]
    reference, candidate = (_ids(value, container.entries) for value in values)
    place = _Place.of(fields)
    if place is None:
        return values
    if reference is None or candidate is None:
        texts = [_container_text(value) for value in values]
        if texts[0] is None or texts[1] is None:
            return values
        return place.summed(section, texts[0]), place.summed(section, texts[1])
    differing = [
        entry for entry in range(container.entries) if reference[entry] != candidate[entry]
    ]
    return (
        place.listed(section, side, [(entry, _id_text(reference[entry])) for entry in differing]),
        place.listed(section, side, [(entry, _id_text(candidate[entry])) for entry in differing]),
    )


def _ids(value: _Value | Absent, entries: int) -> list[int | None] | None:
    """The id at each entry of a canonical container; None if it is not one."""
    if type(value) is int:
        return [value] * entries
    if isinstance(value, bytes):
        return _unpacked_ids(value, entries)
    return None


def _id_text(value: int | None) -> str:
    return "past the palette" if value is None else str(value)


def _container_text(value: _Value | Absent) -> str | None:
    """A canonical container said whole, "all 41" or what is wrong with it; None if neither."""
    if type(value) is int:
        return f"all {value}"
    return value if isinstance(value, str) else None


def _shown_light(
    section: int, values: tuple[_Value | Absent, _Value | Absent], fields: _Sides
) -> tuple[object, object]:
    """What a light section's Divergence shows.

    `section` is the world section it lights: -1 for the one below the world.
    """
    place = _Place.of(fields)
    if place is None:
        return values
    reference, candidate = values
    if isinstance(reference, bytes) and isinstance(candidate, bytes):
        ref_levels, cand_levels = _levels(reference), _levels(candidate)
        differing = [entry for entry, level in enumerate(ref_levels) if level != cand_levels[entry]]
        return (
            place.listed(section, 16, [(entry, str(ref_levels[entry])) for entry in differing]),
            place.listed(section, 16, [(entry, str(cand_levels[entry])) for entry in differing]),
        )
    return place.summed(section, _light_text(reference)), place.summed(
        section, _light_text(candidate)
    )


def _levels(data: bytes) -> list[int]:
    """The light level at each entry of a light array: 4 bits each, low ones first (`DataLayer`)."""
    levels: list[int] = []
    for byte in data:
        levels.extend((byte & 15, byte >> 4))
    return levels


def _light_text(value: _Value | Absent) -> str:
    """A light section said whole: "all 15", "levels 0 to 15", "empty", "not sent", ...."""
    if isinstance(value, bytes):
        found = set(_levels(value))
        return f"all {min(found)}" if len(found) == 1 else f"levels {min(found)} to {max(found)}"
    if isinstance(value, str):
        return value
    return "not sent"


_CANONICAL: Mapping[
    tuple[State, str], Callable[[dict[str, _Value], _Context], dict[str, _Value]]
] = MappingProxyType(
    {
        (State.STATUS, "minecraft:status_response"): _canonical_status_response,
        (State.PLAY, "minecraft:level_chunk_with_light"): _canonical_level_chunk,
        (State.PLAY, "minecraft:light_update"): _canonical_light_update,
    }
)
"""The canonical form of each clientbound packet that has one, by (State, name), from its
fields and its Bot's `_Context`."""

_COVERS: Mapping[tuple[State, str], Callable[[_Path], _Path]] = MappingProxyType(
    {
        (State.PLAY, "minecraft:level_chunk_with_light"): _chunk_cover,
        (State.PLAY, "minecraft:light_update"): _chunk_cover,
    }
)
"""For a packet in `_CANONICAL` whose canonical form is not shaped as it came: the path of the
canonical value each raw path is part of. A raw difference is network traffic only if that
value is the same on both sides (`_network_traffic`)."""

_SHOWN: Mapping[
    tuple[State, str],
    Callable[[_Path, _Value | Absent, _Value | Absent, _Sides], tuple[object, object]],
] = MappingProxyType(
    {
        (State.PLAY, "minecraft:level_chunk_with_light"): _shown_chunk,
        (State.PLAY, "minecraft:light_update"): _shown_chunk,
    }
)
"""For a packet whose gameplay Divergences show something other than their canonical values:
what they show, from the path, the two values and both sides' fields."""

_JSON_TEXT: Mapping[tuple[State, str], str] = MappingProxyType(
    {(State.STATUS, "minecraft:status_response"): "json_response"}
)
"""The field of a packet in `_CANONICAL` that holds JSON text, and is its only field.

Its raw value is diffed parsed but not canonical, so a network traffic Divergence inside
the JSON is reported at its JSON path; and its test cases are named from inside the JSON."""


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
    bot: str,
    reference: Sequence[_Normalized],
    candidate: Sequence[_Normalized],
    compared: set[str],
) -> Iterator[Divergence]:
    pairs = _align([_key(entry) for entry in reference], [_key(entry) for entry in candidate])
    next_reference = next_candidate = 0
    for ref_index, cand_index in [*pairs, (len(reference), len(candidate))]:
        for index in range(next_reference, ref_index):
            yield _unmatched(bot, index, "missing", reference[index])
        for index in range(next_candidate, cand_index):
            yield _unmatched(bot, index, "unexpected", candidate[index])
        if ref_index < len(reference):
            matched = (reference[ref_index], candidate[cand_index])
            yield from _diff_matched(bot, ref_index, *matched, compared)
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
        test_case=_test_case(entry.packet.state, entry.packet.name, ()),
    )


def _diff_matched(
    bot: str, index: int, reference: _Normalized, candidate: _Normalized, compared: set[str]
) -> Iterator[Divergence]:
    """Diff two matched Packets, adding the test case of each pair compared to `compared`.

    Two Packets compared by payload are one test case, the packet's. A pair at a path a
    Mask found a value at counts only if it differs: a masked field is no test case.
    """
    state, name = reference.packet.state, reference.packet.name
    differences: list[tuple[_Path | None, str, object, object]] = []
    if reference.fields is None or candidate.fields is None:
        whole = _test_case(state, name, ())
        compared.add(whole)
        if reference.packet.payload != candidate.packet.payload:
            payloads = (reference.packet.payload.hex(), candidate.packet.payload.hex())
            differences.append((None, whole, *payloads))
    else:
        # Name each shape once: a list of 10,000 entries is 10,000 pairs but one name.
        names: dict[_Path, str] = {}
        masked = reference.masked | candidate.masked
        shown = _SHOWN.get((state, name))
        sides = (reference.fields, candidate.fields)
        for path, ref_value, cand_value in _pairs(reference.fields, candidate.fields, ()):
            shape = tuple(0 if isinstance(step, int) else step for step in path)
            if shape not in names:
                names[shape] = _test_case(state, name, shape)
            if not _same(ref_value, cand_value):
                values = (ref_value, cand_value)
                if shown is not None:
                    values = shown(path, ref_value, cand_value, sides)
                differences.append((path, names[shape], *values))
                compared.add(names[shape])
            elif not (masked and path in masked):
                compared.add(names[shape])
    for path, case, ref_value, cand_value in differences:
        yield Divergence(
            bot=bot,
            index=index,
            kind="field",
            packet=name,
            path=None if path is None else _render(path),
            reference=ref_value,
            candidate=cand_value,
            test_case=case,
        )
    for path, ref_value, cand_value in _network_traffic(reference, candidate):
        yield Divergence(
            bot=bot,
            index=index,
            kind="field",
            packet=name,
            path=_render(path),
            reference=ref_value,
            candidate=cand_value,
            test_case=_test_case(state, name, path),
            observability=Observability.NETWORK_TRAFFIC,
        )


def _network_traffic(
    reference: _Normalized, candidate: _Normalized
) -> Iterator[tuple[_Path, _Value | Absent, _Value | Absent]]:
    """Yield the raw differences whose unmasked canonical values are equal, in path order.

    A raw difference inside JSON text is taken at each JSON path where the parsed values
    differ; only when they are equal (a JSON spelling) is it the whole text. The canonical
    values compared are those at the raw path, or, for a packet in `_COVERS`, at the path of
    the canonical value the raw one is part of.
    """
    if (
        reference.raw is None
        or candidate.raw is None
        or reference.parsed is None
        or candidate.parsed is None
        or reference.unmasked is None
        or candidate.unmasked is None
    ):
        return
    cover = _COVERS.get((reference.packet.state, reference.packet.name))
    for raw_path, raw_ref, raw_cand in _diff(reference.raw, candidate.raw, ()):
        parsed = (_at(reference.parsed, raw_path), _at(candidate.parsed, raw_path))
        found = list(_diff(*parsed, raw_path)) or [(raw_path, raw_ref, raw_cand)]
        for path, ref_value, cand_value in found:
            covering = path if cover is None else cover(path)
            canonical = (_at(reference.unmasked, covering), _at(candidate.unmasked, covering))
            if next(_diff(*canonical, covering), None) is None:
                yield path, ref_value, cand_value


def _at(fields: dict[str, _Value], path: _Path) -> _Value | Absent:
    """The value at `path` in `fields`, or ABSENT if there is none."""
    node: _Value | Absent = fields
    for step in path:
        if isinstance(node, Absent):
            return ABSENT
        node = _child(node, step)
    return node


type _Pair = tuple[_Path, _Value | Absent, _Value | Absent]
"""A path, and the reference and candidate values there."""


def _diff(reference: _Value | Absent, candidate: _Value | Absent, path: _Path) -> Iterator[_Pair]:
    """Yield each pair `_pairs` compares whose two values differ, in path order."""
    return (pair for pair in _pairs(reference, candidate, path) if not _same(pair[1], pair[2]))


def _pairs(reference: _Value | Absent, candidate: _Value | Absent, path: _Path) -> Iterator[_Pair]:
    """Yield (path, reference value, candidate value) for each pair compared, in path order.

    Mappings are compared key by key, in sorted key order, and a key only one side has
    is ABSENT on the other. Lists are compared index by index, and elements past the
    end of the shorter one are ABSENT. Anything else is a leaf, compared as a whole.
    """
    if isinstance(reference, dict) and isinstance(candidate, dict):
        for key in sorted(reference.keys() | candidate.keys()):
            yield from _pairs(reference.get(key, ABSENT), candidate.get(key, ABSENT), (*path, key))
    elif isinstance(reference, list) and isinstance(candidate, list):
        for index in range(max(len(reference), len(candidate))):
            yield from _pairs(
                _element(reference, index), _element(candidate, index), (*path, index)
            )
    else:
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
_EACH = "[*]"
_JSON = json.JSONDecoder()


def _render(path: _MaskPath, *, index_free: bool = False) -> str:
    """Write a field path: `players.sample[0].name`, or `m["not an identifier"]`.

    A key that is an identifier follows a dot (none at the start). Any other key is a
    JSON string in brackets, and a list index is a number in brackets, or nothing in
    them if `index_free` (`players.sample[].name`, as test cases are named). EACH, in a
    Mask's path, is `[*]`.
    """
    parts: list[str] = []
    for step in path:
        if isinstance(step, Each):
            parts.append(_EACH)
        elif isinstance(step, int):
            parts.append("[]" if index_free else f"[{step}]")
        elif _IDENTIFIER.fullmatch(step):
            parts.append(f".{step}" if parts else step)
        else:
            parts.append(f"[{json.dumps(step, ensure_ascii=False)}]")
    return "".join(parts)


def _where(path: _Path) -> str:
    return _render(path) or "fields"


def _mask_steps(mask: Mask) -> _MaskPath:
    """Return the steps of `mask`'s field path, where `[*]` is EACH (see `_steps`)."""
    return _steps(mask.packet, mask.path, "Mask path", each=True)


def _steps(packet: str, path: str, what: str, *, each: bool = False) -> _MaskPath:
    """Return the steps of `path`, a `what` of `packet` (named in any error).

    `[*]` is a step, EACH, only if `each`; a path without one is a `_Path`.

    Raises:
        ValueError: The path is malformed, or not spelled as a Divergence path would be.
    """
    steps = _parse_path(path, each=each)
    if steps is None:
        msg = f"{packet}: malformed {what} {path!r}"
        raise ValueError(msg)
    if (spelling := _render(steps)) != path:
        msg = f"{packet}: {what} {path!r} is spelled unlike a Divergence path; write {spelling!r}"
        raise ValueError(msg)
    return steps


def _parse_path(text: str, *, each: bool) -> _MaskPath | None:
    """Read a field path in the syntax `_render` writes, or return None if malformed.

    A path starts with a key, bare or quoted, never with an index. `[*]` is EACH if
    `each`, and malformed if not.
    """
    steps: list[_MaskStep] = []
    position = 0
    while position < len(text) or not steps:
        step = _next_step(text, position, start=not steps, each=each)
        if step is None:
            return None
        steps.append(step[0])
        position = step[1]
    return tuple(steps)


def _next_step(
    text: str, position: int, *, start: bool, each: bool
) -> tuple[_MaskStep, int] | None:
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
    if each and text.startswith(_EACH, position):
        return EACH, position + len(_EACH)
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


# The random fields' Masks, last: a Mask checks its path with the functions above when it
# is made, so a `RANDOM_FIELDS` key that is not `<packet>.<path>` fails the import.


def _random_mask(field: str, reason: str) -> Mask:
    packet, _, path = field.partition(".")
    return Mask(packet, path, reason=reason)


_RANDOM_MASKS: tuple[Mask, ...] = tuple(
    _random_mask(field, reason) for field, reason in RANDOM_FIELDS.items()
)
