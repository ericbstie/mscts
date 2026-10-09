"""The combat damage Groups: whom they hurt with what, when, and what they undo.

Every test plays a Group against a fake server and reads the Transcript for what each Bot sent
and the Marks (the Observation windows). What a server answers is never asserted: the fake
answers Control's markers, the barrier and a respawn request, and nothing else.
"""

import asyncio
import functools
import json
from contextlib import suppress
from dataclasses import dataclass, field

import pytest

from mscts.bot import SYNC_REQUESTS
from mscts.codec.packets import Packet
from mscts.compare import OBSERVE_OPEN
from mscts.group import GROUPS, GroupContext, GroupKind
from mscts.groups import combat_damage
from mscts.groups.combat_damage import Source
from mscts.spec import Difficulty, ServerSpec
from mscts.transcript import Transcript
from tests.group.test_control import CODEC, text, tree
from tests.group.test_movement import Play, read
from tests.net.fakes import (
    EMPTY_CHUNK,
    NO_STATISTICS,
    TICK_S,
    JoinScript,
    Peer,
    join_server,
    serve,
)
from tests.net.test_bot_move import RESPAWN

CONTROL = "control"
VICTIM = "victim"
MARKER = "tellraw @s "
CHAT_COMMAND, CLIENT_COMMAND = "minecraft:chat_command", "minecraft:client_command"
PERFORM_RESPAWN = 0
COMMANDS = tree(
    "gamerule", "tp", "tick", "kill", "damage", "summon", "effect", "item", "clear", "tellraw"
)
PLAY_TIMEOUT_S = 300.0
"""How long a fake serves a Bot: a play takes about a minute when the host is idle."""

DAMAGER = "@e[type=minecraft:marker,tag=mscts_damager,limit=1]"
SOURCE_TYPES = (
    "generic",
    "player_attack",
    "mob_attack",
    "arrow",
    "fall",
    "in_fire",
    "lava",
    "magic",
    "wither",
    "explosion",
    "out_of_world",
    "starve",
)
BY_MARKER = ("player_attack", "mob_attack", "arrow")


@dataclass
class DamageServer:
    """A fake server that joins like vanilla and answers Control's markers and the barrier.

    It answers a respawn request as `PlayerList.respawn` does: the `respawn` packet, then one
    chunk batch.
    """

    seen: list[Packet] = field(default_factory=list)

    async def __call__(self, peer: Peer) -> None:
        """Serve one connection: a Handler."""
        with suppress(ConnectionError):
            await join_server(self.seen, JoinScript(commands=COMMANDS, then=self._play))(peer)

    async def _play(self, peer: Peer) -> None:
        requests = 0
        async for packet in peer.packets():
            self.seen.append(packet)
            if packet.name == CLIENT_COMMAND and packet.fields == {"action": PERFORM_RESPAWN}:
                await peer.send("minecraft:respawn", **RESPAWN, data_kept=0)
                await peer.send("minecraft:chunk_batch_start")
                await peer.send("minecraft:level_chunk_with_light", **EMPTY_CHUNK)
                await peer.send("minecraft:chunk_batch_finished", batch_size=1)
            elif packet.name == CLIENT_COMMAND:
                requests += 1
                if (requests - 1) % SYNC_REQUESTS != 0:
                    await asyncio.sleep(TICK_S)  # a barrier's answers come a tick apart
                await peer.write(peer.raw_frame("minecraft:award_stats", NO_STATISTICS))
            elif packet.name == CHAT_COMMAND:
                command = str((packet.fields or {})["command"])
                if command.startswith(MARKER):
                    token = json.loads(command.removeprefix(MARKER))
                    await peer.write(
                        peer.frame("minecraft:system_chat", content=text(token), overlay=False)
                    )


async def _play(group_id: str) -> tuple[Transcript, Play]:
    transcript = Transcript(group_id=group_id, server="fake")
    async with serve(CODEC, DamageServer(), timeout_s=PLAY_TIMEOUT_S) as endpoint:
        context = GroupContext(endpoint, transcript, timeout_s=10.0)
        try:
            await GROUPS[group_id].run(context)
        finally:
            await context.close()
    return transcript, read(transcript)


@functools.cache
def play(group_id: str) -> tuple[Transcript, Play]:
    """Play `group_id` against a fake server once; its Transcript and what was read from it.

    A play takes seconds (every respawn and barrier waits for the fake's ticks), so every test
    of a Group reads one.
    """
    return asyncio.run(_play(group_id))


def played(group_id: str) -> Play:
    return play(group_id)[1]


def respawns(transcript: Transcript) -> int:
    """How many times the Bot asked to respawn."""
    return sum(
        1
        for event in transcript.events
        if event.bot == VICTIM
        and event.packet.name == CLIENT_COMMAND
        and event.packet.fields == {"action": PERFORM_RESPAWN}
    )


GROUP_IDS = ("combat/damage-types", "combat/armor", "combat/effects")


# Registration


