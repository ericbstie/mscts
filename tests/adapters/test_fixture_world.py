"""Every Adapter writes the game_rules.dat vanilla and Pumpkin read, with spawning off.

ADR-0013. This checks the file only. Whether a server honours it is checked live: the
reference probe's QUERY Group and test_pumpkin_control.py ask for `spawn_mobs`.
"""

from pathlib import Path

import pytest
from support.nbt_read import read_gzipped

from mscts.adapters.base import Installation
from mscts.cli import ADAPTERS
from mscts.spec import ServerSpec
from mscts.target import TARGET

GAME_RULES = "world/data/minecraft/game_rules.dat"
"""Where vanilla 26.3 and Pumpkin read a world's game rules (a saved data file)."""

# prepare looks up a Java launcher for vanilla; a fake Java 25 keeps the unit tier off the host's.
pytestmark = pytest.mark.usefixtures("java_25")


@pytest.mark.parametrize("name", sorted(ADAPTERS))
def test_every_adapter_writes_a_world_where_no_mob_spawns_on_its_own(
    name: str, tmp_path: Path
) -> None:
    installation = Installation(adapter=name, target=TARGET, root=tmp_path / "cache")
    workdir = tmp_path / "work"
    ADAPTERS[name]().prepare(installation, ServerSpec(host="127.0.0.1", port=25599), workdir)

    saved = read_gzipped((workdir / GAME_RULES).read_bytes())

    rules = saved["data"]
    assert isinstance(rules, dict), saved
    assert rules["minecraft:spawn_mobs"] == 0, saved  # a Byte: false
