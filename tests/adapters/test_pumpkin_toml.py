import dataclasses
import tomllib
from collections.abc import Iterator, Mapping
from importlib import resources
from pathlib import Path

import pytest

from mscts.adapters.base import PrepareError
from mscts.adapters.pumpkin import INVARIANTS as PUMPKIN_INVARIANTS
from mscts.adapters.pumpkin import (
    VANILLA_EQUIVALENTS,
    _put,
    pumpkin_defaults,
    pumpkin_toml,
    toml_document,
)
from mscts.spec import Difficulty, GameMode, ServerSpec

GOLDEN = Path(__file__).with_name("data") / "pumpkin-26.3-default-spec.toml"

# What every Pumpkin Instance must be, whatever the ServerSpec says (dotted TOML paths).
INVARIANTS = {
    "networking.java.enabled": True,
    "networking.java.online_mode": False,
    "networking.java.encryption": False,  # else it sends an encryption request, even offline
    "networking.bedrock.enabled": False,
    "networking.query.enabled": False,
    "networking.rcon.enabled": False,
    "networking.lan_broadcast.enabled": False,
    "networking.proxy.enabled": False,
    "networking.proxy.velocity.enabled": False,
    "networking.proxy.bungeecord.enabled": False,
    "networking.proxy.vine.enabled": False,
    "telemetry.enabled": False,
    "plugins.enabled": False,
    "allow_chat_reports": False,
    "white_list": False,
    "enforce_whitelist": False,
    "spawn_protection": 0,
    "use_favicon": False,
    "commands.use_console": True,  # the LaunchPlan stops Pumpkin with `stop` on stdin
}

UNUSUAL_SPEC = ServerSpec(
    port=41234,
    motd='\xa76a=b: c "q" \\ #',
    max_players=3,
    view_distance=5,
    simulation_distance=4,
    seed=-42,
    game_mode=GameMode.CREATIVE,
    difficulty=Difficulty.HARD,
    operators=("Notch",),
    compression_threshold=-1,
)


def table(value: object) -> dict[str, object]:
    """`value`, a TOML table, typed."""
    assert isinstance(value, dict)
    return {str(key): item for key, item in value.items()}


def parsed(spec: ServerSpec) -> dict[str, object]:
    return table(tomllib.loads(pumpkin_toml(spec)))


def at(document: Mapping[str, object], dotted: str) -> object:
    value: object = document
    for key in dotted.split("."):
        value = table(value)[key]
    return value


def key_paths(document: Mapping[str, object], prefix: str = "") -> Iterator[str]:
    for key, value in document.items():
        if isinstance(value, dict) and value:
            yield from key_paths(table(value), f"{prefix}{key}.")
        else:
            yield f"{prefix}{key}"


def test_the_pinned_defaults_render_as_pumpkins_first_run_file_byte_for_byte() -> None:
    # data/pumpkin.toml is what the nightly (commit a4d6465) wrote on its first run. The
    # renderer reproduces Pumpkin's own serialization of it exactly.
    pristine = resources.files("mscts.adapters").joinpath("data", "pumpkin.toml")
    assert toml_document(pumpkin_defaults()) == pristine.read_text(encoding="utf-8")


def test_default_spec_file_is_pumpkins_own_defaults_plus_documented_substitutions() -> None:
    # The golden file is Pumpkin's pristine first-run pumpkin.toml with only these lines
    # substituted (every other line is byte-identical):
    # - ServerSpec: seed (random) "0"; default_difficulty "Peaceful"; [networking.java]
    #   address "127.0.0.1:25599", max_players 20, view_distance 2, simulation_distance 2,
    #   motd "mscts" (compression threshold 256 is Pumpkin's default too).
    # - Invariants: use_favicon, spawn_protection 0; [networking.java] online_mode and
    #   encryption false; [networking.bedrock] enabled false; [plugins] and [telemetry]
    #   enabled false.
    # - Vanilla 26.3's values: accepts_transfers false (accepts-transfers=false);
    #   scrub_ips false (log-ips=true); [world.chunk.compression] algorithm "ZLib"
    #   (region-file-compression=deflate); [networking.java.compression] level 6 (vanilla's
    #   Deflater() default); [networking.java.packet_limiter] enabled false (rate-limit=0);
    #   [server_links] enabled false, bug_report "" (bug-report-link= is empty, so vanilla
    #   sends no server_links packet); [fun] april_fools false (no date-dependent chat).
    assert pumpkin_toml(ServerSpec(port=25599)) == GOLDEN.read_text(encoding="utf-8")


@pytest.mark.parametrize("spec", [ServerSpec(port=25599), UNUSUAL_SPEC])
def test_writes_exactly_the_keys_pumpkin_writes(spec: ServerSpec) -> None:
    # A key Pumpkin does not know is kept but ignored; a key it misses gets its default.
    golden = table(tomllib.loads(GOLDEN.read_text(encoding="utf-8")))
    assert sorted(key_paths(parsed(spec))) == sorted(key_paths(golden))