@pytest.mark.parametrize("group_id", GROUP_IDS)
def test_each_group_is_tick_exact_needs_nothing_masks_nothing_and_plays_on_normal_difficulty(
    group_id: str,
) -> None:
    group = GROUPS[group_id]
    default = ServerSpec(host="127.0.0.1", port=25566)

    assert group.kind is GroupKind.TICK_EXACT
    assert group.requires == ()
    assert group.masks == ()
    assert group.spec(default) == ServerSpec(
        host="127.0.0.1", port=25566, difficulty=Difficulty.NORMAL
    )


def test_the_windows_compare_the_hit_the_health_the_slots_and_the_death() -> None:
    assert combat_damage.PACKETS == (
        "minecraft:damage_event",
        "minecraft:hurt_animation",
        "minecraft:entity_event",
        "minecraft:set_entity_data",
        "minecraft:set_entity_motion",
        "minecraft:set_health",
        "minecraft:container_set_slot",
        "minecraft:sound",
        "minecraft:system_chat",
        "minecraft:player_combat_kill",
    )


def test_the_kinds_of_damage_are_the_twelve_the_issue_names_and_three_need_an_attacker() -> None:
    assert [source.type for source in combat_damage.SOURCES] == list(SOURCE_TYPES)
    assert [s.type for s in combat_damage.SOURCES if s.by_marker] == list(BY_MARKER)


def test_a_command_names_the_damage_type_and_the_marker_only_when_the_source_has_an_attacker() -> (
    None
):
    assert combat_damage.damage_command(VICTIM, Source("fall")) == "damage victim 4 minecraft:fall"
    assert (
        combat_damage.damage_command(VICTIM, Source("arrow", by_marker=True))
        == f"damage victim 4 minecraft:arrow by {DAMAGER}"
    )
    assert combat_damage.damage_command(VICTIM, Source("fall"), 100) == (
        "damage victim 100 minecraft:fall"
    )


# The shape of every play


@pytest.mark.parametrize("group_id", GROUP_IDS)
def test_the_rules_are_set_before_the_bot_joins_and_put_back_after_everything_else(
    group_id: str,
) -> None:
    transcript, result = play(group_id)

    assert result.first[:5] == (
        "gamerule player_movement_check false",
        "gamerule respawn_radius 0",
        "gamerule natural_health_regeneration false",
        "tp control 96.5 -60 96.5",
        'summon minecraft:marker 3.5 -60 0.5 {Tags:["mscts_damager"]}',
    )
    hello = next(
        e.t_ns for e in transcript.events if e.packet.name == "minecraft:hello" and e.bot != CONTROL
    )
    first_tp = next(
        e.t_ns
        for e in transcript.events
        if e.bot == CONTROL and str((e.packet.fields or {}).get("command", "")).startswith("tp ")
    )
    assert first_tp < hello
    assert result.after[-5:] == (
        f"kill {DAMAGER}",
        "gamerule natural_health_regeneration true",
        "gamerule respawn_radius 10",
        "gamerule player_movement_check true",
        "tick unfreeze",
    )


@pytest.mark.parametrize("group_id", GROUP_IDS)
def test_the_bot_is_put_back_at_the_spawn_before_the_marker_goes(group_id: str) -> None:
    result = played(group_id)

    assert result.after.index("tp victim 0.5 -60 0.5") < result.after.index(f"kill {DAMAGER}")


@pytest.mark.parametrize("group_id", GROUP_IDS)
def test_no_group_touches_mob_spawning_or_removes_what_it_did_not_make(group_id: str) -> None:
    # The Fixture world has `spawn_mobs` off (ADR-0013); turning it back on after a Group would
    # leave it on for every Group that plays after.
    result = played(group_id)

    commands = (*result.first, *result.after, *(c for w in result.windows for c in w.before))
    assert not [c for c in commands if "spawn_mobs" in c or c.startswith("kill @e[type=!")]


@pytest.mark.parametrize("group_id", GROUP_IDS)
def test_the_world_is_frozen_once_the_bot_has_joined(group_id: str) -> None:
    result = played(group_id)

    assert result.first.count("tick freeze") == 1
    assert result.first.index("tick freeze") < result.first.index("kill victim")


# combat/damage-types


def test_each_kind_of_damage_has_a_window_of_its_own_narrowed_to_the_packets() -> None:
    result = played("combat/damage-types")

    assert [w.label for w in result.windows] == [
        f"{OBSERVE_OPEN} {' '.join(combat_damage.PACKETS)}"
    ] * len(SOURCE_TYPES)


def test_damage_types_runs_the_damage_command_in_each_window_and_nothing_else() -> None:
    result = played("combat/damage-types")

    commands = [
        f"damage victim 4 minecraft:{kind}" + (f" by {DAMAGER}" if kind in BY_MARKER else "")
        for kind in SOURCE_TYPES
    ]
    assert [w.sent for w in result.windows] == [((CONTROL, command),) for command in commands]


