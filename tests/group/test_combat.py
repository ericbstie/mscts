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
from typing import cast

import pytest

from mscts.bot import SYNC_REQUESTS, Bot
from mscts.codec.packets import Direction, Packet
from mscts.codec.registry_names import registry_names
from mscts.compare import OBSERVE_CLOSE, OBSERVE_OPEN
from mscts.group import GROUPS, GroupKind
from mscts.groups import combat
from mscts.spec import Difficulty, ServerSpec
from mscts.target import TARGET
from mscts.transcript import Transcript
from tests.group.test_control import playing, text, tree
from tests.group.test_ticks import barriers_before_steps
from tests.net.fakes import NO_STATISTICS, TICK_S, JoinScript, Peer, join_server
from tests.net.test_bot_move import LOGIN


def _login(peer: Peer) -> bytes:
    """The `login` that names the player's entity id, which a sprint command carries."""
    return peer.frame("minecraft:login", **LOGIN)


CONTROL = "control"
MARKER = "tellraw @s "
CHAT_COMMAND, CLIENT_COMMAND = "minecraft:chat_command", "minecraft:client_command"
COMMANDS = tree(
    "gamerule", "tp", "tick", "summon", "item", "effect", "data", "kill", "execute", "tellraw"
)
HUSK = registry_names(TARGET.minecraft_version, "minecraft:entity_type").index("minecraft:husk")
MOVES = ("minecraft:move_player_pos", "minecraft:move_player_pos_rot")
START_SPRINTING, STOP_SPRINTING = 1, 2
STEP = "tick step 1"
SYSTEM_CHAT = "minecraft:system_chat"
HUSK_COMMAND = (
    "summon minecraft:husk 6.0 -60 2.5 "
    '{NoAI:1b,Silent:1b,OnGround:1b,Health:20f,Tags:["mscts_combat","mscts_combat"]}'
)
NONE_LEFT = "commands.execute.conditional.fail"

GROUP_IDS = (
    "combat/melee-mob",
    "combat/critical",
    "combat/knockback",
    "combat/sweep",
    "combat/immunity",
    "combat/pvp",
)
FIGHTER_GROUPS = GROUP_IDS[:4]
PLAYER = registry_names(TARGET.minecraft_version, "minecraft:entity_type").index("minecraft:player")
VICTIM_ID = 200


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
        if peer.name == "victim":
            await self._announce_victim()
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
                stalled = await self._command(peer, str((packet.fields or {})["command"]), stalled)

    async def _command(self, peer: Peer, command: str, stalled: bool) -> bool:  # noqa: FBT001
        """Answer one command; True while the next marker is to stay unanswered."""
        if command == self.stall_after:
            return True
        if command.startswith(MARKER):
            if not stalled:
                token = json.loads(command.removeprefix(MARKER))
                await peer.write(
                    peer.frame("minecraft:system_chat", content=text(token), overlay=False)
                )
            return False
        if command.startswith("execute if entity"):
            await self._say(peer, self.left or NONE_LEFT)
        elif command.startswith("summon minecraft:husk "):
            await self._summon(command)
        elif command.startswith(("data get storage", "data modify storage")):
            await self._say(peer, f"answer to {command}")
        elif command.startswith("tp @e[type=minecraft:husk"):
            await self._send_husks_away()
        return stalled

    async def _send_husks_away(self) -> None:
        """Every husk summoned so far leaves the Bots' sight (a `remove_entities`)."""
        gone = list(range(101, self._next_id + 1))
        for peer in self._peers:
            await peer.send("minecraft:remove_entities", entity_ids=gone)

    async def _announce_victim(self) -> None:
        """Tell every player already in the world that the victim is there (an `add_entity`)."""
        for peer in self._peers[:-1]:
            await peer.send(
                "minecraft:add_entity",
                entity_id=VICTIM_ID,
                entity_uuid=uuid.UUID(int=VICTIM_ID),
                type=PLAYER,
                x=6.0,
                y=-60.0,
                z=2.5,
                velocity={"scale": 0, "x": 0, "y": 0, "z": 0},
                pitch=0,
                yaw=0,
                head_yaw=0,
                data=0,
            )

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
    readbacks: tuple[Window, ...] = ()
    """The windows in which the fighter read the husks back: not among `windows`."""


async def replay(group_id: str, server: CombatServer) -> Play:
    """Play `group_id` against `server`; read what the Transcript shows."""
    transcript = Transcript(group_id=group_id, server="fake")
    async with playing(server, transcript) as context:
        await GROUPS[group_id].run(context)
    return read(transcript)


