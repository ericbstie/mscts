"""A Pumpkin Instance from PumpkinAdapter becomes ready, reads its config, and stops cleanly."""

import asyncio
import contextlib
import dataclasses
import json
import logging
import sys
import time
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from support.leak_guard import kill_survivors

from mscts import install
from mscts.adapters.base import Installation
from mscts.adapters.pumpkin import PumpkinAdapter, pumpkin_toml
from mscts.codec.framing import FrameDecoder, encode_frame
from mscts.codec.packets import Codec, Direction, State
from mscts.net import Endpoint
from mscts.runner import free_endpoint, running
from mscts.spec import ServerSpec
from mscts.target import TARGET

pytestmark = pytest.mark.candidate

READY_TIMEOUT_S = 60  # it was ready in under 1 s here, fresh world included
STOP_TIMEOUT_S = 30
_PROBE_TIMEOUT_S = 1.0
_CODEC = Codec.for_target(TARGET)
_GUARD = "MSCTS_LEAK_GUARD"  # the env variable that tags this test's processes


async def status_of(endpoint: Endpoint) -> dict[str, object] | None:
    """The status JSON the server at `endpoint` answers a status ping with, else None.

    A faithful status ping on the Codec's handshake and status schemas: intention (next
    state status), status_request, then one status_response.
    """
    try:
        reader, writer = await asyncio.open_connection(endpoint.host, endpoint.port)
    except OSError:
        return None
    intention = {
        "protocol_version": TARGET.protocol_version,
        "server_address": endpoint.host,
        "server_port": endpoint.port,
        "intent": 1,  # status
    }
    try:
        for state, name, fields in (
            (State.HANDSHAKE, "minecraft:intention", intention),
            (State.STATUS, "minecraft:status_request", {}),
        ):
            packet = _CODEC.encode(state, Direction.SERVERBOUND, name, fields)
            writer.write(encode_frame(packet, compression_threshold=None))
        await writer.drain()
        decoder = FrameDecoder()
        async with asyncio.timeout(_PROBE_TIMEOUT_S):
            while (frame := decoder.next_frame()) is None:
                chunk = await reader.read(65536)
                if not chunk:
                    return None
                decoder.extend(chunk)
        response = _CODEC.decode(State.STATUS, Direction.CLIENTBOUND, frame)
        if response.name != "minecraft:status_response" or response.fields is None:
            return None
        status: object = json.loads(str(response.fields["json_response"]))
    except (OSError, TimeoutError, ValueError):  # CodecError and JSON errors are ValueErrors
        return None
    finally:
        writer.close()
        with contextlib.suppress(OSError):
            await writer.wait_closed()
    return {str(key): value for key, value in status.items()} if isinstance(status, dict) else None


def protocol_of(status: dict[str, object] | None) -> object:
    version = status.get("version") if status else None
    return version.get("protocol") if isinstance(version, dict) else None


async def answers_status(endpoint: Endpoint) -> bool:
    """Readiness as ADR-0004 defines it: a status ping answers with the Target protocol."""
    return protocol_of(await status_of(endpoint)) == TARGET.protocol_version


@pytest.fixture
def leak_token() -> Iterator[str]:
    """A token for this test's Instances; fails the test if a tagged process outlives it.

    The Instance's env carries it, so a Pumpkin (or a child of it) that the runner failed
    to stop is found in /proc, killed, and reported (tests/support/leak_guard.py).
    """
    token = uuid.uuid4().hex
    yield token
    # A stopped process takes a moment to exit, and PID 1 reaps lazily.
    leaked = kill_survivors(f"{_GUARD}={token}", within=3.0)
    assert not leaked, f"Pumpkin processes outlived the test: {leaked}"


@pytest.fixture
def installation(cache_dir: Path) -> Installation:
    return install.require(PumpkinAdapter(), TARGET, cache_dir)


@pytest.mark.asyncio
async def test_pumpkin_becomes_ready_reads_its_config_and_stops_on_its_stop_line(
    installation: Installation,
    tmp_path: Path,
    leak_token: str,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    caplog.set_level(logging.INFO, logger="mscts.runner")
    endpoint = free_endpoint()  # a loopback host of its own, never 127.0.0.1
    spec = ServerSpec(host=endpoint.host, port=endpoint.port)
    workdir = tmp_path / "pumpkin"
    plan = PumpkinAdapter().prepare(installation, spec, workdir)
    assert plan.stop_stdin == b"stop\n"
    # The one change to the plan: a leak-guard token in its (empty) env. Pumpkin ignores it.
    plan = dataclasses.replace(plan, env={**plan.env, _GUARD: leak_token})
    # Cold: the first boot of a fresh workdir. Warm: the same workdir again, world made.
    for boot in ("cold", "warm"):
        async with running(
            plan, ready=answers_status, ready_timeout=READY_TIMEOUT_S, stop_timeout=STOP_TIMEOUT_S
        ) as instance:
            status = await status_of(plan.endpoint)
            leaving = time.monotonic()
        stopping_s = time.monotonic() - leaving
        assert protocol_of(status) == TARGET.protocol_version
        # It read our pumpkin.toml, not its defaults (1000 players, "A blazingly fast
        # Pumpkin server!", 0.0.0.0:25565): the Endpoint answered with the spec's values.
        assert status is not None
        players, description = status.get("players"), status.get("description")
        assert isinstance(players, dict)
        assert players.get("max") == spec.max_players
        text = description.get("text") if isinstance(description, dict) else description
        assert text == spec.motd
        # And it knew every key in it: a missing one would have made it rewrite the file.
        assert (workdir / "pumpkin.toml").read_text(encoding="utf-8") == pumpkin_toml(spec)
        (record,) = (r for r in caplog.records if f"(pid {instance.pid}) stopped" in r.getMessage())
        assert record.getMessage().endswith("stopped by stdin with exit code 0")
        assert stopping_s < STOP_TIMEOUT_S / 3  # well within: it was never close to SIGTERM
        startup_ms = (instance.ready_ns - instance.launched_ns) / 1e6
        with capsys.disabled():
            sys.stderr.write(
                f"\npumpkin {boot} boot: launched -> ready (status ping) {startup_ms:.0f} ms,"
                f" stop {stopping_s * 1000:.0f} ms\n"
            )
