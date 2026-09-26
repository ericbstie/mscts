"""A Candidate Adapter: Pumpkin (Rust), from its nightly release."""

import hashlib
import json
import math
import re
import tomllib
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from types import MappingProxyType

from mscts.adapters import nbt
from mscts.adapters.base import Installation, LaunchPlan, PrepareError, ProvisionError
from mscts.net import Endpoint
from mscts.spec import Difficulty, GameMode, ServerSpec, WorldPreset
from mscts.target import Target

# The Linux x86-64 binary. Which build, from where, is the Registry's (data/registry.toml).
BINARY = "pumpkin"
_ELF_MAGIC = b"\x7fELF"

type TomlValue = bool | int | float | str | list[TomlValue] | Toml
type Toml = dict[str, TomlValue]  # a TOML table, in Pumpkin's own key order


def _toml_value(value: object) -> TomlValue:
    """`value` from tomllib, typed."""
    if isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, list):
        return [_toml_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _toml_value(item) for key, item in value.items()}
    msg = f"no TOML value: {value!r}"
    raise TypeError(msg)


def pumpkin_defaults() -> Toml:
    """Every key Pumpkin writes to pumpkin.toml, at the value it writes on its first run.

    Read from `data/pumpkin.toml`, the nightly's own first-run file, verbatim (see
    `data/SOURCE.md`). Pinned, so a changed default can never change a Candidate
    Instance silently. A new copy on each call.
    """
    pristine = resources.files("mscts.adapters").joinpath("data", "pumpkin.toml")
    document = _toml_value(tomllib.loads(pristine.read_text(encoding="utf-8")))
    if not isinstance(document, dict):  # a TOML document is always a table
        raise TypeError(pristine)
    return document


# Where Pumpkin's first-run default differs from vanilla 26.3's value for the same
# setting, vanilla's value, so the Candidate runs as the Reference does. Every other key
# stays at Pumpkin's default: it has no vanilla counterpart, or it already equals vanilla
# (op_permission_level 4, keep_alive_time 15 s, autosave every 6000 ticks, region
# compression level 6, a chat and command spam threshold of 200 ticks, ...).
VANILLA_EQUIVALENTS: Mapping[str, TomlValue] = MappingProxyType(
    {
        "accepts_transfers": False,  # accepts-transfers=false
        "scrub_ips": False,  # log-ips=true (only the log is affected)
        "world.chunk.compression.algorithm": "ZLib",  # region-file-compression=deflate
        "networking.java.compression.level": 6,  # vanilla's new Deflater(): zlib's default
        "networking.java.packet_limiter.enabled": False,  # rate-limit=0: no packet limit
        # bug-report-link= is empty, and vanilla sends server links only when one is set.
        "server_links.enabled": False,
        "server_links.bug_report": "",
        "fun.april_fools": False,  # vanilla never shuffles chat words on April 1st
    }
)

