import uuid
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from support.leak_guard import kill_survivors

from mscts.run import Server
from mscts.target import TARGET
from tests.run.fakes import TOKEN_VAR, FakeAdapter


@pytest.fixture
def run_token() -> Iterator[str]:
    """A token for this test's fake Instances; fails the test if one outlives it."""
    token = uuid.uuid4().hex
    yield token
    leaked = kill_survivors(f"{TOKEN_VAR}={token}")
    assert not leaked, f"fake Instances outlived the test: {leaked}"


@pytest.fixture
def fake_server(run_token: str, tmp_path: Path) -> Callable[..., Server]:
    """Make a Server whose Adapter is a FakeAdapter (see its arguments)."""

    def make(name: str, description: str | None = None) -> Server:
        adapter = FakeAdapter(name=name, token=run_token, description=description)
        return Server(adapter, adapter.provision(TARGET, tmp_path / "installations"))

    return make
