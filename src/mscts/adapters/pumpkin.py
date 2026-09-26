"""A Candidate Adapter: Pumpkin (Rust), from its nightly release."""

import datetime
import hashlib
import json
import shutil
import tempfile
from pathlib import Path

from mscts.adapters.base import Installation, ProvisionError
from mscts.adapters.fetch import Fetch, https_get
from mscts.target import Target

# The Linux x86-64 binary of Pumpkin's rolling "nightly" release (docs/research/
# 2026-09-26-pumpkin.md). It redirects to a signed, short-lived GitHub asset URL.
NIGHTLY_URL = "https://github.com/Pumpkin-MC/Pumpkin/releases/download/nightly/pumpkin-X64-Linux"
BINARY = "pumpkin"
# What was fetched, from where and when: the nightly publishes no hash to verify against,
# so the Installation records its own and every later provision checks the binary by it.
SOURCE = "SOURCE.json"
_ELF_MAGIC = b"\x7fELF"


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
    """Provisions the Pumpkin nightly binary."""

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
