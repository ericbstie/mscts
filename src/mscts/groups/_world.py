"""World setup that more than one Group uses."""

import contextlib
from dataclasses import replace

from mscts.bot import Bot
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

_NONE_LEFT = b"conditional.fail"
"""What vanilla's `execute if entity` answers, as a translation key, when nothing matched."""

_MOVEMENT_CHECK = "gamerule player_movement_check"
"""The check that can repeat a join's first `player_position`, a race with the first tick
(docs/research/2026-09-26-join.md; `ServerGamePacketListenerImpl.shouldCheckPlayerMovement`
returns false when the rule is off)."""

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
    """Kill every entity tagged `tag`, leaving no loot and no experience, and wait for them.

    A mob a player hit drops experience, and loot, where it dies; both need `mob_drops`
    (`LivingEntity.die` runs `dropAllDeathLoot` and `dropExperience`, and each checks it), which
    is off while the mobs die. A corpse stays for 20 ticks of its own (`LivingEntity.tickDeath`),
    so the world runs again until none is left: the next play puts new mobs where these stood,
    and would be told apart from them only by the order they were heard in.

    Raises:
        TimeoutError: An entity was still there after `_CORPSE_POLLS` asks.
    """
    try:
        await control.run("gamerule mob_drops false")
        await control.run(f"kill @e[tag={tag}]")
    finally:
        await control.run("gamerule mob_drops true")
    await control.run("tick unfreeze")
    for _ in range(_CORPSE_POLLS):
        said = await control.run(f"execute if entity @e[tag={tag}]")
        if any(_NONE_LEFT in packet.payload for packet in said):
            return
    msg = f"an entity tagged {tag} was still there after {_CORPSE_POLLS} asks"
    raise TimeoutError(msg)
