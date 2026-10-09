"""The combat Groups: what Control sets up, what each Bot does in a window, and what is undone.

Every test plays a Group against a fake server and reads the Transcript for what each Bot sent
(Control's commands, a Bot's attacks) and the Marks (the Observation windows). What a server
answers to a hit is never asserted: the fake only tells every player about each husk Control
summons, so that a Bot has an entity to hit.
"""

import asyncio
import json
import uuid
from contextlib import suppress
from dataclasses import dataclass, field

import pytest

from mscts.bot import SYNC_REQUESTS
from mscts.codec.packets import Direction, Packet
from mscts.codec.registry_names import registry_names
from mscts.compare import OBSERVE_CLOSE, OBSERVE_OPEN
from mscts.group import GROUPS, GroupKind
from mscts.groups import combat
from mscts.spec import Difficulty, ServerSpec
from mscts.target import TARGET
from mscts.transcript import Transcript
from tests.group.test_control import playing, text, tree
from tests.net.fakes import NO_STATISTICS, TICK_S, JoinScript, Peer, join_server
from tests.net.test_bot_move import LOGIN


def _login(peer: Peer) -> bytes:
    """The `login` that names the player's entity id, which a sprint command carries."""
    return peer.frame("minecraft:login", **LOGIN)


CONTROL = "control"
MARKER = "tellraw @s "
CHAT_COMMAND, CLIENT_COMMAND = "minecraft:chat_command", "minecraft:client_command"
COMMANDS = tree("gamerule", "tp", "tick", "summon", "item", "data", "kill", "execute", "tellraw")
HUSK = registry_names(TARGET.minecraft_version, "minecraft:entity_type").index("minecraft:husk")
MOVES = ("minecraft:move_player_pos", "minecraft:move_player_pos_rot")
START_SPRINTING, STOP_SPRINTING = 1, 2
STEP = "tick step 1"
NONE_LEFT = "commands.execute.conditional.fail"

GROUP_IDS = ("combat/melee-mob", "combat/critical")


@dataclass
class CombatServer:
    """A fake server that joins like vanilla, answers Control's markers and the barrier.

    Each `summon minecraft:husk x y z` is told to every player that is in the world, as an
    `add_entity` with the next entity id (from 100).
    """

    seen: list[Packet] = field(default_factory=list)
    stall_after: str | None = None
    """A command after which the fake leaves Control's next marker unanswered."""
    left: str = ""
    """What `execute if entity` answers: nothing left, unless this says a husk is."""
    _peers: list[Peer] = field(default_factory=list)
    _next_id: int = 100

    async def __call__(self, peer: Peer) -> None:
        """Serve one connection: a Handler."""
        with suppress(ConnectionError):
            script = JoinScript(commands=COMMANDS, after_batch=_login, then=self._play)
            await join_server(self.seen, script)(peer)

    async def _play(self, peer: Peer) -> None:
        self._peers.append(peer)
        requests = 0
        stalled = False
        async for packet in peer.packets():
            self.seen.append(packet)
            if packet.name == CLIENT_COMMAND:
                requests += 1
                if (requests - 1) % SYNC_REQUESTS != 0:
                    await asyncio.sleep(TICK_S)  # a barrier's answers come a tick apart
                await peer.write(peer.raw_frame("minecraft:award_stats", NO_STATISTICS))
            elif packet.name == CHAT_COMMAND:
                command = str((packet.fields or {})["command"])
                if command == self.stall_after:
                    stalled = True
                elif command.startswith(MARKER) and stalled:
                    stalled = False
                elif command.startswith(MARKER):
                    token = json.loads(command.removeprefix(MARKER))
                    await peer.write(
                        peer.frame("minecraft:system_chat", content=text(token), overlay=False)
                    )
                elif command.startswith("execute if entity"):
                    await self._say(peer, self.left or NONE_LEFT)
                elif command.startswith("summon minecraft:husk "):
                    await self._summon(command)

    async def _say(self, peer: Peer, message: str) -> None:
        await peer.write(peer.frame("minecraft:system_chat", content=text(message), overlay=False))

    async def _summon(self, command: str) -> None:
        x, y, z = (float(part) for part in command.split()[2:5])
        self._next_id += 1
        for peer in self._peers:
            await peer.send(
                "minecraft:add_entity",
                entity_id=self._next_id,
                entity_uuid=uuid.UUID(int=self._next_id),
                type=HUSK,
                x=x,
                y=y,
                z=z,
                velocity={"scale": 0, "x": 0, "y": 0, "z": 0},
                pitch=0,
                yaw=0,
                head_yaw=0,
                data=0,
            )


