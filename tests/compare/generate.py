"""Seeded random Scripts and Transcripts for property tests.

A Script is the deterministic part of a run: for each Bot, the packets it receives,
by content. `render` turns a Script into a Transcript and chooses everything a re-run
may change at random: the masked fields, how many ambient (dropped) packets arrive and
where, the serverbound packets, the Bots' interleaving, the timestamps, and how the
status JSON is spelled (key order, whitespace, and each description text as `"x"` or
`{"text": "x"}`). Every Packet is built through a real Codec: the Target's for status
packets, a toy one for play packets.
"""

import json
import random
import time
from collections.abc import Mapping, Sequence

from mscts.codec.packets import Codec, Direction, Packet, State
from mscts.codec.schema import LONG, VAR_INT, Schema, String
from mscts.codec.wire import Writer
from mscts.compare import Mask
from mscts.transcript import Transcript

SCENARIO = "test/properties"
CLIENTBOUND, SERVERBOUND = Direction.CLIENTBOUND, Direction.SERVERBOUND

STATUS_CODEC = Codec.load("26.3")
TOY_CODEC = Codec(
    {
        (State.PLAY, CLIENTBOUND): {
            "test:entity": 0x00,
            "test:chat": 0x01,
            "test:nested": 0x02,
            "test:raw": 0x03,
            "test:tick": 0x04,
        },
        (State.PLAY, SERVERBOUND): {"test:action": 0x00},
    },
    schemas={
        (State.PLAY, CLIENTBOUND): {
            "test:entity": Schema(entity_id=VAR_INT, x=LONG),
            "test:chat": Schema(text=String(64)),
            "test:nested": Schema(outer=VAR_INT, inner=Schema(seed=LONG, name=String(16))),
            "test:tick": Schema(time=LONG),
        },
        (State.PLAY, SERVERBOUND): {"test:action": Schema(value=VAR_INT)},
    },
)
"""Play packets: four with schemas, and `test:raw`, which has none."""

MASKS = (
    Mask(packet="test:entity", path="entity_id", reason="entity ids are allocated freely"),
    Mask(packet="test:nested", path="inner.seed", reason="a random seed"),
    Mask(packet="test:tick", path="*", reason="ambient: arrives on the server's clock"),
    Mask(
        packet="minecraft:status_response",
        path="json_response.players.sample",
        reason="who is online varies",
    ),
)
"""What `render` varies between re-runs, besides what compare never looks at."""

type Item = tuple[object, ...]
"""One received packet, by content: its kind first, then what fixes it."""

type Script = Mapping[str, Sequence[Item]]
"""The packets each Bot receives, in order."""

_WORDS = ("hi", "yo", "mscts", "")
_BOTS = ("alice", "bob", "carol")


def seeded(seed: int) -> random.Random:
    """A generator of reproducible test data for `seed`."""
    return random.Random(seed)  # noqa: S311  # seeded to reproduce test data, not for secrets


def script(rng: random.Random, *, most: int = 10) -> Script:
    """A Script of 1 to 3 Bots, each receiving up to `most` packets from a small alphabet."""
    bots = rng.sample(_BOTS, rng.randint(1, len(_BOTS)))
    return {bot: [_item(rng) for _ in range(rng.randint(0, most))] for bot in bots}


def _item(rng: random.Random) -> Item:
    kind = rng.choice(("entity", "chat", "nested", "raw", "pong", "status"))
    if kind == "entity":
        return (kind, rng.randint(-1, 1))
    if kind == "chat":
        return (kind, rng.choice(_WORDS))
    if kind == "nested":
        return (kind, rng.randint(0, 1), rng.choice(_WORDS))
    if kind == "raw":
        return (kind, bytes(rng.choice(((), (1,), (1, 2)))))
    if kind == "pong":
        return (kind, rng.choice((0, -1, 2**63 - 1)))
    return (kind, rng.choice(_WORDS), rng.choice((20, 1000)), rng.randint(0, 1))


