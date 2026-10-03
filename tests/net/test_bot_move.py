"""Bot movement: each call is one scripted client tick, sending what the vanilla client would.

The rules are `LocalPlayer.sendChanges` and `sendPosition`, and `Minecraft.tick` (26.3 client,
javap): the Input if it changed, then a sprint command if sprinting changed, then the movement
packet the change calls for (if any), then `client_tick_end`.
"""

import dataclasses
import math
from collections.abc import Awaitable, Callable, Mapping

import pytest

from mscts.bot import Bot, Position
from mscts.codec.packets import Codec, Packet
from mscts.net import Connection, ConnectionClosedError, ProtocolError
from mscts.target import TARGET
from mscts.transcript import Transcript
from tests.net.fakes import (
    SPAWN,
    Handler,
    JoinScript,
    Peer,
    answer_each_tick,
    join_server,
    status_server,
    with_bot,
)

CODEC = Codec.for_target(TARGET)

ENTITY_ID = 300

LOGIN = {
    "entity_id": ENTITY_ID,
    "is_hardcore": False,
    "dimension_names": ["minecraft:overworld"],
    "max_players": 20,
    "view_distance": 10,
    "simulation_distance": 10,
    "reduced_debug_info": False,
    "enable_respawn_screen": True,
    "do_limited_crafting": False,
    "dimension_type": 0,
    "dimension_name": "minecraft:overworld",
    "hashed_seed": 0,
    "game_mode": 0,
    "previous_game_mode": 0,
    "is_debug": False,
    "is_flat": True,
    "death_location": None,
    "portal_cooldown": 0,
    "sea_level": 63,
    "online_mode": False,
    "enforces_secure_chat": False,
}
"""A play `login` naming the player's entity id, which a sprint command carries."""

TICK_PACKETS = frozenset(
    {
        "minecraft:player_input",
        "minecraft:player_command",
        "minecraft:move_player_pos",
        "minecraft:move_player_pos_rot",
        "minecraft:move_player_rot",
        "minecraft:move_player_status_only",
        "minecraft:client_tick_end",
    }
)

TICK_END = ("minecraft:client_tick_end", {})
ON_GROUND = 0x01
SPAWN_POSITION = {key: SPAWN[key] for key in ("x", "y", "z")}
SPAWN_ROTATION = {key: SPAWN[key] for key in ("yaw", "pitch")}

type Sent = list[tuple[str, Mapping[str, object] | None]]


def moving_server(
    seen: list[Packet],
    *,
    login: bool = True,
    teleport_to: Mapping[str, float] | None = None,
    correct_to: Mapping[str, float] | None = None,
    after_first_tick: tuple[str, Mapping[str, object]] | None = None,
) -> Handler:
    """Join like vanilla, then answer statistics requests a tick apart, as `play_server` does.

    With `login`, the `login` naming the player's entity id comes with the first chunk batch
    (vanilla sends it before the join teleport; the Bot only needs it before it sprints).
    With `teleport_to`, a teleport there follows the Bot's `player_loaded`.
    With `correct_to`, the first position the Bot sends is answered with an absolute
    `player_position` to that place, as vanilla corrects a move it refuses.
    With `after_first_tick`, that packet answers the Bot's first `client_tick_end`.
    """

    async def then(peer: Peer) -> None:
        requests = 0
        corrected = correct_to is None
        ticked = False
        if teleport_to is not None:
            await peer.send("minecraft:player_position", **_teleport(teleport_to))
        async for packet in peer.packets():
            seen.append(packet)
            if packet.name == "minecraft:client_command":
                requests += 1
                await answer_each_tick(peer, requests)
            elif not corrected and packet.name == "minecraft:move_player_pos":
                corrected = True
                await peer.send("minecraft:player_position", **_teleport(correct_to or {}))
            elif not ticked and packet.name == "minecraft:client_tick_end":
                ticked = True
                if after_first_tick is not None:
                    await peer.send(after_first_tick[0], **after_first_tick[1])

    def login_frame(peer: Peer) -> bytes:
        return peer.frame("minecraft:login", **LOGIN) if login else b""

    return join_server(seen, JoinScript(after_batch=login_frame, then=then))


