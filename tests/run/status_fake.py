"""A stand-in server process that answers the status protocol. Standard library only.

Usage: status_fake.py HOST PORT DESCRIPTION

It listens on HOST:PORT and answers each connection's status exchange as vanilla 26.3
does for the default ServerSpec, with DESCRIPTION as the description: a status_request
gets the status JSON, a ping_request its pong, after which it closes the connection.
It stops when a line `stop` arrives on stdin, like vanilla. It starts in ~20 ms, so a
Run over two of them tests the Run's Instance handling hermetically, readiness (the
status ping, with ownership) included.
"""

import json
import os
import socket
import sys
import threading
from collections.abc import Callable

_PROTOCOL = 777
_STATUS_REQUEST = _STATUS_RESPONSE = 0x00
_PING_REQUEST = _PONG_RESPONSE = 0x01


def var_int(value: int) -> bytes:
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def read_var_int(read: Callable[[int], bytes]) -> int:
    result = shift = 0
    while True:
        byte = read(1)[0]
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result
        shift += 7


def frame(packet_id: int, payload: bytes) -> bytes:
    data = var_int(packet_id) + payload
    return var_int(len(data)) + data


def serve_one(connection: socket.socket, status: bytes) -> None:
    stream = connection.makefile("rb")

    def read(n: int) -> bytes:
        data = stream.read(n)
        if len(data) < n:
            raise EOFError
        return data

    with connection, stream:
        try:
            read(read_var_int(read))  # the handshake (intention): status is all this answers
            while True:
                body = read(read_var_int(read))
                packet_id, payload = body[0], body[1:]
                if packet_id == _STATUS_REQUEST:
                    connection.sendall(frame(_STATUS_RESPONSE, var_int(len(status)) + status))
                elif packet_id == _PING_REQUEST:
                    connection.sendall(frame(_PONG_RESPONSE, payload))
                    return
        except (EOFError, OSError):
            return


def main() -> None:
    host, port, description = sys.argv[1], int(sys.argv[2]), sys.argv[3]
    status = json.dumps(
        {
            "description": description,
            "players": {"max": 20, "online": 0},
            "version": {"name": "26.3", "protocol": _PROTOCOL},
        }
    ).encode()
    server = socket.create_server((host, port))

    def accept_forever() -> None:
        while True:
            connection, _ = server.accept()
            threading.Thread(target=serve_one, args=(connection, status), daemon=True).start()

    threading.Thread(target=accept_forever, daemon=True).start()
    os.write(1, b"listening\n")
    for line in sys.stdin:
        if line.strip() == "stop":
            return


if __name__ == "__main__":
    main()
