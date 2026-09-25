"""ServerSpec: a server-agnostic, declarative description of a server's configuration."""

from dataclasses import dataclass
from enum import StrEnum, auto


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
    """

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