def _teleport(position: Mapping[str, float]) -> dict[str, object]:
    return {
        "teleport_id": 2,
        "velocity_x": 0.0,
        "velocity_y": 0.0,
        "velocity_z": 0.0,
        "flags": 0,
        **SPAWN,
        **position,
    }


def ticks_sent(seen: list[Packet]) -> list[Sent]:
    """What the Bot sent after joining, split into client ticks."""
    ticks: list[Sent] = [[]]
    for packet in seen:
        if packet.name in TICK_PACKETS:
            ticks[-1].append((packet.name, packet.fields))
            if packet.name == "minecraft:client_tick_end":
                ticks.append([])
    return ticks[:-1]


def play(
    script: Callable[[Bot], Awaitable[None]],
    *,
    login: bool = True,
    teleport_to: Mapping[str, float] | None = None,
    correct_to: Mapping[str, float] | None = None,
    after_first_tick: tuple[str, Mapping[str, object]] | None = None,
) -> list[Sent]:
    """Join a Bot on `moving_server`, run `script`, then wait until the server has read it."""
    seen: list[Packet] = []

    async def use(bot: Bot) -> None:
        await bot.join()
        await script(bot)
        await bot.sync()

    handler = moving_server(
        seen,
        login=login,
        teleport_to=teleport_to,
        correct_to=correct_to,
        after_first_tick=after_first_tick,
    )
    with_bot(CODEC, Transcript(group_id="test/move", server="fake"), handler, use)
    return ticks_sent(seen)


def pos(
    x: float, y: float, z: float, *, flags: int = ON_GROUND
) -> tuple[str, Mapping[str, object]]:
    return ("minecraft:move_player_pos", {"x": x, "y": y, "z": z, "flags": flags})


def test_the_first_tick_reports_the_pose_the_join_set() -> None:
    # A fresh LocalPlayer last reported nothing: x, y, z, yaw and pitch of 0.
    async def script(bot: Bot) -> None:
        await bot.tick()

    rotated = {**SPAWN_POSITION, **SPAWN_ROTATION, "flags": ON_GROUND}
    assert play(script) == [[("minecraft:move_player_pos_rot", rotated), TICK_END]]


def test_a_tick_with_nothing_changed_sends_only_its_end() -> None:
    async def script(bot: Bot) -> None:
        await bot.tick()
        await bot.tick()

    assert play(script)[1:] == [[TICK_END]]


def test_the_position_is_reported_again_on_the_20th_tick_without_a_change() -> None:
    async def script(bot: Bot) -> None:
        for _ in range(21):
            await bot.tick()

    ticks = play(script)
    assert ticks[1:20] == [[TICK_END]] * 19
    assert ticks[20] == [pos(SPAWN["x"], SPAWN["y"], SPAWN["z"]), TICK_END]


def test_move_reports_the_position_alone_when_the_rotation_is_unchanged() -> None:
    async def script(bot: Bot) -> None:
        await bot.tick()
        await bot.move(6.7, -60.0, 7.5)

    assert play(script)[1:] == [[pos(6.7, -60.0, 7.5), TICK_END]]


def test_a_move_no_longer_than_the_threshold_is_not_reported() -> None:
    # sendPosition reports a move longer than 2.0E-4 blocks (strictly), along any axis.
    async def script(bot: Bot) -> None:
        await bot.move(0.0, 0.0, 0.0)
        await bot.look(0.0, 0.0)
        await bot.move(2.0e-4, 0.0, 0.0)
        await bot.move(0.0, 0.0, 2.1e-4)
        await bot.move(0.0, 2.1e-4, 2.1e-4)

    ticks = play(script)
    assert ticks[2:] == [
        [TICK_END],
        [pos(0.0, 0.0, 2.1e-4), TICK_END],
        [pos(0.0, 2.1e-4, 2.1e-4), TICK_END],
    ]