@pytest.mark.parametrize("spec", [ServerSpec(port=25599), UNUSUAL_SPEC])
@pytest.mark.parametrize(("path", "value"), INVARIANTS.items())
def test_invariant_holds_whatever_the_spec(spec: ServerSpec, path: str, value: object) -> None:
    written = at(parsed(spec), path)
    assert (type(written), written) == (type(value), value)


def test_spec_fields_are_translated() -> None:
    document = parsed(UNUSUAL_SPEC)
    assert {path: at(document, path) for path in TRANSLATED} == TRANSLATED


TRANSLATED = {
    "networking.java.address": "127.0.0.1:41234",
    "networking.java.motd": '\xa76a=b: c "q" \\ #',
    "networking.java.max_players": 3,
    "networking.java.view_distance": 5,
    "networking.java.simulation_distance": 4,
    "seed": "-42",
    "default_gamemode": "Creative",
    "default_difficulty": "Hard",
    "networking.java.compression.enabled": False,
}


@pytest.mark.parametrize(
    ("mode", "value"),
    [
        (GameMode.SURVIVAL, "Survival"),
        (GameMode.CREATIVE, "Creative"),
        (GameMode.ADVENTURE, "Adventure"),
        (GameMode.SPECTATOR, "Spectator"),
    ],
)
def test_game_mode_is_translated(mode: GameMode, value: str) -> None:
    assert parsed(ServerSpec(port=25599, game_mode=mode))["default_gamemode"] == value


@pytest.mark.parametrize(
    ("level", "value"),
    [
        (Difficulty.PEACEFUL, "Peaceful"),
        (Difficulty.EASY, "Easy"),
        (Difficulty.NORMAL, "Normal"),
        (Difficulty.HARD, "Hard"),
    ],
)
def test_difficulty_is_translated(level: Difficulty, value: str) -> None:
    assert parsed(ServerSpec(port=25599, difficulty=level))["default_difficulty"] == value


@pytest.mark.parametrize(
    ("threshold", "enabled", "written"),
    [(-1, False, 256), (-5, False, 256), (0, True, 0), (256, True, 256), (1024, True, 1024)],
)
def test_compression_threshold_is_translated(threshold: int, enabled: bool, written: int) -> None:  # noqa: FBT001
    # Vanilla disables compression for any negative threshold. Pumpkin has a switch for it,
    # and its (then unused) threshold stays at its default.
    document = parsed(ServerSpec(port=25599, compression_threshold=threshold))
    compression = at(document, "networking.java.compression")
    assert compression == {"enabled": enabled, "threshold": written, "level": 6}


@pytest.mark.parametrize(
    "motd",
    ['"quoted"', "back\\slash", "line\nbreak", "tab\there", "\x00\x01\x1f\x7f", "\xa76\U0001f383"],
)
def test_motd_reads_back_exactly(motd: str) -> None:
    assert at(parsed(ServerSpec(port=25599, motd=motd)), "networking.java.motd") == motd


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("port", 0),
        ("port", 65536),
        ("max_players", -1),
        ("max_players", 2**32),
        ("view_distance", 1),
        ("view_distance", 65),
        ("simulation_distance", 0),
        ("simulation_distance", 256),
        ("seed", 2**63),
        ("seed", -(2**63) - 1),
        ("compression_threshold", 2**32),
        ("motd", "\ud800"),
        ("motd", 5),
        ("port", True),
    ],
)
def test_a_value_pumpkin_cannot_read_is_refused(field: str, value: object) -> None:
    # Pumpkin replaces its WHOLE config with its defaults (online mode, encryption,
    # telemetry and Bedrock on) when one value does not fit its type, and only logs it.
    spec = dataclasses.replace(ServerSpec(port=25599), **{field: value})
    with pytest.raises(PrepareError, match=rf"ServerSpec\.{field}"):
        pumpkin_toml(spec)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("port", 1),
        ("port", 65535),
        ("max_players", 0),
        ("max_players", 2**32 - 1),
        ("view_distance", 2),
        ("view_distance", 64),
        ("simulation_distance", 1),
        ("simulation_distance", 255),
        ("seed", 2**63 - 1),
        ("seed", -(2**63)),
        ("compression_threshold", 2**32 - 1),
    ],
)
def test_the_edges_of_what_pumpkin_can_read_are_accepted(field: str, value: object) -> None:
    pumpkin_toml(dataclasses.replace(ServerSpec(port=25599), **{field: value}))


@pytest.mark.parametrize(
    ("path", "value"), [*VANILLA_EQUIVALENTS.items(), *PUMPKIN_INVARIANTS.items()]
)
def test_every_table_entry_is_a_key_pumpkin_writes_with_a_value_of_its_type(
    path: str, value: object
) -> None:
    # Pumpkin keeps an unknown key but ignores it, and falls back to its default config on
    # a value of the wrong type.
    assert type(value) is type(at(pumpkin_defaults(), path))


def test_setting_a_key_pumpkin_does_not_write_is_a_bug() -> None:
    with pytest.raises(KeyError, match="encrypt"):
        _put({"networking": {"java": {"encryption": True}}}, "networking.java.encrypt", value=False)


def test_setting_a_value_of_another_type_is_a_bug() -> None:
    with pytest.raises(TypeError, match="view_distance"):
        _put({"view_distance": 16}, "view_distance", value=True)
