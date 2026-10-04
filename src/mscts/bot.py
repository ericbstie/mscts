"""Bots: the client connections Groups drive."""

import asyncio
import contextlib
import copy
import hashlib
import json
import math
import struct
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Self, cast

from mscts.codec.packets import Codec, Packet, State
from mscts.codec.schemas.configuration import CLIENT_INFORMATION
from mscts.codec.schemas.play.stats import REQUEST_STATS
from mscts.codec.wire import Writer
from mscts.entities import Entities, Entity, EntityTracker, java_round
from mscts.net import Connection, Endpoint, ProtocolError
from mscts.target import Target
from mscts.transcript import Mark, Transcript

PROBE_TIMEOUT_S = 1.0
"""How long one readiness probe attempt waits, from connecting to the status answer."""

CHUNKS_PER_TICK = 9.0
"""The rate a Bot asks for when it acknowledges a chunk batch (chunk_batch_received).

The vanilla client asks for a rate it estimates from how fast it received the batch, so
its answer depends on its timing; a Bot must not. It asks for 9 chunks per tick, the rate
vanilla's server starts at (`PlayerChunkSender.START_CHUNKS_PER_TICK`, 26.3 javap), so
acknowledging never changes the pace the server chose.
"""

BRAND = "vanilla"
"""The brand a Bot sends after `login_finished`, as the vanilla client sends its own.

`ClientBrandRetriever.getClientModName()` returns `VANILLA_NAME`, "vanilla" (26.3 javap),
sent on channel `minecraft:brand` as a String.
"""

_BRAND_MAX = 32767
"""`BrandPayload` writes the brand with `FriendlyByteBuf.writeUtf`, at most 32767."""

_CONFIGURATION_ANSWERS = {
    "minecraft:code_of_conduct": "minecraft:accept_code_of_conduct",
    "minecraft:finish_configuration": "minecraft:finish_configuration",
}
"""Configuration packets answered by a packet with no fields: what each is answered with."""

CHAT_TIMESTAMP_MS = 1_790_000_000_000
"""The time, in milliseconds since the epoch, that every `chat` and `signed_command` carries.

The vanilla client sends its clock (`Instant.now()`); a Bot sends the same time every run.
Vanilla takes an unsigned message's time from its own clock (`SignedMessageBody.unsigned`,
26.3 javap), so this one reaches no other player.
"""

CHAT_SALT = 0
"""The salt every `chat` and `signed_command` carries, where the vanilla client draws one.

Only a signature uses it, and a Bot signs nothing; vanilla gives an unsigned message salt 0.
"""

_UNSIGNED_CHAT: Mapping[str, object] = {
    "timestamp": CHAT_TIMESTAMP_MS,
    "salt": CHAT_SALT,
    "message_count": 0,
    "acknowledged": bytes(3),
    "checksum": 1,
}
"""What the 26.3 client with no chat session sends besides the text (javap): its time and
salt, no message acknowledged since its last (`LastSeenMessagesTracker`: only signed messages
are tracked), and the checksum of an empty last-seen set (`LastSeenMessages.computeChecksum`)."""

_RELATIVE_X, _RELATIVE_Y, _RELATIVE_Z, _RELATIVE_YAW, _RELATIVE_PITCH = (
    1 << bit for bit in range(5)
)
"""Teleport Flags bits (wiki Data types; vanilla's `Relative`): which parts add to the pose."""

_PITCH_LIMIT = 90.0
_FULL_TURN = 360.0

TICK_GAP_S = 0.005
"""How long `sync` waits after an answer arrived before it asks again.

Vanilla handles every packet that has arrived in one pass at the start of a tick, a request
that arrives during the pass included, so two requests sent back to back can be answered
together, before that tick sends anything. Answers inside one pass came 0.1 to 3.6 ms
apart; answers from different ticks, at least 5.4 ms (docs/research/2026-10-01-join-chunks.md).
A request sent this long after an answer arrived lands after that answer's pass.
"""

SYNC_REQUESTS = 3
"""How many statistics requests `sync` sends, each `TICK_GAP_S` after the last answer.

Two would do if every `award_stats` were an answer. A Candidate may send one unasked, and
the Bot cannot tell it from an answer: taken in an answer's place, it can let two requests
land in one pass (#169). With three, one such `award_stats` still leaves two answers a
pass apart.
"""

SYNC_PASSED_OVER = "sync:passed-over"
"""The label of the Mark `sync` leaves for an `award_stats` that came before its request.

A server that answers twice, or sends statistics nobody asked for; followed by the Bot's
name. Compare reads only `observe:` Marks, so it changes no Verdict.
"""

_STATUS_INTENT, _LOGIN_INTENT = 1, 2

_PERFORM_RESPAWN = 0
"""The `client_command` action the client sends from the death screen's respawn button
(`ServerboundClientCommandPacket.Action`: PERFORM_RESPAWN 0, REQUEST_STATS 1; 26.3 javap)."""


def offline_uuid(name: str) -> uuid.UUID:
    """The UUID an offline-mode server gives the player called `name`.

    Vanilla's `UUIDUtil.createOfflinePlayerUUID` (26.3 javap): Java's
    `UUID.nameUUIDFromBytes`, a version 3 (MD5) UUID, of `"OfflinePlayer:" + name` in UTF-8.
    """
    digest = hashlib.md5(f"OfflinePlayer:{name}".encode(), usedforsecurity=False).digest()
    return uuid.UUID(bytes=digest, version=3)


def _binary32(value: float) -> float:
    """`value` rounded to the nearest binary32, as Java's float arithmetic rounds it."""
    try:
        return float(struct.unpack(">f", struct.pack(">f", value))[0])
    except OverflowError:
        return math.copysign(math.inf, value)


_MOVED = 2.0e-4
"""How far the player must have moved for the client to report its position.

`LocalPlayer.sendPosition` (26.3 javap) reports it when `Mth.lengthSquared` of the change
since the last report is above `Mth.square(2.0E-4)`.
"""

_POSITION_REMINDER_TICKS = 20
"""`LocalPlayer.POSITION_REMINDER_INTERVAL`: the client reports its position on the 20th tick
without a report, moved or not."""

_ON_GROUND = 0x01
"""The movement packets' flag for on ground (`ServerboundMovePlayerPacket.packFlags`: bit 0;
bit 1, horizontal collision, a Bot never sets)."""

_FORWARD, _JUMP, _SNEAK, _SPRINT = 0x01, 0x10, 0x20, 0x40
"""The keys of `player_input` a Bot holds (`Input`'s stream codec: forward, jump, shift, sprint)."""

_START_SPRINTING, _STOP_SPRINTING = 1, 2
"""`ServerboundPlayerCommandPacket.Action` ordinals."""

_KEEP_ENTITY_DATA = 0x02
"""`ClientboundRespawnPacket.KEEP_ENTITY_DATA`: the new player keeps the last sent input and
sprinting (`ClientPacketListener.handleRespawn`)."""

type _Send = tuple[str, dict[str, object]]
"""A packet to send: its name and fields."""


_START_DESTROY_BLOCK, _ABORT_DESTROY_BLOCK, _STOP_DESTROY_BLOCK, _RELEASE_USE_ITEM = 0, 2, 3, 6
"""`ServerboundPlayerActionPacket.Action` ordinals (26.3 javap; the wiki misses one at 1)."""

_MAIN_HAND, _OFF_HAND = 0, 1
"""`InteractionHand` ids."""

_HOTBAR_SLOTS = 9
"""`Inventory.isHotbarSlot`: 0 to 8."""

