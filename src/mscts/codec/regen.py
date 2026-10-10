"""Regenerate the vanilla data the codec commits and verify it against the committed copies.

That is the packet report (`packets.json`, copied verbatim), the names of the registries
the codec needs, in protocol id order (`registry_names.json`, derived from the registry
report), how many block states there are (`block_states.json`, from the block report), and
each item's stack size and equipment slot (`items.json`, from the item component reports).
Runnable as `python -m mscts.codec.regen` (check mode; non-zero exit and a message
on any difference) or `python -m mscts.codec.regen --write` (update the committed files).
See also the `regen:packets` mise task.
"""

import argparse
import json
import subprocess  # nosec B404
import sys
import tempfile
from pathlib import Path

from mscts import install
from mscts.adapters.base import ProvisionError
from mscts.adapters.vanilla import VanillaAdapter, resolve_java
from mscts.cache import cache_dir
from mscts.target import TARGET, Target

DATA_DIR = Path(__file__).parent / "data"
_REPORT_RELATIVE = Path("reports") / "packets.json"
_REGISTRIES_REPORT = "registries.json"
_BLOCKS_REPORT = "blocks.json"
_ITEM_REPORTS = Path("minecraft") / "components" / "item"
_DEFAULT_STACK_SIZE = 64
"""`Item.Properties`' default `max_stack_size`: items.json lists only the others."""
_GENERATOR_TIMEOUT_S = 300

REGISTRY_NAME_LISTS = (
    "minecraft:command_argument_type",
    "minecraft:consume_effect_type",
    "minecraft:data_component_type",
    "minecraft:entity_type",
    "minecraft:item",
    "minecraft:menu",
    "minecraft:recipe_display",
    "minecraft:slot_display",
)
"""The registries whose entry names are committed: the data component table and the consume
effect dispatch (`codec/components.py`), the command argument parsers (#17), the player's
entity type (the Comparison's entity renumbering, #21), a stack's item and an open screen's menu
(the Bot's inventory, #28), a recipe's slot display (#106) and a recipe book entry's display
(#62) take their ids from these lists, never from source."""


class RegenError(RuntimeError):
    """The data could not be regenerated or the generator's output is unusable."""


def packets_json_path(target: Target) -> Path:
    """Where the committed packets.json for `target` lives."""
    return DATA_DIR / target.minecraft_version / "packets.json"


def registry_names_path(target: Target) -> Path:
    """Where the committed registry_names.json for `target` lives."""
    return DATA_DIR / target.minecraft_version / "registry_names.json"


def block_states_path(target: Target) -> Path:
    """Where the committed block_states.json for `target` lives."""
    return DATA_DIR / target.minecraft_version / "block_states.json"


def items_path(target: Target) -> Path:
    """Where the committed items.json for `target` lives."""
    return DATA_DIR / target.minecraft_version / "items.json"


def data_generator_argv(java: Path, jar: Path, output: Path) -> list[str]:
    """The vanilla data generator's argv (protocol-research skill) for `jar` into `output`."""
    return [
        str(java),
        "-DbundlerMainClass=net.minecraft.data.Main",
        "-jar",
        str(jar),
        "--reports",
        "--output",
        str(output),
    ]


def run_data_generator(java: Path, jar: Path, output: Path) -> Path:
    """Run the vanilla data generator for `jar` into `output`; return the packets.json it wrote.

    Runs with `output` as the cwd, outside the repo: the bundler unpacks `libraries/` and
    `versions/` into the cwd (protocol-research skill). Raises RegenError on a non-zero
    exit or if the report is missing, so a silently-empty run is never mistaken for a match.
    """
    output.mkdir(parents=True, exist_ok=True)
    argv = data_generator_argv(java, jar, output)
    # argv is our own resolved java launcher plus the hash-verified, provisioned jar: no
    # shell, no untrusted input.
    result = subprocess.run(  # noqa: S603  # nosec B603
        argv,
        cwd=output,
        capture_output=True,
        text=True,
        timeout=_GENERATOR_TIMEOUT_S,
        check=False,
    )
    if result.returncode != 0:
        msg = f"data generator ({argv}) exited {result.returncode}:\n{result.stderr}"
        raise RegenError(msg)
    report = output / _REPORT_RELATIVE
    if not report.is_file():
        msg = f"data generator did not write {report}"
        raise RegenError(msg)
    return report


