"""Bot block actions: each call is one scripted client tick, sending what the vanilla client would.

The rules are `Minecraft.tick`, `startAttack`, `continueAttack` and `MultiPlayerGameMode`
(26.3 client, javap): the held slot if it changed (`ensureHasSentCarriedItem`), then the action,
then the movement packets, then `client_tick_end`. Each action the client predicts (start or
finish digging, use an item on a block, use an item) carries the next block-change sequence
number (`BlockStatePredictionHandler.startPredicting`); cancelling and releasing carry 0.
"""

from collections.abc import Awaitable, Callable, Mapping

import pytest

from mscts.bot import Bot, Face
from mscts.net import ProtocolError
from mscts.transcript import Transcript
from tests.net.fakes import SPAWN, status_server, with_bot
from tests.net.test_bot_move import (
    CODEC,
    LOGIN,
    RESPAWN,
    TICK_END,
    TICK_PACKETS,
    Sent,
    joined,
    ticks_sent,
)

ACTION_PACKETS = frozenset(
    {
        "minecraft:set_carried_item",
        "minecraft:player_action",
        "minecraft:use_item_on",
        "minecraft:use_item",
        "minecraft:punch",
    }
)
NAMES = TICK_PACKETS | ACTION_PACKETS

START, ABORT, STOP, RELEASE = 0, 2, 3, 6
BLOCK = {"x": 3, "y": -61, "z": -2}
ORIGIN = {"x": 0, "y": 0, "z": 0}
PUNCH = ("minecraft:punch", {})


def acts(
    script: Callable[[Bot], Awaitable[None]],
    *,
    after_first_tick: tuple[str, Mapping[str, object]] | None = None,
) -> list[Sent]:
    """What `script` sent, tick by tick, after a first tick that reports the join pose."""

    async def after_a_tick(bot: Bot) -> None:
        await bot.tick()
        await script(bot)

    return ticks_sent(joined(after_a_tick, after_first_tick=after_first_tick), NAMES)[1:]


def action(kind: int, pos: Mapping[str, int], face: int, sequence: int) -> tuple[str, object]:
    fields = {"action": kind, "pos": pos, "face": face, "sequence": sequence}
    return ("minecraft:player_action", fields)


def test_dig_starts_breaking_and_swings_with_the_next_sequence() -> None:
    # startAttack: startDestroyBlock sends START, predicted, then the swing sends punch.
    async def script(bot: Bot) -> None:
        await bot.dig(3, -61, -2, Face.UP)

    assert acts(script) == [[action(START, BLOCK, 1, 1), PUNCH, TICK_END]]


def test_stop_digging_finishes_breaking_and_swings_with_the_next_sequence() -> None:
    # continueDestroyBlock's last tick: STOP, predicted, then continueAttack swings.
    async def script(bot: Bot) -> None:
        await bot.dig(3, -61, -2, Face.NORTH)
        await bot.stop_digging(3, -61, -2, Face.NORTH)

    assert acts(script) == [
        [action(START, BLOCK, 2, 1), PUNCH, TICK_END],
        [action(STOP, BLOCK, 2, 2), PUNCH, TICK_END],
    ]


def test_cancel_digging_aborts_facing_down_with_sequence_0() -> None:
    # stopDestroyBlock, when the attack key is let go: ABORT, face down, not predicted.
    async def script(bot: Bot) -> None:
        await bot.dig(3, -61, -2, Face.EAST)
        await bot.cancel_digging(3, -61, -2)
        await bot.dig(3, -61, -2, Face.EAST)

    assert acts(script) == [
        [action(START, BLOCK, 5, 1), PUNCH, TICK_END],
        [action(ABORT, BLOCK, 0, 0), TICK_END],
        [action(START, BLOCK, 5, 2), PUNCH, TICK_END],
    ]


