"""A Candidate Adapter: Pumpkin (Rust), from its nightly release."""

import datetime
import hashlib
import json
import math
import re
import shutil
import tempfile
import tomllib
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from types import MappingProxyType

from mscts.adapters.base import Installation, LaunchPlan, PrepareError, ProvisionError
from mscts.adapters.fetch import Fetch, https_get
from mscts.net import Endpoint
from mscts.spec import Difficulty, GameMode, ServerSpec
from mscts.target import Target

# The Linux x86-64 binary of Pumpkin's rolling "nightly" release (docs/research/
# 2026-09-26-pumpkin.md). It redirects to a signed, short-lived GitHub asset URL.
NIGHTLY_URL = "https://github.com/Pumpkin-MC/Pumpkin/releases/download/nightly/pumpkin-X64-Linux"
BINARY = "pumpkin"
# What was fetched, from where and when: the nightly publishes no hash to verify against,
# so the Installation records its own and every later provision checks the binary by it.
SOURCE = "SOURCE.json"
_ELF_MAGIC = b"\x7fELF"

# Pumpkin binds loopback only, as the Reference does: offline, anyone who can reach the
# port can log in under an operator's name. The Endpoint uses the same address.
HOST = "127.0.0.1"

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
        "default_difficulty": _DIFFICULTIES[spec.difficulty],
        "default_gamemode": _GAME_MODES[spec.game_mode],
        "networking.java.address": f"{HOST}:{spec.port}",
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


# The ServerSpec fields Pumpkin can honour only for some values, found in its source and
# confirmed live (docs/research/2026-09-26-pumpkin.md, "World and difficulty"). prepare
# refuses any other value: a Candidate that cannot honour a spec is reported, never
# silently approximated.
LIMITS: Mapping[str, Limit] = MappingProxyType(
    {
        "world": Limit(
            honoured=frozenset(),
            why=(
                "pumpkin.toml has no world type: a new Pumpkin world is always "
                "minecraft:noise (with structures). Pumpkin generates a flat one only "
                "for an existing world whose world_gen_settings.dat says so, and it "
                "reads worlds only up to DataVersion 4903 (26.2)"
            ),
        ),
        "difficulty": Limit(
            honoured=frozenset({Difficulty.NORMAL}),
            why="Pumpkin never reads default_difficulty: a new world is always normal",
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


def _sha256_of(path: Path) -> str:
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def _recorded_sha256(root: Path) -> str:
    """The sha256 SOURCE.json records for the binary in `root`."""
    try:
        recorded: object = json.loads((root / SOURCE).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        msg = f"{root} is not a Pumpkin Installation: {error}; delete it to provision again"
        raise ProvisionError(msg) from error
    sha256 = recorded.get("sha256") if isinstance(recorded, dict) else None
    if not isinstance(sha256, str):
        msg = f"{root / SOURCE} records no sha256; delete {root} to provision again"
        raise ProvisionError(msg)
    return sha256


def _verify(root: Path) -> None:
    """Raise ProvisionError unless the binary in `root` is the one SOURCE.json records."""
    recorded = _recorded_sha256(root)
    binary = root / BINARY
    actual = _sha256_of(binary) if binary.is_file() else "missing"
    if actual != recorded:
        msg = (
            f"{binary}: sha256 {actual} is not the recorded {recorded}; delete {root} to "
            "provision the current nightly"
        )
        raise ProvisionError(msg)


class PumpkinAdapter:
    """Provisions the Pumpkin nightly binary and prepares it for a ServerSpec."""

    name = "pumpkin"

    def __init__(self, fetch: Fetch = https_get) -> None:
        """Download with `fetch`. Unit tests pass a fake, so they never touch the network."""
        self._fetch = fetch

    def provision(self, target: Target, cache_dir: Path) -> Installation:
        """Download the nightly into `cache_dir/pumpkin/<version>/`, unless it is there already.

        The cached binary is reused, never refreshed, so every Run measures the same build
        until its Installation is deleted by hand. It is checked against the sha256 recorded
        when it was fetched.
        """
        root = cache_dir.absolute() / self.name / target.minecraft_version
        if not root.exists():
            self._install(root)
        _verify(root)
        return Installation(adapter=self.name, target=target, root=root)

    def _install(self, root: Path) -> None:
        """Fetch the nightly and put it at `root` in one rename, complete or not at all."""
        download = self._fetch(NIGHTLY_URL)
        if not download.body.startswith(_ELF_MAGIC):
            msg = f"{download.url} is not an ELF executable: {download.body[:16]!r}"
            raise ProvisionError(msg)
        source = {
            "url": NIGHTLY_URL,
            "final_url": download.url,
            "sha256": hashlib.sha256(download.body).hexdigest(),
            "size": len(download.body),
            "fetched_at": datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
        }
        root.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(dir=root.parent, prefix=f".{root.name}.", suffix=".part"))
        try:
            staging.chmod(0o755)
            (staging / BINARY).write_bytes(download.body)
            (staging / BINARY).chmod(0o755)
            (staging / SOURCE).write_text(json.dumps(source, indent=2) + "\n", encoding="utf-8")
            try:
                staging.rename(root)
            except OSError:
                if not root.is_dir():
                    raise
                # Another provision (another session) installed it first: use theirs.
        finally:
            shutil.rmtree(staging, ignore_errors=True)  # gone already if the rename worked

    def prepare(self, installation: Installation, spec: ServerSpec, workdir: Path) -> LaunchPlan:
        """Write the complete Pumpkin config for `spec` into `workdir`, new or empty.

        Refuses, before writing anything, a spec Pumpkin cannot honour (LIMITS) or read
        back (its config types), and a non-empty workdir.
        """
        _refuse_what_pumpkin_cannot_honour(spec)
        files = {
            "pumpkin.toml": pumpkin_toml(spec),
            "data/ops.json": ops_json(spec.operators),
            # Pumpkin's own first-run content of each, written so none is left to it.
            "data/whitelist.json": "[]",
            "data/banned-players.json": "[]",
            "data/banned-ips.json": "[]",
        }
        workdir.mkdir(parents=True, exist_ok=True)
        if any(workdir.iterdir()):
            # Pumpkin keeps its world, player data, bans and operators there: a reused
            # workdir would carry one Instance's state into the next.
            msg = f"workdir {workdir} is not empty; each Instance needs a new or empty one"
            raise PrepareError(msg)
        (workdir / "data").mkdir()
        for name, text in files.items():
            (workdir / name).write_text(text, encoding="utf-8")
        return LaunchPlan(
            # It takes no arguments: pumpkin.toml and data/ are read from the cwd.
            argv=(str(installation.root.absolute() / BINARY),),
            cwd=workdir,
            # Nothing leaks from the harness: Pumpkin reads RUST_LOG (its log filter) and,
            # through reqwest, the proxy variables, and needs nothing from its environment.
            env=MappingProxyType({}),
            endpoint=Endpoint(host=HOST, port=spec.port),
            stop_stdin=b"stop\n",  # the console `stop`: saves the worlds, exit code 0
        )