def registry_names_json(registries_report: bytes) -> bytes:
    """The text of registry_names.json for a generated `registries.json`.

    For each of REGISTRY_NAME_LISTS, the entry names in protocol id order (not the report's
    own key order). Raises RegenError if a registry is missing or its protocol ids are not
    0..n-1 (a gap or a repeat would make a name's position a wrong id).
    """
    report: object = json.loads(registries_report)
    lists: dict[str, list[str]] = {}
    for registry in REGISTRY_NAME_LISTS:
        pairs = _id_name_pairs(report, registry)
        if [protocol_id for protocol_id, _ in pairs] != list(range(len(pairs))):
            msg = f"{registry}: protocol ids are not 0 to {len(pairs) - 1} without a gap or repeat"
            raise RegenError(msg)
        lists[registry] = [name for _, name in pairs]
    return (json.dumps(lists, indent=2) + "\n").encode()


def _id_name_pairs(report: object, registry: str) -> list[tuple[int, str]]:
    """`registry`'s `(protocol id, name)` pairs from a parsed registries.json, id first."""
    body = report.get(registry) if isinstance(report, dict) else None
    entries = body.get("entries") if isinstance(body, dict) else None
    if not isinstance(entries, dict):
        msg = f"{_REGISTRIES_REPORT} has no {registry}"
        raise RegenError(msg)
    pairs: list[tuple[int, str]] = []
    for name, entry in entries.items():
        protocol_id = entry.get("protocol_id") if isinstance(entry, dict) else None
        if not isinstance(name, str) or not isinstance(protocol_id, int):
            msg = f"{registry}: entry {name!r} has no integer protocol_id"
            raise RegenError(msg)
        pairs.append((protocol_id, name))
    return sorted(pairs)


def block_states_json(blocks_report: bytes) -> bytes:
    """The text of block_states.json for a generated `blocks.json`: `{"count": n}`.

    `n` is how many block states the blocks have between them: the size of the global block
    state palette, which sets the width of a direct block container in a chunk. Raises
    RegenError if a state has no integer id, or the ids are not 0..n-1.
    """
    report: object = json.loads(blocks_report)
    ids: list[int] = []
    for block in report.values() if isinstance(report, dict) else [None]:
        states = block.get("states") if isinstance(block, dict) else None
        if not isinstance(states, list):
            msg = f"{_BLOCKS_REPORT}: a block has no list of states"
            raise RegenError(msg)
        for state in states:
            state_id = state.get("id") if isinstance(state, dict) else None
            if not isinstance(state_id, int):
                msg = f"{_BLOCKS_REPORT}: a block state has no integer id"
                raise RegenError(msg)
            ids.append(state_id)
    if sorted(ids) != list(range(len(ids))):
        msg = f"block state ids are not 0 to {len(ids) - 1} without a gap or repeat"
        raise RegenError(msg)
    return (json.dumps({"count": len(ids)}, indent=2) + "\n").encode()


