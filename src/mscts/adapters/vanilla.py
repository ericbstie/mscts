"""The Reference Adapter: vanilla Minecraft server for the Target."""

import hashlib
import http.client
import json
import os
import re
import shutil
import ssl
import tempfile
import urllib.request
import uuid
import zipfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from urllib.parse import urlsplit

from mscts.adapters.base import Installation, LaunchPlan, PrepareError, ProvisionError
from mscts.net import Endpoint
from mscts.spec import Difficulty, GameMode, ServerSpec, WorldPreset
from mscts.target import Target

MANIFEST_URL = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"

JAR = "server.jar"
# A fixed max heap, so the Reference's memory (and GC timing) does not depend on the
# host: the JVM default is a quarter of physical RAM.
HEAP = "-Xmx1G"
# ops.json level for ServerSpec.operators: all commands, as op-permission-level.
OPERATOR_LEVEL = 4
# The java launcher to run the Reference with, if the constructor names none.
JAVA_ENV = "MSCTS_JAVA"
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


type Fetch = Callable[[str], bytes]


def _sha1(data: bytes) -> str:
    # Mojang publishes SHA-1; it is an integrity check here, not a security boundary.
    return hashlib.sha1(data, usedforsecurity=False).hexdigest()


def _verify(data: bytes, *, sha1: str, size: int | None = None, what: str) -> None:
    """Raise ProvisionError unless `data` has the published sha1 (and size)."""
    if size is not None and len(data) != size:
        msg = f"{what}: size {len(data)} does not match the published {size}"
        raise ProvisionError(msg)
    if _sha1(data) != sha1:
        msg = f"{what}: sha1 {_sha1(data)} does not match the published {sha1}"
        raise ProvisionError(msg)


@dataclass(frozen=True, slots=True)
class _Download:
    """A download as the version JSON publishes it."""

    url: str
    sha1: str
    size: int


def _protocol_version(jar: Path) -> int:
    """The protocol_version from the version.json inside a server jar."""
    with zipfile.ZipFile(jar) as archive:
        return int(json.loads(archive.read("version.json"))["protocol_version"])


def _replace_atomically(path: Path, data: bytes) -> None:
    """Put `data` at `path` with one rename, so nobody ever sees a partial file there."""
    descriptor, part = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".part")
    with os.fdopen(descriptor, "wb") as file:
        file.write(data)
    Path(part).replace(path)


# JVM system properties that cut every Reference Instance off from all networks except
# loopback, so its behaviour cannot depend on the host's network. Offline vanilla still
# calls Mojang's services. Verified with strace: with these, its only non-UNIX connect is
# a refused one to 127.0.0.1:0, and it never reads the resolver's files
# (docs/research/2026-09-25-domain.md, "Vanilla 26.3 makes no outbound connection").
NO_NETWORK: Mapping[str, str] = MappingProxyType(
    {
        # authlib takes every Mojang service URL (keys, name lookups, ...) from one
        # discovery document, fetched from this URL. (minecraft.api.env would win over it,
        # so it is never set.) Nothing can listen on port 0, so the fetch is refused at once
        # and authlib runs "Services are unavailable", as it does with no network at all.
        "minecraft.api.discovery.host": "http://127.0.0.1:0/",
        # The JDK resolves host names from this (empty) file only, never the OS resolver:
        # no DNS query, whatever the host. log4j looks up the local host name at startup.
        "jdk.net.hosts.file": "/dev/null",
    }
)

# JVM system properties that keep an Instance's launch independent of the host, beyond the
# exact JVM (java_version already pins that). -Duser.timezone=UTC makes every timestamp
# and daylight-savings computation the same on every host; the JVM otherwise defaults to
# the host's zone. -Djava.net.preferIPv4Stack=true makes wildcard/loopback resolution and
# the game socket always use IPv4, so a host without IPv6, or one where it is preferred,
# cannot change what the Reference binds or how a numeric 127.0.0.1 connects. Verified live
# (docs/research/2026-09-25-domain.md, "Host independence of the launch").
HOST_INDEPENDENCE: Mapping[str, str] = MappingProxyType(
    {
        "user.timezone": "UTC",
        "java.net.preferIPv4Stack": "true",
    }
)

