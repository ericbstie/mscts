"""The Reference Adapter: vanilla Minecraft server for the Target."""

import hashlib
import http.client
import json
import os
import ssl
import urllib.request
import uuid
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from urllib.parse import urlsplit

from mscts.adapters.base import Installation, LaunchPlan, ProvisionError
from mscts.net import Endpoint
from mscts.spec import Difficulty, GameMode, ServerSpec, WorldPreset

# The server binds loopback only: in offline mode anyone who can reach the port can log
# in under an operator's name. The Endpoint uses the same address, so it is exactly
# what the server bound (IPv4; never a `localhost` that might resolve to ::1).
HOST = "127.0.0.1"
JAR = "server.jar"
# A fixed max heap, so the Reference's memory (and GC timing) does not depend on the
# host: the JVM default is a quarter of physical RAM.
HEAP = "-Xmx1G"
# ops.json level for ServerSpec.operators: all commands, as op-permission-level.
OPERATOR_LEVEL = 4
_FETCH_TIMEOUT_S = 60


def _https_only_opener() -> urllib.request.OpenerDirector:
    """An opener that can speak nothing but HTTPS: no file:, ftp:, data: or http: handler.

    It honours HTTPS_PROXY and follows no redirects (a 3xx raises), so no URL other than
    the one `https_get` checked is ever opened.
    """
    opener = urllib.request.OpenerDirector()
    for handler in (
        urllib.request.ProxyHandler(),
        urllib.request.HTTPSHandler(context=ssl.create_default_context()),
        urllib.request.HTTPDefaultErrorHandler(),
        urllib.request.HTTPErrorProcessor(),
        urllib.request.UnknownHandler(),
    ):
        opener.add_handler(handler)
    return opener


def https_get(url: str) -> bytes:
    """Return the body of an HTTPS GET of `url`. Any other scheme is refused up front."""
    if urlsplit(url).scheme != "https":
        msg = f"refusing to fetch a non-HTTPS URL: {url}"
        raise ProvisionError(msg)
    with _https_only_opener().open(url, timeout=_FETCH_TIMEOUT_S) as response:
        if not isinstance(response, http.client.HTTPResponse):  # urllib types it as Any
            msg = f"unexpected response {type(response).__name__} from {url}"
            raise TypeError(msg)
        return response.read()


# The invariants (CONTEXT.md, "ServerSpec"): what every Reference Instance is, whatever
# the ServerSpec says. They are applied last, so nothing overrides them. Offline mode
# also means no encryption request, and vanilla has no server telemetry to turn off.
INVARIANTS: Mapping[str, str] = MappingProxyType(
    {
        "online-mode": "false",  # offline login; vanilla then sends no encryption request
        "enforce-secure-profile": "false",  # offline Bots have no chat signing keys
        "white-list": "false",  # the 26.3 default (true) kicks every Bot
        "enforce-whitelist": "false",
        "pause-when-empty-seconds": "0",  # the default (60) stops ticking with no players
        "spawn-protection": "0",  # the default (16) stops non-operators building at spawn
        "player-idle-timeout": "0",  # idle Bots are never kicked
        "enable-status": "true",  # readiness is a status ping (ADR-0004)
        "hide-online-players": "false",  # the status player sample is compared
        "generate-structures": "false",  # the same structure-free flat world every time
        "enable-rcon": "false",  # no listener besides the game port
        "enable-query": "false",
        "management-server-enabled": "false",
        "server-ip": HOST,
    }
)

# Every other key vanilla 26.3 writes, at the value vanilla 26.3 itself writes on first
# run (verified 2026-09-25, docs/research/2026-09-25-domain.md). Pinned, so a changed
# default can never change the Reference silently. (Vanilla generates a random
# management-server-secret only when the key is absent; an empty one stays empty.)
VANILLA_DEFAULTS: Mapping[str, str] = MappingProxyType(
    {
        "accepts-transfers": "false",
        "allow-flight": "false",
        "broadcast-console-to-ops": "true",
        "broadcast-rcon-to-ops": "true",
        "bug-report-link": "",
        "chat-spam-threshold-seconds": "10",
        "command-spam-threshold-seconds": "10",
        "enable-code-of-conduct": "false",
        "enable-jmx-monitoring": "false",
        "entity-broadcast-range-percentage": "100",
        "force-gamemode": "false",
        "function-permission-level": "2",
        "hardcore": "false",
        "initial-disabled-packs": "",
        "initial-enabled-packs": "vanilla",
        "level-name": "world",
        "log-ips": "true",
        "management-server-allowed-origins": "",
        "management-server-host": "localhost",
        "management-server-port": "0",
        "management-server-secret": "",
        "management-server-tls-enabled": "true",
        "management-server-tls-keystore": "",
        "management-server-tls-keystore-password": "",
        "max-chained-neighbor-updates": "1000000",
        "max-tick-time": "60000",
        "max-world-size": "29999984",
        "op-permission-level": "4",
        "prevent-proxy-connections": "false",
        "query.port": "25565",  # unused: query is disabled
        "rate-limit": "0",
        "rcon.password": "",
        "rcon.port": "25575",  # unused: rcon is disabled
        "region-file-compression": "deflate",
        "require-resource-pack": "false",
        "resource-pack": "",
        "resource-pack-id": "",
        "resource-pack-prompt": "",
        "resource-pack-sha1": "",
        "status-heartbeat-interval": "0",
        "sync-chunk-writes": "true",
        "text-filtering-config": "",
        "text-filtering-version": "0",
        "use-native-transport": "true",
    }
)