# The invariants (CONTEXT.md, "ServerSpec"): what every Pumpkin Instance is, whatever the
# ServerSpec says. They are applied last, so nothing overrides them.
INVARIANTS: Mapping[str, TomlValue] = MappingProxyType(
    {
        "networking.java.enabled": True,
        "networking.java.online_mode": False,  # offline login
        # Pumpkin sends an encryption request even offline unless this is off; vanilla
        # offline never does.
        "networking.java.encryption": False,
        "networking.bedrock.enabled": False,  # Java only: no Bedrock listener
        "networking.query.enabled": False,  # no listener besides the game port
        "networking.rcon.enabled": False,
        "networking.lan_broadcast.enabled": False,  # no UDP multicast to the LAN
        "networking.proxy.enabled": False,  # Bots connect directly, never through a proxy
        "networking.proxy.velocity.enabled": False,
        "networking.proxy.bungeecord.enabled": False,
        "networking.proxy.vine.enabled": False,
        "telemetry.enabled": False,  # on by default: a heartbeat to pumpkinmc.org
        "plugins.enabled": False,  # the Candidate itself, with nothing loaded into it
        # Vanilla's enforce-secure-profile=false: offline Bots have no chat signing keys.
        "allow_chat_reports": False,
        "white_list": False,
        "enforce_whitelist": False,
        "spawn_protection": 0,  # the default (16) stops non-operators building at spawn
        "use_favicon": False,  # no server icon (the default is Pumpkin's)
        "commands.use_console": True,  # the LaunchPlan stops Pumpkin with `stop` on stdin
        # No outbound (non-loopback) connection. Verified with strace: with these, Pumpkin
        # connects nowhere but its own loopback listener and never opens the resolver's
        # files (docs/research/2026-09-26-pumpkin.md, "Network").
        # Bedrock off is not enough: at startup Pumpkin fetches Xbox Live's OIDC keys
        # (DNS, then HTTPS to client.discovery.minecraft-services.net) whenever these two
        # are on, whether or not Bedrock is enabled.
        "networking.bedrock.online_mode": False,
        "networking.bedrock.authentication.enabled": False,
        "networking.bedrock.nethernet.enabled": False,  # its UDP and TCP listeners
        # Offline, the session server is never asked; this keeps it so if that changes.
        "networking.java.authentication.enabled": False,
        # telemetry.enabled already stops the heartbeat before a client exists. This keeps
        # a heartbeat off the internet should a nightly ever send one regardless: nothing
        # can listen on port 0, so it would be refused at once.
        "telemetry.endpoint": "http://127.0.0.1:0/",
    }
)

_GAME_MODES: Mapping[GameMode, str] = MappingProxyType(
    {
        GameMode.SURVIVAL: "Survival",
        GameMode.CREATIVE: "Creative",
        GameMode.ADVENTURE: "Adventure",
        GameMode.SPECTATOR: "Spectator",
    }
)
_DIFFICULTIES: Mapping[Difficulty, str] = MappingProxyType(
    {
        Difficulty.PEACEFUL: "Peaceful",
        Difficulty.EASY: "Easy",
        Difficulty.NORMAL: "Normal",
        Difficulty.HARD: "Hard",
    }
)

# level.dat's Difficulty byte (Pumpkin writes it, and reads it only without
# difficulty_settings).
_DIFFICULTY_IDS: Mapping[Difficulty, int] = MappingProxyType(
    {Difficulty.PEACEFUL: 0, Difficulty.EASY: 1, Difficulty.NORMAL: 2, Difficulty.HARD: 3}
)


# The ServerSpec numbers Pumpkin's config types can hold (inclusive; None: unbounded).
# When one value does not fit its type, Pumpkin replaces its WHOLE config with its
# defaults (online mode, encryption, telemetry and Bedrock on) and only logs it, so any
# other value is refused.
_RANGES: Mapping[str, tuple[int | None, int]] = MappingProxyType(
    {
        "port": (1, 2**16 - 1),  # in a SocketAddr
        "max_players": (0, 2**32 - 1),  # u32
        "view_distance": (2, 64),  # NonZero<u8>, and Pumpkin asserts 2..=64
        "simulation_distance": (1, 2**8 - 1),  # NonZero<u8>
        "seed": (-(2**63), 2**63 - 1),  # a string Pumpkin parses as i64 (else hashes it)
        "compression_threshold": (None, 2**32 - 1),  # u32; a negative one disables it
    }
)


def _check_readable(spec: ServerSpec) -> None:
    """Raise PrepareError unless Pumpkin can read every value of `spec` back."""
    for field, (low, high) in _RANGES.items():
        value = getattr(spec, field)
        if type(value) is not int or (low is not None and value < low) or value > high:
            lowest = "" if low is None else f"{low}.."
            msg = f"ServerSpec.{field}={value!r}: Pumpkin reads only integers {lowest}{high}"
            raise PrepareError(msg)
    motd: object = spec.motd
    if not isinstance(motd, str):
        msg = f"ServerSpec.motd={motd!r} is not a string"
        raise PrepareError(msg)
    try:
        motd.encode()
    except UnicodeEncodeError as error:
        msg = f"ServerSpec.motd={motd!r} is not valid Unicode: {error}"
        raise PrepareError(msg) from error