def items_json(reports: Path) -> bytes:
    """The text of items.json for a generated `reports` directory.

    From each item's default components (`minecraft/components/item/<name>.json`):
    `max_stack_size`, each item whose stack size is not 64 by name, and `equippable`, each
    equippable item's equipment slot by name (the Bot's inventory predicts clicks with them,
    #28). Raises RegenError if there are no item reports, or one has no integer stack size or
    an equippable with no slot.
    """
    directory = reports / _ITEM_REPORTS
    files = sorted(directory.glob("*.json")) if directory.is_dir() else []
    if not files:
        msg = f"the data generator wrote no item reports in {_ITEM_REPORTS.as_posix()}"
        raise RegenError(msg)
    sizes: dict[str, int] = {}
    slots: dict[str, str] = {}
    for file in files:
        name = f"minecraft:{file.stem}"
        report: object = json.loads(file.read_bytes())
        components = report.get("components") if isinstance(report, dict) else None
        size = components.get("minecraft:max_stack_size") if isinstance(components, dict) else None
        if not isinstance(components, dict) or not isinstance(size, int):
            msg = f"{name}: its item report has no integer max_stack_size"
            raise RegenError(msg)
        if size != _DEFAULT_STACK_SIZE:
            sizes[name] = size
        equippable = components.get("minecraft:equippable")
        if equippable is not None:
            slot = equippable.get("slot") if isinstance(equippable, dict) else None
            if not isinstance(slot, str):
                msg = f"{name}: its equippable has no slot"
                raise RegenError(msg)
            slots[name] = slot
    lists = {
        "max_stack_size": dict(sorted(sizes.items())),
        "equippable": dict(sorted(slots.items())),
    }
    return (json.dumps(lists, indent=2) + "\n").encode()


def fresh_data(target: Target, reports: Path) -> dict[Path, bytes]:
    """Each committed file's fresh contents, from a data generator's `reports` directory.

    Raises RegenError if `registries.json` or `blocks.json` is missing (packets.json is
    checked by run_data_generator).
    """
    registries, blocks = reports / _REGISTRIES_REPORT, reports / _BLOCKS_REPORT
    for report in (registries, blocks):
        if not report.is_file():
            msg = f"data generator did not write {report}"
            raise RegenError(msg)
    return {
        packets_json_path(target): (reports / "packets.json").read_bytes(),
        registry_names_path(target): registry_names_json(registries.read_bytes()),
        block_states_path(target): block_states_json(blocks.read_bytes()),
        items_path(target): items_json(reports),
    }


def regenerate(target: Target, cache: Path) -> dict[Path, bytes]:
    """Every committed file's fresh contents, from `target`'s installed jar.

    The jar must be installed already (`mscts adapter install vanilla`): install.require
    raises ProvisionError naming that command, and never downloads it here.

    Uses the exact same Java resolution `VanillaAdapter.prepare` uses (`resolve_java`), and
    runs the generator once, in a temporary directory outside the repo.
    """
    installation = install.require(VanillaAdapter(), target, cache)
    java = resolve_java(target)
    jar = (installation.root / "server.jar").absolute()
    with tempfile.TemporaryDirectory(prefix="mscts-regen-") as tmp:
        report = run_data_generator(java, jar, Path(tmp))
        return fresh_data(target, report.parent)


def compare_or_write(generated: bytes, committed_path: Path, *, write: bool) -> str | None:
    """Apply the regen decision. Returns an error message, or None on success.

    `write=True` replaces `committed_path` with `generated` unconditionally (creating its
    parent directory if needed). Otherwise, compares them byte-for-byte.
    """
    if write:
        committed_path.parent.mkdir(parents=True, exist_ok=True)
        committed_path.write_bytes(generated)
        return None
    if not committed_path.is_file():
        return f"{committed_path} does not exist; run with --write to create it"
    committed = committed_path.read_bytes()
    if generated != committed:
        return (
            f"{committed_path} ({len(committed)} bytes) does not match a fresh regen "
            f"({len(generated)} bytes); run `python -m mscts.codec.regen --write` to update it"
        )
    return None


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: `python -m mscts.codec.regen [--write]`."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write",
        action="store_true",
        help="update the committed files instead of failing on a difference",
    )
    args = parser.parse_args(argv)
    try:
        generated = regenerate(TARGET, cache_dir())
    except (RegenError, ProvisionError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    messages = [
        message
        for path, data in generated.items()
        if (message := compare_or_write(data, path, write=args.write)) is not None
    ]
    for message in messages:
        print(f"error: {message}", file=sys.stderr)
    if messages:
        return 1
    verb = "wrote" if args.write else "verified"
    for path, data in generated.items():
        print(f"{verb} {path} ({len(data)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
