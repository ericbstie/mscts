import ipaddress
import socket
import types

import pytest

from mscts import runner
from mscts.runner import free_endpoint


def test_free_endpoint_is_a_loopback_host_and_port_a_server_can_listen_on_right_away() -> None:
    endpoint = free_endpoint()
    host = ipaddress.IPv4Address(endpoint.host)
    # 127.0.0.0/16 (127.0.0.1, systemd's 127.0.0.53, Debian's 127.0.1.1) is left to others.
    assert host in ipaddress.IPv4Network("127.0.0.0/8")
    assert host not in ipaddress.IPv4Network("127.0.0.0/16")
    assert 1024 < endpoint.port <= 65535
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind((endpoint.host, endpoint.port))  # free_endpoint has released it
        server.listen()


@pytest.mark.parametrize(
    ("draw", "host"),
    [(lambda _n: 0, "127.1.0.1"), (lambda n: n - 1, "127.254.255.254")],
    ids=["lowest", "highest"],
)
def test_free_endpoint_hosts_run_from_127_1_0_1_to_127_254_255_254(
    monkeypatch: pytest.MonkeyPatch, draw: object, host: str
) -> None:
    monkeypatch.setattr(runner, "secrets", types.SimpleNamespace(randbelow=draw))
    assert free_endpoint().host == host


def test_free_endpoint_hands_every_instance_its_own_host() -> None:
    # 20 draws from about 16.5 million hosts repeat one with odds of about 1 in 87 000.
    assert len({free_endpoint().host for _ in range(20)}) == 20
