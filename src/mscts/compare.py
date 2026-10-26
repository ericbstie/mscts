"""Comparison: diff the Reference and Candidate Transcripts of one Group into a Verdict.

What is compared is, for every Bot, the ordered stream of the clientbound Packets it
received. If the Group has Observation windows (`GroupContext.observe`), a Bot's play
Packets are compared only inside them, less the heartbeat packets (`is_heartbeat`); its
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
import math
import re
import struct
from array import array
from collections.abc import Callable, Hashable, Iterable, Iterator, Mapping, Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass, replace
from enum import Enum, StrEnum
from functools import cache
from itertools import groupby
from types import MappingProxyType
from typing import Literal, NamedTuple, NoReturn, Self, cast, override
from uuid import UUID

from mscts.codec.entity_ids import EACH, Each, EntityIdPath, Step, Variant
from mscts.codec.packets import Codec, Direction, Packet, State
from mscts.codec.registry_names import registry_names
from mscts.codec.schemas.play.chunks import BIOMES, BLOCK_STATES, PalettedContainer
from mscts.codec.wire import WireError
from mscts.spec import CONTROL_PLAYER
from mscts.stats import Difference
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
    """What a Verdict says about a Group.

    A Run makes no `blocked` Verdict any more: it refuses a Group whose prerequisites
    are not listed before it (`run.run_results`). `blocked` stays for a report.json
    written before, and for `run.prerequisite_verdict` called on its own.
    """

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
`observe:open minecraft:block_update minecraft:system_chat`. A window that compares no play
packet has `OBSERVE_NO_PLAY` after it, which no packet is called.
"""

OBSERVE_NO_PLAY = "-"
"""What follows `observe:open` in a window that compares no play packet, only the packets of
the other States. No packet has this name, so the window's names take no play packet."""

TICK_MARK = "tick:"
"""The start of the label of the Mark that ends a tick of a tick-exact Group: `tick:<k>`.

`GroupContext.step` records one for each tick it steps, k counting from 1 since the freeze:
for each Bot with the Bot's name after a space (`tick:3 alice`), and one with no name for any
Bot that has no Mark of its own for that tick.
"""

TICK_PATH = "(tick)"
"""The path of the `field` Divergence of a packet a tick-exact Group got on different ticks.

Its values are the two ticks, counting from 1 since the freeze (`TICK_MARK`). No field's path
can be it: a path joins identifier keys with dots and puts any other key, and every index, in
brackets, so it never holds a parenthesis.
"""

ORDER_PATH = "(order)"
"""The path of the network traffic `field` Divergence of `registry_data` packets of different
registries that the two sides sent in different orders (#451).

Its values are each side's registry ids of the matched `registry_data`, in the order that side
sent them; its test case is `registry_id`'s. The client loads the registries by key, whatever
their order (docs/research/2026-10-23-registry-order.md). As for `TICK_PATH`, no field's path
can be it.
"""

OBSERVE_CLOSE = "observe:close"
"""The label of the Mark that closes an Observation window.

A window that ends at the barrier gets one per Bot, with the Bot's name after a space
(`observe:close alice`): it closes the window for that Bot only. One with no name closes
it for every Bot that has no close Mark of its own in that window: then also a Bot made
after the window closed.
"""

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
"""The play packets an Observation window never compares by name, each with the reason.
Others are heartbeat packets by their first bytes (`HEARTBEAT_PAYLOADS`).

Evidence: docs/research/2026-09-30-observation-window.md. The barrier's request,
`client_command`, is serverbound, and nothing serverbound is compared.
"""


HEARTBEAT_PAYLOADS: Mapping[tuple[str, bytes], str] = MappingProxyType(
    {
        ("minecraft:player_info_update", b"\x10"): (
            "Only UPDATE_LATENCY: vanilla sends it for every player on a clock (every 601 "
            "ticks, even with the world frozen) whatever a Group does, and no other code sends "
            "that action alone. Its first byte is the set of actions, one bit each, so 0x10 is "
            "that one action and nothing else."
        ),
    }
)
"""The play packets whose name alone does not make them heartbeat packets, but whose payload
starts with the given bytes does, each with the reason. A packet of the same name with other
bytes is compared, so the effects a Group tests under that name stay compared.

Evidence: docs/research/2026-10-03-latency-broadcast.md.
"""


def is_heartbeat(packet: Packet) -> bool:
    """Whether `packet`, a play packet, is a heartbeat packet no window compares.

    It is one if `HEARTBEAT` names it, or if `HEARTBEAT_PAYLOADS` names it with the bytes its
    payload starts with.
    """
    return packet.name in HEARTBEAT or any(
        packet.name == name and packet.payload.startswith(start)
        for name, start in HEARTBEAT_PAYLOADS
    )


