"""World setup that more than one Group uses."""

import asyncio
import contextlib
import functools
from collections.abc import Iterable
from dataclasses import replace

from mscts.bot import Bot
from mscts.codec.packets import Packet
from mscts.entities import Entity
from mscts.group import Control, GroupContext
from mscts.spec import Difficulty, ServerSpec

CONTROL_AT = "96.5 -60 96.5"
"""Where Control stands: 6 chunks from the spawn, clear of every block the Groups set (#300) and
out of the Bot's view, so that its entity is never sent to the Bot again when the Bot respawns:
vanilla sends it a tick or so later, which no window can place."""

SPAWN_AT = "0.5 -60 0.5"
"""Where a Bot is put when the Group ends: the world spawn, clear of every block a Group sets."""

_LOOKUPS = 4
"""How often a Group looks for an entity its Bot may not track yet."""

_CORPSE_POLLS = 20
"""How often Control asks whether a killed entity is left: a corpse goes in about 1 s, a poll
takes about 0.3 s."""

_GONE_SYNCS = 60
"""How many barriers a Bot waits for the killed entities to go: each is at least a tick, and a
body goes 20 ticks after its death."""

_PLAYER = "minecraft:player"

_NONE_LEFT = b"conditional.fail"
"""What vanilla's `execute if entity` answers, as a translation key, when nothing matched."""

_MOVEMENT_CHECK = "gamerule player_movement_check"
"""The check that can repeat a join's first `player_position`, a race with the first tick
(docs/research/2026-09-26-join.md; `ServerGamePacketListenerImpl.shouldCheckPlayerMovement`
returns false when the rule is off)."""

_TIME_QUERY = "time query gametime"
_GAMETIME_KEY = b"commands.time.query.gametime"
_WITH = b"\x09\x00\x04with"
"""The `with` list of a translated text component, as network NBT: its arguments."""

_LONG, _INT, _STRING = 4, 3, 8
"""The NBT tag types a server may give the game time as: vanilla a Long, Pumpkin a String."""

_FADE_TICKS = 100
"""How many running ticks a storm takes to fade: its rain and thunder levels go from 1 to 0 by
0.01 a tick."""

_TIME_READS = 10
"""How often Control reads the game time again before a wait for ticks to run gives up."""

_TICK_S = 0.05

_RESPAWN_RADIUS = "gamerule respawn_radius"
"""How far from the world spawn a player may spawn: 10 by default in 26.3, at random. At 0
both Instances spawn the player at the same place, so they send the same chunks (measured on
#30: 20 of 20 plays, with no `setworldspawn`, which could not be undone)."""


async def pin_joins(control: Control, undo: contextlib.AsyncExitStack) -> None:
    """Make a joining player spawn at the world spawn and be placed there once.

    Sets `respawn_radius` to 0 and turns `player_movement_check` off, through `control`, and
    pushes onto `undo` the commands that set both back to vanilla's defaults.
    """
    await control.run(f"{_MOVEMENT_CHECK} false")
    undo.push_async_callback(control.run, f"{_MOVEMENT_CHECK} true")
    await control.run(f"{_RESPAWN_RADIUS} 0")
    undo.push_async_callback(control.run, f"{_RESPAWN_RADIUS} 10")


async def calm_weather(control: Control, undo: contextlib.AsyncExitStack) -> None:
    """Stop the weather cycle and clear the weather, through `control`; push the undo.

    Turns `advance_weather` off, pushing onto `undo` the command that turns it back on
    (vanilla's default), then runs `weather clear`. A storm that the cycle started during an
    earlier Group would otherwise reach the windows on one Instance only (#426).
    """
    await control.run("gamerule advance_weather false")
    undo.push_async_callback(control.run, "gamerule advance_weather true")
    await control.run("weather clear")


async def until_the_weather_fades(control: Control) -> None:
    """Return once the world has run `_FADE_TICKS` ticks, read from the game time.

    `weather clear` changes the weather at once, but not the rain and thunder levels the
    clients are sent: each moves 0.01 a running tick toward the weather, and a frozen world
    leaves them where they are (`ServerLevel.advanceWeatherCycle`, 26.3 javap). A player in a
    world whose rain level is above 0.2 is in rain (`Level.isRaining`), and is sent the weather
    when it respawns. So a Group that clears a storm and freezes the world at once still
    plays in it (#426). Control reads the game time (`time query gametime`), then waits until
    the ticks have run (`_until_ran`).

    Raises:
        TimeoutError: The world had not run them after `_TIME_READS` more reads: it is frozen.
        ValueError: The server's answer held no game time (`gametime`).
    """
    cleared = gametime(await control.run(_TIME_QUERY))
    await _until_ran(control, cleared, _FADE_TICKS, "for the weather to fade")