def _spec_values(spec: ServerSpec) -> dict[str, TomlValue]:
    """The pumpkin.toml values that translate `spec` (the world has no key in it)."""
    values: dict[str, TomlValue] = {
        "seed": str(spec.seed),
        # Never read by Pumpkin (level.dat's difficulty is), but written to agree with it.
        "default_difficulty": _DIFFICULTIES[spec.difficulty],
        "default_gamemode": _GAME_MODES[spec.game_mode],
        # The one address it binds: the spec's loopback host, as the Reference's (offline,
        # anyone who could reach the port could log in as an operator), and the Endpoint's.
        "networking.java.address": f"{spec.host}:{spec.port}",
        "networking.java.max_players": spec.max_players,
        "networking.java.view_distance": spec.view_distance,
        "networking.java.simulation_distance": spec.simulation_distance,
        "networking.java.motd": spec.motd,
        # Vanilla disables compression for any negative threshold; Pumpkin has a switch.
        "networking.java.compression.enabled": spec.compression_threshold >= 0,
    }
    if spec.compression_threshold >= 0:
        values["networking.java.compression.threshold"] = spec.compression_threshold
    return values


def _put(document: Toml, dotted: str, value: TomlValue) -> None:
    """Set the key at `dotted` in `document`: one Pumpkin writes, to a value of its type.

    Pumpkin would keep an unknown key but ignore it, and falls back to its default config
    on a value of the wrong type, so either is a bug here.
    """
    *parents, key = dotted.split(".")
    table = document
    for part in parents:
        child = table[part]
        if not isinstance(child, dict):
            msg = f"{dotted}: {part} is not a table"
            raise TypeError(msg)
        table = child
    if type(table[key]) is not type(value):
        msg = f"{dotted}: {value!r} is not a {type(table[key]).__name__}"
        raise TypeError(msg)
    table[key] = value


def pumpkin_config(spec: ServerSpec) -> Toml:
    """Every pumpkin.toml entry for `spec`: defaults, vanilla's values, the spec, invariants."""
    _check_readable(spec)
    document = pumpkin_defaults()
    for dotted, value in (
        *VANILLA_EQUIVALENTS.items(),
        *_spec_values(spec).items(),
        *INVARIANTS.items(),
    ):
        _put(document, dotted, value)
    return document


_BARE_KEY = re.compile(r"[A-Za-z0-9_-]+")
_TOML_ESCAPES = MappingProxyType(
    {'"': '\\"', "\\": "\\\\", "\b": "\\b", "\t": "\\t", "\n": "\\n", "\f": "\\f", "\r": "\\r"}
)


def _toml_string(text: str) -> str:
    """`text` as a TOML basic string, escaping what TOML requires and nothing else."""
    escaped = []
    for char in text:
        if char in _TOML_ESCAPES:
            escaped.append(_TOML_ESCAPES[char])
        elif ord(char) < 0x20 or ord(char) == 0x7F:  # noqa: PLR2004 (control characters)
            escaped.append(f"\\u{ord(char):04X}")
        else:
            escaped.append(char)
    return '"' + "".join(escaped) + '"'


def _toml_scalar(value: TomlValue) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(value)
        return repr(value)
    if isinstance(value, str):
        return _toml_string(value)
    if isinstance(value, list):
        return "[" + ", ".join(_toml_scalar(item) for item in value) + "]"
    msg = f"a table is no inline value: {value!r}"
    raise TypeError(msg)


def _toml_key(key: str) -> str:
    return key if _BARE_KEY.fullmatch(key) else _toml_string(key)


def _render_table(table: Toml, path: tuple[str, ...], lines: list[str]) -> None:
    values = [(key, value) for key, value in table.items() if not isinstance(value, dict)]
    tables = [(key, value) for key, value in table.items() if isinstance(value, dict)]
    # Like Pumpkin's serializer: a header only for a table with values of its own, or none
    # at all; a blank line before each header.
    if path and (values or not tables):
        if lines:
            lines.append("")
        lines.append("[" + ".".join(_toml_key(part) for part in path) + "]")
    lines.extend(f"{_toml_key(key)} = {_toml_scalar(value)}" for key, value in values)
    for key, child in tables:
        _render_table(child, (*path, key), lines)