_PLAYS: dict[str, Play] = {}
"""Each Group's play against a default `CombatServer`; no test changes it."""


async def play(group_id: str) -> Play:
    """The play of `group_id` against a default fake server, played the first time it is asked."""
    if group_id not in _PLAYS:
        _PLAYS[group_id] = await replay(group_id, CombatServer())
    return _PLAYS[group_id]


@pytest.mark.asyncio
async def test_the_tests_of_a_group_share_one_play_of_it() -> None:
    """A play takes seconds (the fake's ticks are real), so a Group is played once per process."""
    assert await play("combat/melee-mob") is await play("combat/melee-mob")


def label_of(packets: tuple[str, ...]) -> str:
    return f"{OBSERVE_OPEN} {' '.join(packets)}"


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
    readbacks = tuple(w for w in windows if w.label == label_of((SYSTEM_CHAT,)))
    hits = tuple(w for w in windows if w.label != label_of((SYSTEM_CHAT,)))
    return Play(hits, first, after, transcript, readbacks)


def on_ground(move: Item) -> bool:
    """Whether a move says the player is on the ground (bit 0 of its flags)."""
    flags = move.fields["flags"]
    assert isinstance(flags, int)
    return bool(flags & 1)


def commands(items: tuple[Item, ...], bot: str = CONTROL) -> list[str]:
    return [i.what for i in items if i.bot == bot and i.what.startswith(tuple(_ROOTS))]


_ROOTS = ("gamerule", "tp ", "tick", "summon", "item", "data", "kill", "execute", "effect")


# Registration


@pytest.mark.parametrize("group_id", GROUP_IDS)
def test_each_group_is_tick_exact_on_normal_difficulty_and_masks_a_pitch_only_in_pvp(
    group_id: str,
) -> None:
    group = GROUPS[group_id]
    default = ServerSpec(host="127.0.0.1", port=25566)

    assert group.kind is GroupKind.TICK_EXACT
    assert group.requires == ()
    assert group.masks == ((combat.PITCH_MASK,) if group_id == "combat/pvp" else ())
    assert group.spec(default).difficulty is Difficulty.NORMAL
    assert group.spec(default).game_mode == default.game_mode
    assert (combat.FIGHTER in group.spec(default).operators) is (group_id in FIGHTER_GROUPS)


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


def label(packets: tuple[str, ...]) -> str:
    return f"{OBSERVE_OPEN} {' '.join(packets)}"


