"""Reaching a server over the network."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Endpoint:
    """Where an Instance can be reached."""

    host: str
    port: int
