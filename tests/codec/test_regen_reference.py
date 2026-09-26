from pathlib import Path

import pytest

from mscts.codec import regen

pytestmark = pytest.mark.reference


def test_check_mode_confirms_the_committed_packets_json_is_up_to_date(
    cache_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The real regen, end to end: the installed jar (from the shared cache), run the vanilla data
    # generator in a scratch dir outside the repo, and diff its packets.json byte-for-byte
    # against the committed copy.
    monkeypatch.setattr(regen, "cache_dir", lambda: cache_dir)
    assert regen.main([]) == 0
