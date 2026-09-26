"""ServerSpec: a server-agnostic, declarative description of a server's configuration."""

import ipaddress
from dataclasses import dataclass
from enum import StrEnum, auto

# Every Instance listens on a host of this network only. Offline, anyone who can reach
# the port can log in under an operator's name, so no Instance is reachable from any
# network; and each Instance gets a host of its own (runner.free_endpoint).
LOOPBACK = ipaddress.IPv4Network("127.0.0.0/8")


class WorldPreset(StrEnum):
    """The world a server generates. VOID arrives once it is verified on the Reference."""

    FLAT = auto()


class GameMode(StrEnum):
    """The game mode players are in."""

    SURVIVAL = auto()
    CREATIVE = auto()
    ADVENTURE = auto()
    SPECTATOR = auto()


class Difficulty(StrEnum):
    """The world difficulty."""

    PEACEFUL = auto()
    EASY = auto()
    NORMAL = auto()
    HARD = auto()


@dataclass(frozen=True, slots=True)
class ServerSpec:
    """How a server must be configured.

    Offline mode, no encryption, no whitelist, no pause when empty, no telemetry,
    no server icon and spawn protection 0 are invariants every Adapter enforces,
    so they are not fields.

    `host` and `port` are the Endpoint: the server binds exactly them. `host` must be a
    host address of LOOPBACK, written as a dotted quad (ValueError otherwise).
    """

    host: str
    port: int
    motd: str = "mscts"
    max_players: int = 20
    view_distance: int = 2
    simulation_distance: int = 2
    world: WorldPreset = WorldPreset.FLAT
    seed: int = 0
    game_mode: GameMode = GameMode.SURVIVAL
    difficulty: Difficulty = Difficulty.PEACEFUL
    operators: tuple[str, ...] = ()
    compression_threshold: int = 256

    def __post_init__(self) -> None:
        """Refuse a host that is not a host address of LOOPBACK."""
        if not _is_loopback_host(self.host):
            msg = (
                f"ServerSpec.host={self.host!r} is not a host address of {LOOPBACK} (a dotted "
                "quad, neither its network nor its broadcast address): an Instance listens on "
                "loopback only"
            )
            raise ValueError(msg)


def _is_loopback_host(host: object) -> bool:
    if not isinstance(host, str):
        return False
    try:
        address = ipaddress.IPv4Address(host)
    except ValueError:
        return False
    return LOOPBACK.network_address < address < LOOPBACK.broadcast_address