def test_place_uses_the_held_item_on_a_block_face() -> None:
    async def script(bot: Bot) -> None:
        await bot.place(3, -61, -2, Face.UP)
        await bot.place(3, -61, -2, Face.SOUTH, cursor=(0.25, 1.0, 0.75), off_hand=True)

    hit = {"pos": BLOCK, "inside_block": False, "world_border_hit": False}
    middle = {"cursor_x": 0.5, "cursor_y": 0.5, "cursor_z": 0.5}
    given = {"cursor_x": 0.25, "cursor_y": 1.0, "cursor_z": 0.75}
    assert acts(script) == [
        [
            ("minecraft:use_item_on", {"hand": 0, **hit, "face": 1, **middle, "sequence": 1}),
            TICK_END,
        ],
        [
            ("minecraft:use_item_on", {"hand": 1, **hit, "face": 3, **given, "sequence": 2}),
            TICK_END,
        ],
    ]


def test_use_item_uses_the_held_item_facing_where_the_player_faces() -> None:
    # useItem sends the player's yaw and pitch; releaseUsingItem RELEASE_USE_ITEM at the
    # origin, face down, not predicted.
    async def script(bot: Bot) -> None:
        await bot.use_item()
        await bot.release_item()
        await bot.use_item(off_hand=True)

    rotation = {"yaw": SPAWN["yaw"], "pitch": SPAWN["pitch"]}
    assert acts(script) == [
        [("minecraft:use_item", {"hand": 0, "sequence": 1, **rotation}), TICK_END],
        [action(RELEASE, ORIGIN, 0, 0), TICK_END],
        [("minecraft:use_item", {"hand": 1, "sequence": 2, **rotation}), TICK_END],
    ]


def test_swing_punches() -> None:
    async def script(bot: Bot) -> None:
        await bot.swing()

    assert acts(script) == [[PUNCH, TICK_END]]


def test_hold_sends_a_slot_only_when_it_changed() -> None:
    # ensureHasSentCarriedItem sends the selected slot only when it differs from the one
    # last sent; the keys go in their own tick (LocalPlayer.sendChanges).
    async def script(bot: Bot) -> None:
        await bot.hold(4)
        await bot.sneak(sneaking=True)
        await bot.hold(4)

    assert acts(script) == [
        [("minecraft:set_carried_item", {"slot": 4}), TICK_END],
        [("minecraft:player_input", {"flags": 0x20}), TICK_END],
        [TICK_END],
    ]


def test_an_action_after_hold_sends_no_slot_again() -> None:
    async def script(bot: Bot) -> None:
        await bot.hold(2)
        await bot.hold(0)
        await bot.use_item()

    rotation = {"yaw": SPAWN["yaw"], "pitch": SPAWN["pitch"]}
    assert acts(script) == [
        [("minecraft:set_carried_item", {"slot": 2}), TICK_END],
        [("minecraft:set_carried_item", {"slot": 0}), TICK_END],
        [("minecraft:use_item", {"hand": 0, "sequence": 1, **rotation}), TICK_END],
    ]


def test_the_held_slot_goes_before_the_action_in_the_same_tick() -> None:
    # Minecraft.tick: gameMode.tick sends the held slot (ensureHasSentCarriedItem), then
    # handleKeybinds the action, then client_tick_end.
    async def script(bot: Bot) -> None:
        await bot.sync()
        await bot.place(3, -61, -2, Face.UP)

    ticks = acts(script, after_first_tick=("minecraft:set_held_slot", {"slot": 5}))
    middle = {"cursor_x": 0.5, "cursor_y": 0.5, "cursor_z": 0.5}
    hit = {"pos": BLOCK, "face": 1, **middle, "inside_block": False, "world_border_hit": False}
    assert ticks == [
        [
            ("minecraft:set_carried_item", {"slot": 5}),
            ("minecraft:use_item_on", {"hand": 0, **hit, "sequence": 1}),
            TICK_END,
        ]
    ]


def test_a_slot_the_server_selects_is_sent_back_on_the_next_tick() -> None:
    # handleSetHeldSlot selects the slot but leaves carriedIndex, so the next tick's
    # ensureHasSentCarriedItem sends it back.
    async def script(bot: Bot) -> None:
        await bot.sync()
        await bot.tick()
        await bot.hold(5)

    ticks = acts(script, after_first_tick=("minecraft:set_held_slot", {"slot": 5}))
    assert ticks == [[("minecraft:set_carried_item", {"slot": 5}), TICK_END], [TICK_END]]


