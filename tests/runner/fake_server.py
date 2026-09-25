"""A stand-in server for the runner's unit tests. Standard library only; starts in ~20 ms.

It listens on 127.0.0.1:PORT (accepting and closing every connection) and stops when a
line `stop` arrives on stdin, like vanilla. Flags make it misbehave:

    --listen-after S   listen only after S seconds
    --never-listen     never listen
    --exit-early CODE  write 50 numbered lines, then exit with CODE before listening
    --ignore-stop      answer `stop` with "ignoring stop" and keep running
    --ignore-sigterm   answer SIGTERM with "ignoring SIGTERM" and keep running

It writes what it sees to stdout (and one line to stderr) with raw `os.write`, which is
unbuffered and safe inside a signal handler.
"""

import argparse
import json
import os
import signal
import socket
import sys
import threading
import time
from pathlib import Path


def say(text: str, fd: int = 1) -> None:
    os.write(fd, f"{text}\n".encode())


def accept_forever(server: socket.socket) -> None:
    while True:
        connection, _ = server.accept()
        connection.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("port", type=int)
    parser.add_argument("--listen-after", type=float, default=0.0)
    parser.add_argument("--never-listen", action="store_true")
    parser.add_argument("--exit-early", type=int)
    parser.add_argument("--ignore-stop", action="store_true")
    parser.add_argument("--ignore-sigterm", action="store_true")
    args = parser.parse_args()

    say(f"pid={os.getpid()}")
    say(f"cwd={Path.cwd()}")
    say(f"env={json.dumps(dict(os.environ), sort_keys=True)}")
    say("hello from stderr", fd=2)
    if args.exit_early is not None:
        for number in range(1, 51):
            say(f"line {number}")
        return int(args.exit_early)
    if args.ignore_sigterm:
        signal.signal(signal.SIGTERM, lambda _signum, _frame: say("ignoring SIGTERM"))
    if not args.never_listen:
        time.sleep(args.listen_after)
        server = socket.create_server(("127.0.0.1", args.port))
        threading.Thread(target=accept_forever, args=(server,), daemon=True).start()
        say("listening")
    for line in sys.stdin:
        if line.strip() == "stop":
            if not args.ignore_stop:
                say("stopping")
                return 0
            say("ignoring stop")
    say("stdin closed")  # like vanilla, the end of the console does not stop the server
    while True:
        time.sleep(60)


if __name__ == "__main__":
    sys.exit(main())
