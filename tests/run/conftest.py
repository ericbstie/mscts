from collections.abc import Callable
from pathlib import Path

import pytest

from mscts.adapters.base import Installation
from mscts.run import Server
from mscts.target import TARGET
from tests.run.fakes import FakeAdapter


@pytest.fixture
def fake_server(run_token: str, tmp_path: Path) -> Callable[..., Server]:
    """Make a Server whose Adapter is a FakeAdapter (see its arguments)."""

    def make(
        name: str,
        description: str | None = None,
        *,
        hangs_after_ping: int | None = None,
        lingers_after_ping: int | None = None,
        fails_launch: frozenset[int] = frozenset[int](),
    ) -> Server:
        adapter = FakeAdapter(
            name=name,
            token=run_token,
            description=description,
            hangs_after_ping=hangs_after_ping,
            lingers_after_ping=lingers_after_ping,
            fails_launch=fails_launch,
        )
        installation = Installation(adapter=name, target=TARGET, root=tmp_path / "installations")
        return Server(adapter, installation)

    return make