async def fast_forward(control: Control, ticks: int) -> None:
    """Step the frozen world on `ticks` ticks at once, outside any window; return once they ran.

    For a wait too long to step a tick at a time, about 0.3 s each. Control reads the game time,
    runs `tick step <ticks>`, which answers before the ticks have run, then waits until they
    have (`_until_ran`). A frozen world's game time moves on only on the ticks it steps
    (docs/research/2026-10-03-tick-step.md). The steps get no tick Mark: no Bot passes a barrier.

    Raises:
        TimeoutError: The world had not run them after `_TIME_READS` more reads.
        ValueError: The server's answer held no game time (`gametime`).
    """
    since = gametime(await control.run(_TIME_QUERY))
    await control.run(f"tick step {ticks}")
    await _until_ran(control, since, ticks, "of a fast-forward")


async def _until_ran(control: Control, since: int, ticks: int, purpose: str) -> None:
    """Return once the game time is `ticks` past `since`.

    Control reads the game time, and again after a wait as long as the ticks still to run.
    `purpose` ends the timeout's message, e.g. `for the weather to fade`.

    Raises:
        TimeoutError: The world had not run them after `_TIME_READS` reads.
        ValueError: The server's answer held no game time (`gametime`).
    """
    ran = 0
    for _ in range(_TIME_READS):
        ran = gametime(await control.run(_TIME_QUERY)) - since
        if ran >= ticks:
            return
        await asyncio.sleep((ticks - ran) * _TICK_S)
    msg = f"the world ran {ran} of {ticks} ticks {purpose}"
    raise TimeoutError(msg)


def gametime(said: Iterable[Packet]) -> int:
    """The game time in the answer to `time query gametime` among the system chat in `said`.

    Raises:
        ValueError: None of `said` is that answer.
    """
    for packet in said:
        content = (packet.fields or {}).get("content")
        if isinstance(content, bytes) and _GAMETIME_KEY in content:
            value = _first_argument(content)
            if value is not None:
                return value
    msg = f"no answer to {_TIME_QUERY} among what the server said"
    raise ValueError(msg)


def _first_argument(content: bytes) -> int | None:
    """The first argument of the translated text component `content`, if it is a number."""
    at = content.find(_WITH)
    if at < 0:
        return None
    kind = content[at + len(_WITH)]
    value = content[at + len(_WITH) + 5 :]  # past the element type and the list's length
    if kind == _LONG:
        return int.from_bytes(value[:8], "big", signed=True)
    if kind == _INT:
        return int.from_bytes(value[:4], "big", signed=True)
    if kind == _STRING:
        size = int.from_bytes(value[:2], "big")
        text = value[2 : 2 + size].decode(errors="replace")
        return int(text) if text.lstrip("-").isdigit() else None
    return None


async def join_at_spawn(context: GroupContext, undo: contextlib.AsyncExitStack, name: str) -> Bot:
    """Join a Bot, and have it put back at the spawn when the Group ends.

    The server saves a player where it leaves, so a Bot left in the Group's pool or stone would
    rejoin inside that block, on the next play (#300).
    """
    bot = await context.bot(name)
    await bot.join()
    undo.push_async_callback(context.control.run, f"tp {name} {SPAWN_AT}")
    return bot


def normal(spec: ServerSpec) -> ServerSpec:
    """Play on normal difficulty: peaceful heals, stops most damage and removes hostile mobs."""
    return replace(spec, difficulty=Difficulty.NORMAL)


async def fresh(context: GroupContext, bot: Bot) -> None:
    """Kill the Bot and respawn it, so that it has full health, food and air and is not burning.

    The server saves a player when it leaves: its air, health and fire, and where it was.
    """
    await context.control.run(f"kill {bot.name}")
    await bot.respawn()


_ENTITY_EVENT = "minecraft:entity_event"

_POOF = 60
"""The entity event vanilla sends a dead player 20 ticks after its death, unless it has respawned
(26.3 javap: `LivingEntity.tickDeath` calls `broadcastEntityEvent(this, 60)` once `deathTime` is
20, and `ServerChunkCache.sendToTrackingPlayersAndSelf` sends it to the player too)."""

_LATE = (
    "entity event 60 (vanilla sends it 20 ticks after the death: the respawn request came that "
    "late, or the server sent it early)"
)

_OTHERS = "entity event 60 for another entity (on vanilla no other entity dies in this Group)"


def _poof(own_id: int | None, packet: Packet) -> str | None:
    """Say what entity event 60 shows, for player `own_id` or another; None for other packets."""
    fields = packet.fields or {}
    if packet.name != _ENTITY_EVENT or fields.get("event_id") != _POOF:
        return None
    return _LATE if fields.get("entity_id") == own_id else _OTHERS