def test_a_sprinting_hit_leaves_out_the_entity_data_and_a_sweep_the_end_of_tick_packets() -> None:
    assert (
        tuple(name for name in combat.PACKETS if name != "minecraft:set_entity_data")
        == combat.SPRINT_PACKETS
    )
    assert "minecraft:set_entity_data" in combat.PACKETS
    assert combat.SWEEP_PACKETS == (
        "minecraft:damage_event",
        "minecraft:sound",
        "minecraft:animate",
        "minecraft:level_particles",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("group_id", GROUP_IDS)
async def test_every_window_is_narrowed_to_the_packets_of_its_case(group_id: str) -> None:
    result = await play(group_id)

    expected = {
        "combat/melee-mob": [combat.PACKETS] * 4,
        "combat/critical": [combat.PACKETS, combat.SPRINT_PACKETS],
        "combat/knockback": [combat.PACKETS, combat.SPRINT_PACKETS],
        "combat/sweep": [combat.SWEEP_PACKETS],
        "combat/immunity": [combat.PACKETS] * 3,
        "combat/pvp": [combat.PVP_PACKETS, combat.PVP_SPRINT_PACKETS],
    }[group_id]
    assert [window.label for window in result.windows] == [label(p) for p in expected]


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
    scratch = ["data remove storage mscts:combat r"] if group_id in FIGHTER_GROUPS else []
    assert commands(result.after) == [
        *scratch,
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
    "combat/knockback": (SWORD, SWORD),
    "combat/sweep": (SWORD,),
}
AROUND = {"combat/sweep": ((6.0, 0.9), (6.0, -0.9), (6.9, 0.0))}
"""Where the husks beside the target stand, as (x, offset of z)."""
SIZES = {group_id: len(weapons) for group_id, weapons in WEAPONS.items()}


@pytest.mark.asyncio
@pytest.mark.parametrize("group_id", FIGHTER_GROUPS)
async def test_each_case_hits_the_husk_summoned_for_it_once(group_id: str) -> None:
    result = await play(group_id)

    attacks = [
        [i for i in window.inside if i.what == "minecraft:attack"] for window in result.windows
    ]
    assert [len(a) for a in attacks] == [1] * SIZES[group_id]
    # The husks are told about in order, with ids from 101; each window hits its own.
    assert [a[0].fields["entity_id"] for a in attacks] == [101 + n for n in range(SIZES[group_id])]


@pytest.mark.asyncio
@pytest.mark.parametrize("group_id", FIGHTER_GROUPS)
async def test_each_case_sets_up_the_fighter_the_weapon_and_a_husk(group_id: str) -> None:
    result = await play(group_id)

    for lane, (window, weapon) in enumerate(zip(result.windows, WEAPONS[group_id], strict=True)):
        z = 2.5 + 4 * lane
        held = weapon or "minecraft:air"
        setup = [c for c in commands(window.before) if not c.startswith("tick")]
        summons = [
            f"summon minecraft:husk {x} -60 {z + dz} "
            f'{{NoAI:1b,Silent:1b,OnGround:1b,Health:20f,Tags:["mscts_combat","mscts_combat_{lane}_{n}"]}}'
            for n, (x, dz) in enumerate(((6.0, 0.0), *AROUND.get(group_id, ())))
        ]
        assert setup[-(4 + len(summons)) :] == [
            "effect give fighter minecraft:instant_health 1 10 true",
            "effect give fighter minecraft:saturation 1 10 true",
            f"tp fighter 4.5 -60 {z} -90.0 0",
            f"item replace entity fighter hotbar.0 with {held}",
            *summons,
        ]


@pytest.mark.asyncio
@pytest.mark.parametrize("group_id", FIGHTER_GROUPS)
async def test_each_case_waits_fifteen_steps_for_the_charge_and_steps_two_after_the_hit(
    group_id: str,
) -> None:
    result = await play(group_id)

    for window in result.windows:
        assert commands(window.before).count(STEP) == 15
        assert commands(window.inside).count(STEP) == 2
        names = [i.what for i in window.inside if i.what in ("minecraft:attack", STEP)]
        assert names == ["minecraft:attack", STEP, STEP]


HITTERS = {
    **dict.fromkeys(FIGHTER_GROUPS, (combat.FIGHTER,)),
    "combat/immunity": (combat.STRIKER, combat.TAPPER),
    "combat/pvp": (combat.ATTACKER,),
}


@pytest.mark.asyncio
@pytest.mark.parametrize("group_id", GROUP_IDS)
async def test_each_hit_reaches_the_server_before_the_step_after_it(group_id: str) -> None:
    result = await play(group_id)
    attacks = sum(i.what == "minecraft:attack" for window in result.windows for i in window.inside)

    barriers = [
        count
        for bot in HITTERS[group_id]
        for count in barriers_before_steps(result.transcript, bot, {"minecraft:attack"})
    ]

    assert len(barriers) == attacks > 0
    assert set(barriers) == {SYNC_REQUESTS}


# combat/knockback


@pytest.mark.asyncio
async def test_knockback_sprints_only_in_the_second_case_and_stops_after_it() -> None:
    result = await play("combat/knockback")

    def actions(items: tuple[Item, ...]) -> list[object]:
        return [i.fields["action"] for i in items if i.what == "minecraft:player_command"]

    assert actions(result.windows[0].before) == []
    assert actions(result.windows[1].before) == [START_SPRINTING]
    assert actions(result.readbacks[-1].before) == [STOP_SPRINTING]


# combat/sweep


@pytest.mark.asyncio
async def test_sweep_hits_the_first_husk_summoned_and_not_one_beside_it() -> None:
    result = await play("combat/sweep")

    (window,) = result.windows
    (attack,) = [i for i in window.inside if i.what == "minecraft:attack"]
    assert attack.fields["entity_id"] == 101


@pytest.mark.asyncio
async def test_sweep_stands_on_the_ground_and_does_not_sprint_or_fall() -> None:
    result = await play("combat/sweep")

    (window,) = result.windows
    # The Bot reports where `/tp` put it; no move leaves the ground.
    assert all(m.fields["y"] == -60.0 and on_ground(m) for m in window.inside if m.what == "move")
    assert not [i for i in sent(result.transcript) if i.what == "minecraft:player_command"]


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

    landing = [i for i in result.readbacks[0].before if i.what == "move"]
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
    assert actions(result.readbacks[-1].before) == [STOP_SPRINTING]


@pytest.mark.asyncio
async def test_control_asks_until_no_husk_is_left_then_stops() -> None:
    result = await play("combat/melee-mob")

    asked = [c for c in commands(result.after) if c.startswith("execute")]
    assert asked == ["execute if entity @e[tag=mscts_combat]"]


@pytest.mark.asyncio
async def test_control_asks_twenty_times_and_then_fails_while_a_husk_is_left() -> None:
    server = CombatServer(left="Test passed, count: 1")

    with pytest.raises(TimeoutError, match="mscts_combat was still there after 20 asks"):
        await replay("combat/melee-mob", server)

    asked = [p for p in server.seen if "execute if entity" in str((p.fields or {}).get("command"))]
    assert len(asked) == 20


# combat/immunity


def hits(window: Window) -> list[str]:
    """What happened inside the window: `<bot> hit`, and each step of the world."""
    return [
        STEP if i.what == STEP else f"{i.bot} hit"
        for i in window.inside
        if i.what in (STEP, "minecraft:attack")
    ]


@pytest.mark.asyncio
async def test_immunity_hits_a_husk_twice_with_the_steps_of_the_pair_between_the_hits() -> None:
    result = await play("combat/immunity")

    assert [hits(window) for window in result.windows] == [
        ["striker hit", *[STEP] * 5, "tapper hit", STEP, STEP],
        ["tapper hit", *[STEP] * 5, "striker hit", STEP, STEP],
        ["striker hit", *[STEP] * 11, "tapper hit", STEP, STEP],
    ]


@pytest.mark.asyncio
async def test_immunity_hits_the_same_husk_with_both_bots() -> None:
    result = await play("combat/immunity")

    for number, window in enumerate(result.windows):
        attacks = [i for i in window.inside if i.what == "minecraft:attack"]
        assert [a.fields["entity_id"] for a in attacks] == [101 + number] * 2


@pytest.mark.asyncio
async def test_immunity_stands_the_bots_either_side_of_the_lane_with_a_sword_and_a_hand() -> None:
    result = await play("combat/immunity")

    setup = [c for c in commands(result.windows[0].before) if not c.startswith("tick")]
    assert setup[-9:] == [
        "effect give striker minecraft:instant_health 1 10 true",
        "effect give striker minecraft:saturation 1 10 true",
        "tp striker 4.5 -60 2.0 -90.0 0",
        "item replace entity striker hotbar.0 with minecraft:diamond_sword",
        "effect give tapper minecraft:instant_health 1 10 true",
        "effect give tapper minecraft:saturation 1 10 true",
        "tp tapper 3.5 -60 3.0 -90.0 0",
        "item replace entity tapper hotbar.0 with minecraft:air",
        HUSK_COMMAND,
    ]


@pytest.mark.asyncio
async def test_immunity_sends_the_last_husk_away_and_summons_a_new_one_for_each_case() -> None:
    result = await play("combat/immunity")

    for window in result.windows[1:]:
        setup = [c for c in commands(window.before) if not c.startswith("tick")]
        assert setup == [
            "tp @e[type=minecraft:husk,tag=mscts_combat] 5.5 -60 24.5",
            HUSK_COMMAND,
        ]
    for window in result.windows:
        assert commands(window.before).count(STEP) == 15


# combat/pvp


@pytest.mark.asyncio
async def test_pvp_hits_the_other_bot_once_in_each_window() -> None:
    result = await play("combat/pvp")

    for window in result.windows:
        attacks = [i for i in window.inside if i.what == "minecraft:attack"]
        assert [(a.bot, a.fields["entity_id"]) for a in attacks] == [("attacker", VICTIM_ID)]
        assert commands(window.inside).count(STEP) == 2
        assert commands(window.before).count(STEP) == 15


@pytest.mark.asyncio
async def test_pvp_puts_both_bots_in_the_lane_facing_each_other() -> None:
    result = await play("combat/pvp")

    for lane, window in enumerate(result.windows):
        z = 2.5 + 4 * lane
        setup = [c for c in commands(window.before) if not c.startswith("tick")]
        assert setup[-2:] == [f"tp attacker 4.5 -60 {z} -90.0 0", f"tp victim 6.0 -60 {z} 90.0 0"]


@pytest.mark.asyncio
async def test_pvp_gives_the_attacker_a_sword_and_sprints_only_in_the_second_case() -> None:
    result = await play("combat/pvp")

    assert "item replace entity attacker hotbar.0 with minecraft:diamond_sword" in commands(
        result.first
    )
    actions = [
        [i.fields["action"] for i in w.before if i.what == "minecraft:player_command"]
        for w in result.windows
    ]
    assert actions == [[], [START_SPRINTING]]
    assert [i.fields["action"] for i in result.after if i.what == "minecraft:player_command"] == [
        STOP_SPRINTING
    ]


@pytest.mark.asyncio
async def test_pvp_heals_the_victim_before_the_first_hit() -> None:
    """A Player keeps its health from play to play, so each play starts the victim at full."""
    result = await play("combat/pvp")

    heal = "effect give victim minecraft:instant_health 1 10 true"
    assert heal in commands(result.first)


def test_a_sprinting_pvp_hit_compares_the_victims_health_but_not_the_entity_data() -> None:
    assert (*combat.PACKETS, "minecraft:set_health") == combat.PVP_PACKETS
    assert "minecraft:set_entity_data" not in combat.PVP_SPRINT_PACKETS
    assert "minecraft:set_health" in combat.PVP_SPRINT_PACKETS


class _Lookup:
    """A Bot that finds the husk only after `missing` syncs; it counts the syncs."""

    def __init__(self, missing: int) -> None:
        self.missing = missing
        self.syncs = 0
        self.entities = self

    def find(self, kind: str, *, near: tuple[float, float, float]) -> str:
        if self.syncs < self.missing:
            raise LookupError(kind)
        return f"{kind}@{near}"

    async def sync(self) -> None:
        self.syncs += 1


@pytest.mark.asyncio
async def test_a_lookup_syncs_while_the_bot_tracks_nothing_and_never_steps_the_world() -> None:
    lookup = _Lookup(missing=3)

    found = await combat.find_when_tracked(cast("Bot", lookup), "husk", (1.0, 2.0, 3.0))

    assert found == "husk@(1.0, 2.0, 3.0)"
    assert lookup.syncs == 3


@pytest.mark.asyncio
async def test_a_lookup_gives_up_after_a_few_syncs() -> None:
    lookup = _Lookup(missing=99)

    with pytest.raises(LookupError):
        await combat.find_when_tracked(cast("Bot", lookup), "husk", (0.0, 0.0, 0.0))
    assert lookup.syncs == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("group_id", GROUP_IDS)
async def test_the_steps_before_each_window_do_not_depend_on_what_the_bots_track(
    group_id: str,
) -> None:
    """A step moves every later packet a tick: it may only come from the script, not the wait."""
    result = await play(group_id)

    for window in result.windows:
        assert commands(window.before).count(STEP) == combat._CHARGE_STEPS  # noqa: SLF001


# The readback


@pytest.mark.asyncio
@pytest.mark.parametrize("group_id", FIGHTER_GROUPS)
async def test_each_hit_is_followed_by_a_readback_of_the_health_velocity_and_place_of_each_husk(
    group_id: str,
) -> None:
    result = await play(group_id)

    assert len(result.readbacks) == len(result.windows)
    for lane, window in enumerate(result.readbacks):
        husks = 1 + len(AROUND.get(group_id, ()))
        assert window.label == label((SYSTEM_CHAT,))
        tags = [f"mscts_combat_{lane}_{n}" for n in range(husks)]
        copy = "data modify storage mscts:combat r.{tag}.{path} set from entity"
        assert commands(window.inside, "fighter") == [
            command
            for tag in tags
            for command in (
                *(
                    f"{copy.format(tag=tag, path=path)} @e[tag={tag},limit=1] {path}"
                    for path in ("Health", "Motion", "Pos")
                ),
                f"data get storage mscts:combat r.{tag}",
            )
        ]


@pytest.mark.asyncio
@pytest.mark.parametrize("group_id", FIGHTER_GROUPS)
async def test_the_readback_comes_after_the_hit_window_and_before_the_next_lane(
    group_id: str,
) -> None:
    result = await play(group_id)

    for back in result.readbacks:
        assert not [i for i in back.inside if i.what in ("minecraft:attack", STEP)]


def test_the_fighter_reads_back_and_no_group_but_pvp_masks_a_pitch() -> None:
    assert [g for g in GROUP_IDS if GROUPS[g].masks] == ["combat/pvp"]