@dataclass(frozen=True)
class Item:
    """One thing sent, in the order sent: a command by Control, or a packet by a Bot."""

    t_ns: int
    bot: str
    what: str
    fields: dict[str, object]


def sent(transcript: Transcript) -> list[Item]:
    """Everything the Bots sent but markers, the barrier and the movement, with when."""
    items = []
    for event in transcript.events:
        packet = event.packet
        if packet.direction is not Direction.SERVERBOUND:
            continue
        fields = dict(packet.fields or {})
        if packet.name == CHAT_COMMAND and not str(fields["command"]).startswith(MARKER):
            items.append(Item(event.t_ns, event.bot, str(fields["command"]), fields))
        elif packet.name in ("minecraft:attack", "minecraft:punch", "minecraft:player_command"):
            items.append(Item(event.t_ns, event.bot, packet.name, fields))
        elif packet.name in MOVES:
            items.append(Item(event.t_ns, event.bot, "move", fields))
    return items


@dataclass(frozen=True)
class Window:
    """One Observation window: its open Mark, and what was sent before it and inside it."""

    label: str
    before: tuple[Item, ...]
    inside: tuple[Item, ...]


@dataclass(frozen=True)
class Play:
    """A played Group: every window, what came before the first, and what came after the last."""

    windows: tuple[Window, ...]
    first: tuple[Item, ...]
    after: tuple[Item, ...]
    transcript: Transcript


async def play(group_id: str, server: CombatServer | None = None) -> Play:
    """Play `group_id` against a fake server; read what the Transcript shows."""
    transcript = Transcript(group_id=group_id, server="fake")
    async with playing(server or CombatServer(), transcript) as context:
        await GROUPS[group_id].run(context)
    return read(transcript)


def read(transcript: Transcript) -> Play:
    items = sent(transcript)
    opens = [(m.t_ns, m.label) for m in transcript.marks if m.label.startswith(OBSERVE_OPEN)]
    closes = [m.t_ns for m in transcript.marks if m.label == OBSERVE_CLOSE]
    assert len(opens) == len(closes), transcript.marks
    windows = []
    previous = 0
    for (opened, label), closed in zip(opens, closes, strict=True):
        windows.append(
            Window(
                label=label,
                before=tuple(i for i in items if previous <= i.t_ns < opened),
                inside=tuple(i for i in items if opened <= i.t_ns <= closed),
            )
        )
        previous = closed
    after = tuple(i for i in items if i.t_ns > previous)
    first = tuple(i for i in items if not opens or i.t_ns < opens[0][0])
    return Play(tuple(windows), first, after, transcript)


def on_ground(move: Item) -> bool:
    """Whether a move says the player is on the ground (bit 0 of its flags)."""
    flags = move.fields["flags"]
    assert isinstance(flags, int)
    return bool(flags & 1)


def commands(items: tuple[Item, ...], bot: str = CONTROL) -> list[str]:
    return [i.what for i in items if i.bot == bot and i.what.startswith(tuple(_ROOTS))]


_ROOTS = ("gamerule", "tp ", "tick", "summon", "item", "data", "kill", "execute")


# Registration