# The env every Reference Instance launches with: fixed and explicit, so its behaviour
# cannot depend on who launches it or from where. argv[0] is already the resolved,
# absolute java launcher (see resolve_java), so PATH is no longer needed to find java; a
# small, fixed PATH is kept only in case the JVM or a bundled library ever shells out (a
# crash handler, a native library probe), never the harness's own PATH (this session's mise
# shims, or a worktree-specific directory). Nothing else passes through: no
# JAVA_TOOL_OPTIONS (this container injects proxy settings through it), no LANG, no
# JAVA_HOME.
LAUNCH_ENV: Mapping[str, str] = MappingProxyType({"PATH": "/usr/bin:/bin"})

# The invariants (CONTEXT.md, "ServerSpec"): what every Reference Instance is, whatever
# the ServerSpec says. They are applied last, so nothing overrides them. Offline mode
# also means no encryption request. Vanilla has no telemetry setting; NO_NETWORK stops
# its calls to Mojang's services.
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
        # Vanilla's own default generator-settings. For flat it logs "No key layers in
        # MapLike[{}]" and uses the classic flat preset (bedrock, 2 dirt, grass): y = -60.
        WorldPreset.FLAT: {"level-type": "minecraft:flat", "generator-settings": "{}"},
    }
)


def server_properties(spec: ServerSpec) -> dict[str, str]:
    """Every server.properties entry for `spec`: defaults, then the spec, then invariants."""
    return {
        **VANILLA_DEFAULTS,
        # The one address it binds: the spec's loopback host (offline, anyone who could
        # reach the port could log in as an operator), which is also the Endpoint's.
        "server-ip": spec.host,
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


_JAVA_VERSION = re.compile(r'^JAVA_VERSION="(?P<version>[^"]*)"', re.MULTILINE)


def java_version(java: Path) -> str:
    """The JAVA_VERSION (e.g. "25.0.4.1") of the Java runtime image whose launcher is `java`.

    Every Java 9+ runtime image, JDK or JRE, has its launcher at `<home>/bin/java` and a
    `<home>/release` file naming its JAVA_VERSION. Reading it runs nothing, so prepare
    stays hermetic. A launcher outside a runtime image (a version-manager shim, a
    wrapper script) could run any JVM, so it is refused, not trusted.
    """
    if not java.is_file():
        msg = f"java launcher {java} does not exist"
        raise PrepareError(msg)
    release = java.parent.parent / "release"
    try:
        text = release.read_text(encoding="utf-8", errors="replace")
    except OSError as error:
        msg = (
            f"{java} is not the launcher of a Java runtime image ({release} is missing); "
            f"name the real launcher with java= or {JAVA_ENV}"
        )
        raise PrepareError(msg) from error
    match = _JAVA_VERSION.search(text)
    if match is None:
        msg = f"{release} has no JAVA_VERSION line"
        raise PrepareError(msg)
    return str(match["version"])  # re types a group as Any


def resolve_java(target: Target, java: Path | str | None = None) -> Path:
    """The real, absolute path of a java launcher of `target`'s Java major version.

    Named by `java`, else MSCTS_JAVA, else PATH. Symlinks are resolved, so the LaunchPlan
    names the exact runtime even if a versionless link (mise's temurin-25,
    /etc/alternatives) is repointed later.

    This is the resolution `VanillaAdapter.prepare` uses; it is exposed here (rather than
    kept private on the Adapter) so other callers that need the same java without an
    Installation or a workdir — the codec regen module — reuse it instead of
    re-implementing it.
    """
    named = java or os.environ.get(JAVA_ENV) or shutil.which("java")
    if not named:
        msg = f"no java launcher: pass java=, set {JAVA_ENV}, or put java on PATH"
        raise PrepareError(msg)
    resolved = Path(named).resolve()
    version = java_version(resolved)
    major = re.match(r"\d+", version)
    if major is None or int(major[0]) != target.java_major:
        msg = (
            f"{resolved} is Java {version}, but {target.minecraft_version} needs Java "
            f"{target.java_major}: pass java= or set {JAVA_ENV} to a Java "
            f"{target.java_major} launcher"
        )
        raise PrepareError(msg)
    return resolved


class VanillaAdapter:
    """Provisions the vanilla server jar and prepares it for a ServerSpec."""

    name = "vanilla"

    def __init__(self, fetch: Fetch = https_get, *, java: Path | None = None) -> None:
        """Download with `fetch`, and launch with the `java` launcher.

        Unit tests pass a fake `fetch` so they never touch the network. Without `java`,
        the launcher is MSCTS_JAVA, else the `java` on the harness PATH, looked up at
        prepare time.
        """
        self._fetch = fetch
        self._java = java

    def provision(self, target: Target, cache_dir: Path) -> Installation:
        """Download the server jar for `target` into `cache_dir/vanilla/<version>/`.

        Idempotent: a cached jar whose sha1 matches the manifest is not downloaded again.
        """
        server = self._server_download(target)
        root = cache_dir.absolute() / self.name / target.minecraft_version
        jar = root / JAR
        if not (jar.is_file() and _sha1(jar.read_bytes()) == server.sha1):
            data = self._fetch(server.url)
            _verify(data, sha1=server.sha1, size=server.size, what=server.url)
            root.mkdir(parents=True, exist_ok=True)
            _replace_atomically(jar, data)
        protocol = _protocol_version(jar)
        if protocol != target.protocol_version:
            msg = f"{jar} speaks protocol {protocol}, but the Target is {target.protocol_version}"
            raise ProvisionError(msg)
        return Installation(adapter=self.name, target=target, root=root)

    def _server_download(self, target: Target) -> _Download:
        """The verified manifest -> version JSON -> `downloads.server` chain for `target`."""
        manifest = json.loads(self._fetch(MANIFEST_URL))
        entries = [v for v in manifest["versions"] if v["id"] == target.minecraft_version]
        if len(entries) != 1:
            msg = f"{target.minecraft_version} is not in the version manifest exactly once"
            raise ProvisionError(msg)
        document = self._fetch(entries[0]["url"])
        _verify(document, sha1=entries[0]["sha1"], what=entries[0]["url"])
        version = json.loads(document)
        java = version["javaVersion"]["majorVersion"]
        if java != target.java_major:
            msg = (
                f"{target.minecraft_version} needs Java {java}, "
                f"but the Target says Java {target.java_major}"
            )
            raise ProvisionError(msg)
        server = version["downloads"]["server"]
        return _Download(url=str(server["url"]), sha1=str(server["sha1"]), size=int(server["size"]))

    def _java_launcher(self, target: Target) -> Path:
        """The real, absolute path of a java launcher of `target`'s Java major version."""
        return resolve_java(target, self._java)

    def prepare(self, installation: Installation, spec: ServerSpec, workdir: Path) -> LaunchPlan:
        """Write the complete vanilla config for `spec` into `workdir`, new or empty."""
        java = self._java_launcher(installation.target)
        workdir.mkdir(parents=True, exist_ok=True)
        if any(workdir.iterdir()):
            # Vanilla keeps its world, bans, user cache and icon there: a reused workdir
            # would carry one Instance's state into the next.
            msg = f"workdir {workdir} is not empty; each Instance needs a new or empty one"
            raise PrepareError(msg)
        (workdir / "eula.txt").write_bytes(b"eula=true\n")
        (workdir / "server.properties").write_text(
            java_properties(server_properties(spec)), encoding="ascii"
        )
        (workdir / "ops.json").write_text(ops_json(spec.operators), encoding="utf-8")
        jar = installation.root.absolute() / JAR
        # Documented order: HEAP, then NO_NETWORK (established first), then
        # HOST_INDEPENDENCE, then -jar. The two tables are independent of each other, but a
        # fixed order keeps the LaunchPlan's argv reproducible and the golden-argv test
        # meaningful.
        no_network = tuple(f"-D{name}={value}" for name, value in NO_NETWORK.items())
        host_independence = tuple(f"-D{name}={value}" for name, value in HOST_INDEPENDENCE.items())
        return LaunchPlan(
            argv=(str(java), HEAP, *no_network, *host_independence, "-jar", str(jar), "nogui"),
            cwd=workdir,
            env=LAUNCH_ENV,
            endpoint=Endpoint(host=spec.host, port=spec.port),  # exactly what it binds
            stop_stdin=b"stop\n",
        )