def test_a_fresh_client_last_reported_itself_off_the_ground() -> None:
    # A player put at the origin facing yaw 0 and pitch 0 has nothing to report on its first
    # tick but its feet: LocalPlayer.lastOnGround starts false.
    async def script(bot: Bot) -> None:
        await bot.sync()  # the teleport has arrived
        await bot.tick()

    origin = {"x": 0.0, "y": 0.0, "z": 0.0, "yaw": 0.0, "pitch": 0.0}
    status = ("minecraft:move_player_status_only", {"flags": ON_GROUND})
    assert play(script, teleport_to=origin) == [[status, TICK_END]]


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_move_refuses_a_coordinate_that_is_not_finite(bad: float) -> None:
    # No client can be at one, and vanilla kicks a move to one: nothing is sent or changed.
    positions: list[Position] = []

    async def script(bot: Bot) -> None:
        await bot.tick()
        with pytest.raises(ValueError, match="move needs finite coordinates"):
            await bot.move(1.0, bad, 3.0)
        positions.append(bot.position)
        await bot.tick()

    assert play(script)[1:] == [[TICK_END]]
    assert positions == [Position(**SPAWN_POSITION, **SPAWN_ROTATION)]


def test_a_move_off_the_ground_says_so_in_the_flags() -> None:
    async def script(bot: Bot) -> None:
        await bot.tick()
        await bot.move(6.5, -59.5, 7.5, on_ground=False)

    assert play(script)[1:] == [[pos(6.5, -59.5, 7.5, flags=0), TICK_END]]


def test_landing_without_moving_sends_the_flags_alone() -> None:
    async def script(bot: Bot) -> None:
        await bot.move(6.5, -59.5, 7.5, on_ground=False)
        await bot.move(6.5, -59.5, 7.5, on_ground=True)
        await bot.tick()

    status = ("minecraft:move_player_status_only", {"flags": ON_GROUND})
    assert play(script)[1:] == [[status, TICK_END], [TICK_END]]


def test_look_reports_the_rotation_alone() -> None:
    async def script(bot: Bot) -> None:
        await bot.tick()
        await bot.look(10.0, 20.0)

    rot = ("minecraft:move_player_rot", {"yaw": 10.0, "pitch": 20.0, "flags": ON_GROUND})
    assert play(script)[1:] == [[rot, TICK_END]]


def test_look_turns_as_the_client_does() -> None:
    # Rotations are floats, and pitch is held to -90..90 (Entity.setXRot, javap).
    async def script(bot: Bot) -> None:
        await bot.tick()
        await bot.look(0.1, 100.0)
        await bot.look(0.1, -91.0)

    tenth = 0.10000000149011612  # 0.1f
    ticks = play(script)
    assert ticks[1:] == [
        [("minecraft:move_player_rot", {"yaw": tenth, "pitch": 90.0, "flags": 1}), TICK_END],
        [("minecraft:move_player_rot", {"yaw": tenth, "pitch": -90.0, "flags": 1}), TICK_END],
    ]


def test_sneak_sends_the_input_with_the_sneak_key_held_then_released() -> None:
    async def script(bot: Bot) -> None:
        await bot.tick()
        await bot.sneak(sneaking=True)
        await bot.tick()
        await bot.sneak(sneaking=False)

    assert play(script)[1:] == [
        [("minecraft:player_input", {"flags": 0x20}), TICK_END],
        [TICK_END],
        [("minecraft:player_input", {"flags": 0x00}), TICK_END],
    ]


def test_sprint_sends_the_input_then_the_command_then_the_movement() -> None:
    async def script(bot: Bot) -> None:
        await bot.sprint(sprinting=True)
        await bot.sprint(sprinting=False)

    start = {"entity_id": ENTITY_ID, "action": 1, "jump_boost": 0}
    stop = {"entity_id": ENTITY_ID, "action": 2, "jump_boost": 0}
    rotated = {**SPAWN_POSITION, **SPAWN_ROTATION, "flags": ON_GROUND}
    assert play(script) == [
        [
            ("minecraft:player_input", {"flags": 0x41}),  # forward and sprint
            ("minecraft:player_command", start),
            ("minecraft:move_player_pos_rot", rotated),
            TICK_END,
        ],
        [
            ("minecraft:player_input", {"flags": 0x00}),
            ("minecraft:player_command", stop),
            TICK_END,
        ],
    ]


