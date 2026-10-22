"""Reading what a Transcript recorded."""

from mscts.codec.packets import Direction
from mscts.transcript import Transcript


def arrivals(transcript: Transcript, name: str) -> list[int]:
    return [
        event.t_ns
        for event in transcript.events
        if event.packet.name == name and event.packet.direction is Direction.CLIENTBOUND
    ]
