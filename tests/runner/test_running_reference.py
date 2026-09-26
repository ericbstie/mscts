"""The runner against the Reference: vanilla 26.3 becomes ready and stops on its stop line."""

import asyncio
import contextlib
import json
import logging
import sys
import time
from collections.abc import Callable
from pathlib import Path

import pytest

from mscts.adapters.vanilla import VanillaAdapter
from mscts.codec.framing import FrameDecoder, encode_frame
from mscts.codec.wire import Reader, WireError, Writer
from mscts.net import Endpoint
from mscts.runner import free_port, running
from mscts.spec import ServerSpec
from mscts.target import TARGET

pytestmark = pytest.mark.reference

READY_TIMEOUT_S = 120  # a cold first boot unpacks the bundled libraries and makes a world
STOP_TIMEOUT_S = 30
_PROBE_TIMEOUT_S = 1.0
# Packet ids from the vanilla-generated packets.json for 26.3; layouts from
# docs/research/2026-09-25-domain.md ("Connection sequence", verified).
_INTENTION = _STATUS_REQUEST = _STATUS_RESPONSE = 0
_INTENT_STATUS = 1


async def answers_status(endpoint: Endpoint) -> bool:
    """Readiness as ADR-0004 defines it: a status ping answers with the Target protocol.

    A stand-in until the status-ping client (Connection, Bot.status) lands. A TCP connect
    is not enough: vanilla accepts connections before its world exists, and a console
    line it reads then is lost (docs/research/2026-09-26-runner.md).
    """
    try:
        reader, writer = await asyncio.open_connection(endpoint.host, endpoint.port)
    except OSError:
        return False
    intention = (
        Writer()
        .var_int(_INTENTION)
        .var_int(TARGET.protocol_version)
        .string(endpoint.host, max_length=255)
        .ushort(endpoint.port)
        .var_int(_INTENT_STATUS)
    )
    status_request = Writer().var_int(_STATUS_REQUEST)
    try:
        for packet in (intention, status_request):
            writer.write(encode_frame(packet.to_bytes(), compression_threshold=None))
        await writer.drain()
        decoder = FrameDecoder()
        frames: list[bytes] = []
        async with asyncio.timeout(_PROBE_TIMEOUT_S):
            while not frames:
                chunk = await reader.read(65536)
                if not chunk:
                    return False
                frames = decoder.feed(chunk)
        response = Reader(frames[0])
        if response.var_int() != _STATUS_RESPONSE:
            return False
        protocol = json.loads(response.string(max_length=32767))["version"]["protocol"]
    except (OSError, TimeoutError, WireError, ValueError, KeyError, TypeError):
        return False
    finally:
        writer.close()
        with contextlib.suppress(OSError):
            await writer.wait_closed()
    return isinstance(protocol, int) and protocol == TARGET.protocol_version


@pytest.mark.asyncio
async def test_vanilla_becomes_ready_and_stops_gracefully_on_its_stop_line(
    cache_dir: Path,
    tmp_path: Path,
    is_alive: Callable[[int], bool],
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    caplog.set_level(logging.INFO, logger="mscts.runner")
    adapter = VanillaAdapter()
    installation = adapter.provision(TARGET, cache_dir)
    plan = adapter.prepare(installation, ServerSpec(port=free_port()), tmp_path / "vanilla")
    assert plan.stop_stdin == b"stop\n"
    # Cold: the first boot of a fresh workdir. Warm: the same workdir again, world made.
    for boot in ("cold", "warm"):
        async with running(
            plan, ready=answers_status, ready_timeout=READY_TIMEOUT_S, stop_timeout=STOP_TIMEOUT_S
        ) as instance:
            leaving = time.monotonic()
        stopping_s = time.monotonic() - leaving
        assert not is_alive(instance.pid)
        (record,) = (r for r in caplog.records if f"(pid {instance.pid}) stopped" in r.getMessage())
        assert record.getMessage().endswith("stopped by stdin with exit code 0")
        assert stopping_s < STOP_TIMEOUT_S / 3  # well within: it was never close to SIGTERM
        startup_ms = (instance.ready_ns - instance.launched_ns) / 1e6
        with capsys.disabled():
            sys.stderr.write(
                f"\nvanilla {boot} boot: launched -> ready (status ping) {startup_ms:.0f} ms,"
                f" stop {stopping_s * 1000:.0f} ms\n"
            )