async def respawn_in_a_window(context: GroupContext, bot: Bot, names: Iterable[str]) -> None:
    """Respawn the dead Bot in a window of its own, narrowed to `names`; fail if event 60 is first.

    The window before it ends on the death, or a barrier after it, and this one opens a few ticks
    after, so the respawn comes long before the 20 ticks that event 60 waits for. A Bot that stalls
    most of a second after the death gets the event inside the window on one Instance, and maybe
    not on the other: the windows would differ for the harness's timing.
    So the Bot fails the respawn instead (`Bot.respawn`'s `fail_on`). On the Reference that is an
    `error`. On a Candidate it is a `mismatch`, as is any failure of its play, even when the Bot
    stalled. The Bot's own packets show the order, so this holds however late it reads them. An
    event 60 the barrier that opens the window takes is in no window, and is not checked.
    The check fails on event 60 for any entity: no other entity dies in the Groups that respawn
    this way, so on vanilla any event 60 is the Bot's. Its text says whether the event was the
    Bot's, without the id, which differs between plays.

    Raises:
        ProtocolError: Event 60 came before the `respawn`.
    """
    async with context.observe(*names):
        await bot.respawn(fail_on=functools.partial(_poof, bot.entity_id))


async def find_when_tracked(bot: Bot, kind: str, near: tuple[float, float, float]) -> Entity:
    """The entity of `kind` nearest `near` that `bot` tracks, once the server has sent one.

    The nearest is taken at any distance, and the Bot waits only while it tracks no entity of
    `kind` at all, so a Group must remove the entities it made before the next play makes
    them again (`remove_tagged`).

    The Bot may not have been told of an entity yet when a Group asks. The wait is `Bot.sync`,
    which does not step the world: a step would move every later packet a tick on one side
    only, which a tick-exact Comparison reports as a difference in the hit.
    """
    for _ in range(_LOOKUPS - 1):
        try:
            return bot.entities.find(kind, near=near)
        except LookupError:
            await bot.sync()
    return bot.entities.find(kind, near=near)


async def remove_tagged(control: Control, tag: str) -> None:
    """Kill every entity tagged `tag`, leaving no loot and no experience; unfreeze the world.

    A mob a player hit drops experience, and loot, where it dies; both need `mob_drops`
    (`LivingEntity.die` runs `dropAllDeathLoot` and `dropExperience`, and each checks it), which
    is off while the mobs die. Control then asks until no tagged entity is alive. A killed mob's
    body stays for 20 ticks of its own, and `@e` never matches it while it dies
    (docs/research/2026-10-14-tagged-cleanup.md), so this returns before the bodies are gone:
    a Group with a Bot beside them waits for them with `remove_tagged_until_gone`.

    Raises:
        TimeoutError: An entity was still there after `_CORPSE_POLLS` asks.
    """
    await _kill_tagged(control, tag)
    for _ in range(_CORPSE_POLLS):
        said = await control.run(f"execute if entity @e[tag={tag}]")
        if any(_NONE_LEFT in packet.payload for packet in said):
            return
    msg = f"an entity tagged {tag} was still there after {_CORPSE_POLLS} asks"
    raise TimeoutError(msg)


async def remove_tagged_until_gone(control: Control, tag: str, bot: Bot) -> None:
    """Kill every entity tagged `tag`, and wait until `bot` tracks no entity but players.

    `bot` stands beside the entities, so that their chunk stays loaded, and tracks no other
    entity but players. A body left when the next play freezes the world would stay there, and
    finish dying inside one of its windows, a tick that depends on when the freeze came
    (measured on #365: 3 Self-check plays of 20).

    Control never asks whether a tagged entity is left (`execute if entity`), as
    `remove_tagged` does: the Bot's wait covers it, and a server without `/execute` (Pumpkin)
    would fail a clean-up the Group does not test (docs/research/2026-10-14-tagged-cleanup.md).

    Raises:
        TimeoutError: `bot` still tracked another entity after `_GONE_SYNCS` barriers.
    """
    await _kill_tagged(control, tag)
    await _until_only_players(bot)


async def _kill_tagged(control: Control, tag: str) -> None:
    """Kill every entity tagged `tag` with `mob_drops` off, then unfreeze the world."""
    try:
        await control.run("gamerule mob_drops false")
        await control.run(f"kill @e[tag={tag}]")
    finally:
        await control.run("gamerule mob_drops true")
    await control.run("tick unfreeze")


async def _until_only_players(bot: Bot) -> None:
    """Pass barriers until `bot` tracks no entity but players.

    Raises:
        TimeoutError: `bot` still tracked another entity after `_GONE_SYNCS` barriers.
    """
    for _ in range(_GONE_SYNCS):
        if all(entity.type == _PLAYER for entity in bot.entities.values()):
            return
        await bot.sync()
    msg = f"{bot.name} still tracked an entity after {_GONE_SYNCS} barriers"
    raise TimeoutError(msg)