def render(
    script: Script, rng: random.Random, *, server: str = "vanilla", scenario_id: str = SCENARIO
) -> Transcript:
    """A Transcript of `script`, with every detail a re-run may change chosen by `rng`."""
    streams = []
    for bot, items in script.items():
        # A Bot always sends first (its handshake), so it is in every run's Transcript.
        events: list[tuple[str, Packet]] = [(bot, _toy(SERVERBOUND, "test:action", value=0))]
        for item in items:
            events.extend((bot, packet) for packet in _ambient(rng))
            events.append((bot, _packet(item, rng)))
        events.extend((bot, packet) for packet in _ambient(rng))
        streams.append(events)
    transcript = Transcript(
        scenario_id=scenario_id, server=server, start_ns=time.monotonic_ns() - 10**12
    )
    t_ns = 0
    for bot, packet in _interleave(streams, rng):
        t_ns += rng.randrange(1, 10**6)
        transcript.record(bot, packet, t_ns=t_ns)
    return transcript


def _ambient(rng: random.Random) -> list[Packet]:
    """Zero to two dropped ticks and serverbound actions, in random order."""
    ticks = [_toy(CLIENTBOUND, "test:tick", time=rng.randrange(2**40))] * rng.randint(0, 2)
    actions = [_toy(SERVERBOUND, "test:action", value=rng.randrange(100))] * rng.randint(0, 1)
    ambient = ticks + actions
    rng.shuffle(ambient)
    return ambient


def _packet(item: Item, rng: random.Random) -> Packet:
    match item:
        case ("entity", x):
            return _toy(CLIENTBOUND, "test:entity", entity_id=rng.randrange(2**31), x=x)
        case ("chat", text):
            return _toy(CLIENTBOUND, "test:chat", text=text)
        case ("nested", outer, name):
            inner = {"seed": rng.randrange(-(2**63), 2**63), "name": name}
            return _toy(CLIENTBOUND, "test:nested", outer=outer, inner=inner)
        case ("raw", bytes() as payload):
            data = Writer().var_int(TOY_CODEC.packet_id(State.PLAY, CLIENTBOUND, "test:raw"))
            return TOY_CODEC.decode(State.PLAY, CLIENTBOUND, data.to_bytes() + payload)
        case ("pong", timestamp):
            return _status("minecraft:pong_response", timestamp=timestamp)
        case ("status", description, most, online):
            return _status(
                "minecraft:status_response",
                json_response=_status_json(str(description), most, online, rng),
            )
        case _:
            msg = f"no such item {item!r}"
            raise ValueError(msg)


def _status_json(description: str, most: object, online: object, rng: random.Random) -> str:
    sample = [{"name": rng.choice(_WORDS), "id": "00000000-0000-0000-0000-000000000000"}]
    status: dict[str, object] = {
        "description": description if rng.random() < 0.5 else {"text": description},
        "players": {"max": most, "online": online, "sample": sample * rng.randint(0, 2)},
        "version": {"name": "26.3", "protocol": 777},
    }
    indent = rng.choice((None, 0, 2))
    separators = rng.choice(((",", ":"), (", ", ": "), (" ,", " : ")))
    return json.dumps(_shuffled(status, rng), indent=indent, separators=separators)


def _shuffled(value: object, rng: random.Random) -> object:
    """`value` with every JSON object's keys in a random order."""
    if isinstance(value, dict):
        items = [(str(key), _shuffled(item, rng)) for key, item in value.items()]
        rng.shuffle(items)
        return dict(items)
    if isinstance(value, list):
        return [_shuffled(item, rng) for item in value]
    return value


def _toy(direction: Direction, name: str, **fields: object) -> Packet:
    data = TOY_CODEC.encode(State.PLAY, direction, name, fields)
    return TOY_CODEC.decode(State.PLAY, direction, data)


def _status(name: str, **fields: object) -> Packet:
    data = STATUS_CODEC.encode(State.STATUS, CLIENTBOUND, name, fields)
    return STATUS_CODEC.decode(State.STATUS, CLIENTBOUND, data)


def _interleave(
    streams: list[list[tuple[str, Packet]]], rng: random.Random
) -> list[tuple[str, Packet]]:
    """Merge the streams in a random order that keeps each stream's own order."""
    pending = [list(reversed(stream)) for stream in streams if stream]
    merged: list[tuple[str, Packet]] = []
    while pending:
        chosen = pending[rng.randrange(len(pending))]
        merged.append(chosen.pop())
        pending = [stream for stream in pending if stream]
    return merged
