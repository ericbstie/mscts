from pathlib import Path

import pytest

from mscts.adapters.base import Installation
from mscts.adapters.vanilla import VanillaAdapter
from mscts.spec import Difficulty, GameMode, ServerSpec
from mscts.target import TARGET

# Every key vanilla 26.3 writes to server.properties on first run (observed 2026-09-25).
VANILLA_26_3_KEYS = frozenset(
    [
        "accepts-transfers",
        "allow-flight",
        "broadcast-console-to-ops",
        "broadcast-rcon-to-ops",
        "bug-report-link",
        "chat-spam-threshold-seconds",
        "command-spam-threshold-seconds",
        "difficulty",
        "enable-code-of-conduct",
        "enable-jmx-monitoring",
        "enable-query",
        "enable-rcon",
        "enable-status",
        "enforce-secure-profile",
        "enforce-whitelist",
        "entity-broadcast-range-percentage",
        "force-gamemode",
        "function-permission-level",
        "gamemode",
        "generate-structures",
        "generator-settings",
        "hardcore",
        "hide-online-players",
        "initial-disabled-packs",
        "initial-enabled-packs",
        "level-name",
        "level-seed",
        "level-type",
        "log-ips",
        "management-server-allowed-origins",
        "management-server-enabled",
        "management-server-host",
        "management-server-port",
        "management-server-secret",
        "management-server-tls-enabled",
        "management-server-tls-keystore",
        "management-server-tls-keystore-password",
        "max-chained-neighbor-updates",
        "max-players",
        "max-tick-time",
        "max-world-size",
        "motd",
        "network-compression-threshold",
        "online-mode",
        "op-permission-level",
        "pause-when-empty-seconds",
        "player-idle-timeout",
        "prevent-proxy-connections",
        "query.port",
        "rate-limit",
        "rcon.password",
        "rcon.port",
        "region-file-compression",
        "require-resource-pack",
        "resource-pack",
        "resource-pack-id",
        "resource-pack-prompt",
        "resource-pack-sha1",
        "server-ip",
        "server-port",
        "simulation-distance",
        "spawn-protection",
        "status-heartbeat-interval",
        "sync-chunk-writes",
        "text-filtering-config",
        "text-filtering-version",
        "use-native-transport",
        "view-distance",
        "white-list",
    ]
)

# What every Reference Instance must be, whatever the ServerSpec says. Values as written
# (escaped) in the file.
INVARIANTS = {
    "online-mode": "false",
    "enforce-secure-profile": "false",
    "white-list": "false",
    "enforce-whitelist": "false",
    "pause-when-empty-seconds": "0",
    "spawn-protection": "0",
    "player-idle-timeout": "0",
    "enable-status": "true",
    "hide-online-players": "false",
    "generate-structures": "false",
    "enable-rcon": "false",
    "enable-query": "false",
    "management-server-enabled": "false",
    "server-ip": "127.0.0.1",
}

UNUSUAL_SPEC = ServerSpec(
    port=41234,
    motd="\xa76a=b: c",
    max_players=3,
    view_distance=5,
    simulation_distance=4,
    seed=-42,
    game_mode=GameMode.CREATIVE,
    difficulty=Difficulty.HARD,
    operators=("Notch",),
    compression_threshold=-1,
)


def properties(tmp_path: Path, spec: ServerSpec) -> dict[str, str]:
    """Prepare `spec` and return server.properties as key -> escaped value."""
    installation = Installation(adapter="vanilla", target=TARGET, root=tmp_path / "cache")
    workdir = tmp_path / "work"
    VanillaAdapter().prepare(installation, spec, workdir)
    header, *lines = (workdir / "server.properties").read_text(encoding="ascii").splitlines()
    assert header.startswith("#")
    entries = dict(line.split("=", 1) for line in lines)
    assert len(entries) == len(lines), "duplicate key"
    return entries


def test_default_spec_file_is_vanillas_own_defaults_plus_documented_overrides(
    tmp_path: Path,
) -> None:
    # The golden file is vanilla 26.3's pristine first-run server.properties (date line
    # dropped) with only the ServerSpec keys, the invariants and the random management
    # secret substituted. Vanilla rewrote prepare's output byte-identically (apart from
    # its date line), so every value and escape here is what vanilla itself reads back.
    golden = Path(__file__).with_name("data") / "server-26.3-default-spec.properties"
    installation = Installation(adapter="vanilla", target=TARGET, root=tmp_path / "cache")
    VanillaAdapter().prepare(installation, ServerSpec(port=25599), tmp_path / "work")
    written = (tmp_path / "work/server.properties").read_text(encoding="ascii")
    assert written == golden.read_text(encoding="ascii")


@pytest.mark.parametrize("spec", [ServerSpec(port=25599), UNUSUAL_SPEC])
def test_writes_exactly_the_keys_vanilla_26_3_writes(tmp_path: Path, spec: ServerSpec) -> None:
    assert set(properties(tmp_path, spec)) == VANILLA_26_3_KEYS


@pytest.mark.parametrize("spec", [ServerSpec(port=25599), UNUSUAL_SPEC])
@pytest.mark.parametrize(("key", "value"), INVARIANTS.items())
def test_invariant_holds_whatever_the_spec(
    tmp_path: Path, spec: ServerSpec, key: str, value: str
) -> None:
    assert properties(tmp_path, spec)[key] == value


def test_spec_fields_are_translated(tmp_path: Path) -> None:
    entries = properties(tmp_path, UNUSUAL_SPEC)
    assert {key: entries[key] for key in TRANSLATED} == TRANSLATED


TRANSLATED = {
    "server-port": "41234",
    "motd": "\\u00A76a\\=b\\: c",
    "max-players": "3",
    "view-distance": "5",
    "simulation-distance": "4",
    "level-seed": "-42",
    "gamemode": "creative",
    "difficulty": "hard",
    "network-compression-threshold": "-1",
    "level-type": "minecraft\\:flat",
    "generator-settings": "{}",
}


@pytest.mark.parametrize(
    ("mode", "value"),
    [
        (GameMode.SURVIVAL, "survival"),
        (GameMode.CREATIVE, "creative"),
        (GameMode.ADVENTURE, "adventure"),
        (GameMode.SPECTATOR, "spectator"),
    ],
)
def test_game_mode_is_translated(tmp_path: Path, mode: GameMode, value: str) -> None:
    assert properties(tmp_path, ServerSpec(port=25599, game_mode=mode))["gamemode"] == value


@pytest.mark.parametrize(
    ("level", "value"),
    [
        (Difficulty.PEACEFUL, "peaceful"),
        (Difficulty.EASY, "easy"),
        (Difficulty.NORMAL, "normal"),
        (Difficulty.HARD, "hard"),
    ],
)
def test_difficulty_is_translated(tmp_path: Path, level: Difficulty, value: str) -> None:
    assert properties(tmp_path, ServerSpec(port=25599, difficulty=level))["difficulty"] == value
