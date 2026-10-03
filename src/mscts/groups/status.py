"""Status Groups: the server list ping, as the vanilla client performs it.

The vanilla client's `ServerStatusPinger` (26.3) sends the status handshake and a
`status_request`, and on the `status_response` a `ping_request`, whose `pong_response`
gives the latency it shows. These Groups do the same, with a fixed ping payload
instead of the client's clock, so every run sends the same bytes.

Neither has a Mask: nothing in a status exchange is an identifier without gameplay
meaning (ADR-0006), so a difference in it is a Divergence.
"""

import asyncio
import contextlib

from mscts.group import GroupContext, group
from mscts.settle import until_no_player_online

PING_PAYLOAD = 20_260_926
"""The Long `status/ping` sends. The vanilla client sends its clock; a Group must not."""

STATUS_CACHE_S = 5
"""How long vanilla keeps a built status at most: `STATUS_EXPIRE_TIME_NANOS` is 5 seconds
(docs/research/2026-10-03-status-sample.md). A join drops it sooner, so vanilla lists a new
player from the next tick."""

CACHE_WAIT_S = STATUS_CACHE_S + 1
"""How long `status/with-player` waits after the join: vanilla's longest cache and one
second. Vanilla needs only a tick, so the rest is a margin for a Candidate that builds its
status lazily. A Candidate that takes longer shows no player, and that is a difference."""

PLAY_PACKET = "minecraft:player_chat"
"""The one play packet the window of `status/with-player` compares. Nothing sends it there:
the window only has to leave out the join's play packets, which vary without a Fixture."""


@group("status/basic")
async def basic(context: GroupContext) -> None:
    """Ask for the status once."""
    bot = await context.bot("status")
    await bot.status()


@group("status/ping")
async def ping(context: GroupContext) -> None:
    """Ask for the status, then ping; the `status.rtt` span covers the ping and its pong.

    It requires nothing: a Candidate whose status differs still gets its round trip timed.
    """
    bot = await context.bot("status")
    await bot.status()
    async with context.span("status.rtt"):
        await bot.ping(PING_PAYLOAD)


@group("status/with-player")
async def with_player(context: GroupContext) -> None:
    """One player joins, then the status is asked for after the server's cache has refreshed.

    Both servers build their status from the players online, but a Candidate can count
    differently, list another sample, or give the player another UUID. `player`'s login and
    configuration packets, and the status, are compared; its play packets are not (the join
    position varies without a Fixture, and `join/basic` compares them with it pinned).

    Vanilla drops its cached status when a player joins and lists the player from the next
    tick (docs/research/2026-10-03-status-sample.md). The wait is a margin for a Candidate
    that caches its status lazily. One whose status still lacks the player after it shows no
    player, which is a difference to report, so the wait does not grow to hide it.
    """
    async with contextlib.AsyncExitStack() as undo:
        player = await context.bot("player")
        # The player has left before the next Group: its status must not list her.
        undo.push_async_callback(until_no_player_online, context.endpoint)
        undo.push_async_callback(player.close)
        await player.join()
        async with context.observe(PLAY_PACKET):
            await asyncio.sleep(CACHE_WAIT_S)
            bot = await context.bot("status")
            await bot.status()