@pytest.mark.parametrize("group_id", GROUP_IDS)
def test_each_group_is_tick_exact_on_normal_difficulty_with_the_pitch_mask(group_id: str) -> None:
    group = GROUPS[group_id]
    default = ServerSpec(host="127.0.0.1", port=25566)

    assert group.kind is GroupKind.TICK_EXACT
    assert group.requires == ()
    assert group.masks == (combat.PITCH_MASK,)
    assert group.spec(default).difficulty is Difficulty.NORMAL
    assert group.spec(default).game_mode == default.game_mode


def test_the_pitch_mask_names_the_sound_and_its_reason() -> None:
    assert (combat.PITCH_MASK.packet, combat.PITCH_MASK.path) == ("minecraft:sound", "pitch")
    assert "getVoicePitch" in combat.PITCH_MASK.reason


def test_the_windows_compare_the_hit_and_what_it_does_to_the_husk() -> None:
    assert combat.PACKETS == (
        "minecraft:damage_event",
        "minecraft:hurt_animation",
        "minecraft:entity_event",
        "minecraft:set_entity_motion",
        "minecraft:set_entity_data",
        "minecraft:sound",
        "minecraft:animate",
        "minecraft:level_particles",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("group_id", GROUP_IDS)
async def test_every_window_is_narrowed_to_the_hit_packets(group_id: str) -> None:
    result = await play(group_id)

    assert result.windows
    assert {window.label for window in result.windows} == {
        f"{OBSERVE_OPEN} {' '.join(combat.PACKETS)}"
    }


# The arena


@pytest.mark.asyncio
@pytest.mark.parametrize("group_id", GROUP_IDS)
async def test_the_arena_is_set_before_the_first_window_and_undone_after_the_last(
    group_id: str,
) -> None:
    result = await play(group_id)

    before = commands(result.first)
    assert before[:4] == [
        "gamerule player_movement_check false",
        "gamerule respawn_radius 0",
        "gamerule natural_health_regeneration false",
        "tick freeze",
    ]
    assert f"tp {CONTROL} 5.5 -60 44.5" in before
    assert commands(result.after) == [
        "data merge entity @e[tag=mscts_combat] {last_hurt_by_player_memory_time:0}",
        "gamerule mob_drops false",
        "kill @e[tag=mscts_combat]",
        "gamerule mob_drops true",
        "tick unfreeze",
        "execute if entity @e[tag=mscts_combat]",
        "gamerule natural_health_regeneration true",
        "gamerule respawn_radius 10",
        "gamerule player_movement_check true",
        "tick unfreeze",  # the Group's end, which `playing` runs as a Run does
    ]


@pytest.mark.asyncio
async def test_mob_drops_are_turned_on_again_when_the_kill_never_answers() -> None:
    # The command may have run though its answer never came.
    kill = "kill @e[tag=mscts_combat]"
    transcript = Transcript(group_id="combat/melee-mob", server="fake")
    async with playing(CombatServer(stall_after=kill), transcript) as context:
        with pytest.raises(TimeoutError):
            await GROUPS["combat/melee-mob"].run(context)

    control = [i.what for i in sent(transcript) if i.bot == CONTROL]
    assert control[control.index(kill) + 1] == "gamerule mob_drops true"


# Every Group: one husk, one lane and one window for each case


SWORD = "minecraft:diamond_sword"
WEAPONS = {
    "combat/melee-mob": (None, "minecraft:wooden_sword", SWORD, "minecraft:diamond_axe"),
    "combat/critical": (SWORD, SWORD),
}
SIZES = {group_id: len(weapons) for group_id, weapons in WEAPONS.items()}


@pytest.mark.asyncio
@pytest.mark.parametrize("group_id", GROUP_IDS)
async def test_each_case_hits_the_husk_summoned_for_it_once(group_id: str) -> None:
    result = await play(group_id)

    attacks = [
        [i for i in window.inside if i.what == "minecraft:attack"] for window in result.windows
    ]
    assert [len(a) for a in attacks] == [1] * SIZES[group_id]
    # The husks are told about in order, with ids from 101; each window hits its own.
    assert [a[0].fields["entity_id"] for a in attacks] == [101 + n for n in range(SIZES[group_id])]


@pytest.mark.asyncio
@pytest.mark.parametrize("group_id", GROUP_IDS)
async def test_each_case_sets_up_the_fighter_the_weapon_and_a_husk(group_id: str) -> None:
    result = await play(group_id)

    for lane, (window, weapon) in enumerate(zip(result.windows, WEAPONS[group_id], strict=True)):
        z = 2.5 + 4 * lane
        held = weapon or "minecraft:air"
        setup = [c for c in commands(window.before) if not c.startswith("tick")]
        assert setup[-3:] == [
            f"tp fighter 4.5 -60 {z} -90.0 0",
            f"item replace entity fighter hotbar.0 with {held}",
            (
                f"summon minecraft:husk 6.0 -60 {z} "
                '{NoAI:1b,OnGround:1b,Health:20f,Tags:["mscts_combat"]}'
            ),
        ]


@pytest.mark.asyncio
@pytest.mark.parametrize("group_id", GROUP_IDS)
async def test_each_case_waits_ten_steps_for_the_charge_and_steps_two_after_the_hit(
    group_id: str,
) -> None:
    result = await play(group_id)

    for window in result.windows:
        assert commands(window.before).count(STEP) == 10
        assert commands(window.inside).count(STEP) == 2
        names = [i.what for i in window.inside if i.what in ("minecraft:attack", STEP)]
        assert names == ["minecraft:attack", STEP, STEP]


# combat/critical


@pytest.mark.asyncio
async def test_critical_hops_before_the_first_window_and_comes_down_half_in_it() -> None:
    result = await play("combat/critical")

    fall = result.windows[0]
    hops = [i for i in fall.before if i.what == "move"]
    assert [(h.fields["y"], on_ground(h)) for h in hops] == [(-59.0, False)]
    inside = [i.what for i in fall.inside if i.what in ("move", "minecraft:attack")]
    assert inside == ["move", "minecraft:attack"]
    down = next(i for i in fall.inside if i.what == "move")
    assert (down.fields["y"], on_ground(down)) == (-59.5, False)


@pytest.mark.asyncio
async def test_critical_lands_after_the_falling_hit_and_the_sprinting_hit_does_not_fall() -> None:
    result = await play("combat/critical")

    landing = [i for i in result.windows[1].before if i.what == "move"]
    assert [(m.fields["y"], on_ground(m)) for m in landing][-1:] == [(-60.0, True)]
    assert not [i for i in result.windows[1].inside if i.what == "move"]


@pytest.mark.asyncio
async def test_critical_sprints_before_the_second_window_and_stops_after_it() -> None:
    result = await play("combat/critical")

    def actions(items: tuple[Item, ...]) -> list[object]:
        return [i.fields["action"] for i in items if i.what == "minecraft:player_command"]

    assert actions(result.windows[0].before) == []
    assert actions(result.windows[1].before) == [START_SPRINTING]
    assert actions(result.windows[1].inside) == []
    assert actions(result.after) == [STOP_SPRINTING]


@pytest.mark.asyncio
async def test_control_asks_until_no_husk_is_left_then_stops() -> None:
    result = await play("combat/melee-mob")

    asked = [c for c in commands(result.after) if c.startswith("execute")]
    assert asked == ["execute if entity @e[tag=mscts_combat]"]


@pytest.mark.asyncio
async def test_control_gives_up_asking_after_twenty_answers_that_a_husk_is_left() -> None:
    result = await play("combat/melee-mob", CombatServer(left="Test passed, count: 1"))

    asked = [c for c in commands(result.after) if c.startswith("execute")]
    assert len(asked) == 20
