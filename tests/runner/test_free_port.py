import socket

from mscts.runner import free_port


def test_free_port_is_an_unprivileged_port_a_server_can_listen_on_right_away() -> None:
    port = free_port()
    assert 1024 < port <= 65535
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("127.0.0.1", port))  # free_port has released it
        server.listen()


def test_free_port_hands_out_different_ports() -> None:
    assert len({free_port() for _ in range(20)}) > 1