_GAME_MODES: Mapping[GameMode, str] = MappingProxyType(
    {
        GameMode.SURVIVAL: "survival",
        GameMode.CREATIVE: "creative",
        GameMode.ADVENTURE: "adventure",
        GameMode.SPECTATOR: "spectator",
    }
)
_DIFFICULTIES: Mapping[Difficulty, str] = MappingProxyType(
    {
        Difficulty.PEACEFUL: "peaceful",
        Difficulty.EASY: "easy",
        Difficulty.NORMAL: "normal",
        Difficulty.HARD: "hard",
    }
)
_WORLDS: Mapping[WorldPreset, Mapping[str, str]] = MappingProxyType(
    {
        # Vanilla's classic flat layers (bedrock, 2 dirt, grass); spawn is at y = -60.
        WorldPreset.FLAT: {"level-type": "minecraft:flat", "generator-settings": "{}"},
    }
)


def server_properties(spec: ServerSpec) -> dict[str, str]:
    """Every server.properties entry for `spec`: defaults, then the spec, then invariants."""
    return {
        **VANILLA_DEFAULTS,
        "server-port": str(spec.port),
        "motd": spec.motd,
        "max-players": str(spec.max_players),
        "view-distance": str(spec.view_distance),
        "simulation-distance": str(spec.simulation_distance),
        **_WORLDS[spec.world],
        "level-seed": str(spec.seed),
        "gamemode": _GAME_MODES[spec.game_mode],
        "difficulty": _DIFFICULTIES[spec.difficulty],
        "network-compression-threshold": str(spec.compression_threshold),
        **INVARIANTS,
    }


_PRINTABLE_ASCII = range(0x20, 0x7F)
_ESCAPES = {
    "\\": "\\\\",
    "\t": "\\t",
    "\n": "\\n",
    "\r": "\\r",
    "\f": "\\f",
    "=": "\\=",
    ":": "\\:",
    "#": "\\#",
    "!": "\\!",
}


def _escape(text: str, *, is_key: bool) -> str:
    """Escape `text` exactly as `java.util.Properties.store(OutputStream)` does.

    The result is pure ASCII: every UTF-16 code unit outside printable ASCII becomes a
    Unicode escape, so the file reads the same whichever charset the server decodes it
    with (vanilla tries UTF-8, then falls back to ISO-8859-1).
    """
    utf16 = text.encode("utf-16-be", "surrogatepass")
    escaped: list[str] = []
    for index in range(0, len(utf16), 2):
        unit = int.from_bytes(utf16[index : index + 2])
        char = chr(unit)
        if char == " ":
            escaped.append("\\ " if is_key or index == 0 else " ")
        elif char in _ESCAPES:
            escaped.append(_ESCAPES[char])
        elif unit in _PRINTABLE_ASCII:
            escaped.append(char)
        else:
            escaped.append(f"\\u{unit:04X}")
    return "".join(escaped)


def java_properties(entries: Mapping[str, str]) -> str:
    """Render `entries` as a Java properties file, one line per key in sorted order.

    Sorted order is the order vanilla itself writes `server.properties` in.
    """
    lines = ["#Minecraft server properties"]
    lines.extend(
        f"{_escape(key, is_key=True)}={_escape(value, is_key=False)}"
        for key, value in sorted(entries.items())
    )
    return "\n".join(lines) + "\n"


def offline_uuid(name: str) -> uuid.UUID:
    """The UUID vanilla gives player `name` in offline mode.

    Java's `UUID.nameUUIDFromBytes(("OfflinePlayer:" + name).getBytes(UTF_8))`: an MD5,
    version 3 UUID of the exact, case-sensitive name.
    """
    digest = hashlib.md5(f"OfflinePlayer:{name}".encode(), usedforsecurity=False).digest()
    return uuid.UUID(bytes=digest, version=3)


def ops_json(operators: tuple[str, ...]) -> str:
    """Vanilla's ops.json for `operators`, formatted exactly as vanilla writes it.

    Written directly because the console `op` command, with Mojang's services
    unreachable, ops the lower-cased name, whose UUID no Bot logs in with.
    """
    entries = [
        {
            "uuid": str(offline_uuid(name)),
            "name": name,
            "level": OPERATOR_LEVEL,
            "bypassesPlayerLimit": False,
        }
        for name in operators
    ]
    return json.dumps(entries, indent=2)


class VanillaAdapter:
    """Provisions the vanilla server jar and prepares it for a ServerSpec."""

    name = "vanilla"

    def prepare(self, installation: Installation, spec: ServerSpec, workdir: Path) -> LaunchPlan:
        """Write the complete vanilla config for `spec` into `workdir`."""
        workdir.mkdir(parents=True, exist_ok=True)
        (workdir / "eula.txt").write_bytes(b"eula=true\n")
        (workdir / "server.properties").write_text(
            java_properties(server_properties(spec)), encoding="ascii"
        )
        (workdir / "ops.json").write_text(ops_json(spec.operators), encoding="utf-8")
        return LaunchPlan(
            argv=("java", HEAP, "-jar", str(installation.root.absolute() / JAR), "nogui"),
            cwd=workdir,
            # Only PATH, so `java` resolves to the Target's JVM that mise put on it.
            # Nothing else leaks from the harness: no JAVA_TOOL_OPTIONS (here it injects
            # proxy settings), no locale, no JAVA_HOME.
            env=MappingProxyType({"PATH": os.environ.get("PATH", os.defpath)}),
            endpoint=Endpoint(host=HOST, port=spec.port),
            stop_stdin=b"stop\n",
        )