_CURSOR_MIDDLE = (0.5, 0.5, 0.5)

_LP_VEC3_ZERO_BELOW = 3.051944088384301e-5
"""`LpVec3.write` (26.3 javap) sends the zero vector when no axis is this large."""
_LP_VEC3_LIMIT = 1.7179869183e10
"""`LpVec3.sanitize` holds each axis to plus or minus this."""
_LP_VEC3_QUANTA = 32766.0
"""`LpVec3.pack`: a quantum is `Math.round((v / scale * 0.5 + 0.5) * 32766)`."""


class Face(IntEnum):
    """A block face, as the client names the one it hits (`Direction.get3DDataValue`)."""

    DOWN = 0
    UP = 1
    NORTH = 2
    SOUTH = 3
    WEST = 4
    EAST = 5


@dataclass(slots=True)
class _Interaction:
    """What the client keeps to dig, place and use items, apart from its player.

    `sequence` is the level's `BlockStatePredictionHandler.currentSequenceNr`, which each
    predicted action adds 1 to before it sends it. `selected_slot` is the hotbar slot selected
    (`Inventory.selected`), and `carried_slot` the one last sent
    (`MultiPlayerGameMode.carriedIndex`). All start at 0 (26.3 javap).
    """

    sequence: int = 0
    selected_slot: int = 0
    carried_slot: int = 0

    def next_sequence(self) -> int:
        """The sequence number of a new predicted action, as `startPredicting` counts."""
        self.sequence += 1
        return self.sequence


@dataclass(slots=True)
class _Pose:
    """Where the Bot's player is and faces, as the vanilla client would have it."""

    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    yaw: float = 0.0
    pitch: float = 0.0

    def teleport(self, fields: Mapping[str, object]) -> None:
        """Apply a player_position, as `PositionMoveRotation.calculateAbsolute` does.

        Each flagged part adds to the current value, the others replace it; rotation is
        summed in binary32, then turned to as `turn` does.
        """
        flags = _field(fields, "flags", int)
        self.x = (self.x if flags & _RELATIVE_X else 0.0) + _field(fields, "x", float)
        self.y = (self.y if flags & _RELATIVE_Y else 0.0) + _field(fields, "y", float)
        self.z = (self.z if flags & _RELATIVE_Z else 0.0) + _field(fields, "z", float)
        self.turn(
            _binary32((self.yaw if flags & _RELATIVE_YAW else 0.0) + _field(fields, "yaw", float)),
            _binary32(
                (self.pitch if flags & _RELATIVE_PITCH else 0.0) + _field(fields, "pitch", float)
            ),
        )

    def turn(self, yaw: float, pitch: float) -> None:
        """Face `yaw` and `pitch`, each rounded to binary32, as the client's floats hold them.

        As in `Entity.setYRot` and `setXRot`, a rotation that is not finite leaves the old
        one, and pitch is taken modulo 360 (with the sign of the dividend), then held to -90..90.
        """
        yaw, pitch = _binary32(yaw), _binary32(pitch)
        if math.isfinite(yaw):
            self.yaw = yaw
        if math.isfinite(pitch):
            # Java's float remainder: exact, with the dividend's sign, as math.fmod.
            pitch = math.fmod(pitch, _FULL_TURN)
            self.pitch = max(-_PITCH_LIMIT, min(pitch, _PITCH_LIMIT))


@dataclass(frozen=True, slots=True)
class Position:
    """Where a Bot's player is and faces, as its client has it (`Bot.position`).

    Attributes:
        x: Its x, in blocks.
        y: Its feet's y, in blocks.
        z: Its z, in blocks.
        yaw: Its yaw, in degrees.
        pitch: Its pitch, in degrees, from -90 (up) to 90 (down).
    """

    x: float
    y: float
    z: float
    yaw: float
    pitch: float


@dataclass(slots=True)
class _Controls:
    """What the player does besides where it is: its feet on the ground, the keys it holds."""

    on_ground: bool = True
    keys: int = 0  # the player_input flags
    sprinting: bool = False


@dataclass(slots=True)
class _Reported:
    """What the client last reported, which it keeps so that it sends only changes.

    `LocalPlayer`'s `xLast`, `yLast`, `zLast`, `yRotLast`, `xRotLast`, `lastOnGround`,
    `positionReminder`, `lastSentInput` and `wasSprinting`; a fresh player's are 0, false,
    0, `Input.EMPTY` and false (26.3 javap: its constructor, `MultiPlayerGameMode.createPlayer`).
    A correction from the server changes none of them (`ClientPacketListener.handleMovePlayer`).
    """

    pose: _Pose = field(default_factory=_Pose)
    on_ground: bool = False
    ticks_since_position: int = 0
    keys: int = 0
    sprinting: bool = False


def _client_tick(
    pose: _Pose, controls: _Controls, reported: _Reported, entity_id: int | None
) -> list[_Send]:
    """What the vanilla client sends on one tick for `pose` and `controls`; updates `reported`.

    `Minecraft.tick` (26.3 javap) has `LocalPlayer.sendChanges` send the Input if it
    changed, then (`sendPosition`) a sprint command if sprinting changed, then the
    movement packet, and ends with `client_tick_end`. `entity_id` is the player's, which a
    sprint command carries.
    """
    return [
        *_input_change(controls, reported),
        *_sprint_change(controls, reported, entity_id),
        *_movement(pose, controls, reported),
        ("minecraft:client_tick_end", {}),
    ]


def _input_change(controls: _Controls, reported: _Reported) -> list[_Send]:
    """`player_input` with the keys held, if they changed since the last one sent."""
    if controls.keys == reported.keys:
        return []
    reported.keys = controls.keys
    return [("minecraft:player_input", {"flags": controls.keys})]


def _sprint_change(controls: _Controls, reported: _Reported, entity_id: int | None) -> list[_Send]:
    """`player_command` starting or stopping sprinting, if that changed since the last one."""
    if controls.sprinting == reported.sprinting:
        return []
    reported.sprinting = controls.sprinting
    action = _START_SPRINTING if controls.sprinting else _STOP_SPRINTING
    return [
        ("minecraft:player_command", {"entity_id": entity_id, "action": action, "jump_boost": 0})
    ]


def _movement(pose: _Pose, controls: _Controls, reported: _Reported) -> list[_Send]:
    """The movement packet `LocalPlayer.sendPosition` picks, if any, and what it reports.

    The position goes if it moved more than `_MOVED` or on the `_POSITION_REMINDER_TICKS`th
    tick since it last went, the rotation if it changed, both in one packet if both do;
    with neither, the flags alone if on ground changed.
    """
    reported.ticks_since_position += 1
    moved = (
        _moved_squared(pose, reported.pose) > _MOVED * _MOVED
        or reported.ticks_since_position >= _POSITION_REMINDER_TICKS
    )
    turned = (pose.yaw, pose.pitch) != (reported.pose.yaw, reported.pose.pitch)
    landed_or_left = controls.on_ground != reported.on_ground
    flags = _ON_GROUND if controls.on_ground else 0
    sends = _movement_packet(pose, flags, moved=moved, turned=turned, flags_only=landed_or_left)
    _remember(reported, pose, controls, moved=moved, turned=turned)
    return sends


def _moved_squared(pose: _Pose, last: _Pose) -> float:
    """`Mth.lengthSquared` of the move from `last` to `pose`."""
    dx, dy, dz = pose.x - last.x, pose.y - last.y, pose.z - last.z
    return dx * dx + dy * dy + dz * dz