def test_damage_types_makes_the_bot_fresh_before_every_window() -> None:
    transcript, result = play("combat/damage-types")

    assert [w.before for w in result.windows[1:]] == [("kill victim",)] * (len(SOURCE_TYPES) - 1)
    assert result.windows[0].before[-1] == "kill victim"
    assert respawns(transcript) == len(SOURCE_TYPES)


# combat/armor

SETS = (
    ("iron", ""),
    ("diamond", ""),
    ("netherite", ""),
    ("diamond", "[enchantments={protection:4}]"),
    ("diamond", "[enchantments={fire_protection:4}]"),
    ("diamond", "[enchantments={blast_protection:4}]"),
)


def wearing(material: str, components: str) -> tuple[str, ...]:
    """The commands that put a set on `victim`, head to feet."""
    return tuple(
        f"item replace entity victim armor.{slot} with minecraft:{material}_{piece}{components}"
        for slot, piece in (
            ("head", "helmet"),
            ("chest", "chestplate"),
            ("legs", "leggings"),
            ("feet", "boots"),
        )
    )


def damages() -> list[str]:
    """The damage commands of one pass over the kinds of damage."""
    return [
        f"damage victim 4 minecraft:{kind}" + (f" by {DAMAGER}" if kind in BY_MARKER else "")
        for kind in SOURCE_TYPES
    ]


def test_armor_has_a_window_for_each_kind_of_damage_in_each_set() -> None:
    result = played("combat/armor")

    assert len(result.windows) == len(SETS) * len(SOURCE_TYPES)
    assert {w.label for w in result.windows} == {
        f"{OBSERVE_OPEN} {' '.join(combat_damage.PACKETS)}"
    }
    assert [w.sent for w in result.windows] == [((CONTROL, c),) for c in damages() * len(SETS)]


def test_armor_puts_on_each_set_before_its_first_window_and_only_then() -> None:
    result = played("combat/armor")

    per_set = len(SOURCE_TYPES)
    for index, (material, components) in enumerate(SETS):
        first, *rest = result.windows[index * per_set : (index + 1) * per_set]
        assert first.before[-5:] == (*wearing(material, components), "kill victim")
        assert {w.before for w in rest} == {("kill victim",)}


def test_armor_keeps_the_stacks_through_each_death_and_clears_them_when_it_ends() -> None:
    transcript, result = play("combat/armor")

    assert result.first.index("gamerule keep_inventory true") < result.first.index("tick freeze")
    assert result.after.index("clear victim") < result.after.index("gamerule keep_inventory false")
    assert respawns(transcript) == len(SETS) * len(SOURCE_TYPES)


def test_the_command_for_a_set_names_every_piece_and_the_enchantment_at_level_iv() -> None:
    wear = combat_damage.wear_commands

    assert wear(VICTIM, combat_damage.Armor("iron")) == wearing("iron", "")
    assert wear(VICTIM, combat_damage.Armor("diamond", "blast_protection")) == wearing(
        "diamond", "[enchantments={blast_protection:4}]"
    )
    assert [(a.material, a.enchantment) for a in combat_damage.ARMORS] == [
        ("iron", None),
        ("diamond", None),
        ("netherite", None),
        ("diamond", "protection"),
        ("diamond", "fire_protection"),
        ("diamond", "blast_protection"),
    ]


# combat/effects

EFFECTS = (
    ("resistance", 0),
    ("resistance", 1),
    ("resistance", 2),
    ("resistance", 3),
    ("absorption", 1),
)


def giving(effect: str, amplifier: int) -> str:
    return f"effect give victim minecraft:{effect} 1000000 {amplifier} true"


def test_effects_has_a_window_for_each_kind_of_damage_under_each_effect() -> None:
    result = played("combat/effects")

    assert len(result.windows) == len(EFFECTS) * len(SOURCE_TYPES)
    assert {w.label for w in result.windows} == {
        f"{OBSERVE_OPEN} {' '.join(combat_damage.PACKETS)}"
    }
    assert [w.sent for w in result.windows] == [((CONTROL, c),) for c in damages() * len(EFFECTS)]


def test_effects_gives_the_effect_after_every_respawn_and_before_the_window() -> None:
    transcript, result = play("combat/effects")

    expected = [
        ("kill victim", giving(effect, amplifier))
        for effect, amplifier in EFFECTS
        for _ in SOURCE_TYPES
    ]
    assert [w.before[-2:] for w in result.windows] == expected
    assert respawns(transcript) == len(EFFECTS) * len(SOURCE_TYPES)


def test_effects_wears_no_armor_and_keeps_no_stacks() -> None:
    result = played("combat/effects")

    commands = (*result.first, *result.after, *(c for w in result.windows for c in w.before))
    assert not [c for c in commands if c.startswith("item ") or "keep_inventory" in c]


def test_the_command_for_an_effect_has_no_particles_and_lasts_past_the_window() -> None:
    assert combat_damage.effect_command(VICTIM, combat_damage.Effect("absorption", 1)) == giving(
        "absorption", 1
    )
    assert [(e.name, e.amplifier) for e in combat_damage.EFFECTS] == list(EFFECTS)
