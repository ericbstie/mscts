"""Regenerate the vanilla data the codec commits and verify it against the committed copies.

That is the packet report (`packets.json`, copied verbatim) and the names of the registries
the codec needs, in protocol id order (`registry_names.json`, derived from the registry
report). Runnable as `python -m mscts.codec.regen` (check mode; non-zero exit and a message
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
_GENERATOR_TIMEOUT_S = 300

REGISTRY_NAME_LISTS = (
    "minecraft:command_argument_type",
    "minecraft:consume_effect_type",
    "minecraft:data_component_type",
)
"""The registries whose entry names are committed: the data component table and the consume
effect dispatch (`codec/components.py`) and the command argument parsers (#17) take their ids
from these lists, never from source."""


class RegenError(RuntimeError):
    """The data could not be regenerated or the generator's output is unusable."""


def packets_json_path(target: Target) -> Path:
    """Where the committed packets.json for `target` lives."""
    return DATA_DIR / target.minecraft_version / "packets.json"


def registry_names_path(target: Target) -> Path:
    """Where the committed registry_names.json for `target` lives."""
    return DATA_DIR / target.minecraft_version / "registry_names.json"


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


def fresh_data(target: Target, reports: Path) -> dict[Path, bytes]:
    """Each committed file's fresh contents, from a data generator's `reports` directory.

    Raises RegenError if `registries.json` is missing (packets.json is checked by
    run_data_generator).
    """
    registries = reports / _REGISTRIES_REPORT
    if not registries.is_file():
        msg = f"data generator did not write {registries}"
        raise RegenError(msg)
    return {
        packets_json_path(target): (reports / "packets.json").read_bytes(),
        registry_names_path(target): registry_names_json(registries.read_bytes()),
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
