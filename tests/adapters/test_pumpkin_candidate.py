import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from mscts.adapters.base import Installation
from mscts.adapters.fetch import Download, https_get
from mscts.adapters.pumpkin import NIGHTLY_URL, PumpkinAdapter
from mscts.target import TARGET

pytestmark = pytest.mark.candidate


def test_provision_fetches_the_nightly_and_records_it(cache_dir: Path) -> None:
    installation = PumpkinAdapter().provision(TARGET, cache_dir)
    assert installation == Installation(
        adapter="pumpkin", target=TARGET, root=cache_dir / "pumpkin/26.3"
    )
    binary = (installation.root / "pumpkin").read_bytes()
    source = json.loads((installation.root / "SOURCE.json").read_text(encoding="utf-8"))
    assert binary.startswith(b"\x7fELF")
    assert (source["url"], source["size"], source["sha256"]) == (
        NIGHTLY_URL,
        len(binary),
        hashlib.sha256(binary).hexdigest(),
    )
    # GitHub redirects the release URL to its asset host; every hop stayed on HTTPS.
    final = urlsplit(source["final_url"])
    assert (final.scheme, final.hostname) == ("https", "release-assets.githubusercontent.com")


def test_provision_does_not_download_a_cached_nightly_again(cache_dir: Path) -> None:
    binary = PumpkinAdapter().provision(TARGET, cache_dir).root / "pumpkin"
    before = binary.stat()
    fetched: list[str] = []

    def recording_get(url: str) -> Download:
        fetched.append(url)
        return https_get(url)

    PumpkinAdapter(fetch=recording_get).provision(TARGET, cache_dir)
    assert fetched == []
    after = binary.stat()
    assert (after.st_ino, after.st_mtime_ns) == (before.st_ino, before.st_mtime_ns)
