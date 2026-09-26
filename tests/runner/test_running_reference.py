"""The runner against the Reference: vanilla 26.3 becomes ready and stops on its stop line."""

import logging
import sys
import time
from collections.abc import Callable
from pathlib import Path

import pytest

from mscts import install
from mscts.adapters.vanilla import VanillaAdapter
from mscts.bot import status_probe
from mscts.runner import free_endpoint, running
from mscts.spec import ServerSpec
from mscts.target import TARGET

pytestmark = pytest.mark.reference

READY_TIMEOUT_S = 120  # a cold first boot unpacks the bundled libraries and makes a world
STOP_TIMEOUT_S = 30


# Two full boot/stop cycles: worst case 2 x (ready_timeout + 2 x stop_timeout), above the
# global 120 s pytest-timeout.
@pytest.mark.timeout(300)
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
    installation = install.require(adapter, TARGET, cache_dir)
    endpoint = free_endpoint()  # a loopback host of its own, never 127.0.0.1
    spec = ServerSpec(host=endpoint.host, port=endpoint.port)
    plan = adapter.prepare(installation, spec, tmp_path / "vanilla")
    assert plan.stop_stdin == b"stop\n"
    assert plan.endpoint == endpoint  # and vanilla binds exactly it (else never ready)
    # Cold: the first boot of a fresh workdir. Warm: the same workdir again, world made.
    for boot in ("cold", "warm"):
        async with running(
            plan,
            ready=status_probe(TARGET),
            ready_timeout=READY_TIMEOUT_S,
            stop_timeout=STOP_TIMEOUT_S,
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
