"""A Pumpkin Instance from PumpkinAdapter becomes ready, reads its config, and stops cleanly."""

import asyncio
import contextlib
import json
import logging
import sys
import time
from pathlib import Path

import pytest
from support.reference import STOP_TIMEOUT_S, booted

from mscts import install
from mscts.adapters.pumpkin import PumpkinAdapter, pumpkin_toml
from mscts.codec.framing import FrameDecoder, encode_frame
from mscts.codec.packets import Codec, Direction, State
from mscts.net import Endpoint
from mscts.runner import free_endpoint
from mscts.spec import ServerSpec
from mscts.target import TARGET

pytestmark = pytest.mark.candidate

_PROBE_TIMEOUT_S = 1.0
_CODEC = Codec.for_target(TARGET)


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


@pytest.mark.asyncio
async def test_pumpkin_becomes_ready_reads_its_config_and_stops_on_its_stop_line(
    cache_dir: Path,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    caplog.set_level(logging.INFO, logger="mscts.runner")
    endpoint = free_endpoint()  # a loopback host of its own, never 127.0.0.1
    spec = ServerSpec(host=endpoint.host, port=endpoint.port)
    workdir = tmp_path / "pumpkin"
    adapter = PumpkinAdapter()
    plan = adapter.prepare(install.require(adapter, TARGET, cache_dir), spec, workdir)
    assert plan.stop_stdin == b"stop\n"
    with pytest.raises(ValueError, match="ServerSpec changes cannot be applied"):
        async with booted(cache_dir, workdir, plan=plan, motd="ignored"):
            pytest.fail("a prepared LaunchPlan silently ignored a ServerSpec change")
    # Cold: the first boot of a fresh workdir. Warm: the same workdir again, world made.
    for boot in ("cold", "warm"):
        async with booted(cache_dir, workdir, plan=plan) as instance:
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