def toml_document(document: Toml) -> str:
    """Render `document` as TOML, laid out exactly as Pumpkin itself writes pumpkin.toml."""
    lines: list[str] = []
    _render_table(document, (), lines)
    return "\n".join(lines) + "\n"


def pumpkin_toml(spec: ServerSpec) -> str:
    """The complete pumpkin.toml for `spec`."""
    return toml_document(pumpkin_config(spec))


@dataclass(frozen=True, slots=True)
class Limit:
    """The values of one ServerSpec field Pumpkin can honour, and why it cannot the rest."""

    honoured: frozenset[object]
    why: str


# The world save prepare writes (ADR-0007): pumpkin.toml has no world type and Pumpkin
# never reads default_difficulty, so a WorldPreset and a Difficulty reach Pumpkin only as
# an existing world, in Pumpkin's own format. What Pumpkin reads from it, and what vanilla
# writes for the same ServerSpec: docs/research/2026-09-26-pumpkin.md, "A native world
# save".

# The newest world Pumpkin reads (26.2), as it stamps its own saves: it exits on a
# level.dat outside DataVersion 4435..=4903 or version 19132..=19133, so vanilla 26.3's own
# save (DataVersion 5023) cannot be used.
WORLD_DATA_VERSION = 4903
WORLD_LEVEL_VERSION = 19133
# Where Pumpkin reads them, under its cwd (pumpkin.toml keeps the default world path).
LEVEL_DAT = "world/level.dat"
WORLD_GEN_SETTINGS = "world/data/minecraft/world_gen_settings.dat"

# Each WorldPreset's overworld generator, exactly as vanilla 26.3 writes it into
# world_gen_settings.dat for the same ServerSpec (VanillaAdapter's level-type and
# generator-settings), which Pumpkin reads as it is.
_OVERWORLD_GENERATORS: Mapping[WorldPreset, nbt.Compound] = MappingProxyType(
    {
        # Vanilla's classic flat preset: bedrock, 2 dirt, grass block, so the surface is
        # y = -60. Pumpkin's FlatGenerator ignores features, lakes and structure_overrides
        # (it places none of them); vanilla places none either, with generate-structures
        # off.
        WorldPreset.FLAT: {
            "settings": {
                "features": nbt.Byte(0),
                "biome": "minecraft:plains",
                "layers": nbt.List(
                    tuple(
                        {"block": f"minecraft:{block}", "height": nbt.Int(height)}
                        for block, height in (("bedrock", 1), ("dirt", 2), ("grass_block", 1))
                    )
                ),
                "structure_overrides": nbt.List(("minecraft:strongholds", "minecraft:villages")),
                "lakes": nbt.Byte(0),
            },
            "type": "minecraft:flat",
        },
    }
)
# The nether and the end, as vanilla writes them for every WorldPreset.
_NETHER_GENERATOR: nbt.Compound = {
    "settings": "minecraft:nether",
    "biome_source": {"preset": "minecraft:nether", "type": "minecraft:multi_noise"},
    "type": "minecraft:noise",
}
_END_GENERATOR: nbt.Compound = {
    "settings": "minecraft:end",
    "biome_source": {"type": "minecraft:the_end"},
    "type": "minecraft:noise",
}
# The world spawn vanilla 26.3 sets in a flat world (level.dat spawn.pos). Pumpkin puts a
# first-time player at (x + 0.5, the top block + 1, z + 0.5): it has no spawn radius.
_SPAWN = (0, -60, 0)


def world_gen_settings(spec: ServerSpec) -> nbt.Compound:
    """Pumpkin's world/data/minecraft/world_gen_settings.dat for `spec`, in Pumpkin's layout.

    The seed and dimensions are what vanilla writes for `spec`. generate_structures and
    bonus_chest (never read by Pumpkin) are vanilla's values too.
    """
    return {
        "data": {
            "DataVersion": nbt.Int(WORLD_DATA_VERSION),
            "seed": nbt.Long(spec.seed),
            "generate_structures": nbt.Byte(0),  # vanilla's generate-structures=false
            "bonus_chest": nbt.Byte(0),
            "dimensions": {
                "minecraft:overworld": {
                    "type": "minecraft:overworld",
                    "generator": _OVERWORLD_GENERATORS[spec.world],
                },
                "minecraft:the_nether": {
                    "type": "minecraft:the_nether",
                    "generator": _NETHER_GENERATOR,
                },
                "minecraft:the_end": {"type": "minecraft:the_end", "generator": _END_GENERATOR},
            },
        }
    }


