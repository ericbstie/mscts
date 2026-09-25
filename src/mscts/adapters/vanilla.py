"""The Reference Adapter: vanilla Minecraft server for the Target."""

import os
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType

from mscts.adapters.base import Installation, LaunchPlan
from mscts.net import Endpoint
from mscts.spec import ServerSpec

# The server binds loopback only: in offline mode anyone who can reach the port can log
# in under an operator's name. The Endpoint uses the same address, so it is exactly
# what the server bound (IPv4; never a `localhost` that might resolve to ::1).
HOST = "127.0.0.1"
JAR = "server.jar"
# A fixed max heap, so the Reference's memory (and GC timing) does not depend on the
# host: the JVM default is a quarter of physical RAM.
HEAP = "-Xmx1G"

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


class VanillaAdapter:
    """Provisions the vanilla server jar and prepares it for a ServerSpec."""

    name = "vanilla"

    def prepare(self, installation: Installation, spec: ServerSpec, workdir: Path) -> LaunchPlan:
        """Write the complete vanilla config for `spec` into `workdir`."""
        workdir.mkdir(parents=True, exist_ok=True)
        (workdir / "eula.txt").write_bytes(b"eula=true\n")
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
