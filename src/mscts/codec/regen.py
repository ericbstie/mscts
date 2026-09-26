"""Regenerate the vanilla packet report and verify it against the committed copy.

Runnable as `python -m mscts.codec.regen` (check mode; non-zero exit and a message on any
difference) or `python -m mscts.codec.regen --write` (update the committed file). See also
the `regen:packets` mise task.
"""

import argparse
import subprocess  # nosec B404
import sys
import tempfile
from pathlib import Path

from mscts.adapters.vanilla import VanillaAdapter, resolve_java
from mscts.cache import cache_dir
from mscts.target import TARGET, Target

DATA_DIR = Path(__file__).parent / "data"
_REPORT_RELATIVE = Path("reports") / "packets.json"
_GENERATOR_TIMEOUT_S = 300


class RegenError(RuntimeError):
    """The packet report could not be regenerated or the generator's output is unusable."""


def packets_json_path(target: Target) -> Path:
    """Where the committed packets.json for `target` lives."""
    return DATA_DIR / target.minecraft_version / "packets.json"


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


def regenerate(target: Target, cache: Path) -> bytes:
    """Provision `target`'s jar and return a freshly generated packets.json's bytes.

    Uses the exact same Java resolution `VanillaAdapter.prepare` uses (`resolve_java`), and
    runs the generator in a temporary directory outside the repo.
    """
    installation = VanillaAdapter().provision(target, cache)
    java = resolve_java(target)
    jar = (installation.root / "server.jar").absolute()
    with tempfile.TemporaryDirectory(prefix="mscts-regen-") as tmp:
        report = run_data_generator(java, jar, Path(tmp))
        return report.read_bytes()


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
        help="update the committed packets.json instead of failing on a difference",
    )
    args = parser.parse_args(argv)
    committed_path = packets_json_path(TARGET)
    try:
        generated = regenerate(TARGET, cache_dir())
    except RegenError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    message = compare_or_write(generated, committed_path, write=args.write)
    if message is not None:
        print(f"error: {message}", file=sys.stderr)
        return 1
    verb = "wrote" if args.write else "verified"
    print(f"{verb} {committed_path} ({len(generated)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
