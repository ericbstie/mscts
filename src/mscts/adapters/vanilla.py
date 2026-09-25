"""The Reference Adapter: vanilla Minecraft server for the Target."""

from collections.abc import Mapping

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
