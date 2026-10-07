"""Block and world events, caused through Control inside Observation windows (#29).

The live tests play the same script against vanilla (every packet of the issue must decode
strictly) and Pumpkin (what it sends is listed as evidence): a watcher Bot joins, and Control
runs the commands that make a server send block and world events. Setup commands run before a
window, so only the command that causes the event is inside it.
"""

from dataclasses import dataclass

from mscts.codec.packets import Codec, CodecError, Direction, Packet, State
from mscts.codec.wire import Writer
from mscts.group import CommandMissing, GroupContext
from mscts.target import TARGET
from mscts.transcript import Transcript
from support.window import window_since

WATCHER = "watcher"
"""The Bot whose packets are looked at."""

CODEC = Codec.for_target(TARGET)

PACKETS = frozenset(
    f"minecraft:{name}"
    for name in (
        "block_update",
        "section_blocks_update",
        "block_entity_data",
        "block_event",
        "block_destruction",
        "level_event",
        "sound",
        "sound_entity",
        "level_particles",
        "game_event",
        "explode",
    )
)
"""The packets of #29: the ones whose decoding is looked at."""


@dataclass(frozen=True, slots=True)
class Scenario:
    """One window: what Control sets up outside it, and runs inside it.

    Attributes:
        name: What it does, for a failure message.
        setup: Commands that run before the window opens.
        commands: Commands that run inside the window, and cause what is looked at.
        expects: Packets the watcher must get inside the window.
    """

    name: str
    setup: tuple[str, ...]
    commands: tuple[str, ...]
    expects: frozenset[str]


PRELUDE = ("gamerule random_tick_speed 0", "setblock 8 -60 8 minecraft:note_block")
"""Commands that run before the first window, which is also when Control joins: random ticks off,
and the note block the third Scenario plays.

With random ticks on, a grass block under a placed block can turn to dirt in the tick that sends
the placement, and vanilla sends two changes to one section in one tick as a
`section_blocks_update`, not a `block_update` (`ChunkHolder.broadcastChanges`, #303). The test
boots an Instance of its own, so nothing turns them back on."""

SCENARIOS = (
    Scenario(
        name="setblock",
        setup=(),
        commands=("setblock 1 -60 1 minecraft:stone",),
        expects=frozenset({"minecraft:block_update"}),
    ),
    Scenario(
        name="fill",
        setup=(),
        commands=("fill 2 -60 2 3 -59 3 minecraft:stone",),
        expects=frozenset({"minecraft:section_blocks_update"}),
    ),
    Scenario(
        name="a note block played by a redstone block",
        setup=(),
        commands=("setblock 9 -60 8 minecraft:redstone_block",),
        expects=frozenset({"minecraft:block_event", "minecraft:sound"}),
    ),
    Scenario(
        name="a TNT explosion near the Bot",
        setup=(),
        commands=(f"execute at {WATCHER} run summon tnt ~3 ~ ~ {{fuse:1}}",),
        expects=frozenset({"minecraft:explode"}),
    ),
)
"""The windows, in order: each one's setup leaves the world as the next one needs it."""


@dataclass(frozen=True, slots=True)
class Played:
    """What the watcher got inside one Scenario's window.

    Attributes:
        scenario: The Scenario.
        packets: The packets of `PACKETS` the watcher received inside the window, in order.
        missing: The command the server has no such command for, if Control raised
            `CommandMissing`: nothing of the Scenario ran after it.
        error: Why a Bot could not decode a packet, if one failed: a Bot that got a packet
            the Codec refuses is failed, so nothing of the Scenario or after it ran.
    """

    scenario: Scenario
    packets: tuple[Packet, ...]
    missing: str = ""
    error: str = ""

    @property
    def names(self) -> frozenset[str]:
        """The names of the packets that arrived."""
        return frozenset(packet.name for packet in self.packets)


async def play(context: GroupContext, transcript: Transcript) -> tuple[Played, ...]:
    """Join the watcher and play each of `SCENARIOS` through Control, a window each."""
    watcher = await context.bot(WATCHER)
    await watcher.join()
    for command in PRELUDE:
        await context.control.run(command)
    played = []
    for scenario in SCENARIOS:
        since = transcript.now_ns()
        try:
            for command in scenario.setup:
                await context.control.run(command)
            async with context.observe(*sorted(PACKETS)):
                for command in scenario.commands:
                    await context.control.run(command)
        except CommandMissing as missing:
            played.append(Played(scenario, _watched(transcript, since), missing=missing.root))
            continue
        except CodecError as refused:
            played.append(Played(scenario, _watched(transcript, since), error=str(refused)))
            break
        played.append(Played(scenario, _watched(transcript, since)))
    return tuple(played)


def _watched(transcript: Transcript, since_ns: int) -> tuple[Packet, ...]:
    """The packets of `PACKETS` the watcher received in the window that opened since."""
    return tuple(
        event.packet
        for event in window_since(transcript, WATCHER, since_ns)
        if event.packet.direction is Direction.CLIENTBOUND and event.packet.name in PACKETS
    )


def undecoded(played: tuple[Played, ...]) -> list[str]:
    """Every packet that did not decode into fields and encode back to its bytes, and why."""
    problems = []
    for one in played:
        if one.error:
            problems.append(f"{one.scenario.name}: {one.error}")
        for packet in one.packets:
            where = f"{one.scenario.name}: {packet.name}"
            if packet.decode_error is not None or packet.fields is None:
                problems.append(f"{where}: {packet.decode_error or 'no fields'}")
                continue
            again = CODEC.encode(State.PLAY, Direction.CLIENTBOUND, packet.name, packet.fields)
            if again != Writer().var_int(packet.packet_id).to_bytes() + packet.payload:
                problems.append(f"{where}: encodes to other bytes than it was decoded from")
    return problems