def level_dat(spec: ServerSpec) -> nbt.Compound:
    """Pumpkin's world/level.dat for `spec`: every key Pumpkin writes, in its write order.

    Each value is the one Pumpkin writes into its own new world (`LevelData::default`),
    except these substitutions: the difficulty is the spec's; the spawn is vanilla's
    (Pumpkin searches noise terrain for one); allowCommands is vanilla's false (Pumpkin
    uses it only for Bedrock); LastPlayed is 0 rather than the time, so the file depends
    on the spec alone (Pumpkin never reads it); and the seed is the spec's.
    """
    difficulty = str(spec.difficulty)  # "peaceful": the name Pumpkin reads
    x, y, z = _SPAWN
    return {
        "Data": {
            "allowCommands": nbt.Byte(0),
            "BorderCenterX": nbt.Double(0.0),
            "BorderCenterZ": nbt.Double(0.0),
            "BorderDamagePerBlock": nbt.Double(0.2),
            "BorderSize": nbt.Double(60_000_000.0),
            "BorderSafeZone": nbt.Double(5.0),
            "BorderSizeLerpTarget": nbt.Double(60_000_000.0),
            "BorderSizeLerpTime": nbt.Long(0),
            "BorderWarningBlocks": nbt.Double(5.0),
            "BorderWarningTime": nbt.Double(15.0),
            "DataPacks": {"Disabled": nbt.List(()), "Enabled": nbt.List(("vanilla",))},
            "DataVersion": nbt.Int(WORLD_DATA_VERSION),
            # Pumpkin reads this compound, and Difficulty only if it is absent.
            "difficulty_settings": {
                "difficulty": difficulty,
                "hardcore": nbt.Byte(0),
                "locked": nbt.Byte(0),
            },
            "Difficulty": nbt.Byte(_DIFFICULTY_IDS[spec.difficulty]),
            "DifficultyLocked": nbt.Byte(0),
            "LastPlayed": nbt.Long(0),
            "LevelName": "world",
            "spawn": {
                "dimension": "minecraft:overworld",
                "pos": nbt.IntArray((x, y, z)),
                "pitch": nbt.Float(0.0),
                "yaw": nbt.Float(0.0),
            },
            "SpawnX": nbt.Int(x),
            "SpawnY": nbt.Int(y),
            "SpawnZ": nbt.Int(z),
            "SpawnAngle": nbt.Float(0.0),
            "SpawnPitch": nbt.Float(0.0),
            "Version": {
                "Name": "26.3",  # Pumpkin's label for its 26.2-format saves
                "Id": nbt.Int(WORLD_DATA_VERSION),
                "Snapshot": nbt.Byte(0),
                "Series": "main",
            },
            "version": nbt.Int(WORLD_LEVEL_VERSION),
            "map_id": nbt.Int(0),
            "WorldGenSettings": {"seed": nbt.Long(spec.seed)},
        }
    }


# The ServerSpec fields Pumpkin can honour only for some values, found in its source and
# confirmed live (docs/research/2026-09-26-pumpkin.md). prepare refuses any other value: a
# Candidate that cannot honour a spec is reported, never silently approximated.
LIMITS: Mapping[str, Limit] = MappingProxyType(
    {
        "world": Limit(
            honoured=frozenset(_OVERWORLD_GENERATORS),
            why=(
                "pumpkin.toml has no world type, so prepare writes the world save, and "
                "it can write one only for these WorldPresets"
            ),
        ),
    }
)


def _refuse_what_pumpkin_cannot_honour(spec: ServerSpec) -> None:
    """Raise PrepareError naming every field of `spec` Pumpkin cannot honour."""
    refusals = [
        f"ServerSpec.{field}={getattr(spec, field)}: {limit.why}"
        for field, limit in LIMITS.items()
        if getattr(spec, field) not in limit.honoured
    ]
    if refusals:
        msg = "Pumpkin cannot honour this ServerSpec:\n- " + "\n- ".join(refusals)
        raise PrepareError(msg)


