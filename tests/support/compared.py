"""Packets and Verdicts the Comparison tests build."""

from mscts.codec.packets import Packet, State
from mscts.compare import Verdict, compare
from support.play import CLIENTBOUND, CODEC
from tests.compare.build import packet, transcript

VANILLA = (
    '{"description":"mscts","players":{"max":20,"online":0},'
    '"version":{"name":"26.3","protocol":777}}'
)
"""What vanilla 26.3 answered for the default ServerSpec (docs/research, verified)."""


PUMPKIN_NIGHTLY = (
    '{"version":{"name":"26.3","protocol":777},'
    '"players":{"max":20,"online":0,"sample":[]},'
    '"description":{"text":"mscts"},"favicon":null,"enforceSecureChat":true}'
)
"""Shaped like Pumpkin nightly-48cba7ee's live status: a null favicon, and a misspelled
`enforceSecureChat` the client's codec never reads (docs/research)."""


def status(json_response: str) -> Packet:
    data = CODEC.encode(
        State.STATUS, CLIENTBOUND, "minecraft:status_response", {"json_response": json_response}
    )
    return CODEC.decode(State.STATUS, CLIENTBOUND, data)


def verdict_of(reference: Packet, candidate: Packet) -> Verdict:
    return compare(transcript(("alice", reference)), transcript(("alice", candidate)), [])


def block(state: int) -> Packet:
    return packet("minecraft:block_update", bytes([state]))