def test_sprint_holds_forward_as_a_sprinting_client_must() -> None:
    # LocalPlayer.canStartSprinting needs a forward impulse, and shouldStopRunSprinting stops
    # sprinting once it goes (26.3 javap): no client sprints without holding forward.
    async def script(bot: Bot) -> None:
        await bot.tick()
        await bot.sprint(sprinting=True)
        await bot.sprint(sprinting=True)
        await bot.sneak(sneaking=True)
        await bot.sneak(sneaking=False)

    ticks = play(script)
    assert ticks[1][0] == ("minecraft:player_input", {"flags": 0x41})
    assert ticks[2:] == [
        [TICK_END],
        [("minecraft:player_input", {"flags": 0x61}), TICK_END],  # sneaking stops no sprint
        [("minecraft:player_input", {"flags": 0x41}), TICK_END],
    ]


def test_sprint_refuses_a_sneaking_player() -> None:
    # canStartSprinting refuses while isMovingSlowly, which crouching is (26.3 javap).
    async def script(bot: Bot) -> None:
        await bot.tick()
        await bot.sneak(sneaking=True)
        with pytest.raises(ProtocolError, match="sprint needs a player that is not sneaking"):
            await bot.sprint(sprinting=True)
        await bot.tick()

    assert play(script)[1:] == [[("minecraft:player_input", {"flags": 0x20}), TICK_END], [TICK_END]]


def test_sprint_refuses_before_the_server_named_the_player() -> None:
    async def script(bot: Bot) -> None:
        with pytest.raises(ProtocolError, match="sprint needs the player's entity id"):
            await bot.sprint(sprinting=True)
        await bot.tick()

    rotated = {**SPAWN_POSITION, **SPAWN_ROTATION, "flags": ON_GROUND}
    assert play(script, login=False) == [[("minecraft:move_player_pos_rot", rotated), TICK_END]]


def test_jump_holds_the_jump_key_for_one_tick() -> None:
    # The next call releases it; two jumps in a row hold it for two ticks.
    async def script(bot: Bot) -> None:
        await bot.tick()
        await bot.jump()
        await bot.move(6.5, -59.5, 7.5, on_ground=False)
        await bot.jump()
        await bot.jump()
        await bot.tick()

    jump = ("minecraft:player_input", {"flags": 0x10})
    release = ("minecraft:player_input", {"flags": 0x00})
    assert play(script)[1:] == [
        [jump, TICK_END],
        [release, pos(6.5, -59.5, 7.5, flags=0), TICK_END],
        [jump, TICK_END],
        [TICK_END],
        [release, TICK_END],
    ]


def test_position_is_where_the_bot_last_moved_and_looked() -> None:
    positions: list[Position] = []

    async def script(bot: Bot) -> None:
        positions.append(bot.position)
        await bot.move(1.0, 2.0, 3.0)
        await bot.look(45.0, -10.0)
        positions.append(bot.position)

    play(script)
    assert positions == [
        Position(**SPAWN_POSITION, **SPAWN_ROTATION),
        Position(x=1.0, y=2.0, z=3.0, yaw=45.0, pitch=-10.0),
    ]


def test_position_is_read_only() -> None:
    position = Position(x=1.0, y=2.0, z=3.0, yaw=0.0, pitch=0.0)
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(position, "x", 5.0)  # noqa: B010 - a frozen field, set by name


def test_a_correction_moves_the_bot_and_the_next_tick_reports_where_it_is() -> None:
    # Vanilla answers a refused move with player_position. The client takes the pose and
    # confirms it, but its last reported position stays the refused one
    # (ClientPacketListener.handleMovePlayer, javap), so its next tick reports the new one.
    positions: list[Position] = []

    async def script(bot: Bot) -> None:
        await bot.tick()
        await bot.move(30.0, -60.0, 7.5)
        await bot.sync()
        positions.append(bot.position)
        await bot.tick()

    ticks = play(script, correct_to={"x": 6.0, "z": 7.0})
    assert positions == [Position(x=6.0, y=-60.0, z=7.0, **SPAWN_ROTATION)]
    assert ticks[1:] == [[pos(30.0, -60.0, 7.5), TICK_END], [pos(6.0, -60.0, 7.0), TICK_END]]


