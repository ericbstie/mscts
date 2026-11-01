"""A stand-in server process that a Group's Control can join, for Run tests (#531).

Usage: control_fake.py HOST PORT [crash COMMAND] [refuse COMMAND]

It listens on HOST:PORT. A status connection is answered as vanilla 26.3 answers it for the
default ServerSpec (`VANILLA_STATUS`), and a login is served as `support.control.ControlServer`
serves it: a Bot joins, and Control's commands, `tick` included, are answered. It stops when a
line `stop` arrives on stdin, like vanilla.

Given `crash COMMAND`, the process exits at once with code 101 when COMMAND arrives, before it
answers, as Pumpkin exits when it panics: every connection is lost. Given `refuse COMMAND`, it
answers no marker from COMMAND on, as a server that will not unfreeze its world (#228): it
still answers a status request.

It imports mscts and the test fakes, so it needs the project's Python and PYTHONPATH (the
FakeAdapter gives both); it starts in about 0.3 s.
"""

import asyncio
import contextlib
import json
import os
import sys
import threading
from typing import override

from support.control import TREE, ControlServer

from mscts.codec.packets import Codec, Packet, State
from mscts.target import TARGET
from tests.net.fakes import VANILLA_STATUS, Peer, status_server

CRASH_EXIT_CODE = 101
"""The code the process exits with when its `crash` command arrives: Rust's for a panic."""


class _Replayed(Peer):
    """A Peer whose next `recv` returns a packet already read, then reads on."""

    def __init__(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, codec: Codec
    ) -> None:
        super().__init__(reader, writer, codec)
        self._again: Packet | None = None

    def replay(self, packet: Packet) -> None:
        """Return `packet` from the next `recv`."""
        self._again = packet

    @override
    async def recv(self) -> Packet:
        if self._again is not None:
            packet, self._again = self._again, None
            return packet
        return await super().recv()


def _control(options: dict[str, str]) -> ControlServer:
    """The ControlServer for a login, crashing or refusing as `options` say."""
    crash, refuse = options.get("crash"), options.get("refuse")

    def on_command(command: str) -> None:
        if command == crash:
            os._exit(CRASH_EXIT_CODE)
        if command == refuse:
            server.answers_markers = False

    server = ControlServer(commands=TREE, on_command=on_command)
    return server


async def _serve(host: str, port: int, options: dict[str, str]) -> None:
    """Serve each connection at `host`:`port`, by the intent of its intention, forever."""
    codec = Codec.for_target(TARGET)
    status = status_server(json.dumps(VANILLA_STATUS), [])
    control = _control(options)
    tasks: set[asyncio.Task[None]] = set()

    async def handle(peer: _Replayed) -> None:
        try:
            with contextlib.suppress(EOFError, ConnectionError):  # the client went first
                intention = await peer.recv()
                peer.replay(intention)
                await (status if peer.state is State.STATUS else control)(peer)
        finally:
            await peer.close()

    def on_connect(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        task = asyncio.create_task(handle(_Replayed(reader, writer, codec)))
        tasks.add(task)
        task.add_done_callback(tasks.discard)

    server = await asyncio.start_server(on_connect, host, port)
    async with server:
        await server.serve_forever()


def main() -> None:
    host, port = sys.argv[1], int(sys.argv[2])
    options = dict(zip(sys.argv[3::2], sys.argv[4::2], strict=True))
    serving = threading.Thread(target=asyncio.run, args=(_serve(host, port, options),))
    serving.daemon = True
    serving.start()
    for line in sys.stdin:
        if line.strip() == "stop":
            return


if __name__ == "__main__":
    main()
