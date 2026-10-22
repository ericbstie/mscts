"""Fixtures the Group tests share."""

import pytest
from support import control


@pytest.fixture
def long_play(monkeypatch: pytest.MonkeyPatch) -> None:
    """Let a fake serve a Bot for a play that takes minutes (a test that asks for it)."""
    monkeypatch.setattr(control, "PLAY_TIMEOUT_S", 280.0)