def test_a_tick_that_failed_to_send_is_not_taken_as_reported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The client keeps what it last reported only once it has sent it: a move whose packet
    # never went is reported again by the next tick.
    send = Connection.send
    failed: list[str] = []

    async def fail_the_first_move(self: Connection, name: str, /, **fields: object) -> None:
        if name == "minecraft:move_player_pos" and not failed:
            failed.append(name)
            msg = "lost"
            raise ConnectionClosedError(msg)
        await send(self, name, **fields)

    async def script(bot: Bot) -> None:
        await bot.tick()
        monkeypatch.setattr(Connection, "send", fail_the_first_move)
        with pytest.raises(ConnectionClosedError):
            await bot.move(6.7, -60.0, 7.5)
        await bot.tick()

    assert play(script)[1:] == [[pos(6.7, -60.0, 7.5), TICK_END]]


RESPAWN = {
    key: LOGIN[key]
    for key in (
        "dimension_type",
        "dimension_name",
        "hashed_seed",
        "game_mode",
        "previous_game_mode",
        "is_debug",
        "is_flat",
        "death_location",
        "portal_cooldown",
        "sea_level",
    )
}
KEEP_ENTITY_DATA = 0x02
SPRINT_START = [
    ("minecraft:player_input", {"flags": 0x41}),
    ("minecraft:player_command", {"entity_id": ENTITY_ID, "action": 1, "jump_boost": 0}),
    ("minecraft:move_player_pos_rot", {**SPAWN_POSITION, **SPAWN_ROTATION, "flags": ON_GROUND}),
    TICK_END,
]


async def sprint_then_tick(bot: Bot) -> None:
    await bot.sprint(sprinting=True)
    await bot.sync()  # what answered the first tick has arrived
    await bot.tick()


@pytest.mark.parametrize(
    "fresh_player",
    [("minecraft:login", LOGIN), ("minecraft:respawn", {**RESPAWN, "data_kept": 0})],
    ids=["login", "respawn"],
)
def test_a_fresh_player_has_reported_nothing(
    fresh_player: tuple[str, Mapping[str, object]],
) -> None:
    # A second play login, or a respawn, makes a new LocalPlayer (ClientPacketListener
    # handleLogin, handleRespawn; 26.3 javap): it last reported a pose of 0, off the ground,
    # no keys and not sprinting, so its next tick reports everything again.
    assert play(sprint_then_tick, after_first_tick=fresh_player) == [SPRINT_START, SPRINT_START]


def test_a_respawn_that_keeps_entity_data_keeps_the_keys_and_the_sprint() -> None:
    # With KEEP_ENTITY_DATA, the new player takes the old one's last sent input and
    # sprinting; its position and rotation are still a fresh player's.
    kept = ("minecraft:respawn", {**RESPAWN, "data_kept": KEEP_ENTITY_DATA})
    assert play(sprint_then_tick, after_first_tick=kept) == [SPRINT_START, SPRINT_START[2:]]


MOVES: list[tuple[str, Callable[[Bot], Awaitable[None]]]] = [
    ("move", lambda bot: bot.move(1.0, 2.0, 3.0)),
    ("look", lambda bot: bot.look(1.0, 2.0)),
    ("sprint", lambda bot: bot.sprint(sprinting=True)),
    ("sneak", lambda bot: bot.sneak(sneaking=True)),
    ("jump", lambda bot: bot.jump()),
    ("tick", lambda bot: bot.tick()),
]


@pytest.mark.parametrize(("name", "call"), MOVES, ids=[name for name, _ in MOVES])
def test_moving_refuses_a_bot_that_is_not_in_play(
    name: str, call: Callable[[Bot], Awaitable[None]]
) -> None:
    transcript = Transcript(group_id="test/move", server="fake")

    async def use(bot: Bot) -> None:
        with pytest.raises(
            ProtocolError, match=f"{name} needs a Bot in play, not one in handshake"
        ):
            await call(bot)
        assert bot.position == Position(x=0.0, y=0.0, z=0.0, yaw=0.0, pitch=0.0)

    with_bot(CODEC, transcript, status_server("{}", []), use)
    assert transcript.events == []