# data/ops.json level for ServerSpec.operators: all commands, as vanilla's.
OPERATOR_LEVEL = 4


def offline_uuid(name: str) -> uuid.UUID:
    """The UUID Pumpkin gives player `name` in offline mode (not vanilla's).

    The first 16 bytes of the SHA-256 of the bare UTF-8 name, taken as they are: no
    version or variant bits. Vanilla uses an MD5, version 3 UUID of "OfflinePlayer:<name>".
    """
    return uuid.UUID(bytes=hashlib.sha256(name.encode()).digest()[:16])


def ops_json(operators: tuple[str, ...]) -> str:
    """Pumpkin's data/ops.json for `operators`, formatted exactly as Pumpkin writes it.

    Pumpkin matches an operator to a player by UUID, so each entry carries Pumpkin's own
    offline UUID for the name.
    """
    for name in operators:
        try:
            name.encode()
        except UnicodeEncodeError as error:
            # Pumpkin would fail to parse the file and load no operators, logging it only.
            msg = f"ServerSpec.operators: {name!r} is not valid Unicode: {error}"
            raise PrepareError(msg) from error
    entries = [
        {
            "uuid": str(offline_uuid(name)),
            "name": name,
            "level": OPERATOR_LEVEL,
            "bypasses_player_limit": False,
        }
        for name in operators
    ]
    return json.dumps(entries, indent=2, ensure_ascii=False)  # as serde_json's pretty printer


class PumpkinAdapter:
    """Checks a Pumpkin build and prepares it for a ServerSpec."""

    name = "pumpkin"
    binary = BINARY

    def check(self, binary: Path, target: Target) -> None:  # noqa: ARG002 (any Target)
        """Raise ProvisionError unless `binary` is an ELF executable, as every Pumpkin build is."""
        with binary.open("rb") as file:
            head = file.read(16)
        if not head.startswith(_ELF_MAGIC):
            msg = f"{binary} is not an ELF executable: {head!r}"
            raise ProvisionError(msg)

    def prepare(self, installation: Installation, spec: ServerSpec, workdir: Path) -> LaunchPlan:
        """Write the complete Pumpkin config and world save for `spec` into `workdir`.

        `workdir` must be new or empty. Refuses, before writing anything, a spec Pumpkin
        cannot honour (LIMITS) or read back (its config types), and a non-empty workdir.
        """
        _refuse_what_pumpkin_cannot_honour(spec)
        texts = {
            "pumpkin.toml": pumpkin_toml(spec),
            "data/ops.json": ops_json(spec.operators),
            # Pumpkin's own first-run content of each, written so none is left to it.
            "data/whitelist.json": "[]",
            "data/banned-players.json": "[]",
            "data/banned-ips.json": "[]",
        }
        files = {name: text.encode() for name, text in texts.items()}
        # The world save, which alone carries the world type and the difficulty.
        files[LEVEL_DAT] = nbt.gzipped(level_dat(spec))
        files[WORLD_GEN_SETTINGS] = nbt.gzipped(world_gen_settings(spec))
        workdir.mkdir(parents=True, exist_ok=True)
        if any(workdir.iterdir()):
            # Pumpkin keeps its world, player data, bans and operators there: a reused
            # workdir would carry one Instance's state into the next.
            msg = f"workdir {workdir} is not empty; each Instance needs a new or empty one"
            raise PrepareError(msg)
        for name, content in files.items():
            (workdir / name).parent.mkdir(parents=True, exist_ok=True)
            (workdir / name).write_bytes(content)
        return LaunchPlan(
            # It takes no arguments: pumpkin.toml and data/ are read from the cwd.
            argv=(str(installation.root.absolute() / BINARY),),
            cwd=workdir,
            # Nothing leaks from the harness: Pumpkin reads RUST_LOG (its log filter) and,
            # through reqwest, the proxy variables, and needs nothing from its environment.
            env=MappingProxyType({}),
            endpoint=Endpoint(host=spec.host, port=spec.port),  # exactly what it binds
            stop_stdin=b"stop\n",  # the console `stop`: saves the worlds, exit code 0
        )
