"""Chunk loading Groups: which chunks the world loads around a player, and which it forgets.

A Bot called `walker` joins, is teleported, or walks, and each window compares the chunks it is sent
(`level_chunk_with_light`), the ones it is told to forget (`forget_level_chunk`) and where its
view is centred (`set_chunk_cache_center`).

A window lasts until the walker has every chunk of its new view: vanilla sends them over
several ticks, a batch a tick, so a window that ended at the barrier would end partway. Which
chunks a view holds is vanilla's rule (`ChunkTrackingView`, below). A server that never sends
one of them fails the Group when the wait times out; one that sends more has them compared
up to the window's close.

The batches themselves (`chunk_batch_start`, `chunk_batch_finished`) are not compared: which
chunks go in which batch depends on how soon each is ready, and differed between two vanilla
Instances (docs/research/2026-10-04-chunk-loading.md). Nor is the order of the chunks between
two other packets: the Comparison puts them in order of position, as the client keeps them
(docs/research/2026-10-02-chunks-light.md).
"""

import contextlib
from collections.abc import AsyncIterator, Callable
from dataclasses import replace

from mscts.bot import Bot
from mscts.group import GroupContext, group
from mscts.groups._world import pin_joins
from mscts.settle import until_no_player_online
from mscts.spec import ServerSpec

WALKER = "walker"
"""The Bot whose chunks are compared."""

_CHUNK = "minecraft:level_chunk_with_light"

PACKETS = (
    _CHUNK,
    "minecraft:forget_level_chunk",
    "minecraft:set_chunk_cache_center",
)
"""What a window compares: the chunks sent, the chunks forgotten, and the view's centre."""

SENT_TIMEOUT_S = 10.0
"""How long the walker waits for its view: `run.GROUP_TIMEOUT_S`, a Bot's bound."""

VIEW_DISTANCE = 2
"""The view distance of `chunks/join-view`, `chunks/teleport` and `chunks/walk`."""

FAR_VIEW_DISTANCE = 5
"""The view distance of `chunks/view-distance`."""

SPAWN = (0, 0)
"""The chunk a joining player is in: `gamerule respawn_radius 0` puts it at 0.5 -60 0.5."""

SPAWN_AT = "0.5 -60 0.5"
"""Where a joining player is put, which the walker is put back to when the Group ends."""

FAR = (20, 0)
"""The chunk `chunks/teleport` moves the walker to, 20 chunks east of the spawn."""

FAR_AT = "320.5 -60 0.5"
"""Where in `FAR` the walker is teleported to."""

WALK = (0.25, 0.0, -0.25)
"""The x of each step of `chunks/walk`, one a tick, west from 0.5: the last is in chunk -1."""

type Chunk = tuple[int, int]


def view(center: Chunk, distance: int) -> frozenset[Chunk]:
    """The chunks a vanilla server sends a player whose view is `center` and `distance`.

    `ChunkTrackingView.Positioned.contains(x, z)` (26.3 javap): a chunk is in the view when
    `dx * dx + dz * dz < distance * distance`, where `dx` is `max(0, |x - cx| - 2)` and `dz`
    likewise. So the view distance 2 is the 7 by 7 square around the centre.
    """
    cx, cz = center
    reach = distance + 1  # the box `Positioned.forEach` walks
    return frozenset(
        (x, z)
        for x in range(cx - reach, cx + reach + 1)
        for z in range(cz - reach, cz + reach + 1)
        if _past(x - cx) ** 2 + _past(z - cz) ** 2 < distance * distance
    )


def _past(offset: int) -> int:
    """How far an offset is past the two chunks next to the centre (`isWithinDistance`)."""
    return max(0, abs(offset) - 2)


async def _until_sent(bot: Bot, chunks: frozenset[Chunk]) -> None:
    """Take the walker's packets until it holds every chunk in `chunks`.

    The chunks it already holds count, whichever packets took them (`Bot.chunks`): which
    chunks the join's first batch holds is not compared, and on vanilla it is the 9 nearest
    chunks that are ready (`PlayerChunkSender.collectChunksToSend`, 26.3 javap).

    Raises:
        TimeoutError: One had not arrived within `SENT_TIMEOUT_S`; it names those missing.
    """

    def missing() -> frozenset[Chunk]:
        return chunks - bot.chunks

    if not missing():
        return
    try:
        await bot.expect(_CHUNK, timeout_s=SENT_TIMEOUT_S, where=lambda _: not missing())
    except TimeoutError:
        msg = f"chunks {sorted(missing())} never arrived within {SENT_TIMEOUT_S} s"
        raise TimeoutError(msg) from None


@contextlib.asynccontextmanager
async def _walker(context: GroupContext) -> AsyncIterator[Bot]:
    """Set the Fixture, let Control leave, and connect the walker; undo it all after.

    The walker joins alone: Control's player at the spawn would be sent to it between two
    chunk batches. Each undo runs even if another fails.
    """
    async with contextlib.AsyncExitStack() as undo:
        control = context.control
        await pin_joins(control, undo)
        await control.run("tick freeze")
        undo.push_async_callback(control.run, "tick unfreeze")
        await control.leave()
        await until_no_player_online(context.endpoint)
        walker = await context.bot(WALKER)
        undo.push_async_callback(walker.close)
        # The server keeps where a player left: the next play's walker joins at the spawn.
        undo.push_async_callback(control.run, f"tp {WALKER} {SPAWN_AT}")
        yield walker


def _at(distance: int) -> Callable[[ServerSpec], ServerSpec]:
    return lambda spec: replace(spec, view_distance=distance)


async def _join_view(context: GroupContext, distance: int) -> None:
    async with _walker(context) as walker, context.observe(*PACKETS):
        await walker.join()
        await _until_sent(walker, view(SPAWN, distance))


@group("chunks/join-view", requires=("join/basic",), spec=_at(VIEW_DISTANCE))
async def join_view(context: GroupContext) -> None:
    """The walker joins, and is sent its view."""
    await _join_view(context, VIEW_DISTANCE)


@group("chunks/view-distance", requires=("join/basic",), spec=_at(FAR_VIEW_DISTANCE))
async def view_distance(context: GroupContext) -> None:
    """The walker joins a server whose view distance is 5, and is sent its view."""
    await _join_view(context, FAR_VIEW_DISTANCE)


@group("chunks/teleport", requires=("join/basic",), spec=_at(VIEW_DISTANCE))
async def teleport(context: GroupContext) -> None:
    """Control teleports the walker 20 chunks east: it forgets its view and is sent a new one."""
    async with _walker(context) as walker:
        await walker.join()
        await _until_sent(walker, view(SPAWN, VIEW_DISTANCE))
        async with context.observe(*PACKETS):
            await context.control.run(f"tp {WALKER} {FAR_AT}")
            await _until_sent(walker, view(FAR, VIEW_DISTANCE))


@group("chunks/walk", requires=("join/basic",), spec=_at(VIEW_DISTANCE))
async def walk(context: GroupContext) -> None:
    """The walker steps west into the next chunk, one step a tick."""
    async with _walker(context) as walker:
        await walker.join()
        await _until_sent(walker, view(SPAWN, VIEW_DISTANCE))
        async with context.observe(*PACKETS):
            *before, across = WALK
            for x in before:
                await walker.move(x, -60.0, 0.5)
                await walker.sync()
            # The wait for the new view, then the window's barrier, follow the step across.
            await walker.move(across, -60.0, 0.5)
            await _until_sent(walker, view((-1, 0), VIEW_DISTANCE))
