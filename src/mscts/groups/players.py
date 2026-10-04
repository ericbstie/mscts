"""Players Groups: what a player sees of another one joining, changing game mode and leaving.

ada is in the world, and bob joins, changes game mode or leaves next to her. Each window
compares what reaches the tab list (`player_info_update`, `player_info_remove`), the player's
body (`add_entity`, `set_entity_data`, `remove_entities`) and the chat (`system_chat`, the
join and leave messages), for both Bots. `players/server-full` compares the refusal a player
gets when the server is full.

The tab list shows each player's latency, measured by the server, so it is compared, not
masked (ADR-0006). Vanilla starts every player's latency at 0
(`CommonListenerCookie.createInitial`) and measures it first with a keep-alive 15 s after the
player joined (`ServerCommonPacketListenerImpl.keepConnectionAlive`), so the second player's
latency is 0 when it joins in `players/join-seen` (26.3 javap, #67). The latency update vanilla
sends on a clock is a heartbeat packet, which no window compares (`compare.HEARTBEAT_PAYLOADS`).

Both players join at the world spawn (`gamerule respawn_radius 0`), and the world is frozen.
No mob spawns in a Fixture world (ADR-0013), so nothing but the Group changes what they see.
Every setting is put back afterwards: every Group is played on the same two Instances.
"""

import contextlib
from collections.abc import AsyncIterator
from dataclasses import replace

from mscts.group import Control, GroupContext, group
from mscts.groups._world import pin_joins
from mscts.groups.blocks import FEEDBACK_TIMEOUT_S
from mscts.net import ProtocolError
from mscts.settle import until_no_player_online
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

_GAME_MODES = ("creative", "adventure", "spectator", "survival")
"""The game modes the second player changes to, in turn, ending as it joined."""


@contextlib.asynccontextmanager
async def _still_world(control: Control) -> AsyncIterator[None]:
    """Set the join rules and freeze the world; on the way out, undo each.

    Both players join at the world spawn (`pin_joins`), so each sees the other at the same
    place on both Instances (#30). Each undo runs even if another fails, and after the body
    however it ended.
    """
    async with contextlib.AsyncExitStack() as undo:
        await pin_joins(control, undo)
        await control.run("tick freeze")
        undo.push_async_callback(control.run, "tick unfreeze")
        yield


@group("players/join-seen")
async def join_seen(context: GroupContext) -> None:
    """The second player joins next to the first, and each sees the other."""
    async with _still_world(context.control):
        # Control leaves, so the second player sees only the first one: Control rejoins to
        # undo the rules once the window is over. A server removes a closed player a tick
        # later, so the first player joins only once it has, and never sees Control go.
        await context.control.leave()
        await until_no_player_online(context.endpoint)
        first = await context.bot(FIRST)
        await first.join()
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
            # The server removes the player a tick later: a barrier covers only what the
            # first player itself sent, so it waits to see the second one go.
            await first.expect("minecraft:player_info_remove", timeout_s=FEEDBACK_TIMEOUT_S)


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

    The refusal is compared as the second player's `login_disconnect`: a window compares
    every packet before play. A server that lets it in instead sends it the login, and that
    is the Divergence. In play, the window compares only `system_chat` (a join message, if
    the server let the second player in), because the world is not frozen here: Control
    would take the only place.
    """
    first = await context.bot(FIRST)
    await first.join()
    second = await context.bot(SECOND)
    async with context.observe("minecraft:system_chat"):
        with contextlib.suppress(ProtocolError):  # the refusal, which the Transcript holds
            await second.join()
        # Closed inside the window: the server has closed its side, and the end of the
        # window would take that as the server's fault.
        await second.close()