@pytest.mark.parametrize("slot", [-1, 9])
def test_a_slot_outside_the_hotbar_from_the_server_is_ignored(slot: int) -> None:
    async def script(bot: Bot) -> None:
        await bot.sync()
        await bot.tick()

    ticks = acts(script, after_first_tick=("minecraft:set_held_slot", {"slot": slot}))
    assert ticks == [[TICK_END]]


@pytest.mark.parametrize("slot", [-1, 9])
def test_hold_refuses_a_slot_outside_the_hotbar(slot: int) -> None:
    async def script(bot: Bot) -> None:
        with pytest.raises(ValueError, match="hold needs a hotbar slot from 0 to 8"):
            await bot.hold(slot)

    assert acts(script) == []


@pytest.mark.parametrize(
    ("fresh", "sequence"),
    [
        (("minecraft:login", LOGIN), 1),
        (
            (
                "minecraft:respawn",
                {**RESPAWN, "dimension_name": "minecraft:the_end", "data_kept": 0},
            ),
            1,
        ),
        (("minecraft:respawn", {**RESPAWN, "data_kept": 0}), 2),
    ],
    ids=["login", "respawn-elsewhere", "respawn-here"],
)
def test_the_sequence_starts_again_with_a_new_level(
    fresh: tuple[str, Mapping[str, object]], sequence: int
) -> None:
    # The counter belongs to the ClientLevel: a new one comes with each play login, and with
    # a respawn into another dimension (ClientPacketListener.handleRespawn).
    async def script(bot: Bot) -> None:
        await bot.use_item()
        await bot.sync()
        await bot.use_item()

    def first_sequence_after(ticks: list[Sent]) -> object:
        packet = next(packet for packet in ticks[-1] if packet[0] == "minecraft:use_item")
        fields = packet[1]
        assert fields is not None
        return fields["sequence"]

    ticks = ticks_sent(joined(script, after_first_tick=fresh), NAMES)
    assert first_sequence_after(ticks) == sequence


def test_a_login_starts_the_held_slots_again() -> None:
    # A play login brings a new MultiPlayerGameMode (carriedIndex 0) and a new LocalPlayer
    # (slot 0 selected), so holding the old slot again sends it again.
    async def script(bot: Bot) -> None:
        await bot.hold(3)
        await bot.sync()
        await bot.hold(3)

    ticks = ticks_sent(joined(script, after_first_tick=("minecraft:login", LOGIN)), NAMES)
    # First in the tick: the fresh player's pose follows it.
    assert ticks[-1][0] == ("minecraft:set_carried_item", {"slot": 3})


ACTIONS: list[tuple[str, Callable[[Bot], Awaitable[None]]]] = [
    ("hold", lambda bot: bot.hold(1)),
    ("dig", lambda bot: bot.dig(0, 0, 0, Face.UP)),
    ("stop_digging", lambda bot: bot.stop_digging(0, 0, 0, Face.UP)),
    ("cancel_digging", lambda bot: bot.cancel_digging(0, 0, 0)),
    ("place", lambda bot: bot.place(0, 0, 0, Face.UP)),
    ("use_item", lambda bot: bot.use_item()),
    ("release_item", lambda bot: bot.release_item()),
    ("swing", lambda bot: bot.swing()),
]


@pytest.mark.parametrize(("name", "call"), ACTIONS, ids=[name for name, _ in ACTIONS])
def test_acting_refuses_a_bot_that_is_not_in_play(
    name: str, call: Callable[[Bot], Awaitable[None]]
) -> None:
    transcript = Transcript(group_id="test/blocks", server="fake")

    async def use(bot: Bot) -> None:
        with pytest.raises(
            ProtocolError, match=f"{name} needs a Bot in play, not one in handshake"
        ):
            await call(bot)

    with_bot(CODEC, transcript, status_server("{}", []), use)
    assert transcript.events == []