@dataclass(frozen=True, slots=True)
class Mask:
    """A normalization rule: a field's value, or a whole packet, is excluded from Comparison.

    Attributes:
        packet: The packet name, e.g. `minecraft:login`, in whatever State.
        path: The field path, spelled as Divergence paths are (e.g. `entity_id`,
            `players.sample[0].name`), where `[*]` is every index of a list
            (`players.sample[*].name`); or `*` (WHOLE_PACKET) for the whole packet.
            An index is each list's own, hidden on both sides before lists are lined up,
            so a Divergence path's arrow (`[→2]`, `[1→3]`) is refused, naming the Mask that
            hides it: on the whole list, or with `[*]`.
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
            ValueError: The packet name or the reason is empty, the path is malformed,
                not spelled as a Divergence path would be or has an arrow, or it is an
                entity id (or a list of them), which every Comparison names or numbers
                instead (#21).
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
        "minecraft:section_blocks_update": (
            "blocks, sorted by position (y, z, x). Vanilla sends them in hash order: "
            "ChunkHolder.broadcastChanges writes the section's changed positions in the "
            "iteration order of a ShortOpenHashSet. The client sets each block at its own "
            "position in turn (ClientboundSectionBlocksUpdatePacket.runUpdates, then "
            "ClientLevel.setServerVerifiedBlockState with flags 19: on the client "
            "Level.updateNeighborsAt does nothing, and flag 16 skips the shape updates), so a "
            "position sent twice keeps the last state."
        ),
        "minecraft:recipe_book_add": (
            "entries, those with the toast flag (1) first in their order, then the others "
            "sorted by what each shows: its display id left out, and of its group number only "
            "whether it has one. At a "
            "join vanilla sends a player's known recipes in identity hash order, with no toast "
            "flag: ServerRecipeBook keeps them in a Sets.newIdentityHashSet, which "
            "sendInitialRecipeBook iterates. The client puts each entry in its book, a HashMap "
            "keyed by display id (ClientPacketListener.handleRecipeBookAdd, then "
            "ClientRecipeBook.add), and highlights it in a HashSet, so the order of those "
            "entries is not kept. An entry with the toast flag is also added to the recipe "
            "toast (RecipeToast.addOrUpdate), which shows its recipes one after another in "
            "the order they came, so those keep their order."
        ),
        "minecraft:recipe_book_remove": (
            "recipes, sorted by the numbers their display ids take, then by the names they "
            "take, after they are named or numbered: "
            "each server picks its ids, so their own order would follow its numbering. Vanilla "
            "lists them in the order of the collection it is given (ServerRecipeBook"
            ".removeRecipes). The client removes each id from its book at its own key "
            "(ClientPacketListener.handleRecipeBookRemove: ClientRecipeBook.remove, a "
            "HashMap.remove and a HashSet.remove for each), then refreshes the book once, so "
            "their order is not kept."
        ),
    }
)
"""The packets, in any State, whose unordered lists every Comparison sorts, each with the
reason: the hash collection vanilla iterates to send the list, in an order the client does
not keep and that may change from one boot (or join) to the next, and the map or set the
client reads the list into. The sort key is the key of the client's map or set,
and the sort is stable, so of a key sent twice the last stays last. The recipe book's key is
a number the server picks, so its entries are sorted by what they show instead, and the ones
the client also shows in turn keep their order (`_sorted_recipe_book_add`); a recipe book
removal holds only such numbers, so it is sorted once they are numbered (`_RecipeNumbers`).
That order is never a
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
        "minecraft:player_chat.timestamp": (
            "Vanilla reads it from its clock for a message from a player with no chat session, "
            "as every Bot: SignedMessageBody.unsigned sets it to Instant.now() when the server "
            "takes the message, and it is sent as milliseconds since the epoch. The client "
            "uses it only to check a signed message's age; the message is still compared."
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


type DivergenceKind = Literal["bot", "missing", "unexpected", "field", "failed", "distribution"]


class Observability(StrEnum):
    """Which kind of difference a Divergence is (ADR-0007).

    `GAMEPLAY`: a vanilla client could tell the two values apart, so a player could
    notice it. `NETWORK_TRAFFIC`: the two servers send the same thing in different
    formats, and a vanilla client ends up with the same result.
    """

    GAMEPLAY = "gameplay"
    NETWORK_TRAFFIC = "network traffic"


NETWORK_TRAFFIC_ONLY_PASSES: bool = True
"""Whether a test case that differs only in network traffic passes (ADR-0007).

The one place that decides it: the Report's test cases and Score (`report`), and
whether a prerequisite passed (`run.prerequisite_verdict`), both read it here, as
`mscts.compare.NETWORK_TRAFFIC_ONLY_PASSES`.
"""


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
            Candidate failure, `run.judge`; never made by `compare`). `bot` is the Bot
            that failed, or "" when the Group's own script raised; `packet` is "",
            `index` 0, `reference` ABSENT.
            `distribution`: a statistical Group's samples of one name do not come from
            one distribution (`run.judge_samples`; never made by `compare`). `bot` and
            `packet` are "", `index` 0, `test_case` the sample name; `reference` and
            `candidate` are each side's `stats.Summary`; `tested` is the test that
            rejected.
        packet: The packet name; "" for `bot`, `failed` and `distribution`.
        path: Where in the matched Packets they differ, or None for their whole
            payload. Always None for `bot`, `missing`, `unexpected`, `failed` and
            `distribution`.
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
            and values are the raw ones; or a `missing` or `unexpected` `chunk_batch_start`
            or `chunk_batch_finished`, or one on another tick (`TICK_PATH`), which leave
            the client's world as it is; or the order of `registry_data` (`ORDER_PATH`),
            which the client loads by registry. `gameplay`:
            every other Divergence, including every `bot` and `failed` one.
        tested: For `distribution`, the test that rejected, its p-value after Holm's
            correction; None if a side has no samples of the name, or one side's are
            numbers and the other's categories. None for every other kind.
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
    tested: Difference | None = None

    def __post_init__(self) -> None:
        """Refuse a `bot` or `failed` Divergence that is network traffic.

        It is about the whole Group and gives it a line of its own, which always fails;
        a prerequisite passes only without one (`run.prerequisite_verdict`, #221).
        """
        if self.kind in {"bot", "failed"} and self.observability is not Observability.GAMEPLAY:
            msg = f"a {self.kind} Divergence is gameplay, not {self.observability}"
            raise ValueError(msg)


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
        test_cases: Every test case the Comparison compared, matched or not, and each field
            of a reference Packet the Candidate did not send (#101), sorted and each once;
            none if the Verdict was made without one (`error`, `blocked`). A test case that
            no compared pair names and only network traffic Divergences do is not among
            them, so a Candidate that sends another spelling does not get one more test case
            than one that sends vanilla's (#330). A Candidate
            failure lists the Reference's play's own (`run.judge`), and so does one whose
            Group was played on the Reference alone (#266, #285).
        omitted: How many Divergences a report.json left out of `divergences` (#254): the
            Verdict a Comparison makes has none left out, and a Verdict read back from a
            report.json that capped them has the count that file gave.
    """

    group_id: str
    outcome: Outcome
    divergences: tuple[Divergence, ...] = ()
    detail: str = ""
    test_cases: tuple[str, ...] = ()
    omitted: int = 0

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

    Each Bot's stream is normalized first: the chunks in a row are sorted by position
    (`_by_position`), and the resends in a row for different entities by entity (`_RESENDS`,
    `_by_entity`), and the `registry_data` of a configuration by registry (`_by_registry`);
    then, if the Transcript has Observation windows, the play Packets they
    do not observe are left out (`_Windows.observes`); the Packets a `*` Mask names are
    dropped; the lists of the Packets `UNORDERED` names are
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
    (`_Numbers`), as does each recipe display id, counted on its own over the sorted Packets
    or named by what it shows if first got outside them, and each recipe book group number
    becomes the names and numbers of its recipes (`_RecipeNumbers`); and in the Packets of a Mask's
    name, the value at its path is MASKED on both sides, wherever present, unless it is
    None: a Mask hides a value, never whether it is there, so a field or a list element
    one side lacks is still a Divergence, and a masked field is no test case where it does
    not diverge. The Masks are one for each of the `RANDOM_FIELDS`, then `masks`. Indices
    count the normalized stream, so they do not shift when a re-run has more or fewer
    Packets left out or dropped; paths and values are those of the sorted, canonical,
    numbered form.

    Each Bot's two streams are aligned on their packet keys (State and name, the position
    of a packet about one chunk, and the registry of a `registry_data`), leaving as few
    Packets unmatched as possible; swapping the sides mirrors the alignment. Between two
    matched pairs, `missing` Divergences come before `unexpected` ones. An unmatched chunk,
    light update or forgotten chunk shows `chunk <x> <z>`, any other Packet its value. If the
    matched `registry_data` of a run of the reference's came in another order on each side,
    the first of them is preceded by one network traffic `field` Divergence at `ORDER_PATH`
    (`_registry_orders`).

    In a tick-exact Group (its Transcript has `TICK_MARK` Marks), each play Packet holds the
    tick it arrived on (`_Ticks`), and the Packets are aligned as without ticks. Two matched
    Packets on different ticks are a `field` Divergence at `TICK_PATH`, with the two ticks
    as its values and the packet's test case, then the Packets' differences. When both
    streams have ticks, the ticks break ties between the longest alignments
    (`_align_timed`): the copy of a repeated packet on a tick the other side lacks is the
    one left unmatched.

    Two matched Packets with fields are diffed field by field (see `_pairs`), giving one
    gameplay `field` Divergence per differing leaf, in path order, except in a list that
    is lined up (`_LINED_UP`), which is in the order of its steps. A list or mapping more
    than 255 levels into a field's value is one leaf, a text that writes it whole
    (`Nested`). If they have a
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
    `unexpected` Packet's value is its normalized fields, or its payload as hex. Payload
    hex is cut to `PAYLOAD_SHOWN_BYTES` and a count of the rest (`_shown_payload`); two
    long payloads that differ show the bytes around the first difference
    (`_shown_payloads`).

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
    compared.update(
        divergence.test_case
        for divergence in divergences
        if divergence.observability is Observability.GAMEPLAY
    )
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


class _RegistryPlace(NamedTuple):
    """A `registry_data` the codec read, as a Bot's stream holds it (`_by_registry`).

    Attributes:
        registry: Its registry id (`_registry_id`).
        run: Which run of registries of the stream it came in, counting from 0.
        arrived: Its index in the normalized stream before the runs were sorted.
    """

    registry: str
    run: int
    arrived: int


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
        tick: For a play Packet of a tick-exact Group, the tick it arrived on (`_Ticks`);
            else None.
        registry: For a `registry_data` the codec read, its registry and where it came
            (`_by_registry`); else None.
    """

    packet: Packet
    fields: dict[str, _Value] | None
    raw: dict[str, _Value] | None = None
    parsed: dict[str, _Value] | None = None
    unmasked: dict[str, _Value] | None = None
    masked: frozenset[_Path] = frozenset()
    tick: int | None = None
    registry: _RegistryPlace | None = None

    @property
    def value(self) -> object:
        """What a `missing` or `unexpected` Divergence shows: fields, else payload hex."""
        return _shown_payload(self.packet.payload) if self.fields is None else self.fields


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
    Every recipe book packet, compared or not, changes the book the recipe numbers follow
    (`_Numbers.uncompared`, `_RecipeNumbers`). If the Transcript has tick Marks
    (`TICK_MARK`), each play Packet holds the tick it arrived on (`_Ticks`). All of this
    runs over the Bot's Packets once its chunk packets are put in order (`_by_position`).
    The sort moves only chunk packets, which carry no entity ids, so it changes no
    entity's name or number. Each run of compared resends
    (`_runs`) is then taken in the order of its entities' names and numbers before the run
    (`_by_entity`). So the same resends get the same places on both sides however each server
    ordered them, as long as both sides named and numbered those entities alike: an entity
    a Bot first hears of in the run keeps its place, since its number comes from it. A run
    ends at a window's end and at a tick Mark, so in a tick-exact Group it holds one tick's
    resends; elsewhere it may hold several ticks' of one window, and the order of different
    entities' resends across those ticks is not compared. Last, each run of `registry_data`
    is sorted by registry (`_by_registry`).
    """
    windows = _Windows.of(transcript, bot)
    ticks = _Ticks.of(transcript, bot)
    events = _by_position(
        [
            event
            for event in transcript.events
            if event.bot == bot and event.packet.direction is Direction.CLIENTBOUND
        ]
    )
    arrivals = [
        _Arrival.of(event, context, windows, masks, ticks)
        for event, context in zip(events, _Context.each(events), strict=True)
    ]
    numbers = _Numbers(ids={}, uuids={})
    stream: list[_Normalized] = []
    for run in _runs(arrivals):
        taken = [_take(arrival, masks, numbers) for arrival in _by_entity(run, numbers.ranks())]
        stream.extend(normalized for normalized in taken if normalized is not None)
    return _by_registry(stream)


class _Arrival(NamedTuple):
    """One of a Bot's clientbound Events, with what `_stream` needs to take it.

    Attributes:
        event: The Event.
        context: What its canonical form needs (`_Context`).
        observed: Whether an Observation window takes it, or the Transcript has none.
        compared: Whether it is compared: observed, and no `*` Mask drops it.
        tick: For a play Packet of a tick-exact Group, the tick it arrived on; else None.
        window: The index of the last `observe:` Mark at or before it (`_Windows.latest`),
            so the same for every Packet of one window; -1 if there is none.
    """

    event: Event
    context: "_Context"
    observed: bool
    compared: bool
    tick: int | None
    window: int

    @classmethod
    def of(
        cls,
        event: Event,
        context: "_Context",
        windows: "_Windows | None",
        masks: _Masks,
        ticks: "_Ticks | None",
    ) -> Self:
        """`event`, with `context`, as the Bot's `windows`, `masks` and `ticks` see it."""
        packet = event.packet
        observed = windows is None or windows.observes(event)
        tick = ticks.of_arrival(event.t_ns) if ticks and packet.state is State.PLAY else None
        window = windows.latest(event.t_ns) if windows else -1
        compared = observed and packet.name not in masks.dropped
        return cls(event, context, observed, compared, tick, window)


def _take(arrival: _Arrival, masks: _Masks, numbers: "_Numbers") -> _Normalized | None:
    """Note `arrival` in `numbers`, and return it normalized if it is compared; else None."""
    packet = arrival.event.packet
    normalized = None
    if not arrival.observed:
        numbers.spawned(packet, masks)
    if arrival.compared:
        numbers.take(packet)
        normalized = _normalize(packet, masks, numbers, arrival.context)
        if arrival.tick is not None:
            normalized = replace(normalized, tick=arrival.tick)
    else:
        numbers.uncompared(packet, masks)
    numbers.removed(packet)
    return normalized


_RESENDS = frozenset(
    {
        "minecraft:set_entity_data",
        "minecraft:set_entity_motion",
        "minecraft:update_attributes",
        "minecraft:rotate_head",
        "minecraft:move_entity_pos",
        "minecraft:move_entity_pos_rot",
        "minecraft:move_entity_rot",
        "minecraft:entity_position_sync",
    }
)
"""The play packets of vanilla's tick-end resends that are each about the one entity whose
`entity_id` they hold (#320, docs/research/2026-10-15-unordered-resends.md).

At the end of each tick `ChunkMap.tick` walks its tracked entities, an `Int2ObjectOpenHashMap`
keyed by the raw entity id, and `ServerEntity.sendChanges` sends what changed about each: so
the resends of several entities come in an order that follows their raw ids, which differ
between Instances. The client applies each to the entity it names, and to no other
(`ClientPacketListener.handleSetEntityData`, `handleSetEntityMotion`,
`handleUpdateAttributes`, `handleRotateMob`, `handleMoveEntity`, `handleEntityPositionSync`).
`set_passengers` names two entities, and the projectile power comes in a bundle, so neither
is one."""

_NAMING = frozenset({"minecraft:add_entity", "minecraft:remove_entities"})
"""The packets that may name or number an entity, or end its name or number, when they are
not compared: an `add_entity` outside every window (`_Numbers.spawned`), and any
`remove_entities` (`_Numbers.removed`). A run ends at each, even one that names nothing."""


def _runs(arrivals: Sequence[_Arrival]) -> Iterator[list[_Arrival]]:
    """`arrivals` split into runs: each run of compared resends, and each other one alone.

    A run of resends is a longest stretch of compared packets in `_RESENDS`
    (`_resend_entity`). A packet that is not compared goes across a run, as `_by_position`
    lets a neutral packet go across a run of chunks (#33), and comes after it: a heartbeat
    comes on the server's clock, whose phase differs between Instances, and a dropped packet
    is not compared at all. Neither reads or changes an entity's name or number, except an
    `add_entity` or `remove_entities` (`_NAMING`), which ends the run. A recipe book packet
    or a `login` changes the recipe book, but no resend holds a recipe id, so taking one
    after the run changes no recipe's name or number.

    A run also ends at a window's end: a resend in the next Observation window starts the
    next run, since each window is a step of the Group. In a tick-exact Group a run also
    ends at a tick Mark: a resend on the next tick starts the next run. Elsewhere a
    Transcript holds no tick ends, so a run may span the ticks of one window: the gaps
    between arrivals do not tell them apart (one tick's resends came up to 3.2 ms
    apart on a live vanilla play, two ticks' as little as 25.7 ms or none,
    docs/research/2026-10-15-unordered-resends.md).
    """
    run: list[_Arrival] = []
    held: list[_Arrival] = []  # what goes across the run
    for arrival in arrivals:
        packet = arrival.event.packet
        resend = arrival.compared and _resend_entity(packet) is not None
        if resend and (not run or _same_step(arrival, run[0])):
            run.append(arrival)
        elif not arrival.compared and packet.name not in _NAMING:
            held.append(arrival)
        else:
            yield from _ended(run, held)
            run = [arrival] if resend else []
            held = []
            if not resend:
                yield [arrival]
    yield from _ended(run, held)


def _same_step(arrival: _Arrival, other: _Arrival) -> bool:
    """Whether `arrival` and `other` came in the same window and on the same tick."""
    return (arrival.window, arrival.tick) == (other.window, other.tick)


def _ended(run: list[_Arrival], held: list[_Arrival]) -> Iterator[list[_Arrival]]:
    """A run that ended, if any, then each packet that went across it, alone."""
    if run:
        yield run
    for arrival in held:
        yield [arrival]


def _by_entity(
    run: Sequence[_Arrival], ranks: Mapping[int, tuple[int, int, str]]
) -> list[_Arrival]:
    """`run` stably sorted by the rank of the entity each packet is about (`_Numbers.ranks`).

    An entity with no rank comes last. So the resends of one entity keep their order, as the
    client applies them in turn, and those of entities the Bot has not heard of yet keep the
    order they arrived in, which their numbers come from.
    """
    return sorted(run, key=lambda arrival: _rank(arrival.event.packet, ranks))


def _rank(packet: Packet, ranks: Mapping[int, tuple[int, int, str]]) -> tuple[int, int, str]:
    """The rank of `packet`'s entity in `ranks`, or `_UNRANKED`."""
    entity = _resend_entity(packet)
    return _UNRANKED if entity is None else ranks.get(entity, _UNRANKED)


_UNRANKED = (2, 0, "")
"""Where an entity the Bot has not heard of yet sorts in a run: after every named one."""


def _resend_entity(packet: Packet) -> int | None:
    """The entity id of `packet` if it is a resend (`_RESENDS`) that holds one; else None."""
    if packet.state is not State.PLAY or packet.name not in _RESENDS or packet.fields is None:
        return None
    entity = packet.fields.get("entity_id")
    return entity if type(entity) is int else None


_CHUNK_PACKETS = frozenset(
    {"minecraft:level_chunk_with_light", "minecraft:light_update", "minecraft:forget_level_chunk"}
)
"""The play packets about one chunk, which the client applies to the chunk at their position:
`ClientChunkCache.replaceWithPacketData` and the light queue, `ClientLevel.queueLightUpdate`, and
`ClientChunkCache.drop` with `queueLightRemoval`."""


_CHUNK_NEUTRAL = frozenset(
    {
        "minecraft:chunk_batch_start",
        "minecraft:chunk_batch_finished",
        "minecraft:pong_response",
        "minecraft:bundle_delimiter",
        "minecraft:add_entity",
        "minecraft:move_entity_pos",
        "minecraft:move_entity_pos_rot",
        "minecraft:move_entity_rot",
        "minecraft:rotate_head",
        "minecraft:set_entity_motion",
        "minecraft:update_attributes",
        "minecraft:remove_entities",
        "minecraft:set_health",
        "minecraft:set_experience",
    }
)
"""The play packets a run of chunk packets goes across: a chunk packet has the same effect, or
nearly, on either side of one (javap on the 26.3 client, docs/research/2026-10-02-chunks-
light.md), besides the heartbeat packets (`_neutral`). A batch's start and end feed only
`ChunkBatchSizeCalculator`; `pong_response` touches the ping monitor; and the entity handlers set
the entity's fields, while its chunk being loaded decides only whether it ticks
(`TransientEntitySectionManager`), which either order ends with the same. One exception is
accepted: a `move_entity_*` handler ends in `Entity.setOnGround`, whose `checkSupportingBlock`
reads the blocks under the entity (`Level.findSupportingBlock`). That only sets which block the
entity stands on until it next moves, and ending runs there would bring back false mismatches
where two vanilla servers split chunks into batches differently. `set_health` sets the
player's health and food (`LocalPlayer.hurtTo`, `FoodData.setFoodLevel`), and
`set_experience` its experience bar (`LocalPlayer.setExperienceValues`): Pumpkin sends both
between its batches, where vanilla sends them before its view (#294)."""


_SLEEPING_POS = 14
"""The entity data index of a living entity's sleeping position, whose handler sets the
entity's position from the bed block there (`LivingEntity.onSyncedDataUpdated`,
`setPosToBed`, javap on the 26.3 client)."""


def _by_position(events: Sequence[Event]) -> list[Event]:
    """A Bot's clientbound `events`, with the chunk packets of each run sorted by position.

    A run is the packets between two packets that are neither about one chunk
    (`_CHUNK_PACKETS`) nor ones whose handling reads no chunk (`_CHUNK_NEUTRAL`), in the whole
    stream: before the windows, their narrowing or a Mask leave anything out, since the client
    applies every packet in turn. It becomes its chunk packets, sorted by position, x then z,
    stably, so those about one chunk keep their order, then its other packets in their order:
    so a neutral packet is in the same place whether it came before a run's first chunk or
    after it. The server
    sends the chunks at one distance from the player in the iteration order of a hash set, and
    which of them are ready for a batch races (`PlayerChunkSender.sendNextChunks`); it sends the
    light updates of a tick in the order of an identity hash set
    (`ServerChunkCache.chunkHoldersToBroadcast`); and the client keeps chunks and their light by
    position (docs/research/2026-10-02-chunks-light.md).
    """
    result: list[Event] = []
    chunks: list[Event] = []
    positions: list[tuple[int, int]] = []
    held: list[Event] = []  # the run's other packets so far

    def end_run() -> None:
        order = sorted(range(len(chunks)), key=positions.__getitem__)
        result.extend(chunks[index] for index in order)
        result.extend(held)
        chunks.clear()
        positions.clear()
        held.clear()

    for event in events:
        if (at := _position(event.packet)) is not None:
            chunks.append(event)
            positions.append(at)
        elif _neutral(event.packet):
            held.append(event)
        else:
            end_run()
            result.append(event)
    end_run()
    return result


def _neutral(packet: Packet) -> bool:
    """Whether `packet` is a play packet a run of chunk packets goes across.

    One `_CHUNK_NEUTRAL` names, a heartbeat packet (`is_heartbeat`), or entity data without a
    sleeping position (`_data_reading_no_chunk`). The heartbeat packets come on the server's
    clock, or answer the barrier, so one can fall between two batches on one Instance only
    (#33), and none reads a chunk: `keep_alive` and `set_time` touch the clock,
    `award_stats` (the barrier's answer, not a clock packet) sets the Bot's statistics
    (`StatsCounter.setValue`), and the latency broadcast only sets each player's latency in
    the tab list (`ClientPacketListener.applyPlayerInfoUpdate`, `PlayerInfo.setLatency`, javap
    on the 26.3 client).
    """
    return packet.state is State.PLAY and (
        packet.name in _CHUNK_NEUTRAL or is_heartbeat(packet) or _data_reading_no_chunk(packet)
    )


def _data_reading_no_chunk(packet: Packet) -> bool:
    """Whether `packet` is `set_entity_data` whose handling reads no chunk.

    Of the client's `onSyncedDataUpdated` overrides only a living entity's sleeping position
    (`_SLEEPING_POS`) reads a block (docs/research/2026-10-02-chunks-light.md; a pose's
    `fudgePositionAfterSizeChange` is skipped on the client). Pumpkin sends the player's data
    between its batches, where vanilla sends it before its view (#294). Data whose entries
    cannot be read, or that hold a sleeping position, ends a run.
    """
    if packet.name != "minecraft:set_entity_data" or packet.fields is None:
        return False
    entries = packet.fields.get("entries")
    return isinstance(entries, list) and all(
        isinstance(entry, Mapping) and entry.get("index") != _SLEEPING_POS
        for entry in cast("list[object]", entries)
    )


def _position(packet: Packet) -> tuple[int, int] | None:
    """The chunk (x, z) of a play packet about one chunk (`_CHUNK_PACKETS`); else None.

    A chunk the codec could not read has the position of its first two Ints, which the client
    reads first (`ClientboundLevelChunkWithLightPacket`), if it has 8 bytes.
    """
    if packet.state is not State.PLAY or packet.name not in _CHUNK_PACKETS:
        return None
    if packet.fields is None:
        if packet.name != _CHUNK or len(packet.payload) < _CHUNK_POSITION_BYTES:
            return None
        x, z = struct.unpack(">ii", packet.payload[:_CHUNK_POSITION_BYTES])
        return x, z
    x, z = packet.fields.get("chunk_x"), packet.fields.get("chunk_z")
    return (x, z) if type(x) is int and type(z) is int else None


_CHUNK = "minecraft:level_chunk_with_light"
_CHUNK_POSITION_BYTES = 8


_BIOMES_REGISTRY = "minecraft:worldgen/biome"


_REGISTRY_DATA = "minecraft:registry_data"


def _by_registry(stream: Sequence[_Normalized]) -> list[_Normalized]:
    """A Bot's normalized `stream`, with each run of `registry_data` sorted by registry, stably.

    A run is a longest stretch of configuration packets that each hold a registry
    (`_registry_id`) or read none (`_REGISTRY_NEUTRAL`). Until `finish_configuration` the
    client only collects each registry's entries apart, and then loads the registries by key,
    in an order of its own; the entries of two packets of one registry it appends in the order
    they came (docs/research/2026-10-23-registry-order.md). A run becomes its registries,
    sorted by registry, stably, so those of one registry keep their order, then its other
    packets in their order: so such a packet is in the same place whether it came before a
    registry or after it. Each registry notes its registry, its run and its index in `stream`
    (`_Normalized.registry`), so the order each side sent them in can still be compared
    (`_registry_order`).
    """
    result: list[_Normalized] = []
    for number, (start, run) in enumerate(_registry_runs(stream)):
        result.extend(stream[len(result) : start])
        result.extend(_placed_and_sorted(run, number=number, start=start))
    result.extend(stream[len(result) :])
    return result


def _registry_runs(stream: Sequence[_Normalized]) -> Iterator[tuple[int, list[_Normalized]]]:
    """Each run of registries of `stream` (`_by_registry`), with the index it starts at."""
    start = 0
    for in_run, entries in groupby(stream, key=_in_registry_run):
        run = list(entries)
        if in_run:
            yield start, run
        start += len(run)


def _in_registry_run(entry: _Normalized) -> bool:
    """Whether `entry` holds a registry (`_registry_id`) or is one a run goes across."""
    packet = entry.packet
    return _holds_registry(entry) or (
        packet.state is State.CONFIGURATION and packet.name in _REGISTRY_NEUTRAL
    )


_REGISTRY_NEUTRAL = frozenset(
    {
        "minecraft:clear_dialog",
        "minecraft:code_of_conduct",
        "minecraft:cookie_request",
        "minecraft:custom_payload",
        "minecraft:custom_report_details",
        "minecraft:keep_alive",
        "minecraft:ping",
        "minecraft:post_effects",
        "minecraft:reset_chat",
        "minecraft:resource_pack_pop",
        "minecraft:resource_pack_push",
        "minecraft:select_known_packs",
        "minecraft:server_links",
        "minecraft:show_dialog",
        "minecraft:store_cookie",
        "minecraft:update_enabled_features",
        "minecraft:update_tags",
    }
)
"""The configuration packets a run of registries goes across: every clientbound one but
`registry_data`, `finish_configuration`, which loads the registries collected, and `disconnect`
and `transfer`, after which the client handles nothing more (`Connection.disconnect`). The
registries collected are in `ClientConfigurationPacketListenerImpl.registryDataCollector`, a
private field that only `handleRegistryData`, `handleUpdateTags` (which adds the tags apart,
`RegistryDataCollector.appendTags`) and `handleConfigurationFinished` read (javap on the 26.3
client, docs/research/2026-10-23-registry-order.md)."""


def _placed_and_sorted(run: Sequence[_Normalized], *, number: int, start: int) -> list[_Normalized]:
    """Run `number` of registries, which starts at index `start`, in the order it is compared.

    Its registries, each noting where it came (`_RegistryPlace`), sorted by registry, stably;
    then its other packets, in their order.
    """
    placed = [
        replace(entry, registry=_RegistryPlace(registry, run=number, arrived=start + offset))
        for offset, entry in enumerate(run)
        if (registry := _registry_id(entry.packet)) is not None
    ]
    others = [entry for entry in run if not _holds_registry(entry)]
    return [*sorted(placed, key=_registry_text), *others]


def _holds_registry(entry: _Normalized) -> bool:
    """Whether `entry` is a `registry_data` whose registry the codec read (`_registry_id`)."""
    return _registry_id(entry.packet) is not None


def _registry_text(entry: _Normalized) -> str:
    """`registry <id>` for a `registry_data` the codec read (`_by_registry`), else ""."""
    return "" if entry.registry is None else f"registry {entry.registry.registry}"


def _registry_id(packet: Packet) -> str | None:
    """The registry id of a configuration `registry_data` the codec read, as the client reads it.

    With its namespace (`_registry_key`). None for any other packet.
    """
    if packet.state is not State.CONFIGURATION or packet.name != _REGISTRY_DATA:
        return None
    return None if packet.fields is None else _registry_key(packet.fields)


def _registry_key(fields: Mapping[str, object]) -> str | None:
    """The registry id of a `registry_data`'s `fields`, as the client reads it.

    With its namespace (`_client_identifier`), or as sent if the client cannot read it. None
    if the fields have no registry id.
    """
    registry = fields.get("registry_id")
    if not isinstance(registry, str):
        return None
    return _client_identifier(registry) or registry


def _client_identifier(text: str) -> str | None:
    """`text` as the client's `Identifier.parse` reads it, with its namespace; None if it throws.

    (`Identifier.bySeparator`: with no `:`, or with one first, the path is the rest, in the
    `minecraft` namespace. `createUntrusted` and `withDefaultNamespace` then throw
    `IdentifierException` for a namespace or path that `isValidNamespace` or `isValidPath`
    refuses, which disconnects the client; javap on the 26.3 client.)
    """
    namespace, colon, path = text.partition(":")
    if not colon:
        namespace, path = "", text
    namespace = namespace or "minecraft"
    return f"{namespace}:{path}" if _valid_identifier(namespace, path) else None


def _valid_identifier(namespace: str, path: str) -> bool:
    """Whether `Identifier.isValidNamespace(namespace)` and `isValidPath(path)` both hold."""
    return (
        namespace != ".."
        and set(namespace) <= _NAMESPACE_CHARACTERS
        and set(path) <= _NAMESPACE_CHARACTERS | {"/"}
    )


_NAMESPACE_CHARACTERS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789_-.")
"""The characters `Identifier.validNamespaceChar` allows; `validPathChar` allows `/` too."""


@dataclass(frozen=True, slots=True)
class _Context:
    """What a canonical form needs from the rest of a Bot's Transcript.

    Attributes:
        biomes: How many biomes the server sent the Bot in configuration (the entries of
            its `registry_data` for `minecraft:worldgen/biome`), or None if it sent none.
    """

    biomes: int | None

    @classmethod
    def each(cls, events: Sequence[Event]) -> list[Self]:
        """The context of each of a Bot's clientbound `events`, compared or not, in their order.

        The biomes are those of the last configuration before the Event: the client collects
        each configuration's registries afresh (`ClientConfigurationPacketListenerImpl.<init>`
        makes a new `RegistryDataCollector`), and appends the entries of every `registry_data`
        for one registry (`RegistryDataCollector$ContentsCollector.append`).
        """
        contexts: list[Self] = []
        biomes: int | None = None
        counts: list[int] | None = None  # in the configuration the Bot is in, if it is in one
        for event in events:
            packet = event.packet
            if packet.state is not State.CONFIGURATION:
                if counts is not None:
                    # A configuration that sends no biomes gives None, not the earlier count.
                    # What the client does then is out of scope: no server leaves them out.
                    biomes, counts = (sum(counts) if counts else None), None
            else:
                counts = [] if counts is None else counts
                if (
                    _registry_id(packet) == _BIOMES_REGISTRY
                    and packet.fields is not None
                    and isinstance(entries := packet.fields.get("entries"), list)
                ):
                    counts.append(len(cast("list[object]", entries)))
            contexts.append(cls(biomes=biomes))
        return contexts


def window_takes(transcript: Transcript, event: Event) -> bool | None:
    """Whether the Comparison takes `event`, a clientbound Packet of `transcript`, by its windows.

    None if `transcript` has no Observation windows as the event's Bot sees them: then every
    Packet is compared. Otherwise as `_Windows.observes` says.
    """
    windows = _Windows.of(transcript, event.bot)
    return None if windows is None else windows.observes(event)


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
    def of(cls, transcript: Transcript, bot: str) -> Self | None:
        """Index the windows of `transcript` as `bot` sees them; None if it has none.

        A close Mark that names a Bot (`observe:close alice`) closes the window for that
        Bot only; one that names none closes it for every Bot that has no close Mark of
        its own in that window (one that joined after the window closed, say).
        """
        times: list[int] = []
        names: list[frozenset[str] | None] = []
        own: int | None = None  # the window's first close Mark naming `bot`
        unnamed: int | None = None  # the window's first close Mark naming no Bot

        def close() -> None:
            nonlocal own, unnamed
            closed = own if own is not None else unnamed
            if closed is not None:
                times.append(closed)
                names.append(None)
            own = unnamed = None

        for mark in sorted(transcript.marks, key=lambda mark: mark.t_ns):
            label, *rest = mark.label.split(" ")
            if label == OBSERVE_OPEN:
                close()
                times.append(mark.t_ns)
                names.append(frozenset(rest))
            elif label == OBSERVE_CLOSE and rest == [bot] and own is None:
                own = mark.t_ns
            elif label == OBSERVE_CLOSE and not rest and unnamed is None:
                unnamed = mark.t_ns
        close()
        return cls(times=times, names=names) if times else None

    def observes(self, event: Event) -> bool:
        """Whether the Comparison takes `event`, a clientbound Packet of this Transcript.

        A packet of any State but play is always taken. A play packet is taken if it
        arrived at or after an open Mark and before the next Mark (a window that never
        closed runs to the end), the window's names include it, if it has any, and it
        is not a heartbeat packet (`is_heartbeat`).
        """
        packet = event.packet
        if packet.state is not State.PLAY:
            return True
        if is_heartbeat(packet):
            return False
        latest = self.latest(event.t_ns)
        if latest < 0:
            return False
        narrowed = self.names[latest]
        return narrowed is not None and (not narrowed or packet.name in narrowed)

    def latest(self, t_ns: int) -> int:
        """The index of the last Mark at or before `t_ns`; -1 if there is none."""
        return bisect.bisect_right(self.times, t_ns) - 1


@dataclass(frozen=True, slots=True)
class _Ticks:
    """A Transcript's ticks as one Bot sees them: when each stepped tick ended.

    Attributes:
        ends: When each tick ended, ascending: tick k's own Mark for the Bot
            (`tick:<k> <Bot name>`), else its Mark that names no Bot.
    """

    ends: Sequence[int]

    @classmethod
    def of(cls, transcript: Transcript, bot: str) -> Self | None:
        """Index the tick Marks of `transcript` as `bot` sees them; None if it has none."""
        own: dict[int, int] = {}
        unnamed: dict[int, int] = {}
        for mark in transcript.marks:
            label, *rest = mark.label.split(" ")
            if not label.startswith(TICK_MARK):
                continue
            k = int(label.removeprefix(TICK_MARK))
            if rest == [bot]:
                own[k] = mark.t_ns
            elif not rest:
                unnamed[k] = mark.t_ns
        ends = {**unnamed, **own}
        return cls(ends=sorted(ends.values())) if ends else None

    def of_arrival(self, t_ns: int) -> int:
        """The tick a packet that arrived at `t_ns` arrived on, counting from 1.

        Tick k holds what arrived after tick k-1's end and before tick k's end; a packet
        stamped at an end's time is after it. What arrived after the last end is on the
        tick after the last one stepped.
        """
        return bisect.bisect_right(self.ends, t_ns) + 1


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


_RECIPE_BOOK_ADD = "minecraft:recipe_book_add"
_RECIPE_BOOK_REMOVE = "minecraft:recipe_book_remove"
_LOGIN = "minecraft:login"


type _RecipeKey = int | str
"""What a recipe's name or number belongs to: what its entry shows (`_shown_recipe`), or the
display id of a recipe the book does not hold."""


@dataclass(slots=True)
class _Numbering:
    """Keys numbered from 1 by first appearance, unless named first; no number is given twice.

    A named key is written as itself. A number lasts until it ends (`end`), and a name until
    `end_names_but` leaves it out.

    Attributes:
        numbers: Each numbered key's number, until it ends.
        named: The keys written as themselves.
        given: How many numbers have been given.
    """

    numbers: dict[_RecipeKey, int] = dataclasses.field(default_factory=dict)
    named: set[str] = dataclasses.field(default_factory=set)
    given: int = 0

    def of(self, key: _RecipeKey) -> str:
        """`key` as written (`written`), once it takes the next number if it has neither."""
        if key not in self.named and key not in self.numbers:
            self.given += 1
            self.numbers[key] = self.given
        return self.written(key)

    def written(self, key: _RecipeKey) -> str:
        """`key` as written: itself if it is named, else its number as `#<n>`.

        Raises:
            KeyError: `key` has neither a name nor a number.
        """
        return str(key) if key in self.named else f"#{self.numbers[key]}"

    def rank(self, key: _RecipeKey) -> tuple[int, int, str]:
        """Where `key` sorts (`_numbers_first`).

        Raises:
            KeyError: `key` has neither a name nor a number.
        """
        return (
            _numbers_first(None, str(key))
            if key in self.named
            else _numbers_first(self.numbers[key], "")
        )

    def name(self, key: str) -> None:
        """Name `key` as itself, unless it has a number."""
        if key not in self.numbers:
            self.named.add(key)

    def end_names_but(self, kept: AbstractSet[str]) -> None:
        """End the name of each key not in `kept`: it takes a name or number if it comes again."""
        self.named &= kept

    def end(self, key: _RecipeKey) -> None:
        """End `key`'s number, if it has one: it takes the next one if it comes again."""
        self.numbers.pop(key, None)


def _numbers_first(number: int | None, name: str) -> tuple[int, int, str]:
    """Where a key sorts by its number, or by its name if it has none: numbers first, in order."""
    return (1, 0, name) if number is None else (0, number, "")


type _Group = tuple[str, int]
"""A recipe book group as the client keys its buttons: its category (as JSON) and number."""


@dataclass(frozen=True, slots=True)
class _Held:
    """A recipe in the client's book.

    Attributes:
        shown: What its entry shows (`_shown_recipe`), which keys its name or number.
        group: Its group, None for none.
    """

    shown: str
    group: _Group | None


@dataclass(slots=True)
class _RecipeNumbers:
    """The names and numbers of the recipes a Bot receives, and of their groups.

    The client looks a recipe up by its display id (`ClientRecipeBook.known`, a HashMap) and
    puts the recipes of one category and group number in one button
    (`categorizeAndGroupRecipes`, a HashBasedTable). Both are numbers the server picks. They
    are `recipe_book_add`'s `entries[].contents.id` and `.group`, and `recipe_book_remove`'s
    `recipes[]`. `place_ghost_recipe` shows a display, with no id, and `place_recipe`, which
    sends one back, is serverbound, so no Comparison sees it.

    A display id is written as the name or number of the recipe the book holds at it, and a
    recipe is what its entry shows (`_shown_recipe`), so its id does not decide it. A recipe
    with neither that the Bot gets in a compared packet is numbered by first appearance, in
    the order the Packets are compared (sorted, `UNORDERED`), and one it gets in a packet
    that is not compared is named by what it shows (`uncompared`), as an entity spawned
    outside the windows is. A number lasts until a `login`, so a server that takes a recipe
    and gives it back, with its id or another, shows the same. A name lasts while the book
    holds a recipe that shows it, so a recipe one server alone gives and takes outside the
    windows changes nothing. So what came before decides how a recipe reads only when the
    books differed before the window: a recipe named outside the windows that one server
    alone took before both give it again reads as a number on that side and as its name on
    the other. Recipes that show the same are written the same. An add that gives an id
    another recipe than the one the book holds there is written `<recipe> in place of
    <recipe>`: the client puts the new one in its place (`known.put`). An id the book does
    not hold, in a removal, takes the next number, which the removal ends.

    The book follows every packet the Bot receives, compared or not (`follow`): a
    `recipe_book_remove` takes its ids out (`ClientRecipeBook.remove`), a `recipe_book_add`
    that replaces the book empties it first (`ClientRecipeBook.clear`), and a `login` empties
    it, since the client gives the player it makes a new book
    (`ClientPacketListener.handleLogin`). A `login` also ends every number, and the next is
    `#1`, so a rejoin reads the same whatever the windows before it held.

    A group number is written as the names and numbers of the recipes the book holds in the
    group, just after the add (`_group_names`): the client shows those recipes as one
    button, and the number itself only keys them. A group is its category and group number,
    the client's key: vanilla gives a group one number across categories, which the client
    shows as one button in each. So a server that gives a group another number, or the
    recipes of a group another order, shows the same, and one that splits or joins buttons
    does not.

    Attributes:
        recipes: The names and numbers of the recipes, and of the ids a removal finds no
            recipe at.
        book: The recipe at each display id of the client's book, from every packet the Bot
            received, compared or not.
    """

    recipes: _Numbering = dataclasses.field(default_factory=_Numbering)
    book: dict[int, _Held] = dataclasses.field(default_factory=dict)

    def number(
        self, packet: Packet, copies: Sequence[dict[str, _Value]], paths: Sequence[_MaskPath]
    ) -> None:
        """Write the display ids and group numbers in `copies`, each a copy of `packet`'s fields.

        `packet` is the Bot's next compared one, and the copies are sorted (`_copy`), so
        the first copy's order numbers the recipes. A removal is followed after its ids are
        written, and an add before (`follow`, through `paths`, the Masks of `packet`).
        """
        if packet.name == _RECIPE_BOOK_REMOVE:
            self._number_removal(copies)
        replaced = self.follow(packet, paths)
        if packet.name == _RECIPE_BOOK_ADD:
            self._write_ids(copies, replaced)
            self._write_groups(copies)
        self._end_names_gone()

    def uncompared(self, packet: Packet, paths: Sequence[_MaskPath]) -> None:
        """Change the book as `packet`, one not compared, changes it (`follow`); name what it adds.

        Each recipe of a `recipe_book_add` that has no name or number yet is named by what
        it shows through `paths`, the Masks of `packet`, as `_Numbers.spawned` names an
        entity, so a recipe got outside the windows is told from another however many came
        first.
        """
        self.follow(packet, paths)
        if packet.name == _RECIPE_BOOK_ADD:
            for held in self.book.values():
                self.recipes.name(held.shown)
        self._end_names_gone()

    def _end_names_gone(self) -> None:
        """End the name of each recipe the book holds none of: it is named anew if it comes back."""
        self.recipes.end_names_but({held.shown for held in self.book.values()})

    def follow(self, packet: Packet, paths: Sequence[_MaskPath]) -> dict[int, str]:
        """Change the book as `packet`, compared or not, changes the client's.

        What a recipe added shows is read through `paths`, the Masks of `packet`
        (`_book_entries`). A `login` also ends every name and number, and the next number
        is `#1` again.

        Returns:
            Each display id at which a `recipe_book_add` put another recipe in place of the
            one the book held, with what that one showed.
        """
        if packet.fields is None:
            return {}
        if packet.name == _RECIPE_BOOK_ADD:
            return self._add(packet.fields, paths)
        if packet.name == _RECIPE_BOOK_REMOVE:
            self._remove(packet.fields)
        elif packet.name == _LOGIN:
            self.book.clear()
            self.recipes = _Numbering()
        return {}

    def _add(self, fields: Mapping[str, object], paths: Sequence[_MaskPath]) -> dict[int, str]:
        """Put the entries of `fields`, a `recipe_book_add`'s, in the book, or in its place.

        Returns:
            Each display id at which an entry put another recipe in place of the one the book
            held, with what that one showed.
        """
        if fields.get("replace") is True:
            self.book.clear()
        added = dict(_book_entries(fields, paths))
        replaced = {
            display_id: held.shown
            for display_id, held in self.book.items()
            if display_id in added and added[display_id].shown != held.shown
        }
        self.book.update(added)
        return replaced

    def _remove(self, fields: Mapping[str, object]) -> None:
        """Take the ids of `fields`, a removal's, out of the book, and end their numbers."""
        for display_id in _removed_ids(fields):
            self.recipes.end(display_id)
            self.book.pop(display_id, None)

    def _write_ids(self, copies: Sequence[dict[str, _Value]], replaced: Mapping[int, str]) -> None:
        """Write each display id in `copies` as the name or number of the recipe at it.

        A recipe with neither takes the next number. An id in `replaced` is also written
        with the recipe it took the place of.
        """
        for copy in copies:
            for contents in _recipe_contents(copy):
                if type(display_id := contents.get("id")) is int:
                    written = self.recipes.of(self.book[display_id].shown)
                    if (before := replaced.get(display_id)) is not None:
                        written = f"{written} in place of {self.recipes.written(before)}"
                    contents["id"] = written

    def _write_groups(self, copies: Sequence[dict[str, _Value]]) -> None:
        """Write each group number in `copies` as the recipes the book holds in the group.

        A group of an entry that the same add put in another group after it has no recipe in
        the book: it is written "".
        """
        names = self._group_names()
        for copy in copies:
            for contents in _recipe_contents(copy):
                if (group := _group(contents)) is not None:
                    contents["group"] = names.get(group, "")

    def _group_names(self) -> dict[_Group, str]:
        """Each group of the book as its recipes' names and numbers, in `recipes`' order, joined."""
        members: dict[_Group, list[str]] = {}
        for held in self.book.values():
            if held.group is not None:
                members.setdefault(held.group, []).append(held.shown)
        return {
            group: ", ".join(
                self.recipes.written(each) for each in sorted(shown, key=self.recipes.rank)
            )
            for group, shown in members.items()
        }

    def _number_removal(self, copies: Sequence[dict[str, _Value]]) -> None:
        """Number `copies`, each a copy of a `recipe_book_remove`'s fields.

        Each copy's ids are sorted by their names and numbers (`UNORDERED`).
        """
        for copy in copies:
            if isinstance(recipes := copy.get("recipes"), list):
                recipes[:] = _numbered_and_sorted(recipes, self.book, self.recipes)


def _numbered_and_sorted(
    recipes: Sequence[_Value], book: Mapping[int, _Held], numbering: _Numbering
) -> list[_Value]:
    """`recipes`, a removal's, each display id as the name or number of its recipe in `book`.

    An id `book` holds no recipe at takes the next number of its own, in the removal's order.
    The ids are in `numbering.rank`'s order, and anything that is not an id follows them, in
    order.
    """
    keys: list[_RecipeKey] = [
        book[each].shown if each in book else each for each in recipes if type(each) is int
    ]
    written = {key: numbering.of(key) for key in keys}
    others = [each for each in recipes if type(each) is not int]
    return [written[key] for key in sorted(keys, key=numbering.rank)] + others


def _shown_recipe(contents: _Value, paths: Sequence[_MaskPath]) -> str:
    """What a recipe book entry with `contents` shows, through `paths`, its packet's Masks.

    That is `_shown_entry` of the entry without its flags, once the Masks hide what they
    hide in it, as in a compared copy (`_hide_all`). The Masks go on a copy made through
    JSON, which `_shown_entry` writes anyway: `_copy` recurses once a level.
    """
    seen = json.loads(json.dumps({"entries": [{"contents": contents}]}, default=repr))
    _hide_all(seen, paths)
    entries = seen["entries"]
    return _shown_entry(entries[0] if isinstance(entries, list) else entries)


def _group(contents: Mapping[str, object]) -> _Group | None:
    """The group of `contents`, one recipe book entry's, or None if it is in none."""
    number = contents.get("group")
    if type(number) is not int:
        return None
    return json.dumps(contents.get("category"), sort_keys=True, default=repr), number


def _book_entries(
    fields: Mapping[str, object], paths: Sequence[_MaskPath]
) -> Iterator[tuple[int, _Held]]:
    """Each entry of `fields`, a `recipe_book_add`'s, that has a display id: the id and recipe.

    What the recipe shows is read through `paths`, the packet's Masks (`_shown_recipe`), and
    its group as sent: the client keys its buttons on it.
    """
    for contents in _recipe_contents(fields):
        if type(display_id := contents.get("id")) is int:
            yield display_id, _Held(_shown_recipe(contents, paths), _group(contents))


def _removed_ids(fields: Mapping[str, object]) -> Iterator[int]:
    """The display ids `fields`, a `recipe_book_remove`'s, remove."""
    removed = fields.get("recipes")
    for display_id in removed if isinstance(removed, list) else ():
        if type(display_id) is int:
            yield display_id


def _recipe_contents(fields: Mapping[str, object]) -> Iterator[dict[str, _Value]]:
    """The `contents` of each entry of `fields`, a `recipe_book_add`'s, that has them."""
    entries = fields.get("entries")
    for entry in entries if isinstance(entries, list) else ():
        if isinstance(entry, dict) and isinstance(contents := entry.get("contents"), dict):
            yield cast("dict[str, _Value]", contents)


@dataclass(slots=True)
class _Numbers:
    """The names and numbers of a Bot's entities so far, and of its recipes, fed in order.

    An entity spawned outside the windows is named by its `add_entity` (`spawned`); any
    other entity id, and each entity UUID, is numbered by first appearance in the compared
    Packets (`take`): `#1` is the first. The recipes are named and numbered on their own
    (`recipes`): a compared recipe book packet through `_normalize`, and one that is not
    compared changes the book they follow, and names what it adds (`uncompared`).

    Attributes:
        ids: Each entity id's name or number.
        uuids: Each entity UUID's number, counted on their own.
        numbered: How many entity ids have taken a number.
        names: How many entities have taken each name, before its suffix.
        numbers: The number of each entity id in `ids` that took one, as an int.
        recipes: The names and numbers of the recipe display ids, and the group numbers.
    """

    ids: dict[int, str]
    uuids: dict[UUID, str]
    numbered: int = 0
    names: dict[str, int] = dataclasses.field(default_factory=dict)
    numbers: dict[int, int] = dataclasses.field(default_factory=dict)
    recipes: _RecipeNumbers = dataclasses.field(default_factory=_RecipeNumbers)

    def ranks(self) -> dict[int, tuple[int, int, str]]:
        """Where each entity known so far sorts in a run of resends, as of now (`_by_entity`).

        Numbered entities first, by number, then named ones, by name.
        """
        return {
            entity: _numbers_first(self.numbers.get(entity), name)
            for entity, name in self.ids.items()
        }

    def uncompared(self, packet: Packet, masks: _Masks) -> None:
        """Change the recipe book as `packet`, one not compared, changes the client's (`follow`).

        It also names what an add brings, through the Group's `masks`
        (`_RecipeNumbers.uncompared`). A compared one changes the book as it is numbered
        (`_normalize`), so each changes it once.
        """
        self.recipes.uncompared(packet, masks.paths.get(packet.name, ()))

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
                self.numbers[found] = self.numbered
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
                self.numbers.pop(found, None)

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
    """Copy `packet`'s fields; sort, canonicalize, number, and apply the Masks.

    Sorting is `UNORDERED`'s, the numbers of the entities and the recipes are `numbers`',
    and the canonical form may use `context`.
    """
    if packet.fields is None:
        return _Normalized(packet=packet, fields=None)
    paths = masks.paths.get(packet.name, ())
    canonical = _CANONICAL.get((packet.state, packet.name))
    if canonical is None:
        fields = _copy(packet, packet.fields)
        numbers.apply(packet, fields)
        numbers.recipes.number(packet, (fields,), paths)
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
    numbers.recipes.number(packet, (raw, parsed, unmasked, fields), paths)
    for copy in (raw, parsed):
        _hide_all(copy, paths)
    masked = _hide_all(fields, paths)
    return _Normalized(
        packet=packet, fields=fields, raw=raw, parsed=parsed, unmasked=unmasked, masked=masked
    )


def _copy(packet: Packet, fields: Mapping[str, object]) -> dict[str, _Value]:
    """A copy of `fields`, `packet`'s, in the value model.

    Cut to what the client reads (`_CAPS`), in one spelling (`_ONE_SPELLING`), and sorted if
    `UNORDERED` names it. A list or mapping deeper than `_NESTING_LIMIT` in a field's value is
    one leaf (`Nested`), so no walk of the copy recurses deeper than that.
    """
    copy = _plain_mapping(fields.items(), packet.name, ())
    if (cap := _CAPS.get((packet.state, packet.name))) is not None:
        copy = cap(copy)
    if (spelling := _ONE_SPELLING.get((packet.state, packet.name))) is not None:
        copy = spelling(copy)
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
        name = _field_name(key, packet, path)
        copy[name] = _plain(item, packet, (*path, name))
    return copy


def _field_name(key: object, packet: str, path: _Path) -> str:
    """`key`, of the mapping at `path` in `packet`'s fields, checked to be a str.

    Raises:
        TypeError: It is not.
    """
    if not isinstance(key, str):
        msg = f"{packet}: {_where(path)}: {type(key).__name__} key {key!r} is not a field name"
        raise TypeError(msg)
    return key


_NESTING_LIMIT = 255
"""How many levels of lists and mappings a field's value keeps; the rest is one `Nested`.

A Candidate's value nests as deep as the codec decodes it, near Python's recursion limit, and
every walk of a copy recurses once or twice a level (`_plain`, `_pairs`, `_leaves`, and
report.json's `_value` and `_read_value`). At 255, a walk of the deepest value kept still has
474 frames to spare (#479). The status JSON `_strict_json` passes through `_plain` is at most
`_JSON_NESTING_LIMIT` deep, the same number, so it is never cut; the two are set apart.
"""


class Nested(str):
    """A list or mapping more than 255 levels into a field's value, as one leaf.

    Its text is `(nested deeper than 255 levels) ` and then the value as report.json writes one:
    JSON with sorted keys, bytes, a UUID or a float JSON cannot hold as a tagged object, and a
    mapping whose only key is a tag inside `{"dict": ...}` (`_TAG_KEYS`). A NaN keeps its bits:
    `{"float": "nan(7ff8000000000001)"}`. Two are equal exactly when the values are. `_same`
    compares leaves by exact type, so it never equals a string a server sent.
    """

    __slots__ = ()


def _plain(value: object, packet: str, path: _Path) -> _Value:
    if isinstance(value, Mapping | list) and len(path) > _NESTING_LIMIT:
        return _nested(value, packet, path)
    if isinstance(value, Mapping):
        return _plain_mapping(value.items(), packet, path)
    if isinstance(value, list):
        return [_plain(item, packet, (*path, index)) for index, item in enumerate(value)]
    return _plain_leaf(value, packet, path)


def _plain_leaf(value: object, packet: str, path: _Path) -> _Value:
    """`value`, a leaf at `path` in `packet`'s fields, checked to be in the value model.

    Raises:
        TypeError: It is not.
    """
    if value is None:
        return None
    if isinstance(value, (bool, int, float, str, bytes, UUID)) and type(value) in _LEAF_TYPES:
        return value
    msg = f"{packet}: {_where(path)}: {type(value).__name__} is not a codec value"
    raise TypeError(msg)


class _Pending(NamedTuple):
    """A value in a `Nested`'s text still to write."""

    value: object


type _Token = str | _Pending
"""A piece of a `Nested`'s text: written as it is, or a value still to write."""

_TAG_KEYS = frozenset({"absent", "bytes", "uuid", "float", "dict"})
"""The keys of report.json's tagged objects; a `Nested` writes a mapping with one alone in one."""


def _nested(value: object, packet: str, path: _Path) -> Nested:
    """`value`, at `path` in `packet`'s fields, as a `Nested`; written without recursion.

    Raises:
        TypeError: As `_plain` does, at `path` for anything in `value`.
    """
    parts = [f"(nested deeper than {_NESTING_LIMIT} levels) "]
    pending: list[_Token] = [_Pending(value)]
    while pending:
        token = pending.pop()
        if isinstance(token, str):
            parts.append(token)
        elif isinstance(node := token.value, Mapping | list):
            container = cast("Mapping[object, object] | list[object]", node)
            pending.extend(reversed(_tokens(container, packet, path)))
        else:
            parts.append(_leaf_text(_plain_leaf(node, packet, path)))
    return Nested("".join(parts))


def _tokens(node: Mapping[object, object] | list[object], packet: str, path: _Path) -> list[_Token]:
    """The pieces of `node`'s text, in order: `{"a": 1, "b": [2]}`.

    Raises:
        TypeError: A key is not a str, as `_plain_mapping` says, at `path`.
    """
    if isinstance(node, list):
        return _enclosed("[", [("", item) for item in node], "]")
    return _mapping_tokens(node, packet, path)


def _mapping_tokens(mapping: Mapping[object, object], packet: str, path: _Path) -> list[_Token]:
    """The pieces of `mapping`'s text, keys sorted, in `{"dict": ...}` if its one key is a tag.

    Raises:
        TypeError: A key is not a str, as `_plain_mapping` says, at `path`.
    """
    entries = sorted(
        ((_field_name(key, packet, path), item) for key, item in mapping.items()),
        key=lambda entry: entry[0],
    )
    tokens = _enclosed("{", [(f"{_json_text(key)}: ", item) for key, item in entries], "}")
    if len(entries) == 1 and entries[0][0] in _TAG_KEYS:
        return ['{"dict": ', *tokens, "}"]
    return tokens


def _enclosed(start: str, items: Sequence[tuple[str, object]], end: str) -> list[_Token]:
    """`start`, then each item's label and value, with `, ` between items, then `end`."""
    tokens: list[_Token] = [start]
    for index, (label, item) in enumerate(items):
        tokens.extend(((", " if index else "") + label, _Pending(item)))
    tokens.append(end)
    return tokens


def _leaf_text(leaf: _Value) -> str:
    """`leaf` as report.json writes it, but a NaN with its bits: `{"float": "nan(7ff8...)"}`."""
    match leaf:
        case float() if math.isnan(leaf):
            return _json_text({"float": f"nan({struct.pack('>d', leaf).hex()})"})
        case float() if math.isinf(leaf):
            return _json_text({"float": repr(leaf)})
        case bytes() | UUID():
            return _json_text(_json_leaf(leaf))
    return _json_text(leaf)


def _json_text(value: object) -> str:
    """`value`, in the value model with no NaN or infinity, as JSON."""
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


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


def _sorted_section_blocks(fields: dict[str, _Value]) -> dict[str, _Value]:
    """Order `blocks` by position, y then z then x.

    The sort is stable, so a position sent twice keeps the order of its states: the client
    sets each in turn, and keeps the last.
    """
    if "blocks" not in fields:
        return fields
    return {**fields, "blocks": _sorted_on(fields["blocks"], _block_position)}


def _sorted_recipe_book_add(fields: dict[str, _Value]) -> dict[str, _Value]:
    """Put the `entries` with a toast first, in their order, then the others by what they show.

    What an entry shows is its fields but its display id, and of its group number only
    whether it has one (`_shown_entry`), so the order depends on neither server's numbering.
    The sort is stable.
    """
    entries = fields.get("entries")
    if not isinstance(entries, list):
        return fields
    toasts = [entry for entry in entries if _shows_toast(entry)]
    others = [entry for entry in entries if not _shows_toast(entry)]
    return {**fields, "entries": toasts + sorted(others, key=_shown_entry)}


_TOAST_FLAG = 1
"""`ClientboundRecipeBookAddPacket$Entry.FLAG_NOTIFICATION`: the entry's recipe joins the toast."""


def _shows_toast(entry: _Value) -> bool:
    """Whether a `recipe_book_add` entry has the toast flag; one with no int flags counts as so."""
    flags = entry.get("flags") if isinstance(entry, dict) else None
    return type(flags) is not int or bool(flags & _TOAST_FLAG)


def _shown_entry(entry: _Value) -> str:
    """A `recipe_book_add` entry as JSON with sorted keys, as the server's numbers leave it.

    Its display id is left out, and its group number is only whether it has one.
    """
    shown = entry
    if isinstance(entry, dict) and isinstance(contents := entry.get("contents"), dict):
        kept = {key: value for key, value in contents.items() if key != "id"}
        if "group" in kept:
            kept["group"] = kept["group"] is not None
        shown = {**entry, "contents": kept}
    return json.dumps(shown, sort_keys=True, default=repr)


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
        "minecraft:section_blocks_update": _sorted_section_blocks,
        "minecraft:recipe_book_add": _sorted_recipe_book_add,
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
            status = {**status, "description": _description(status["description"])}
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


def _description(description: _Value) -> _Value:
    """The text component the client shows for the status's `description`, canonical.

    A description with an empty list in it is `{"text": ""}`, the declared default: the
    client's text component codec refuses it (`_has_empty_list`), and `ServerStatus.CODEC`
    reads a description it cannot decode as `CommonComponents.EMPTY` (docs/research/
    2026-09-26-comparison.md). Any other is `_text_component`.
    """
    if _has_empty_list(description):
        return {"text": ""}
    return _text_component(description)


def _has_empty_list(component: _Value) -> bool:
    """Whether `component`, or a text component in it, is an empty list or has an empty `extra`.

    `ExtraCodecs.nonEmptyList` wraps both the list form and `extra`, so the client's codec
    refuses either when it is empty, at any depth.
    """
    if isinstance(component, list):
        return not component or any(_has_empty_list(element) for element in component)
    if isinstance(component, dict) and isinstance(extra := component.get("extra"), list):
        return not extra or any(_has_empty_list(element) for element in extra)
    return False


def _text_component(component: _Value) -> _Value:
    """Write each text component as the object the client reads it as.

    A plain string is `{"text": string}`, and a list is its first component with the rest
    added to its `extra` (`_from_list`). The components are `component` itself, each
    element of its list form, and each element of its `extra`, recursively. Nothing else
    in it changes.
    """
    if isinstance(component, str):
        return {"text": component}
    if isinstance(component, list):
        return _from_list([_text_component(element) for element in component])
    if isinstance(component, dict) and isinstance(extra := component.get("extra"), list):
        return {**component, "extra": [_text_component(element) for element in extra]}
    return component


def _from_list(components: list[_Value]) -> _Value:
    """The text component the client builds from the list form `components`.

    `ComponentSerialization.createFromList` copies the first and appends each of the
    rest, so the rest go at the end of the first's `extra` (docs/research/
    2026-09-26-comparison.md). The list stays as it is unless its first element is an
    object whose `extra`, if it has one, is a list.
    """
    match components:
        case [dict() as first, *rest] if isinstance(extra := first.get("extra", []), list):
            return {**first, "extra": [*extra, *rest]} if rest else first
        case _:
            return components


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
    if "heightmaps" in fields:
        fields = {**fields, "heightmaps": _kept_heightmaps(fields["heightmaps"])}
    sections = fields.get("sections")
    if not isinstance(sections, list):
        return fields
    result = {
        **fields,
        "sections": [_canonical_section(section, context.biomes) for section in sections],
    }
    if "light" in fields:
        light_sections = min(len(sections), _SECTIONS_MAX) + _LIGHT_MARGIN
        result["light"] = _canonical_light(fields["light"], light_sections)
    return result


def _kept_heightmaps(heightmaps: _Value) -> _Value:
    """The heightmaps the client keeps: for each type it reads, the last one sent, by type.

    The client reads an unknown type as 0 and puts each into an `EnumMap`
    (`ClientboundLevelChunkPacketData`, `ByteBufCodecs.map`), so a later one of a type
    replaces an earlier one. Heightmaps of no known type stay as they are.
    """
    if not isinstance(heightmaps, list):
        return heightmaps
    kept: dict[int, _Value] = {}
    for item in heightmaps:
        kind = _heightmap_type(item)
        if kind is None or not isinstance(item, dict):
            return heightmaps
        kept[kind[0]] = {**item, "type": kind[0]}
    return [kept[kind] for kind in sorted(kept)]


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
    """A biome container's ids (`_entries`) as the client reads them.

    The client reads a direct biome container at `Mth.ceillog2` of the biomes the server sent
    it (`Strategy.<init>`, `Configuration$Global`), whatever bits per entry are sent; the
    codec reads it at the bits sent. If the Transcript has the biomes, a direct container
    whose data is as long as that width takes is read at that width, so its ids are the ones
    the client reads and the bits sent are network traffic. Data of another length cannot be
    what the client reads: the container is then a value of its own, the bits, the width the
    client reads, and the data.
    """
    bits, data = value.get("bits"), value.get("data")
    if biomes is not None and value.get("palette") is None and isinstance(data, bytes):
        width = (biomes - 1).bit_length()
        if bits == width:
            return _entries(BIOMES, value)
        if width and len(data) == _LONG_BYTES * -(-BIOMES.entries // (_LONG_BITS // width)):
            return _entries(replace(BIOMES, id_count=biomes), value)
        return f"{bits} bits per entry where the client reads {width}: {data.hex()}"
    return _entries(BIOMES, value)


_LONG_BITS = 64
_LONG_BYTES = 8
"""A packed Long's bits and bytes: a container's data is whole Longs (`SimpleBitStorage`)."""


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


def _in_palette_order(container: PalettedContainer, value: _Value) -> _Value:
    """A list or hash palette container with its palette in ascending order of id.

    Vanilla sends a container it holds in memory with its values in the order they were set,
    and one it read back from disk in entry order (`PalettedContainer.pack`), so the order is a
    spelling vanilla varies (docs/research/2026-10-03-vanilla-chunk-spellings.md). Each entry's
    index changes to match; the bits, each Long's unused high bits and any slots after the last
    entry stay as sent. A container with an entry past its palette stays as it is, and so does
    a hash palette longer than its bits have slots for: the client reads one of any length
    (`HashMapPalette.read`), but sorted, an entry's index might not fit its slot. (Only a
    list or hash palette is a list: the codec reads a single value as an int, and the global
    palette as None.)
    """
    if not isinstance(value, dict):
        return value
    bits, palette, data = value.get("bits"), value.get("palette"), value.get("data")
    if not (isinstance(bits, int) and isinstance(palette, list) and isinstance(data, bytes)):
        return value
    ids = [each for each in palette if isinstance(each, int)]
    width = max(bits, container.min_width)
    if len(ids) != len(palette) or len(ids) > 1 << width:
        return value
    order = sorted(range(len(ids)), key=ids.__getitem__)
    indexes = {old: new for new, old in enumerate(order)}
    reindexed = _reindexed(data, width, container.entries, indexes)
    if reindexed is None:
        return value
    ordered: list[_Value] = [*sorted(ids)]
    return {**value, "palette": ordered, "data": reindexed}


def _reindexed(data: bytes, width: int, entries: int, indexes: Mapping[int, int]) -> bytes | None:
    """`data` with each index replaced by `indexes`' for it.

    `data` is `entries` of `width` bits, packed as the client reads them (the codec reads as
    many Longs as they take). None if an index has none in `indexes`, or its new one does not
    fit `width` bits.
    """
    per_long, mask = _LONG_BITS // width, (1 << width) - 1
    longs: list[bytes] = []
    for number, start in enumerate(range(0, len(data), _LONG_BYTES)):
        word = int.from_bytes(data[start : start + _LONG_BYTES], "big")
        for slot in range(min(per_long, entries - number * per_long)):
            shift = slot * width
            index = indexes.get(word >> shift & mask)
            if index is None or index > mask:
                return None
            word = word & ~(mask << shift) | index << shift
        longs.append(word.to_bytes(_LONG_BYTES, "big"))
    return b"".join(longs)


def _one_spelling_level_chunk(fields: dict[str, _Value]) -> dict[str, _Value]:
    """A chunk in one of the spellings vanilla varies between its own runs.

    Each section's containers are `_in_palette_order`, and its light has
    `_sky_below_the_world_empty`.
    """
    result = dict(fields)
    if isinstance(sections := fields.get("sections"), list):
        result["sections"] = [_section_in_palette_order(each) for each in sections]
    if "light" in fields:
        result["light"] = _sky_below_the_world_empty(fields["light"])
    return result


def _one_spelling_light_update(fields: dict[str, _Value]) -> dict[str, _Value]:
    """A light update whose data has `_sky_below_the_world_empty`."""
    if "data" not in fields:
        return fields
    return {**fields, "data": _sky_below_the_world_empty(fields["data"])}


def _sky_below_the_world_empty(light: _Value) -> _Value:
    """Light data with sky light section 0 sent as an empty section, not an array of zeros.

    Vanilla sends either for the light section below the world, depending on whether its
    light engine has made an array for it, and the client keeps the same light either way
    (docs/research/2026-10-03-vanilla-chunk-spellings.md). Bit 0 leaves the sky mask, the
    array goes, and bit 0 joins the empty sky mask. Each mask keeps as many zero bytes after
    its last bit as it was sent with (`BitSet.toByteArray()` writes none, and the codec keeps
    them), so they stay network traffic.
    """
    if not isinstance(light, dict):
        return light
    mask, empty = light.get("sky_light_mask"), light.get("empty_sky_light_mask")
    arrays = light.get("sky_light_arrays")
    if not (isinstance(mask, bytes) and isinstance(empty, bytes) and isinstance(arrays, list)):
        return light
    sent = int.from_bytes(mask, "little")
    if not (sent & 1 and arrays and arrays[0] == bytes(_LIGHT_BYTES)):
        return light
    return {
        **light,
        "sky_light_mask": _with_bit_0(mask, set_it=False),
        "empty_sky_light_mask": _with_bit_0(empty, set_it=True),
        "sky_light_arrays": arrays[1:],
    }


def _with_bit_0(bit_set: bytes, *, set_it: bool) -> bytes:
    """`bit_set`, lowest byte first, with bit 0 set or cleared.

    As many bytes long as its bits need, plus the zero bytes it was sent with after them.
    """
    number = int.from_bytes(bit_set, "little")
    extra = len(bit_set) - _bytes_for(number)
    changed = number | 1 if set_it else number & ~1
    return changed.to_bytes(_bytes_for(changed) + extra, "little")


def _bytes_for(number: int) -> int:
    """How many bytes `BitSet.toByteArray()` writes for `number`: none after its last bit."""
    return (number.bit_length() + 7) // 8


def _section_in_palette_order(section: _Value) -> _Value:
    if not isinstance(section, dict):
        return section
    result = dict(section)
    for key, (container, _) in _CONTAINERS.items():
        if key in section:
            result[key] = _in_palette_order(container, section[key])
    return result


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

_SECTIONS_MAX = _LIGHT_SECTIONS_MAX - _LIGHT_MARGIN
"""The most sections a level has: 254."""

_EMPTY = "empty"
"""A light section sent empty, where the client's light is not the same as an array of 0s."""


def _capped(items: _Value, most: int, what: str) -> _Value:
    """`items`' first `most` elements, then one that counts the rest (`19746 more sections`)."""
    if not isinstance(items, list) or len(items) <= most:
        return items
    return [*items[:most], f"{len(items) - most} more {what}"]


def _capped_light(light: _Value) -> _Value:
    """Light data with at most `_LIGHT_SECTIONS_MAX` arrays in each layer (`_capped`).

    A mask has a bit for each array the client takes, and no bit from the light section count
    up is read (`_canonical_light`), so no array past the 256th is.
    """
    if not isinstance(light, dict):
        return light
    return {
        key: _capped(value, _LIGHT_SECTIONS_MAX, "arrays") if key.endswith("_arrays") else value
        for key, value in light.items()
    }


def _capped_level_chunk(fields: dict[str, _Value]) -> dict[str, _Value]:
    """A chunk with at most `_SECTIONS_MAX` sections and `_capped_light` light.

    The client reads one section for each section of its level and never the bytes after
    them (`LevelChunk.replaceWithPacketData`), so a chunk of more sections than any level has
    is compared as that many and a count of the rest: one value, not one for each.
    """
    result = dict(fields)
    if "sections" in fields:
        result["sections"] = _capped(fields["sections"], _SECTIONS_MAX, "sections")
    if "light" in fields:
        result["light"] = _capped_light(fields["light"])
    return result


def _capped_light_update(fields: dict[str, _Value]) -> dict[str, _Value]:
    """A light update with `_capped_light` data."""
    return {**fields, "data": _capped_light(fields["data"])} if "data" in fields else fields


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


def _without(key: str) -> Callable[[dict[str, _Value], _Context], dict[str, _Value]]:
    """A canonical form that leaves out the field `key` and keeps the others.

    A Divergence of a packet that only one side sent (missing or unexpected) shows the packet
    without that field too, since it shows the canonical form.
    """

    def canonical(fields: dict[str, _Value], _context: _Context) -> dict[str, _Value]:
        return {name: value for name, value in fields.items() if name != key}

    return canonical


_CANONICAL_BATCH_FINISHED = _without("batch_size")
"""No `batch_size`: the client feeds it only to the rate it asks the server for.

(`ClientPacketListener.handleChunkBatchFinished`: `ChunkBatchSizeCalculator.onBatchFinished`,
then `chunk_batch_received` with `getDesiredChunksPerTick`.) Which chunks a batch holds races
between two vanilla Instances, and the client keeps each chunk by its position."""

_CANONICAL_CONTAINER_STATE = _without("state_id")
"""No `state_id`: the client only echoes it back in its next click.

(`ClientPacketListener.handleContainerContent` and `handleContainerSetSlot` pass it to
`AbstractContainerMenu.initializeContents` and `setItem`, which store it in `stateId`;
`MultiPlayerGameMode.handleContainerInput` is the one client code that reads it, and copies
it into `ServerboundContainerClickPacket`.) Nothing the player sees depends on it. A
`container_set_content` or `container_set_slot` that only one side sent shows in its Divergence
without `state_id`, as a `chunk_batch_finished` does without `batch_size`."""


def _canonical_registry_data(fields: dict[str, _Value], _context: _Context) -> dict[str, _Value]:
    """A `registry_data` with its registry id as the client reads it (`_registry_key`).

    (`ClientboundRegistryDataPacket.STREAM_CODEC` reads the id with `Identifier.STREAM_CODEC`,
    which is `Identifier.parse`, javap on the 26.3 client.) So `worldgen/biome` against
    `minecraft:worldgen/biome` is network traffic.
    """
    registry = _registry_key(fields)
    return fields if registry is None else {**fields, "registry_id": registry}


_BATCH_PACKETS = frozenset(
    {(State.PLAY, "minecraft:chunk_batch_start"), (State.PLAY, "minecraft:chunk_batch_finished")}
)
"""The packets that mark a chunk batch: the client's world does not change with them, so one that
only one side sent is network traffic (`_CANONICAL_BATCH_FINISHED`)."""


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
        texts = [_container_text(value, container.entries) for value in values]
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


def _container_text(value: _Value | Absent, entries: int) -> str | None:
    """A canonical container said whole; None if it is not one.

    "all 41", "ids 3 to 41" (with "and entries past the palette" if it has any), or what is
    wrong with it.
    """
    if type(value) is int:
        return f"all {value}"
    if isinstance(value, str):
        return value
    if not isinstance(value, bytes):
        return None
    ids = _unpacked_ids(value, entries)
    known = sorted({each for each in ids if each is not None})
    if not known:
        return "every entry past the palette"
    text = f"id {known[0]}" if len(known) == 1 else f"ids {known[0]} to {known[-1]}"
    return text + (" and entries past the palette" if None in ids else "")


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
    """A light section said whole: "all 15", "levels 0 to 15", "empty", "not sent", ....

    ABSENT is past the side's light sections: "no such light section".
    """
    if isinstance(value, bytes):
        found = set(_levels(value))
        return f"all {min(found)}" if len(found) == 1 else f"levels {min(found)} to {max(found)}"
    if isinstance(value, str):
        return value
    return "no such light section" if value is ABSENT else "not sent"


_CANONICAL: Mapping[
    tuple[State, str], Callable[[dict[str, _Value], _Context], dict[str, _Value]]
] = MappingProxyType(
    {
        (State.STATUS, "minecraft:status_response"): _canonical_status_response,
        (State.CONFIGURATION, _REGISTRY_DATA): _canonical_registry_data,
        (State.PLAY, "minecraft:level_chunk_with_light"): _canonical_level_chunk,
        (State.PLAY, "minecraft:light_update"): _canonical_light_update,
        (State.PLAY, "minecraft:chunk_batch_finished"): _CANONICAL_BATCH_FINISHED,
        (State.PLAY, "minecraft:container_set_content"): _CANONICAL_CONTAINER_STATE,
        (State.PLAY, "minecraft:container_set_slot"): _CANONICAL_CONTAINER_STATE,
    }
)
"""The canonical form of each clientbound packet that has one, by (State, name), from its
fields and its Bot's `_Context`."""

_CAPS: Mapping[tuple[State, str], Callable[[dict[str, _Value]], dict[str, _Value]]] = (
    MappingProxyType(
        {
            (State.PLAY, "minecraft:level_chunk_with_light"): _capped_level_chunk,
            (State.PLAY, "minecraft:light_update"): _capped_light_update,
        }
    )
)
"""For a packet whose lists can be longer than the client ever reads: every copy of its fields
cut to what can be read, and one value that counts the rest (`_capped`)."""

_ONE_SPELLING: Mapping[tuple[State, str], Callable[[dict[str, _Value]], dict[str, _Value]]] = (
    MappingProxyType(
        {
            (State.PLAY, "minecraft:level_chunk_with_light"): _one_spelling_level_chunk,
            (State.PLAY, "minecraft:light_update"): _one_spelling_light_update,
        }
    )
)
"""For a packet that vanilla spells two ways between its own runs, where the client keeps the
same either way: every copy of its fields in one of them, so neither is a Divergence."""

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


type _Key = tuple[str, ...]
"""What a Packet is aligned on (`_key`): its State, its name and, for a packet about one chunk,
its position (`chunk x z`; empty for any other Packet). The client keeps a chunk and its light by
position, so two such packets at different positions are never one Packet sent two ways. And for a
`registry_data` the codec read, its registry (`registry <id>`, `_registry_text`; empty for any
other Packet, so it pairs only with a `registry_data` of the same registry): the client collects
each registry's entries apart, so a registry only one side sends is one Packet left unmatched
(#451). Not its tick in a tick-exact Group: two matched Packets on different ticks are a
Divergence of their own (`_diff_ticks`), so a run of packets each a tick late still matches one
for one (#23)."""


def _key(entry: _Normalized) -> _Key:
    return (
        entry.packet.state.value,
        entry.packet.name,
        _place_text(entry.packet),
        _registry_text(entry),
    )


def _place_text(packet: Packet) -> str:
    """`chunk <x> <z>` for a packet about one chunk (`_position`), else the empty string."""
    at = _position(packet)
    return "" if at is None else f"chunk {at[0]} {at[1]}"


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
    prefix, suffix = _common_ends(reference, candidate)
    ref_stop, cand_stop = len(reference) - suffix, len(candidate) - suffix
    middle = _longest_common_subsequence(reference[prefix:ref_stop], candidate[prefix:cand_stop])
    return [
        *((index, index) for index in range(prefix)),
        *((prefix + ref_index, prefix + cand_index) for ref_index, cand_index in middle),
        *((ref_stop + offset, cand_stop + offset) for offset in range(suffix)),
    ]


def _common_ends(reference: Sequence[Hashable], candidate: Sequence[Hashable]) -> tuple[int, int]:
    """How long the two sequences' common prefix is, then their common suffix after it."""
    shorter = min(len(reference), len(candidate))
    prefix = 0
    while prefix < shorter and reference[prefix] == candidate[prefix]:
        prefix += 1
    suffix = 0
    while suffix < shorter - prefix and reference[-1 - suffix] == candidate[-1 - suffix]:
        suffix += 1
    return prefix, suffix


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


def _align_timed(
    reference: Sequence[_Key],
    candidate: Sequence[_Key],
    reference_ticks: Sequence[int | None],
    candidate_ticks: Sequence[int | None],
) -> list[tuple[int, int]]:
    """`_align` for two streams that both have ticks (#229): ticks break the ties.

    As many Packets are matched as `_align` matches, and of those alignments, the one with
    the most pairs on the same tick. So of two copies of a packet, the one on the other
    side's tick is matched, and the copy on a tick the other side has not is the one left
    unmatched. The common prefix and suffix are those of equal keys on equal ticks; in
    between, a pair is matched whenever matching it keeps an alignment that is best so;
    otherwise the side whose skipping keeps one is skipped, and on a tie the smaller key
    and tick, whichever side it is on, so swapping the sides mirrors the choice.
    """
    full_reference = [
        (key, _tick_order(tick)) for key, tick in zip(reference, reference_ticks, strict=True)
    ]
    full_candidate = [
        (key, _tick_order(tick)) for key, tick in zip(candidate, candidate_ticks, strict=True)
    ]
    prefix, suffix = _common_ends(full_reference, full_candidate)
    ref_stop, cand_stop = len(reference) - suffix, len(candidate) - suffix
    middle = _best_timed_subsequence(
        full_reference[prefix:ref_stop], full_candidate[prefix:cand_stop]
    )
    return [
        *((index, index) for index in range(prefix)),
        *((prefix + ref_index, prefix + cand_index) for ref_index, cand_index in middle),
        *((ref_stop + offset, cand_stop + offset) for offset in range(suffix)),
    ]


def _tick_order(tick: int | None) -> int:
    """A tick as `_align_timed` orders it: none (a Packet outside play) before tick 1."""
    return 0 if tick is None else tick


def _best_timed_subsequence(
    reference: Sequence[tuple[_Key, int]], candidate: Sequence[tuple[_Key, int]]
) -> list[tuple[int, int]]:
    """Trace `_align_timed`'s middle: the most pairs, then the most of them on one tick.

    Each entry is a key and its tick. A pair of equal keys scores `weight`, plus one
    if their ticks are equal too; `weight` exceeds any count of equal ticks, so the number
    of pairs always comes first.
    """
    rows, columns = len(reference), len(candidate)
    weight = min(rows, columns) + 1
    # best[i][j]: the best score of reference[i:] against candidate[j:].
    best = [array("Q", [0]) * (columns + 1) for _ in range(rows + 1)]

    def paired(i: int, j: int) -> int:
        """The score of pairing reference[i] with candidate[j], or 0 if they cannot pair."""
        if reference[i][0] != candidate[j][0]:
            return 0
        return weight + (reference[i][1] == candidate[j][1])

    for i in range(rows - 1, -1, -1):
        row, below = best[i], best[i + 1]
        for j in range(columns - 1, -1, -1):
            score = paired(i, j)
            row[j] = max(below[j], row[j + 1], score + below[j + 1] if score else 0)
    pairs: list[tuple[int, int]] = []
    i = j = 0
    while i < rows and j < columns:
        score = paired(i, j)
        if score and score + best[i + 1][j + 1] == best[i][j]:
            pairs.append((i, j))
            i, j = i + 1, j + 1
        elif best[i + 1][j] > best[i][j + 1]:
            i += 1
        elif best[i][j + 1] > best[i + 1][j]:
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
    ref_keys, cand_keys = [_key(entry) for entry in reference], [_key(entry) for entry in candidate]
    timed = any(e.tick is not None for e in reference) and any(
        e.tick is not None for e in candidate
    )
    pairs = (
        _align_timed(ref_keys, cand_keys, [e.tick for e in reference], [e.tick for e in candidate])
        if timed
        else _align(ref_keys, cand_keys)
    )
    orders = _registry_orders(bot, reference, candidate, pairs)
    next_reference = next_candidate = 0
    for ref_index, cand_index in [*pairs, (len(reference), len(candidate))]:
        for index in range(next_reference, ref_index):
            missing = _unmatched(bot, index, "missing", reference[index])
            if missing.observability is Observability.GAMEPLAY:
                compared.update(_field_cases(reference[index]))
            yield missing
        for index in range(next_candidate, cand_index):
            yield _unmatched(bot, index, "unexpected", candidate[index])
        if ref_index < len(reference):
            matched = (reference[ref_index], candidate[cand_index])
            if (order := orders.get(ref_index)) is not None:
                yield order
            yield from _diff_ticks(bot, ref_index, *matched)
            yield from _diff_matched(bot, ref_index, *matched, compared)
        next_reference, next_candidate = ref_index + 1, cand_index + 1


class _MatchedRegistry(NamedTuple):
    """Two matched `registry_data` the codec read (`_matched_registries`).

    Attributes:
        index: The reference packet's index in its normalized stream.
        reference: Where the reference packet came.
        candidate: Where the candidate packet came.
    """

    index: int
    reference: _RegistryPlace
    candidate: _RegistryPlace


def _registry_orders(
    bot: str,
    reference: Sequence[_Normalized],
    candidate: Sequence[_Normalized],
    pairs: Sequence[tuple[int, int]],
) -> dict[int, Divergence]:
    """The order of the matched packets of each run of registries of the reference, by index.

    For each run whose matched packets the sides sent in different orders, its order
    (`_registry_order`), by the index of the first of them. The sort moves a packet only
    within its run, so packets of different runs keep their order on both sides.
    """
    matched = _matched_registries(reference, candidate, pairs)
    runs = groupby(matched, key=lambda pair: pair.reference.run)
    orders = (_registry_order(bot, reference, list(run)) for _, run in runs)
    return {order.index: order for order in orders if order is not None}


def _registry_order(
    bot: str, reference: Sequence[_Normalized], matched: Sequence[_MatchedRegistry]
) -> Divergence | None:
    """The order of the `matched` packets of one run of registries, if the sides' differ.

    One network traffic `field` Divergence at `ORDER_PATH`, at the first of them, with each
    side's registry ids of them in the order it sent them (`_RegistryPlace.arrived`), and the
    test case of `registry_id`: the client loads the registries by key, whatever their order
    (`_by_registry`). None if both sent them in one order.
    """
    sent_reference = _sent_order(pair.reference for pair in matched)
    sent_candidate = _sent_order(pair.candidate for pair in matched)
    if sent_reference == sent_candidate:
        return None
    first = reference[matched[0].index].packet
    return Divergence(
        bot=bot,
        index=matched[0].index,
        kind="field",
        packet=first.name,
        path=ORDER_PATH,
        reference=sent_reference,
        candidate=sent_candidate,
        test_case=_test_case(first.state, first.name, ("registry_id",)),
        observability=Observability.NETWORK_TRAFFIC,
    )


def _matched_registries(
    reference: Sequence[_Normalized],
    candidate: Sequence[_Normalized],
    pairs: Sequence[tuple[int, int]],
) -> list[_MatchedRegistry]:
    """The `pairs` of `registry_data` the codec read, in order (`_Normalized.registry`).

    A packet with a registry pairs only with one of the same registry (`_key`).
    """
    places = [
        (ref_index, reference[ref_index].registry, candidate[cand_index].registry)
        for ref_index, cand_index in pairs
    ]
    return [
        _MatchedRegistry(index, ref_place, cand_place)
        for index, ref_place, cand_place in places
        if ref_place is not None and cand_place is not None
    ]


def _sent_order(places: Iterable[_RegistryPlace]) -> list[str]:
    """The registries of `places`, in the order they came (`_RegistryPlace.arrived`)."""
    return [place.registry for place in sorted(places, key=lambda place: place.arrived)]


def _field_cases(entry: _Normalized) -> set[str]:
    """The test cases of a Packet's own fields, as a match with itself would compare them.

    So each field of a reference Packet the Candidate did not send is a test case it fails,
    and leaving a Packet out never scores better than sending it wrong (#101). A Packet
    without fields is one test case, its packet's; a masked field is none.
    """
    state, name = entry.packet.state, entry.packet.name
    if entry.fields is None:
        return {_test_case(state, name, ())}
    return _leaf_cases(state, name, entry.fields, (), entry.masked)


def _leaf_cases(
    state: State, name: str, value: _Value | Absent, path: _Path, masked: frozenset[_Path]
) -> set[str]:
    """The test cases of the leaves of `value`, at `path` in a Packet: none where masked.

    An empty list or mapping is a leaf too, so a compound of empty ones is not worth less
    than one of values when it is replaced or left out.
    """
    names: dict[_Path, str] = {}
    for leaf in _leaves(value, path):
        shape = _shape(leaf)
        if shape not in names and leaf not in masked:
            names[shape] = _test_case(state, name, shape)
    return set(names.values())


def _shape(path: _Path) -> _Path:
    """`path` with every list index 0: the same for each element of a list."""
    return tuple(0 if isinstance(step, int) else step for step in path)


def _leaves(value: _Value | Absent, path: _Path) -> Iterator[_Path]:
    """The path of each leaf of `value`, in the order `_pairs` gives, empty compounds included."""
    if isinstance(value, dict) and value:
        for key in sorted(value):
            yield from _leaves(value[key], (*path, key))
    elif isinstance(value, list) and value:
        for index, item in enumerate(value):
            yield from _leaves(item, (*path, index))
    else:
        yield path


def _diff_ticks(
    bot: str, index: int, reference: _Normalized, candidate: _Normalized
) -> Iterator[Divergence]:
    """The ticks of two matched Packets, if both have one and they differ (#23).

    One `field` Divergence at `TICK_PATH`, with the two ticks, and the packet's test case;
    the Packets' own differences follow it (`_diff_matched`). It is network traffic for a
    packet that marks a chunk batch (`_BATCH_PACKETS`), as one left out is (`_unmatched`), so
    a marker sent late never scores lower than one not sent.
    """
    if reference.tick is None or candidate.tick is None or reference.tick == candidate.tick:
        return
    state, name = reference.packet.state, reference.packet.name
    yield Divergence(
        bot=bot,
        index=index,
        kind="field",
        packet=name,
        path=TICK_PATH,
        reference=reference.tick,
        candidate=candidate.tick,
        test_case=_test_case(state, name, ()),
        observability=(
            Observability.NETWORK_TRAFFIC
            if (state, name) in _BATCH_PACKETS
            else Observability.GAMEPLAY
        ),
    )


def _unmatched(
    bot: str, index: int, kind: Literal["missing", "unexpected"], entry: _Normalized
) -> Divergence:
    """A Packet one side has: its value, or where it is for one about a chunk (`chunk x z`).

    It is network traffic for a packet that marks a chunk batch (`_BATCH_PACKETS`) and for a
    `registry_data` the client never loads (`_never_loaded`), else gameplay.
    """
    state, name = entry.packet.state, entry.packet.name
    value = _place_text(entry.packet) or entry.value
    return Divergence(
        bot=bot,
        index=index,
        kind=kind,
        packet=name,
        path=None,
        reference=value if kind == "missing" else ABSENT,
        candidate=value if kind == "unexpected" else ABSENT,
        test_case=_test_case(state, name, ()),
        observability=(
            Observability.NETWORK_TRAFFIC
            if (state, name) in _BATCH_PACKETS or _never_loaded(entry.packet)
            else Observability.GAMEPLAY
        ),
    )


def _never_loaded(packet: Packet) -> bool:
    """Whether `packet` is a `registry_data` the client reads, for a registry it never loads.

    The client reads it when it reads its registry id and each entry id (`_client_reads_ids`),
    and never loads a registry outside `_SYNCHRONIZED_REGISTRIES`.
    """
    registry = _registry_id(packet)
    return (
        registry is not None
        and registry not in _SYNCHRONIZED_REGISTRIES
        and packet.fields is not None
        and _client_reads_ids(packet.fields)
    )


def _client_reads_ids(fields: Mapping[str, object]) -> bool:
    """Whether the client reads the registry id and each entry id of a `registry_data`'s `fields`.

    It reads each with `Identifier.STREAM_CODEC` (`ClientboundRegistryDataPacket.STREAM_CODEC`,
    `RegistrySynchronization$PackedRegistryEntry.STREAM_CODEC`, javap on the 26.3 client), and
    one it cannot read disconnects it (`_client_identifier`).
    """
    ids = [fields.get("registry_id"), *_entry_ids(fields)]
    return all(isinstance(text, str) and _client_identifier(text) is not None for text in ids)


def _entry_ids(fields: Mapping[str, object]) -> list[object]:
    """The `entry_id` of each entry of a `registry_data`'s `fields`."""
    entries = fields.get("entries")
    if not isinstance(entries, list):
        return []
    return [
        cast("Mapping[str, object]", entry).get("entry_id")
        for entry in cast("list[object]", entries)
        if isinstance(entry, Mapping)
    ]


_SYNCHRONIZED_REGISTRIES = frozenset(
    {
        "minecraft:banner_pattern",
        "minecraft:block_transformer",
        "minecraft:cat_sound_variant",
        "minecraft:cat_variant",
        "minecraft:chat_type",
        "minecraft:chicken_sound_variant",
        "minecraft:chicken_variant",
        "minecraft:cow_sound_variant",
        "minecraft:cow_variant",
        "minecraft:damage_type",
        "minecraft:decorated_pot_pattern",
        "minecraft:dialog",
        "minecraft:dimension_type",
        "minecraft:enchantment",
        "minecraft:frog_variant",
        "minecraft:instrument",
        "minecraft:jukebox_song",
        "minecraft:painting_variant",
        "minecraft:pig_sound_variant",
        "minecraft:pig_variant",
        "minecraft:sulfur_cube_archetype",
        "minecraft:test_environment",
        "minecraft:test_instance",
        "minecraft:timeline",
        "minecraft:trim_material",
        "minecraft:trim_pattern",
        "minecraft:wolf_sound_variant",
        "minecraft:wolf_variant",
        "minecraft:world_clock",
        "minecraft:worldgen/biome",
        "minecraft:worldgen/block_state_provider",
        "minecraft:zombie_nautilus_variant",
    }
)
"""The registries the 26.3 client loads from `registry_data`: `RegistryDataLoader.
SYNCHRONIZED_REGISTRIES` (javap on the 26.3 client; vanilla 26.3 sends exactly these, live).

The client keeps every `registry_data` it gets, by registry
(`RegistryDataCollector$ContentsCollector.append`), and at `finish_configuration` makes one
load task for each of these, which takes its registry's entries by `Map.get`
(`RegistryDataLoader.load`, `NetworkRegistryLoadTask.load`). So a `registry_data` for any other
registry is never loaded: one only one side sends is network traffic, if the client can read it
(`_never_loaded`). The client also decodes each entry's NBT `data` under its NBT limits, which
the codec does not check."""


PAYLOAD_SHOWN_BYTES = 256
"""How many bytes of a payload a Divergence shows, as hex, before it counts the rest.

A packet compared by its payload (it has no fields: the Codec could not decode it) can be
tens of kilobytes, such as a chunk; shown whole, one would swamp a Report. The Comparison
itself still compares every byte.
"""


PAYLOAD_LEAD_BYTES = 16
"""How many bytes before the first difference two long payloads' shown bytes start, at least.

The start is also a multiple of it, so the bytes shown line up with offsets a reader counts.
"""


def _shown_payload(payload: bytes, start: int = 0) -> str:
    """`payload` as a Divergence shows it: hex, cut to `PAYLOAD_SHOWN_BYTES` and counts.

    The bytes shown begin at `start`. For example `0001…ff (257 more bytes)`, or
    `(576 bytes before) 0000…00 (168 more bytes)`.
    """
    if len(payload) <= PAYLOAD_SHOWN_BYTES:
        return payload.hex()
    end = start + PAYLOAD_SHOWN_BYTES
    shown = payload[start:end].hex()
    before = f"({start} bytes before) " if start else ""
    rest = len(payload) - end
    return f"{before}{shown} ({rest} more bytes)" if rest > 0 else f"{before}{shown}"


def _shown_payloads(reference: bytes, candidate: bytes) -> tuple[str, str]:
    """Two differing payloads as a `field` Divergence shows them (`_shown_payload`).

    If both are longer than `PAYLOAD_SHOWN_BYTES`, both show the same bytes, from
    `PAYLOAD_LEAD_BYTES` before the first that differs, down to a multiple of it, so the
    difference is in view; else each shows its first bytes.
    """
    if min(len(reference), len(candidate)) <= PAYLOAD_SHOWN_BYTES:
        return _shown_payload(reference), _shown_payload(candidate)
    first = next(
        (
            index
            for index, pair in enumerate(zip(reference, candidate, strict=False))
            if pair[0] != pair[1]
        ),
        min(len(reference), len(candidate)),
    )
    start = max(0, first - PAYLOAD_LEAD_BYTES) // PAYLOAD_LEAD_BYTES * PAYLOAD_LEAD_BYTES
    return _shown_payload(reference, start), _shown_payload(candidate, start)


def _diff_matched(
    bot: str, index: int, reference: _Normalized, candidate: _Normalized, compared: set[str]
) -> Iterator[Divergence]:
    """Diff two matched Packets, adding the test case of each pair compared to `compared`.

    Two Packets compared by payload are one test case, the packet's. A pair at a path a
    Mask found a value at counts only if it differs: a masked field is no test case. A
    reference list or mapping the Candidate sent as something else, or left out, adds the
    test case of each of its unmasked leaves too, so replacing it never scores better than
    sending each leaf wrong (#225). Likewise a reference Packet with fields that the
    Candidate sent undecodable: the test case of each of its fields, so a Packet that
    does not decode never scores better than one sent wrong (#230).
    """
    state, name = reference.packet.state, reference.packet.name
    differences: list[tuple[_Path | None, str, object, object]] = []
    if reference.fields is None or candidate.fields is None:
        whole = _test_case(state, name, ())
        compared.add(whole)
        compared.update(_field_cases(reference))  # the packet's alone, if it has no fields
        if reference.packet.payload != candidate.packet.payload:
            payloads = _shown_payloads(reference.packet.payload, candidate.packet.payload)
            differences.append((None, whole, *payloads))
    else:
        # Name each shape once: a list of 10,000 entries is 10,000 pairs but one name.
        names: dict[_Path, str] = {}
        masked = reference.masked | candidate.masked
        shown = _SHOWN.get((state, name))
        sides = (reference.fields, candidate.fields)
        lined_up = _LINED_UP.get(name, frozenset())
        for path, ref_value, cand_value in _pairs(*sides, (), lambda at: _shape(at) in lined_up):
            shape = _shape(path)
            if shape not in names:
                names[shape] = _test_case(state, name, shape)
            if not _same(ref_value, cand_value):
                values = (ref_value, cand_value)
                if shown is not None:
                    values = shown(path, ref_value, cand_value, sides)
                differences.append((path, names[shape], *values))
                compared.add(names[shape])
                # A reference compound replaced or left out whole: each of its leaves (#225).
                compared.update(_leaf_cases(state, name, ref_value, path, masked))
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
    """Yield each pair `_pairs` compares whose two values differ, in path order.

    Every list is compared index by index, so a path reads the same element on each side.
    """
    pairs = _pairs(reference, candidate, path, _no_list)
    return (pair for pair in pairs if not _same(pair[1], pair[2]))


type _LinedUp = Callable[[_Path], bool]
"""Whether `_pairs` lines up the two lists at a path, rather than compare them index by index."""


def _no_list(_path: _Path) -> bool:
    """`_LinedUp` for comparing every list index by index."""
    return False


_LINED_UP: Mapping[str, frozenset[_Path]] = MappingProxyType(
    {
        "minecraft:update_tags": frozenset(
            {("tagged_registries", 0, "tags"), ("tagged_registries", 0, "tags", 0, "entries")}
        ),
    }
)
"""The lists, by packet name in any State and by `_shape`, that are lined up (#256).

Every other list is compared index by index: in many, the index is what the client goes by,
such as a container's slot, a network id or a section's height, so an element at another
index is a difference. The client reads a registry's tags into a map by name, and `UNORDERED`
sorts them by name, so their index means nothing. A tag's entries stay in the order sent.
Lined up, a tag or an id only one side sends is one difference, and the ones after it are
still compared with their counterparts."""


def _pairs(
    reference: _Value | Absent, candidate: _Value | Absent, path: _Path, lined_up: _LinedUp
) -> Iterator[_Pair]:
    """Yield (path, reference value, candidate value) for each pair compared.

    Mappings are compared key by key, in sorted key order, and a key only one side has
    is ABSENT on the other. Lists are lined up where `lined_up` says so (`_fewest_edits`),
    in the order of its steps, and other lists are compared index by index, in path order,
    elements past the end of the shorter one being ABSENT. An element only the reference
    has is at its index, one only the candidate has at its own (`_Added`), and a pair at the
    reference's (`_Moved` if the candidate's differs). Anything else is a leaf, compared as
    a whole.
    """
    if isinstance(reference, dict) and isinstance(candidate, dict):
        for key in sorted(reference.keys() | candidate.keys()):
            values = (reference.get(key, ABSENT), candidate.get(key, ABSENT))
            yield from _pairs(*values, (*path, key), lined_up)
    elif isinstance(reference, list) and isinstance(candidate, list):
        for ref_index, cand_index in _list_edits(reference, candidate, lined_up=lined_up(path)):
            if ref_index is not None and cand_index is not None:
                values = (reference[ref_index], candidate[cand_index])
                yield from _pairs(*values, (*path, _paired(ref_index, cand_index)), lined_up)
            elif ref_index is not None:
                yield (*path, ref_index), reference[ref_index], ABSENT
            elif cand_index is not None:
                yield (*path, _Added(cand_index)), ABSENT, candidate[cand_index]
    else:
        yield path, reference, candidate


def _paired(ref_index: int, cand_index: int) -> int:
    """The path step of two elements compared: their index, or a `_Moved` if they differ."""
    return ref_index if ref_index == cand_index else _Moved(ref_index, cand_index)


class _Moved(int):
    """A list index in a path where `_pairs` compared elements at two different indexes.

    It is the reference's index, which test cases and `_at` go by (a Mask hides each side's own
    index, before `_pairs` lines lists up), and it keeps the candidate's, which `_render`
    shows next to it (`tags[2→5]`). So the rendered path of a
    pair is never that of an element only one side has. Unrendered, it equals its
    reference index (`_Moved(2, 5) == 2`), as an `_Added` equals its candidate index, so a
    set or dict keyed on unrendered paths takes either for that plain index. `masked` is the
    only one, and it only decides which test cases a pair adds, never what differs.
    """

    candidate: int

    def __new__(cls, reference: int, candidate: int) -> Self:
        """The reference's index `reference`, with the candidate's index `candidate`."""
        step = super().__new__(cls, reference)
        step.candidate = candidate
        return step


class _Added(int):
    """A list index in a path where `_pairs` found an element only the candidate has.

    It is the candidate's index, which `_at` and the candidate's Masks go by, and `_render`
    writes it after an arrow (`tags[→5]`), with no reference index before it. So its
    rendered path is never that of a pair or of an element only the reference has.
    """


type _Edit = tuple[int, int] | tuple[int, None] | tuple[None, int]
"""One step from a reference list to a candidate list: the indexes of two elements compared
with each other, or the index of an element only the reference or only the candidate has,
and None on the other side."""


def _list_edits(
    reference: Sequence[_Value], candidate: Sequence[_Value], *, lined_up: bool
) -> list[_Edit]:
    """The steps `_pairs` compares two lists by: lined up on their identities, or not."""
    if not lined_up:
        return _index_by_index(len(reference), len(candidate))
    return _fewest_edits(
        [_identity(item) for item in reference], [_identity(item) for item in candidate]
    )


def _index_by_index(ref_length: int, cand_length: int) -> list[_Edit]:
    """The elements at each index compared, then those past the end of the shorter list."""
    shorter = min(ref_length, cand_length)
    return [
        *((index, index) for index in range(shorter)),
        *((index, None) for index in range(shorter, ref_length)),
        *((None, index) for index in range(shorter, cand_length)),
    ]


def _identity(value: _Value) -> str:
    """What a list element is lined up on: its whole value as JSON, keys sorted.

    Two elements `_pairs` finds no difference between have the same identity, and JSON
    keeps apart what Python calls equal (1, 1.0 and true; 0.0 and -0.0). Bytes and UUIDs
    are written as an object holding their text. Two different elements with one identity
    are compared with each other, so that changes how they are lined up, never what differs.
    """
    return json.dumps(value, sort_keys=True, default=_json_leaf)


def _json_leaf(value: object) -> dict[str, str]:
    """Bytes or a UUID, which JSON has no type for, as `_identity` and a `Nested` write it.

    Anything else is outside the value model, a harness bug: TypeError, as `json.dumps`
    expects of its `default`.
    """
    if isinstance(value, bytes):
        return {"bytes": value.hex()}
    if isinstance(value, UUID):
        return {"uuid": str(value)}
    msg = f"a list element holds a {type(value).__name__}, which no codec value is"
    raise TypeError(msg)


_LINE_UP_LIMIT = 1_000_000
"""The most pairs of elements `_fewest_edits` weighs between the common ends of two lists.

It bounds each list, not a packet. `compare` runs on the Run's event loop, and weighing the
pairs takes time and memory in their number and in the length of both lists: at the limit,
0.3 s and 8 MB for 1,000 by 1,000 elements, 0.8 s and 200 MB for 1 by 10^6, and 1.8 s and
225 MB for 10^6 by 1 (#455).
The most pairs between the common ends of a tag list in a join against Pumpkin nightly
44d881c are 89,726."""


def _fewest_edits(reference: Sequence[str], candidate: Sequence[str]) -> list[_Edit]:
    """Line up two lists of identities (#256), returning the steps in order.

    The steps are as few as can be, each an element compared with another, which counts
    only if they differ, or an element only one side has. So a shifted element is no
    difference: `a, b, c, d` against `b, c, d` is `a` alone, and one element changed in
    place is one change. Of the fewest, the choice is fixed so that swapping the two sides
    mirrors it: the common prefix and suffix are compared as they stand, and in between,
    equal elements are compared with each other, then two elements are compared in place
    whenever that keeps the steps fewest, else the smaller one, whichever side it is on, is
    the one only its side has.

    Between the prefix and the suffix this takes O(n·m) time and memory, as `_align` does.
    So if there are more than `_LINE_UP_LIMIT` pairs of elements there, the elements there
    are compared index by index instead.
    """
    prefix, suffix = _common_ends(reference, candidate)
    ref_stop, cand_stop = len(reference) - suffix, len(candidate) - suffix
    ref_middle, cand_middle = reference[prefix:ref_stop], candidate[prefix:cand_stop]
    middle = (
        _traced(ref_middle, cand_middle, _fewest_table(ref_middle, cand_middle))
        if len(ref_middle) * len(cand_middle) <= _LINE_UP_LIMIT
        else _index_by_index(len(ref_middle), len(cand_middle))
    )
    return [
        *((index, index) for index in range(prefix)),
        *(_shifted(edit, prefix) for edit in middle),
        *((ref_stop + offset, cand_stop + offset) for offset in range(suffix)),
    ]


def _shifted(edit: _Edit, by: int) -> _Edit:
    """`edit` with each of its indexes `by` more."""
    match edit:
        case (int() as ref_index, int() as cand_index):
            return ref_index + by, cand_index + by
        case (int() as ref_index, None):
            return ref_index + by, None
        case (None, int() as cand_index):
            return None, cand_index + by


def _fewest_table(reference: Sequence[str], candidate: Sequence[str]) -> list[array[int]]:
    """`fewest[i][j]`: the fewest steps from `reference[i:]` to `candidate[j:]` that differ."""
    rows, columns = len(reference), len(candidate)
    # The last row starts as it stays: from nothing, each candidate element is one step.
    fewest = [array("L", range(columns, -1, -1)) for _ in range(rows + 1)]
    for i in range(rows - 1, -1, -1):
        row, below, key = fewest[i], fewest[i + 1], reference[i]
        row[columns] = rows - i
        for j in range(columns - 1, -1, -1):
            row[j] = (
                below[j + 1] if key == candidate[j] else 1 + min(below[j + 1], below[j], row[j + 1])
            )
    return fewest


def _traced(
    reference: Sequence[str], candidate: Sequence[str], fewest: Sequence[Sequence[int]]
) -> list[_Edit]:
    """The steps of `_fewest_edits` between the common ends, read from the front of `fewest`."""
    rows, columns = len(reference), len(candidate)
    edits: list[_Edit] = []
    i = j = 0
    while i < rows and j < columns:
        here = fewest[i][j]
        if reference[i] == candidate[j] or here == 1 + fewest[i + 1][j + 1]:
            edits.append((i, j))
            i, j = i + 1, j + 1
        elif here == 1 + fewest[i + 1][j] and (
            here != 1 + fewest[i][j + 1] or reference[i] < candidate[j]
        ):
            edits.append((i, None))
            i += 1
        else:
            edits.append((None, j))
            j += 1
    edits.extend((index, None) for index in range(i, rows))
    edits.extend((None, index) for index in range(j, columns))
    return edits


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
_ADDED = re.compile(r"\[→(0|[1-9][0-9]*)\]")
_MOVED = re.compile(r"\[(0|[1-9][0-9]*)→(0|[1-9][0-9]*)\]")
_EACH = "[*]"
_JSON = json.JSONDecoder()


def _render(path: _MaskPath, *, index_free: bool = False) -> str:
    """Write a field path: `players.sample[0].name`, or `m["not an identifier"]`.

    A key that is an identifier follows a dot (none at the start). Any other key is a
    JSON string in brackets, and a list index is a number in brackets, or nothing in
    them if `index_free` (`players.sample[].name`, as test cases are named). A `_Moved`
    index is both numbers (`[1→3]`), an `_Added` one an arrow and the candidate's (`[→3]`).
    EACH, in a Mask's path, is `[*]`.
    """
    parts: list[str] = []
    for step in path:
        if isinstance(step, Each):
            parts.append(_EACH)
        elif isinstance(step, _Moved) and not index_free:
            parts.append(f"[{step}→{step.candidate}]")
        elif isinstance(step, _Added) and not index_free:
            parts.append(f"[→{step}]")
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
    """Return the steps of `mask`'s field path, where `[*]` is EACH (see `_steps`).

    Raises:
        ValueError: As `_steps` does, or the path has an arrow (`[→2]`, `[1→3]`), which no
            Mask path has, and the message says what Mask hides that instead (`_arrow_advice`).
    """
    steps = _steps(mask.packet, mask.path, "Mask path", each=True)
    if (advice := _arrow_advice(mask.packet, steps)) is not None:
        msg = (
            f"{mask.packet}: Mask path {mask.path!r} has an arrow, which only a Divergence "
            f"path writes: {advice}"
        )
        raise ValueError(msg)
    return steps


def _arrow_advice(packet: str, path: _MaskPath) -> str | None:
    """What an arrow in `path`, a Mask path of `packet`, is, and what hides it; None if none.

    The arrow is the first `_Added` step, or else the first `_Moved` one, and `_hiding_mask`
    is the Mask that hides it, unless it is an entity id: then only WHOLE_PACKET does.
    """
    arrow = _first_arrow(path)
    if arrow is None:
        return None
    hiding = _hiding_mask(path)
    if isinstance(arrow, _Moved):
        return (
            f"{_render((arrow,))} pairs two elements of a list that is lined up after the Masks "
            "apply, so an index names a different element on each side; write "
            f"{_render(hiding)!r} to mask it in every element"
        )
    if _is_entity_id(packet, hiding):
        return (
            f"{_render((arrow,))} is an entity only the Candidate has; a Mask hides a value, "
            "never whether it is there, and an entity id needs no Mask, so only a Mask on the "
            f"whole packet, {WHOLE_PACKET!r}, hides it"
        )
    return (
        f"{_render((arrow,))} is an element only the Candidate has, and a Mask hides a value, "
        f"never whether it is there; only a Mask on the whole list, {_render(hiding)!r}, hides it"
    )


def _first_arrow(path: _MaskPath) -> _Added | _Moved | None:
    """The first `_Added` step of `path`, or else its first `_Moved` step, or else None."""
    added = [step for step in path if isinstance(step, _Added)]
    moved = [step for step in path if isinstance(step, _Moved)]
    return next(iter([*added, *moved]), None)


def _hiding_mask(path: _MaskPath) -> _MaskPath:
    """The Mask path that hides what the arrows in `path`, a Divergence path, name (#477).

    It is `path` up to its first `_Added` step, or its first list index after a `_Moved` step,
    with each `_Moved` step as EACH. No index in a Mask hides either arrow. An `_Added` step is
    an element only the candidate has, and a Mask hides a value, never whether it is there, so
    only a Mask on its whole list hides it. A `_Moved` step pairs two elements of a list
    `_pairs` lines up, and a Mask hides each list's own index before that, so an index names a
    different element on each side, and EACH, every element, takes its place. Past a pair, an
    index in a list inside it
    can name a different element on each side too (`update_tags`' entries are lined up as
    well), so the Mask stops at that list.
    """
    hiding: list[_MaskStep] = []
    moved = False
    for step in path:
        if isinstance(step, _Added) or (moved and isinstance(step, int)):
            break
        moved = moved or isinstance(step, _Moved)
        hiding.append(EACH if isinstance(step, _Moved) else step)
    return tuple(hiding)


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
    if each and text.startswith(_EACH, position):
        return EACH, position + len(_EACH)
    return _index(text, position)


def _index(text: str, position: int) -> tuple[int, int] | None:
    """Read a list index at `position` as `_render` writes it (`[2]`, `[→2]`, `[1→3]`)."""
    if match := _INDEX.match(text, position):
        return int(match[1]), match.end()
    if match := _ADDED.match(text, position):
        return _Added(int(match[1])), match.end()
    if match := _MOVED.match(text, position):
        return _paired(int(match[1]), int(match[2])), match.end()
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
