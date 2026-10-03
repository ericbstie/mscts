import hashlib
from pathlib import Path

import pytest

from mscts import install
from mscts.adapters.pumpkin import PumpkinAdapter
from mscts.target import TARGET

pytestmark = pytest.mark.candidate


def test_require_gives_the_installed_build_verified_and_recorded(cache_dir: Path) -> None:
    installation = install.require(PumpkinAdapter(), TARGET, cache_dir)
    assert installation.root == cache_dir / "pumpkin/26.3"
    assert installation.source is not None
    binary = (installation.root / "pumpkin").read_bytes()
    assert binary.startswith(b"\x7fELF")
    assert (installation.source.sha256, installation.source.size) == (
        hashlib.sha256(binary).hexdigest(),
        len(binary),
    )
    # It names the commit the binary itself names.
    named = PumpkinAdapter().check(installation.root / "pumpkin", TARGET)
    assert installation.source.build is not None
    assert installation.source.commit == named.commit
