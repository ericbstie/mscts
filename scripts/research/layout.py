r"""Print the wire-relevant instructions of a class's methods, from javap output.

A `STREAM_CODEC` is built from lambdas and method references, so its layout is in the static
initializer and the `lambda$...` methods it binds. This runs `scripts/research/javap.py -v`
on one class and prints, for every method whose header matches a regex, only the instructions
that decide the layout (invocations, field accesses, constants, branches). Each
`invokedynamic` is resolved to the method it binds, so a lambda can be followed by name:

    mise exec -- uv run python scripts/research/layout.py server \
        net.minecraft.core.component.DataComponentPatch 'static|lambda'
"""

import argparse
import re
import subprocess  # nosec B404
import sys
from pathlib import Path

_JAVAP = Path(__file__).with_name("javap.py")
_METHOD_HEADER = re.compile(r"^  [^\s#\d].*[;{]$")  # not a constant pool or bootstrap row
_INSTRUCTION = re.compile(r"^\s+\d+: (\w+)\s*(.*)$")
_BOOTSTRAP_HEAD = re.compile(r"^  (\d+): #\d+ ")
_BOOTSTRAP_HANDLE = re.compile(r"^\s+#\d+ (REF_\w+) (\S+?):")
_INVOKEDYNAMIC = re.compile(r"InvokeDynamic #(\d+):")
_KEPT = (
    "invoke",
    "getstatic",
    "putstatic",
    "getfield",
    "putfield",
    "ldc",
    "bipush",
    "sipush",
    "new",
    "if",
    "iconst",
    "checkcast",
    "instanceof",
    "goto",
    "tableswitch",
    "lookupswitch",
)
_MAX_WIDTH = 240


def _short(text: str) -> str:
    return text.replace("net/minecraft/", "").replace("java/lang/", "")


def _bootstrap_targets(lines: list[str]) -> dict[int, str]:
    """Each bootstrap method's bound method (its first method handle argument), by index."""
    targets: dict[int, str] = {}
    index: int | None = None
    in_table = False
    for line in lines:
        if line == "BootstrapMethods:":
            in_table = True
            continue
        if not in_table:
            continue
        head = _BOOTSTRAP_HEAD.match(line)
        if head:
            index = int(head[1])
            continue
        handle = _BOOTSTRAP_HANDLE.match(line)
        if handle and index is not None:
            targets.setdefault(index, f"{handle[1]} {_short(handle[2])}")
    return targets


def _operand(rest: str, targets: dict[int, str]) -> str:
    """An instruction's operand as the constant pool resolves it (javap's `//` comment)."""
    _, _, comment = rest.partition("//")
    text = comment.strip() if comment else rest.strip()
    bound = _INVOKEDYNAMIC.search(text)
    if bound:
        return f"-> {targets.get(int(bound[1]), text)}"
    return _short(text)


def layout(javap: str, method: str, *, show_all: bool = False) -> list[str]:
    """The instructions of each method of `javap` whose header matches the regex `method`.

    Args:
        javap: Output of `javap -c -p -constants -v` for one class.
        method: A regex searched in each method (or field) header line.
        show_all: Keep every instruction, not only the ones that decide a layout.

    Returns:
        A `METHOD <header>` line for each match, then one indented line per instruction.
    """
    lines = javap.splitlines()
    targets = _bootstrap_targets(lines)
    pattern = re.compile(method)
    printed: list[str] = []
    selected = False
    for line in lines:
        if line == "BootstrapMethods:":
            break
        if line and not line[0].isspace():
            selected = False
        if _METHOD_HEADER.match(line):
            header = line.strip()
            is_method = "(" in header or header == "static {};"  # a field has no code
            selected = is_method and pattern.search(header) is not None
            if selected:
                printed.append(f"METHOD {header[:_MAX_WIDTH]}")
            continue
        found = _INSTRUCTION.match(line) if selected else None
        if found and (show_all or found[1].startswith(_KEPT)):
            operand = _operand(found[2], targets)
            printed.append(f"    {found[1]} {operand}".rstrip()[:_MAX_WIDTH])
    return printed


def javap_text(side: str, class_name: str) -> str:
    """`javap.py -v` output for `class_name` on the `side` jar.

    Raises:
        RuntimeError: javap.py failed (a missing class, no Java 25); the message is its stderr.
    """
    argv = [sys.executable, str(_JAVAP), "-v", side, class_name]
    # Our own interpreter running the sibling script, with separate arguments and no shell.
    result = subprocess.run(  # noqa: S603  # nosec B603
        argv, capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        msg = f"javap.py exited {result.returncode}: {result.stderr.strip()}"
        raise RuntimeError(msg)
    return result.stdout


def main(argv: list[str] | None = None) -> int:
    """Print the layout instructions for `Class METHOD-REGEX` and return the exit status."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("side", choices=("client", "server"))
    parser.add_argument("class_name", metavar="Class", help="fully qualified; quote a `$`")
    parser.add_argument("method", metavar="METHOD-REGEX", help="searched in each method header")
    parser.add_argument("--all", action="store_true", help="print every instruction")
    args = parser.parse_args(argv)
    try:
        text = javap_text(args.side, args.class_name)
    except (OSError, RuntimeError) as error:
        print(f"layout.py: {error}", file=sys.stderr)
        return 1
    for line in layout(text, args.method, show_all=args.all):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
