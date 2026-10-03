"""What every Adapter writes into the Fixture world besides its own config (ADR-0013).

Natural mob spawning is off from the first tick. A mob near the spawn plays its sounds at
random and vanilla sends them to every player within 16 blocks, so mobs that spawn on
their own make Groups differ by chance (docs/research/2026-10-03-join-sounds.md). A Group
that tests natural spawning turns it on itself.
"""

from mscts.adapters import nbt

WORLD_FOLDER = "world"
"""The Fixture world's folder, under the server's cwd: every Adapter names it in its config."""

GAME_RULES_DAT = f"{WORLD_FOLDER}/data/minecraft/game_rules.dat"
"""Where vanilla 26.3 and Pumpkin read a world's game rules, under the server's cwd.

Vanilla loads it as the saved data `minecraft:game_rules` when it starts, new world or
not, and gives every rule the file leaves out its default (`GameRules`, 26.3 javap).
Pumpkin reads its `data` compound the same way (`read_game_rules`).
"""


def game_rules(data_version: int) -> nbt.Compound:
    """The game_rules.dat of the Fixture world, stamped with the server's `data_version`."""
    return {
        "data": {"minecraft:spawn_mobs": nbt.Byte(0)},
        "DataVersion": nbt.Int(data_version),
    }