def _movement_packet(
    pose: _Pose, flags: int, *, moved: bool, turned: bool, flags_only: bool
) -> list[_Send]:
    """The one movement packet for what changed, or none."""
    position = {"x": pose.x, "y": pose.y, "z": pose.z}
    rotation = {"yaw": pose.yaw, "pitch": pose.pitch}
    if moved and turned:
        return [("minecraft:move_player_pos_rot", {**position, **rotation, "flags": flags})]
    if moved:
        return [("minecraft:move_player_pos", {**position, "flags": flags})]
    if turned:
        return [("minecraft:move_player_rot", {**rotation, "flags": flags})]
    if flags_only:
        return [("minecraft:move_player_status_only", {"flags": flags})]
    return []


def _remember(
    reported: _Reported, pose: _Pose, controls: _Controls, *, moved: bool, turned: bool
) -> None:
    """Keep what this tick reported, as the end of `LocalPlayer.sendPosition` does."""
    if moved:
        reported.pose.x, reported.pose.y, reported.pose.z = pose.x, pose.y, pose.z
        reported.ticks_since_position = 0
    if turned:
        reported.pose.yaw, reported.pose.pitch = pose.yaw, pose.pitch
    reported.on_ground = controls.on_ground


_PUNCH: _Send = ("minecraft:punch", {})

_CHUNK_ARRIVES = "minecraft:level_chunk_with_light"
_CHUNK_ARRIVES_OR_GOES = frozenset({_CHUNK_ARRIVES, "minecraft:forget_level_chunk"})


def _carried_change(interaction: _Interaction) -> list[_Send]:
    """`set_carried_item` with the selected slot, if it differs from the one last sent."""
    if interaction.selected_slot == interaction.carried_slot:
        return []
    interaction.carried_slot = interaction.selected_slot
    return [("minecraft:set_carried_item", {"slot": interaction.selected_slot})]


def _lp_vec3(vector: tuple[float, float, float]) -> dict[str, int]:
    """`vector` as `LpVec3.write` encodes it (26.3 javap): a scale and three 15-bit quanta.

    The scale is the largest axis, rounded up (`Mth.ceilLong`); each quantum is the axis over
    the scale, from -1..1 to 0..32766, rounded as `Math.round` rounds (half up).
    """
    held = [max(-_LP_VEC3_LIMIT, min(_LP_VEC3_LIMIT, axis)) for axis in vector]
    largest = max(abs(axis) for axis in held)
    if largest < _LP_VEC3_ZERO_BELOW:
        return {"scale": 0, "x": 0, "y": 0, "z": 0}
    scale = math.ceil(largest)
    x, y, z = (java_round((axis / scale * 0.5 + 0.5) * _LP_VEC3_QUANTA) for axis in held)
    return {"scale": scale, "x": x, "y": y, "z": z}


def _player_action(action: int, block: tuple[int, int, int], face: Face, sequence: int) -> _Send:
    x, y, z = block
    fields = {"action": action, "pos": {"x": x, "y": y, "z": z}, "face": int(face)}
    return ("minecraft:player_action", {**fields, "sequence": sequence})


class Replies:
    """What a Bot answers by itself, as each packet arrives, the way the vanilla client does.

    A Connection's answer (`Connection.open(answer=...)`): the Bot's background reader
    awaits it for every Packet, in wire order, whether or not a Group is reading. Per
    the 26.3 client (javap):

    - login `login_finished` → `login_acknowledged`, then the brand (a configuration
      `custom_payload` on `minecraft:brand` holding `BRAND`) and `client_information`
      (`CLIENT_INFORMATION`, a fresh vanilla client's), all three at once;
    - configuration `select_known_packs` → the same packs back (the vanilla client sends
      those it knows, in the server's order: for vanilla's own offer, all of them);
    - configuration `code_of_conduct` → `accept_code_of_conduct`;
    - configuration `finish_configuration` → `finish_configuration`;
    - `keep_alive` (configuration and play) → the same id back;
    - play `player_position` → `accept_teleportation` with the pose it results in, which
      becomes `pose`;
    - play `chunk_batch_finished` → `chunk_batch_received` at `CHUNKS_PER_TICK`;
    - play `start_configuration` → `configuration_acknowledged`.

    Every other packet gets no answer. Play `login` names the player's entity id. A play
    `login` or `respawn` makes a new player, as the client makes a new `LocalPlayer`, so
    `reported` starts again from a fresh player's; a respawn that keeps entity data
    (`data_kept` bit 1) keeps the keys and sprinting last reported. A login, or a respawn into
    another dimension, starts the block-change sequence again; a login also the held slots.
    A respawn selects slot 0 and keeps the slot last sent, so the next tick sends 0 if that
    differs. Play `set_held_slot` selects a hotbar slot. Every play packet goes to `tracker`,
    which follows the entity packets; a login, or a respawn into another dimension, brings a
    new level, so the tracker forgets every entity (cleared in place, so a view kept from
    before shows the new level). A chunk joins `chunks` with `level_chunk_with_light` and
    leaves it with `forget_level_chunk`; a new level starts with none, as its
    `ClientChunkCache` does.

    Attributes:
        saw_disconnect: Whether the server's disconnect has arrived, taken or not.
        pose: Where the player is and faces: the last teleport's pose, or where the Bot
            moved since.
        entity_id: The player's entity id from play's `login`, or None before it arrives.
        reported: What the client last reported of its player, which a tick compares with.
        interaction: The block-change sequence and the hotbar slots selected and last sent.
        tracker: The entities the server has told the Bot about, in this level.
        chunks: The chunks (x, z) the server has sent in this level and not told the Bot to
            forget.
    """

    def __init__(self) -> None:
        """Start with the player at the origin, facing yaw 0 and pitch 0."""
        self.pose = _Pose()
        self.saw_disconnect = False
        self.entity_id: int | None = None
        self.reported = _Reported()
        self.interaction = _Interaction()
        self.tracker = EntityTracker()
        self.chunks: set[tuple[int, int]] = set()
        self._dimension: str | None = None

    async def __call__(self, connection: Connection, packet: Packet) -> None:
        """Send `packet`'s answer, if it has one, on `connection`."""
        self.saw_disconnect |= _ends_the_session(packet)
        fields = packet.fields or {}
        self._track(packet, fields)
        match packet.state, packet.name:
            case State.LOGIN, "minecraft:login_finished":
                # The ack moves the outbound state on, so the brand and the client
                # information go out in configuration, before the next frame is handled.
                await connection.send("minecraft:login_acknowledged")
                await connection.send(
                    "minecraft:custom_payload",
                    channel="minecraft:brand",
                    data=Writer().string(BRAND, max_length=_BRAND_MAX).to_bytes(),
                )
                await connection.send("minecraft:client_information", **CLIENT_INFORMATION)
            case State.CONFIGURATION, "minecraft:select_known_packs":
                await connection.send(
                    "minecraft:select_known_packs", known_packs=fields.get("known_packs")
                )
            case (
                State.CONFIGURATION,
                "minecraft:code_of_conduct" | "minecraft:finish_configuration",
            ):
                await connection.send(_CONFIGURATION_ANSWERS[packet.name])
            case State.CONFIGURATION | State.PLAY, "minecraft:keep_alive":
                await connection.send(
                    "minecraft:keep_alive", keep_alive_id=fields.get("keep_alive_id")
                )
            case State.PLAY, "minecraft:login" | "minecraft:respawn":
                self._new_player(packet.name, fields)
            case State.PLAY, "minecraft:set_held_slot":
                self._select_slot(_field(fields, "slot", int))
            case State.PLAY, "minecraft:player_position":
                self.pose.teleport(fields)
                await connection.send(
                    "minecraft:accept_teleportation",
                    teleport_id=fields.get("teleport_id"),
                    x=self.pose.x,
                    y=self.pose.y,
                    z=self.pose.z,
                    yaw=self.pose.yaw,
                    pitch=self.pose.pitch,
                )
            case State.PLAY, "minecraft:chunk_batch_finished":
                await connection.send(
                    "minecraft:chunk_batch_received", chunks_per_tick=CHUNKS_PER_TICK
                )
            case State.PLAY, "minecraft:start_configuration":
                await connection.send("minecraft:configuration_acknowledged")
            case _:
                pass

    def _track(self, packet: Packet, fields: Mapping[str, object]) -> None:
        """Give a play packet to `tracker`, which follows the entity packets among them.

        A chunk packet adds its chunk to `chunks`, or drops it. A chunk that does not decode
        never comes here: the reader stops at it, and the Bot's next read raises CodecError.
        """
        if packet.state is not State.PLAY:
            return
        self.tracker.follow(packet.name, fields)
        if packet.name in _CHUNK_ARRIVES_OR_GOES:
            at = (_field(fields, "chunk_x", int), _field(fields, "chunk_z", int))
            if packet.name == _CHUNK_ARRIVES:
                self.chunks.add(at)
            else:
                self.chunks.discard(at)

    def _new_player(self, name: str, fields: Mapping[str, object]) -> None:
        """Start again with the new player a login or a respawn brings (26.3 javap).

        A login names the player's entity id, and brings a new level and a new
        `MultiPlayerGameMode`: `interaction` starts again. A login or a respawn makes a new
        `LocalPlayer`, so `reported` starts again; a respawn that keeps entity data keeps the
        keys and sprinting last reported, and one into another dimension brings a new level,
        whose block-change sequence starts at 0 (`ClientPacketListener.handleLogin`,
        `handleRespawn`). A respawn's new player selects slot 0 (a new `Inventory`), while the
        `MultiPlayerGameMode` keeps the slot last sent.
        """
        dimension = _field(fields, "dimension_name", str)
        if name == "minecraft:login":
            self.entity_id = _field(fields, "entity_id", int)
            self.reported = _Reported()
            self.interaction = _Interaction()
            self.tracker.clear()
            self.chunks.clear()
        else:
            old = self.reported
            kept = _field(fields, "data_kept", int) & _KEEP_ENTITY_DATA
            self.reported = (
                _Reported(keys=old.keys, sprinting=old.sprinting) if kept else _Reported()
            )
            self.interaction.selected_slot = 0
            if dimension != self._dimension:
                self.interaction.sequence = 0
                self.tracker.clear()
                self.chunks.clear()
        self._dimension = dimension

    def _select_slot(self, slot: int) -> None:
        """Select the held slot the server sent, if it is in the hotbar (`handleSetHeldSlot`).

        The slot last sent stays, so the next tick sends the selected one back.
        """
        if 0 <= slot < _HOTBAR_SLOTS:
            self.interaction.selected_slot = slot


