"""A live check that scripts/research/join.py's own `join` works end to end against vanilla."""

import importlib.util
import types
from pathlib import Path

import pytest

from mscts import install
from mscts.adapters.vanilla import VanillaAdapter
from mscts.cache import cache_dir
from mscts.runner import free_endpoint
from mscts.spec import ServerSpec
from mscts.target import TARGET

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "research" / "join.py"

pytestmark = pytest.mark.reference


@pytest.fixture
def join_module() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("research_join_reference", _SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.asyncio
async def test_join_records_a_decoded_login_and_a_decodable_chunk(
    join_module: types.ModuleType, tmp_path: Path
) -> None:
    adapter = VanillaAdapter()
    installation = install.require(adapter, TARGET, cache_dir())
    endpoint = free_endpoint()
    spec = ServerSpec(host=endpoint.host, port=endpoint.port)
    workdir = tmp_path / "workdir"

    transcript = await join_module.join(adapter, installation, spec, workdir)

    assert not workdir.exists()
    logins = [event.packet for event in transcript.events if event.packet.name == "minecraft:login"]
    assert len(logins) == 1
    assert logins[0].fields is not None
    chunk_payloads = [
        event.packet.payload
        for event in transcript.events
        if event.packet.name == "minecraft:level_chunk_with_light"
    ]
    assert chunk_payloads
    chunk = join_module.chunkformat.decode_chunk(
        chunk_payloads[0], join_module.chunkformat.OVERWORLD_SECTIONS
    )
    assert chunk.sections
