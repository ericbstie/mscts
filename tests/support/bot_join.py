"""A fake server a Bot joins and ticks against, and what the Bot sends while it does."""

from collections.abc import Awaitable, Callable, Mapping

from mscts.bot import Bot
from mscts.codec.packets import Codec, Packet
from mscts.target import TARGET
from mscts.transcript import Transcript
from tests.net.fakes import (
    SPAWN,
    Handler,
    JoinScript,
    Peer,
    answer_each_tick,
    join_server,
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


def ticks_sent(seen: list[Packet], names: frozenset[str] = TICK_PACKETS) -> list[Sent]:
    """What the Bot sent after joining among `names`, split into client ticks."""
    ticks: list[Sent] = [[]]
    for packet in seen:
        if packet.name in names:
            ticks[-1].append((packet.name, packet.fields))
            if packet.name == "minecraft:client_tick_end":
                ticks.append([])
    return ticks[:-1]


def joined(
    script: Callable[[Bot], Awaitable[None]],
    *,
    login: bool = True,
    teleport_to: Mapping[str, float] | None = None,
    correct_to: Mapping[str, float] | None = None,
    after_first_tick: tuple[str, Mapping[str, object]] | None = None,
) -> list[Packet]:
    """Join a Bot on `moving_server`, run `script`, wait until the server has read it.

    Returns every packet the server read.
    """
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
    return seen


PUNCH = ("minecraft:punch", {})