@dataclass(frozen=True, slots=True)
class AnsweredConnection:
    """An open Connection and the Replies it was opened with (`Connection.open(answer=...)`)."""

    connection: Connection
    replies: Replies


class Bot:
    """One client connection driven by a Group.

    It speaks the Target's protocol version, and records everything it sends and
    receives to its Transcript under its name. Every operation, connecting included,
    is bounded by `timeout_s` seconds, and raises TimeoutError past it.

    Attributes:
        name: The Bot's name, as its Events record it.
        failure: What its last failed operation raised, or None: so whoever gets an
            exception out of a Group can tell which Bot it came from.
    """

    def __init__(
        self,
        answered: AnsweredConnection,
        endpoint: Endpoint,
        target: Target,
        *,
        name: str,
        timeout_s: float,
    ) -> None:
        """Drive an open Connection to `endpoint`, and its answer. Use `connect` to make one."""
        self.name = name
        self.failure: Exception | None = None
        self._connection = answered.connection
        self._replies = answered.replies  # sees each packet as it arrives, taken or not
        self._endpoint = endpoint
        self._target = target
        self._timeout_s = timeout_s
        self._closed = False
        self._disconnected = False  # expect returned the server's disconnect
        self._controls = _Controls()

    @classmethod
    async def connect(
        cls,
        endpoint: Endpoint,
        target: Target,
        *,
        name: str,
        transcript: Transcript,
        timeout_s: float,
    ) -> Self:
        """Open a Connection to `endpoint` for a Bot called `name`, speaking `target`.

        From then on, the Bot's `Replies` answer each packet as it arrives.

        Raises:
            OSError: The connection failed, e.g. ConnectionRefusedError.
            TimeoutError: It did not connect within `timeout_s`.
        """
        codec = Codec.for_target(target)
        replies = Replies()
        async with asyncio.timeout(timeout_s):
            connection = await Connection.open(
                endpoint, codec, bot=name, transcript=transcript, answer=replies
            )
        answered = AnsweredConnection(connection=connection, replies=replies)
        return cls(answered, endpoint, target, name=name, timeout_s=timeout_s)

    @property
    def closed(self) -> bool:
        """Whether `close` was called."""
        return self._closed

    @property
    def disconnected(self) -> bool:
        """Whether `expect` has returned the server's disconnect: the server sends it no more.

        A Group that tests a kick takes it so; `sync` and `drain` refuse one they take.
        """
        return self._disconnected

    @property
    def in_play(self) -> bool:
        """Whether the Bot has joined and is not closed: what `sync` needs."""
        return not self._closed and self._connection.state is State.PLAY

    @property
    def position(self) -> Position:
        """Where the player is and faces: the last teleport's pose, or where it moved since."""
        pose = self._replies.pose
        return Position(x=pose.x, y=pose.y, z=pose.z, yaw=pose.yaw, pitch=pose.pitch)

    @property
    def entities(self) -> Entities:
        """The entities the server has told the Bot about, by entity id, as the client tracks them.

        Each is where the server last put it: the Bot does not move an entity between packets as
        the client does. A login, or a respawn into another dimension, forgets them all, in
        this same view (docs/research/2026-10-03-bot-entities.md). It changes only as the Bot
        reads packets: after `sync`, it holds everything the server sent before.
        """
        return self._replies.tracker.entities

    @property
    def chunks(self) -> frozenset[tuple[int, int]]:
        """The chunks (x, z) the server has sent the Bot and not told it to forget (a copy).

        A login, or a respawn into another dimension, starts with none, as the client's level
        does. Unlike the client, it keeps a chunk more than `max(2, d) + 3` chunks from the
        view's centre in x or z, where `d` is the view distance the server sent: the client
        drops one (`ClientChunkCache.calculateStorageRange`, `Storage.inRange`, measured from
        `set_chunk_cache_center`). It also keeps the chunks held through a reconfiguration
        (`handleConfigurationStart` clears the client's level). It changes
        only as the Bot reads packets, whether or not a Group takes them, so it also holds the
        chunks `join` or `sync` took.
        """
        return frozenset(self._replies.chunks)

    async def status(self) -> Mapping[str, object]:
        """Ask for the server's status, and return the parsed status JSON.

        Sends the status handshake first, unless this Bot already has.

        Raises:
            ProtocolError: The answer is not a `status_response` holding a JSON object.
            TimeoutError: There was no answer within `timeout_s`.
        """
        async with self._operation(self._timeout_s):
            await self._handshake_for_status()
            await self._connection.send("minecraft:status_request")
            packet = await self._connection.recv(timeout_s=self._timeout_s)
            _expect(packet, "minecraft:status_response")
            return _json_object(packet, (packet.fields or {}).get("json_response"))

    async def ping(self, payload: int) -> None:
        """Ping the server with `payload`, a Long, and check the pong echoes it.

        Sends the status handshake first, unless this Bot already has.

        Raises:
            ProtocolError: The answer is not a `pong_response` echoing `payload`.
            TimeoutError: There was no answer within `timeout_s`.
        """
        async with self._operation(self._timeout_s):
            await self._handshake_for_status()
            await self._connection.send("minecraft:ping_request", timestamp=payload)
            packet = await self._connection.recv(timeout_s=self._timeout_s)
            _expect(packet, "minecraft:pong_response")
            echoed = (packet.fields or {}).get("timestamp")
            if echoed != payload:
                msg = f"pong_response echoed {echoed!r}, not the ping payload {payload!r}"
                raise ProtocolError(msg)

    async def join(self) -> None:
        """Join the server offline, and return once play's first chunk batch has finished.

        Sends the login handshake (intent 2) and a `hello` with the Bot's name and its
        `offline_uuid`, then takes each packet until play's first `chunk_batch_finished`,
        and sends `player_loaded`, once, to say the Bot has loaded the world. On the way,
        the Bot's Replies answer as the vanilla client does: they ack login and send the
        brand and client information, ack configuration, echo the known packs and any
        keep-alive, accept a code of conduct, confirm the join teleport, and acknowledge
        the chunk batch.

        Raises:
            ProtocolError: The Connection is not fresh (a handshake was sent), or the server
                asked for encryption (online mode) or disconnected the Bot.
            TimeoutError: The first chunk batch had not finished within `timeout_s`.
        """
        if self._connection.state is not State.HANDSHAKE:
            msg = f"join needs a fresh Connection, not one in {self._connection.state}"
            raise ProtocolError(msg)
        async with self._operation(self._timeout_s):
            await self._handshake(_LOGIN_INTENT)
            await self._connection.send(
                "minecraft:hello", name=self.name, player_uuid=offline_uuid(self.name)
            )
            await self.expect("minecraft:chunk_batch_finished", timeout_s=self._timeout_s)
            # The vanilla client says it has loaded the world once its renderer has built
            # the player's section, a moment that depends on its timing. A Bot says so as
            # soon as the first batch has arrived and been acknowledged (Replies answered it
            # before expect returned): the batch starts with the player's own chunk, so no
            # client could be ready earlier (docs/research/2026-09-26-join.md).
            await self._connection.send("minecraft:player_loaded")

    async def respawn(self) -> None:
        """Respawn a dead player, and return once the Bot has said it loaded the world again.

        Sends `client_command` PERFORM_RESPAWN, as the death screen's button does, takes each
        packet until the server's `respawn` and then the first `chunk_batch_finished` after it,
        and sends `player_loaded`. The client waits for its world to load again after a
        respawn (`ClientPacketListener.handleRespawn`), and until it says so, the server
        ignores its attacks and interactions (`hasClientLoaded`); as at the join, the Bot says
        so once the first chunk batch has arrived and been acknowledged.

        Raises:
            ProtocolError: The Bot is not in play, or the server disconnected it.
            TimeoutError: The respawn and its first chunk batch did not come within
                `timeout_s`: the server ignores the request while the player is alive.
        """
        self._require_play("respawn")
        async with self._operation(self._timeout_s):
            await self._connection.send("minecraft:client_command", action=_PERFORM_RESPAWN)
            await self.expect("minecraft:respawn", timeout_s=self._timeout_s)
            await self.expect("minecraft:chunk_batch_finished", timeout_s=self._timeout_s)
            await self._connection.send("minecraft:player_loaded")

    async def expect(
        self,
        name: str,
        /,
        *others: str,
        timeout_s: float,
        where: Callable[[Packet], bool] | None = None,
    ) -> Packet:
        """Take packets until one is called any of `names` and `where` holds for it; return it.

        With several names, whichever such packet arrives first ends the wait: a server
        may carry the same thing in another packet (`disguised_chat` for `player_chat`).
        `expect` can't see an Observation window: in one narrowed to other packets, a packet
        outside it is never compared, so name every packet you wait for in the window's
        names too.
        `where` is called with a packet of any of the names, so it must read only fields
        they all have. Every packet taken is recorded, the ones before it included, and the Bot's
        Replies have already answered each of them.

        Raises:
            ValueError: A name is given twice.
            ProtocolError: The server disconnected the Bot, or asked for encryption,
                before such a packet arrived.
            TimeoutError: None arrived within `timeout_s`.
        """
        names = (name, *others)
        if len(set(names)) < len(names):
            msg = f"expect names a packet twice: {', '.join(names)}"
            raise ValueError(msg)
        async with self._operation(timeout_s):
            while True:
                packet = await self._connection.recv(timeout_s=timeout_s)
                if packet.name in names and (where is None or where(packet)):
                    self._disconnected |= _ends_the_session(packet)
                    return packet
                self._refuse(packet)

    async def command(self, command: str) -> None:
        """Run `command`, without its leading `/`, as this Bot's player.

        Sends it as an unsigned `chat_command` and returns at once: whatever the server
        answers arrives later, like any other packet.

        Raises:
            ProtocolError: The Bot is not in play.
        """
        if not self.in_play:
            msg = f"command needs a Bot in play, not one in {self._connection.state}"
            raise ProtocolError(msg)
        async with self._operation(self._timeout_s):
            await self._connection.send("minecraft:chat_command", command=command)

    async def signed_command(self, command: str) -> None:
        """Run `command`, without its leading `/`, as the vanilla client runs a message command.

        The vanilla client sends a command with a message argument (`/say`, `/me`, `/msg`,
        `/teammsg`) as a `chat_command_signed`, signing each such argument; with no chat
        session, as every Bot, it signs none. The Bot sends it so, with its fixed time and salt
        (see `chat`), and returns at once.

        Raises:
            ProtocolError: The Bot is not in play.
        """
        self._require_play("signed_command")
        async with self._operation(self._timeout_s):
            await self._connection.send(
                "minecraft:chat_command_signed",
                command=command,
                argument_signatures=[],
                **_UNSIGNED_CHAT,
            )

    async def chat(self, message: str) -> None:
        """Say `message` in chat, as the vanilla client sends it with no chat session.

        Sends a `chat` with no signature and returns at once. The vanilla client sends its clock
        and a random salt; a Bot sends `CHAT_TIMESTAMP_MS` and `CHAT_SALT`, so every run sends
        the same bytes.

        Raises:
            ProtocolError: The Bot is not in play.
        """
        self._require_play("chat")
        async with self._operation(self._timeout_s):
            await self._connection.send(
                "minecraft:chat", message=message, signature=None, **_UNSIGNED_CHAT
            )

    async def chat_at_once(self, *messages: str) -> None:
        """Say each of `messages` in chat, as `chat` does, all in one write, and return.

        The frames all leave together, in one write. The server can still tick between two
        of them, as vanilla handles each message in a task of its own. Vanilla's spam kick
        adds 20 for each message and takes 1 off each tick, so messages sent together add
        up (docs/research/2026-10-04-chat.md).

        Raises:
            ValueError: No message is given.
            ProtocolError: The Bot is not in play.
        """
        self._require_play("chat_at_once")
        if not messages:
            msg = "chat_at_once needs at least one message"
            raise ValueError(msg)
        chats = [
            ("minecraft:chat", {"message": message, "signature": None, **_UNSIGNED_CHAT})
            for message in messages
        ]
        async with self._operation(self._timeout_s):
            await self._connection.send_all(chats)

    async def move(self, x: float, y: float, z: float, *, on_ground: bool = True) -> None:
        """Move the player to `x`, `y`, `z`, on the ground or not, in one client tick.

        The Bot does not simulate physics: the Group gives each position, as a vanilla
        client sends one each tick it moves. One call is one tick (see `tick`).

        Raises:
            ProtocolError: The Bot is not in play.
            ValueError: A coordinate is NaN or infinite; nothing is sent.
        """
        self._require_play("move")
        if not all(math.isfinite(coordinate) for coordinate in (x, y, z)):
            msg = f"move needs finite coordinates, not {x}, {y}, {z}"
            raise ValueError(msg)
        pose = self._replies.pose
        pose.x, pose.y, pose.z = x, y, z
        self._controls.on_ground = on_ground
        await self._tick()

    async def look(self, yaw: float, pitch: float) -> None:
        """Turn the player to `yaw` and `pitch`, in degrees, in one client tick.

        Each is rounded to a float, and pitch held to -90..90, as the client holds them; a
        value that is not finite leaves that one as it was. One call is one tick (see `tick`).

        Raises:
            ProtocolError: The Bot is not in play.
        """
        self._require_play("look")
        self._replies.pose.turn(yaw, pitch)
        await self._tick()

    async def sprint(self, sprinting: bool) -> None:  # noqa: FBT001 - #25: bot.sprint(True)
        """Start or stop sprinting, in one client tick, holding or releasing forward and sprint.

        A client sprints only while it holds forward, and cannot start while it sneaks
        (`LocalPlayer.canStartSprinting`, `shouldStopRunSprinting`), so the Bot holds both
        keys while it sprints. The tick reports the keys, then the sprint command naming the
        player's entity id (from play's `login`). One call is one tick (see `tick`).

        Raises:
            ProtocolError: The Bot is not in play, the server has not sent its `login`, or
                the player sneaks and `sprinting` is True.
        """
        self._require_play("sprint")
        if self._replies.entity_id is None:
            msg = "sprint needs the player's entity id, and no login has arrived"
            raise ProtocolError(msg)
        if sprinting and self._controls.keys & _SNEAK:
            msg = "sprint needs a player that is not sneaking"
            raise ProtocolError(msg)
        self._controls.keys = _held(self._controls.keys, _FORWARD | _SPRINT, held=sprinting)
        self._controls.sprinting = sprinting
        await self._tick()

    async def sneak(self, sneaking: bool) -> None:  # noqa: FBT001 - #25: bot.sneak(True)
        """Start or stop sneaking, in one client tick, holding or releasing the sneak key.

        Raises:
            ProtocolError: The Bot is not in play.
        """
        self._require_play("sneak")
        self._controls.keys = _held(self._controls.keys, _SNEAK, held=sneaking)
        await self._tick()

    async def jump(self) -> None:
        """Press the jump key for one client tick: the next call releases it.

        It does not make the player jump: the Group moves it up and down with `move`.

        Raises:
            ProtocolError: The Bot is not in play.
        """
        self._require_play("jump")
        self._controls.keys |= _JUMP
        try:
            await self._tick()
        finally:
            self._controls.keys &= ~_JUMP

    async def tick(self) -> None:
        """Send what the vanilla client sends on a tick in which the player does nothing.

        Every movement call is one such tick, with its change: the keys held if they changed
        (`player_input`), a sprint command if sprinting changed (`player_command`), the
        movement packet the change calls for (position, rotation, both, or on-ground alone),
        and `client_tick_end`. The position also goes on the 20th tick without one, as the
        client reminds the server. Nothing waits for the server's tick: to move once per
        server tick, call `sync` between calls.

        Raises:
            ProtocolError: The Bot is not in play.
        """
        self._require_play("tick")
        await self._tick()

    async def _tick(self, actions: tuple[_Send, ...] = ()) -> None:
        """Send one client tick for the pose and controls as they are now, with `actions`.

        As `Minecraft.tick` does: the held slot if it changed (`MultiPlayerGameMode.tick`),
        then `actions` (`handleKeybinds`), then what the player reports (`sendChanges`), then
        `client_tick_end`. What it reports is kept only once every packet has gone, so a tick
        that failed to send is reported again by the next.
        """
        before = self._replies.reported
        reported = copy.deepcopy(before)
        sends = [
            *_carried_change(self._replies.interaction),
            *actions,
            *_client_tick(self._replies.pose, self._controls, reported, self._replies.entity_id),
        ]
        async with self._operation(self._timeout_s):
            for name, fields in sends:
                await self._connection.send(name, **fields)
        if self._replies.reported is before:  # else a fresh player arrived while it sent
            self._replies.reported = reported

    async def hold(self, slot: int) -> None:
        """Select hotbar slot `slot` (0 to 8), in one client tick that sends it.

        The client sends the slot it selected at the start of its next tick
        (`MultiPlayerGameMode.ensureHasSentCarriedItem`); the Bot's tick is that one. One call
        is one tick (see `tick`).

        Raises:
            ProtocolError: The Bot is not in play.
            ValueError: `slot` is not 0 to 8; nothing is sent.
        """
        self._require_play("hold")
        if not 0 <= slot < _HOTBAR_SLOTS:
            msg = f"hold needs a hotbar slot from 0 to 8, not {slot}"
            raise ValueError(msg)
        self._replies.interaction.selected_slot = slot
        await self._tick()

    async def dig(self, x: int, y: int, z: int, face: Face) -> None:
        """Start breaking the block at `x`, `y`, `z` from `face`, in one client tick.

        The tick sends what the client sends when the attack key goes down on a block
        (`Minecraft.startAttack`): `player_action` START_DESTROY_BLOCK with the next sequence
        number, then the swing (`punch`). The Bot does not time the breaking: in survival, call
        `stop_digging` at the tick to test; in creative, the start breaks the block. One call
        is one tick (see `tick`).

        Raises:
            ProtocolError: The Bot is not in play.
        """
        self._require_play("dig")
        sequence = self._replies.interaction.next_sequence()
        await self._tick((_player_action(_START_DESTROY_BLOCK, (x, y, z), face, sequence), _PUNCH))

    async def stop_digging(self, x: int, y: int, z: int, face: Face) -> None:
        """Finish breaking the block at `x`, `y`, `z`, in one client tick.

        The tick sends what the client sends on the tick it thinks the block broke
        (`MultiPlayerGameMode.continueDestroyBlock`): `player_action` STOP_DESTROY_BLOCK with
        the next sequence number, then the swing (`punch`). One call is one tick (see `tick`).

        Raises:
            ProtocolError: The Bot is not in play.
        """
        self._require_play("stop_digging")
        sequence = self._replies.interaction.next_sequence()
        await self._tick((_player_action(_STOP_DESTROY_BLOCK, (x, y, z), face, sequence), _PUNCH))

    async def cancel_digging(self, x: int, y: int, z: int) -> None:
        """Stop breaking the block at `x`, `y`, `z` before it breaks, in one client tick.

        The tick sends what the client sends when the attack key goes up
        (`MultiPlayerGameMode.stopDestroyBlock`): `player_action` ABORT_DESTROY_BLOCK facing
        down, with sequence 0, since the client predicts nothing. One call is one tick (see
        `tick`).

        Raises:
            ProtocolError: The Bot is not in play.
        """
        self._require_play("cancel_digging")
        await self._tick((_player_action(_ABORT_DESTROY_BLOCK, (x, y, z), Face.DOWN, 0),))

    async def place(  # noqa: PLR0913 - #26: a block, its face, and where on it
        self,
        x: int,
        y: int,
        z: int,
        face: Face,
        cursor: tuple[float, float, float] = _CURSOR_MIDDLE,
        *,
        off_hand: bool = False,
    ) -> None:
        """Use the held item on `face` of the block at `x`, `y`, `z`, in one client tick.

        It places a block, opens a door, or does whatever the item does to a block:
        `use_item_on` from the main hand (or the off hand), hitting the face at `cursor` (0 to
        1 on each axis, from the block's lowest corner), with the next sequence number. The
        client's swing for it sends nothing. A client that sees the use do nothing goes on to
        `use_item`; the Bot cannot see that, so it sends `use_item_on` only. One call is one
        tick (see `tick`).

        Raises:
            ProtocolError: The Bot is not in play.
        """
        self._require_play("place")
        cursor_x, cursor_y, cursor_z = cursor
        fields: dict[str, object] = {
            "hand": _OFF_HAND if off_hand else _MAIN_HAND,
            "pos": {"x": x, "y": y, "z": z},
            "face": int(face),
            "cursor_x": cursor_x,
            "cursor_y": cursor_y,
            "cursor_z": cursor_z,
            "inside_block": False,
            "world_border_hit": False,
            "sequence": self._replies.interaction.next_sequence(),
        }
        await self._tick((("minecraft:use_item_on", fields),))

    async def use_item(self, *, off_hand: bool = False) -> None:
        """Start using the held item (eat, draw a bow, raise a shield), in one client tick.

        `use_item` from the main hand (or the off hand), with the next sequence number and the
        way the player faces. One call is one tick (see `tick`).

        Raises:
            ProtocolError: The Bot is not in play.
        """
        self._require_play("use_item")
        pose = self._replies.pose
        fields: dict[str, object] = {
            "hand": _OFF_HAND if off_hand else _MAIN_HAND,
            "sequence": self._replies.interaction.next_sequence(),
            "yaw": pose.yaw,
            "pitch": pose.pitch,
        }
        await self._tick((("minecraft:use_item", fields),))

    async def release_item(self) -> None:
        """Stop using the held item (loose the arrow, lower the shield), in one client tick.

        `player_action` RELEASE_USE_ITEM at the origin facing down, with sequence 0
        (`MultiPlayerGameMode.releaseUsingItem`). One call is one tick (see `tick`).

        Raises:
            ProtocolError: The Bot is not in play.
        """
        self._require_play("release_item")
        await self._tick((_player_action(_RELEASE_USE_ITEM, (0, 0, 0), Face.DOWN, 0),))

    async def attack(self, entity: Entity) -> None:
        """Hit `entity` with the held item, in one client tick.

        The tick sends what the client sends when the attack key goes down on an entity
        (`Minecraft.startAttack`, `MultiPlayerGameMode.attack`): `attack` with the entity's id,
        then the swing (`punch`). One call is one tick (see `tick`).

        The client attacks with an item that has `piercing_weapon` (a spear) through another
        packet, and vanilla's server ignores an `attack` made with one, so such an attack does
        nothing on vanilla. Vanilla disconnects a player that attacks an item, an experience orb,
        an arrow or itself (`invalid_entity_attacked`), which no real client sends.

        Raises:
            ProtocolError: The Bot is not in play.
        """
        self._require_play("attack")
        await self._tick((("minecraft:attack", {"entity_id": entity.id}), _PUNCH))

    async def interact(
        self,
        entity: Entity,
        at: tuple[float, float, float] = (0.0, 0.0, 0.0),
        *,
        off_hand: bool = False,
    ) -> None:
        """Use the held item on `entity` (trade, shear, put on a saddle), in one client tick.

        `interact` with the entity's id, the main hand (or the off hand), where on the entity
        relative to its position (`at`, its feet by default), and whether the sneak key is held
        (`MultiPlayerGameMode.interact`). The client's swing for it sends nothing. A client that
        sees the use do nothing goes on (`Minecraft.startUseItem`): `use_item` with the same hand
        if it holds something, then the same with the off hand. The Bot cannot see that, so it
        sends `interact` only; a Group calls `use_item` itself. One call is one tick (see
        `tick`).

        Raises:
            ProtocolError: The Bot is not in play.
            ValueError: A coordinate of `at` is NaN or infinite; nothing is sent.
        """
        self._require_play("interact")
        if not all(math.isfinite(axis) for axis in at):
            msg = f"interact needs a finite location on the entity, not {at}"
            raise ValueError(msg)
        fields: dict[str, object] = {
            "entity_id": entity.id,
            "hand": _OFF_HAND if off_hand else _MAIN_HAND,
            "location": _lp_vec3(at),
            "sneaking": bool(self._controls.keys & _SNEAK),
        }
        await self._tick((("minecraft:interact", fields),))

    async def swing(self) -> None:
        """Swing the main hand, in one client tick: `punch`, as the client attacks or digs.

        Raises:
            ProtocolError: The Bot is not in play.
        """
        self._require_play("swing")
        await self._tick((_PUNCH,))

    def _require_play(self, operation: str) -> None:
        """Raise ProtocolError, naming `operation`, unless the Bot is in play."""
        if not self.in_play:
            msg = f"{operation} needs a Bot in play, not one in {self._connection.state}"
            raise ProtocolError(msg)

    async def sync(self) -> None:
        """Return once the server has sent everything caused by what it received before.

        The barrier of an Observation window. The Bot asks for its statistics
        (`client_command`, `REQUEST_STATS`) and takes packets until the answer
        (`award_stats`), `SYNC_REQUESTS` times. Vanilla handles every packet that has
        arrived in one pass at the start of a tick, before that tick sends what it
        changed, and a pass lasts under `TICK_GAP_S`. So the Bot sends each request only
        once `TICK_GAP_S` has passed since the last answer arrived: the request lands
        after that pass, its answer comes from a later tick, and by then the server has
        sent everything caused by what it had received. The proof is the wait, which a
        stall in the Bot's own loop can only lengthen. Every packet taken is recorded, and
        the Bot's Replies have already answered each
        (docs/research/2026-10-01-join-chunks.md). Two requests are the barrier; the
        third keeps it when one `award_stats` the server sent unasked is taken as an
        answer (#169). Two such `award_stats` in one sync can still end it a pass early.

        It covers what the server does in its packet pass and the tick after. A chat
        command is not run there (vanilla queues it as a server task, between ticks), so
        wait for a command's feedback before calling it, as `OperatorBot.run` does.

        Raises:
            ProtocolError: The Bot is not in play, or the server disconnected it.
            TimeoutError: The answers had not arrived within `timeout_s`.
        """
        if not self.in_play:
            msg = f"sync needs a Bot in play, not one in {self._connection.state}"
            raise ProtocolError(msg)
        async with self._operation(self._timeout_s):
            answered = await self._ask_for_statistics()
            for _ in range(SYNC_REQUESTS - 1):
                await self._wait_until(answered + round(TICK_GAP_S * 1e9))
                answered = await self._ask_for_statistics()

    async def _wait_until(self, t_ns: int) -> None:
        """Return once the Transcript's clock has reached `t_ns`."""
        transcript = self._connection.transcript
        while True:
            remaining_ns = t_ns - transcript.now_ns()
            if remaining_ns <= 0:
                return
            await asyncio.sleep(remaining_ns / 1e9)

    async def _ask_for_statistics(self) -> int:
        """Request the statistics, take packets until the answer, and return when it arrived.

        An `award_stats` stamped before the request was sent is not its answer (a server
        that answered twice, or sent one unasked): it is taken, passed over, and leaves
        the Mark `sync:passed-over <Bot name>`. The reader first catches up with what
        reached the socket, so one that arrived before the request is stamped before it,
        however busy the loop was.
        """
        transcript = self._connection.transcript
        await self._connection.caught_up()
        asked_ns = transcript.now_ns()

        def arrived_since_asked(_: Packet) -> bool:
            # `where` runs on the Packet `recv` just returned, so this is its arrival.
            arrived_ns = cast("int", self._connection.last_arrival_ns)
            if arrived_ns > asked_ns:
                return True
            label = f"{SYNC_PASSED_OVER} {self.name}"
            transcript.marks.append(Mark(t_ns=arrived_ns, label=label))
            return False

        await self._connection.send("minecraft:client_command", action=REQUEST_STATS)
        await self.expect(
            "minecraft:award_stats", timeout_s=self._timeout_s, where=arrived_since_asked
        )
        return cast("int", self._connection.last_arrival_ns)

    async def drain(self) -> None:
        """Take every packet that has already arrived, without waiting for another.

        Each is recorded, and the Bot's Replies have already answered it.

        Raises:
            CodecError: A frame the Bot took does not decode.
            ConnectionError: The Connection is closed, or the server closed or reset it,
                and nothing is left to take.
            ProtocolError: The server disconnected the Bot: a Group that tests a kick takes
                the disconnect itself, with `expect`.
        """
        try:
            while True:
                try:
                    packet = await self._connection.recv(timeout_s=0)
                except TimeoutError:
                    return
                self._refuse(packet)
        except Exception as error:
            self.failure = error
            raise

    async def refuse_queued_disconnect(self) -> None:
        """Take what has arrived (`drain`) if the server's disconnect is among it, untaken.

        A Group's end calls it before closing its Bots, so a disconnect nothing took still
        fails the Bot. It does nothing, and records nothing, if no such disconnect has
        reached the socket, or the Bot is closed or its `expect` returned the disconnect.

        Raises:
            ProtocolError: The server disconnected the Bot; the Bot's `failure`.
        """
        if self._closed or self._disconnected:
            return
        await self._connection.caught_up()
        if self._replies.saw_disconnect:
            await self.drain()

    async def close(self) -> None:
        """Close the Bot's Connection. Calling it again does nothing."""
        self._closed = True
        await self._connection.close()

    @contextlib.asynccontextmanager
    async def _operation(self, timeout_s: float) -> AsyncIterator[None]:
        """Bound an operation by `timeout_s`, and keep what it raises as `failure`."""
        try:
            async with asyncio.timeout(timeout_s):
                yield
        except Exception as error:
            self.failure = error
            raise

    async def _handshake_for_status(self) -> None:
        if self._connection.state is State.HANDSHAKE:
            await self._handshake(_STATUS_INTENT)

    async def _handshake(self, intent: int) -> None:
        await self._connection.send(
            "minecraft:intention",
            protocol_version=self._target.protocol_version,
            server_address=self._endpoint.host,
            server_port=self._endpoint.port,
            intent=intent,
        )

    def _refuse(self, packet: Packet) -> None:
        """Raise ProtocolError if `packet` ends the Bot's session: a disconnect, or encryption."""
        match packet.state, packet.name:
            case State.LOGIN, "minecraft:login_disconnect":
                reason: object = packet.payload
            case State.CONFIGURATION | State.PLAY, "minecraft:disconnect":
                reason = (packet.fields or {}).get("reason")
            case State.LOGIN, "minecraft:hello":
                msg = f"the server asks for encryption (online mode), and {self.name} is offline"
                raise ProtocolError(msg)
            case _:
                return
        msg = f"the server disconnected {self.name} in {packet.state}: {reason!r}"
        raise ProtocolError(msg)


