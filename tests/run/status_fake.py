"""A stand-in server process that answers the status protocol. Standard library only.

Usage: status_fake.py HOST PORT DESCRIPTION [hang PING] [linger PING]

It listens on HOST:PORT and answers each connection's status exchange as vanilla 26.3
does for the default ServerSpec, with DESCRIPTION as the description: a status_request
gets the status JSON, a ping_request its pong, after which it closes the connection.
It stops when a line `stop` arrives on stdin, like vanilla. It starts in ~20 ms, so a
Run over two of them tests the Run's Instance handling hermetically, readiness (the
status ping, with ownership) included.

Given `hang PING`, a ping whose payload is that number gets its pong, and then the
fake hangs, as Pumpkin does on some clicks (#513): it still accepts connections and
reads what comes, but never answers anything again. It hangs before the pong is sent,
so a request sent on seeing the pong is never answered.

Given `linger PING`, a ping whose payload is that number gets its pong, and from then on
the status says `LINGERER` is online, as Pumpkin's does after some of those clicks (#513):
the player of a Bot that has left is never removed. The status says so from before the
pong is sent.
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

LINGERER = "crafter"
"""The player a fake given `linger PING` keeps online after that ping."""


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


class Hang:
    """Whether the fake has hung, and the ping payload that hangs it (None: none does)."""

    def __init__(self, after_ping: bytes | None) -> None:
        self.after_ping = after_ping
        self.hung = threading.Event()

    def block_if_hung(self) -> None:
        """Never return once the fake has hung: nothing is answered any more."""
        if self.hung.is_set():
            threading.Event().wait()

    def pinged(self, payload: bytes) -> None:
        """Hang from now on if `payload` is the ping payload that hangs the fake."""
        if payload == self.after_ping:
            self.hung.set()


class Status:
    """The status JSON the fake answers with, and the ping payload after which a player lingers."""

    def __init__(self, description: str, linger_after_ping: bytes | None) -> None:
        self.description = description
        self.linger_after_ping = linger_after_ping
        self.lingering = threading.Event()

    def json(self) -> bytes:
        """The status: no player online, or `LINGERER` once the fake lingers."""
        players: dict[str, object] = {"max": 20, "online": 0}
        if self.lingering.is_set():
            players = {"max": 20, "online": 1, "sample": [{"name": LINGERER, "id": _UUID}]}
        return json.dumps(
            {
                "description": self.description,
                "players": players,
                "version": {"name": "26.3", "protocol": _PROTOCOL},
            }
        ).encode()

    def pinged(self, payload: bytes) -> None:
        """Keep `LINGERER` online from now on if `payload` is the ping payload that does so."""
        if payload == self.linger_after_ping:
            self.lingering.set()


_UUID = "00000000-0000-0000-0000-000000000513"


def serve_one(connection: socket.socket, status: Status, hang: Hang) -> None:
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
                hang.block_if_hung()
                packet_id, payload = body[0], body[1:]
                if packet_id == _STATUS_REQUEST:
                    text = status.json()
                    connection.sendall(frame(_STATUS_RESPONSE, var_int(len(text)) + text))
                elif packet_id == _PING_REQUEST:
                    # Before the pong, not after: a status ask made on seeing it must find
                    # the fake hung or lingering, however this thread is scheduled (#524).
                    status.pinged(payload)
                    hang.pinged(payload)
                    connection.sendall(frame(_PONG_RESPONSE, payload))
                    return
        except (EOFError, OSError):
            return


def ping_payload(options: dict[str, str], name: str) -> bytes | None:
    """The ping payload option `name` (`hang`, `linger`) gives, as the ping sends it; or None."""
    value = options.get(name)
    return None if value is None else int(value).to_bytes(8, "big", signed=True)


def main() -> None:
    host, port, description = sys.argv[1], int(sys.argv[2]), sys.argv[3]
    options = dict(zip(sys.argv[4::2], sys.argv[5::2], strict=True))
    hang = Hang(ping_payload(options, "hang"))
    status = Status(description, ping_payload(options, "linger"))
    server = socket.create_server((host, port))

    def accept_forever() -> None:
        while True:
            connection, _ = server.accept()
            threading.Thread(target=serve_one, args=(connection, status, hang), daemon=True).start()

    threading.Thread(target=accept_forever, daemon=True).start()
    os.write(1, b"listening\n")
    for line in sys.stdin:
        if line.strip() == "stop":
            return


if __name__ == "__main__":
    main()
