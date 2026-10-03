"""Players Groups: what a player sees of another one joining, changing game mode and leaving.

ada is in the world, and bob joins, changes game mode or leaves next to her. Each window
compares what reaches the tab list (`player_info_update`, `player_info_remove`), the player's
body (`add_entity`, `set_entity_data`, `remove_entities`) and the chat (`system_chat`, the
join and leave messages), for both Bots. `players/server-full` compares the refusal a player
gets when the server is full.

The tab list shows each player's latency, measured by the server, so it is compared, not
masked (ADR-0006). Vanilla starts every player's latency at 0
(`CommonListenerCookie.createInitial`) and measures it first with a keep-alive 15 s after the
player joined (`ServerCommonPacketListenerImpl.keepConnectionAlive`), so every latency these
Groups see is 0 on vanilla (26.3 javap, #67).

Both players join at the world spawn (`gamerule respawn_radius 0`), and the world is frozen
with no mob near the spawn, so nothing but the Group changes what they see. Every setting is
put back afterwards: every Group is played on the same two Instances.
"""

import contextlib
from collections.abc import AsyncIterator
from dataclasses import replace

from mscts.group import Control, GroupContext, group
from mscts.net import ProtocolError
from mscts.spec import ServerSpec

FIRST = "ada"
"""The player who is in the world first, and watches."""

SECOND = "bob"
"""The player who joins, changes game mode and leaves next to the first."""

PACKETS = (
    "minecraft:player_info_update",
    "minecraft:player_info_remove",
    "minecraft:add_entity",
    "minecraft:set_entity_data",
    "minecraft:remove_entities",
    "minecraft:system_chat",
)
"""The packets a window compares: the tab list, the other player's body and the chat."""

_RULES = (
    ("spawn_mobs", "false", "true"),
    ("respawn_radius", "0", "10"),
    ("player_movement_check", "false", "true"),
)
"""Each game rule the Groups set, its value while they play, and vanilla's default after.

No mob spawns while they play. Both players join at the world spawn, so each sees the other
at the same place on both Instances (#30). A join can repeat its first `player_position`, a
race with the first tick, unless the movement check is off (docs/research/2026-09-26-join.md).
"""

_MOBS_AWAY = "tp @e[type=!minecraft:player] 2000 -60 2000"
"""Move every mob the world already has out of the players' sight, before the world freezes.

Where a mob stands depends on how long it has wandered, which differs between Instances, and
each joining player would see the mobs near the spawn.
"""

_GAME_MODES = ("creative", "adventure", "spectator", "survival")
"""The game modes the second player changes to, in turn, ending as it joined."""


@contextlib.asynccontextmanager
async def _still_world(control: Control) -> AsyncIterator[None]:
    """Set the rules, move the mobs away and freeze the world; on the way out, undo each.

    Each undo runs even if another fails, and after the body however it ended.
    """
    async with contextlib.AsyncExitStack() as undo:
        for rule, value, default in _RULES:
            await control.run(f"gamerule {rule} {value}")
            undo.push_async_callback(control.run, f"gamerule {rule} {default}")
        await control.run(_MOBS_AWAY)
        await control.run("tick freeze")
        undo.push_async_callback(control.run, "tick unfreeze")
        yield


@group("players/join-seen")
async def join_seen(context: GroupContext) -> None:
    """The second player joins next to the first, and each sees the other."""
    async with _still_world(context.control):
        first = await context.bot(FIRST)
        await first.join()
        # Control leaves, so the second player sees only the first one join it: Control
        # rejoins to undo the rules once the window is over.
        await context.control.leave()
        second = await context.bot(SECOND)
        async with context.observe(*PACKETS):
            await second.join()


@group("players/leave-seen")
async def leave_seen(context: GroupContext) -> None:
    """The second player leaves, and the first sees it go."""
    async with _still_world(context.control):
        first = await context.bot(FIRST)
        await first.join()
        second = await context.bot(SECOND)
        await second.join()
        async with context.observe(*PACKETS):
            await second.close()


@group("players/mode-seen")
async def mode_seen(context: GroupContext) -> None:
    """Control changes the second player's game mode to each mode in turn; both see it."""
    async with _still_world(context.control), contextlib.AsyncExitStack() as undo:
        first = await context.bot(FIRST)
        await first.join()
        second = await context.bot(SECOND)
        await second.join()
        # The server saves the player's game mode: it must join in survival next time.
        undo.push_async_callback(context.control.run, f"gamemode survival {SECOND}")
        for mode in _GAME_MODES:
            async with context.observe(*PACKETS):
                await context.control.run(f"gamemode {mode} {SECOND}")


def _one_player(spec: ServerSpec) -> ServerSpec:
    """Let one player in at a time."""
    return replace(spec, max_players=1)


@group("players/server-full", spec=_one_player)
async def server_full(context: GroupContext) -> None:
    """The first player takes the only place; the second tries to join and is refused.

    The refusal is compared as the second player's `login_disconnect`. A server that lets it
    in instead sends it the login, and that is the Divergence.
    """
    first = await context.bot(FIRST)
    await first.join()
    second = await context.bot(SECOND)
    async with context.observe(*PACKETS):
        with contextlib.suppress(ProtocolError):  # the refusal, which the Transcript holds
            await second.join()
        # Closed inside the window: the server has closed its side, and the end of the
        # window would take that as the server's fault.
        await second.close()