def status_probe(
    target: Target, *, timeout_s: float = PROBE_TIMEOUT_S
) -> Callable[[Endpoint], Awaitable[bool]]:
    """Return a readiness probe for an Instance of `target`, for `runner.running`.

    Each call makes one short status exchange with the Endpoint. It returns True if
    the server answers with the Target's protocol version. It returns False if the
    Instance is not ready yet: the connection is refused, reset or closed, or there is
    no answer within `timeout_s` seconds. Anything else raises, because a server that
    answers wrongly is the wrong server, not a server still starting.

    The probe raises:
        ProtocolError: The status names another protocol version, or none.
        CodecError: The answer cannot be decoded.
    """

    async def probe(endpoint: Endpoint) -> bool:
        transcript = Transcript(group_id="readiness", server="")  # discarded
        try:
            bot = await Bot.connect(
                endpoint, target, name="probe", transcript=transcript, timeout_s=timeout_s
            )
        except (ConnectionError, TimeoutError):
            return False
        try:
            status = await bot.status()
        except (ConnectionError, TimeoutError):
            return False
        finally:
            await bot.close()
        version = _json_field(status, "version")
        protocol = _json_field(version, "protocol")
        if isinstance(protocol, bool) or not isinstance(protocol, int):
            msg = f"status has no integer version.protocol: {status!r}"
            raise ProtocolError(msg)
        if protocol != target.protocol_version:
            msg = (
                f"the server at {endpoint.host}:{endpoint.port} speaks protocol {protocol} "
                f"({_json_field(version, 'name')!r}), not the Target's {target.protocol_version}"
            )
            raise ProtocolError(msg)
        return True

    return probe


def _held(keys: int, key: int, *, held: bool) -> int:
    """`keys` with `key` held or released."""
    return keys | key if held else keys & ~key


def _field[T](fields: Mapping[str, object], name: str, kind: type[T]) -> T:
    """`fields[name]`, which the packet's schema guarantees is a `kind`."""
    value = fields.get(name)
    if not isinstance(value, kind):
        msg = f"expected a {kind.__name__} {name}, got {value!r}"
        raise ProtocolError(msg)
    return value


def _json_field(value: object, key: str) -> object:
    """Return `value[key]` if `value` is a JSON object holding `key`, else None."""
    if not isinstance(value, Mapping):
        return None
    return {str(name): item for name, item in value.items()}.get(key)


def _ends_the_session(packet: Packet) -> bool:
    """Whether `packet` is the server's disconnect, after which it closes the connection."""
    match packet.state, packet.name:
        case (State.LOGIN, "minecraft:login_disconnect") | (
            State.CONFIGURATION | State.PLAY,
            "minecraft:disconnect",
        ):
            return True
        case _:
            return False


def _expect(packet: Packet, name: str) -> None:
    if packet.name != name:
        msg = f"expected {name}, got {packet.name}"
        raise ProtocolError(msg)


def _json_object(packet: Packet, text: object) -> dict[str, object]:
    where = f"{packet.name.removeprefix('minecraft:')} json_response"
    if not isinstance(text, str):
        msg = f"{where} is not a string"
        raise ProtocolError(msg)
    try:
        value: object = json.loads(text)
    except (ValueError, RecursionError) as exc:  # a JSONDecodeError is a ValueError (audit H3)
        msg = f"{where} is not JSON: {exc}"
        raise ProtocolError(msg) from exc
    if not isinstance(value, dict):
        msg = f"{where} is not a JSON object"
        raise ProtocolError(msg)
    return {str(key): item for key, item in value.items()}
