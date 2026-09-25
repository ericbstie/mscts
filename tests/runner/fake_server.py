"""A stand-in server for the runner's unit tests. Standard library only; starts in ~20 ms.

It listens on 127.0.0.1:PORT (accepting and closing every connection) and stops when a
line `stop` arrives on stdin, like vanilla. Flags make it misbehave:

    --listen-after S   listen only after S seconds
    --never-listen     never listen
    --exit-early CODE  write 50 numbered lines, then exit with CODE before listening
    --ignore-stop      answer `stop` with "ignoring stop" and keep running
    --ignore-sigterm   answer SIGTERM with "ignoring SIGTERM" and keep running
    --child            fork a sleeping child into its process group, and never wait for it

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


def fork_sleeper() -> int:
    """Fork a child that sleeps for a minute; return its pid. Call before any thread."""
    child = os.fork()
    if child == 0:
        time.sleep(60)
        os._exit(0)
    return child


def listen(port: int, after: float) -> None:
    time.sleep(after)
    server = socket.create_server(("127.0.0.1", port))
    threading.Thread(target=accept_forever, args=(server,), daemon=True).start()
    say("listening")


def accept_forever(server: socket.socket) -> None:
    while True:
        connection, _ = server.accept()
        connection.close()


def console(*, ignore_stop: bool) -> None:
    """Read stdin until a `stop` it obeys, or until stdin closes; then return."""
    for line in sys.stdin:
        if line.strip() == "stop":
            if not ignore_stop:
                say("stopping")
                return
            say("ignoring stop")
    say("stdin closed")  # like vanilla, the end of the console does not stop the server
    while True:
        time.sleep(60)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("port", type=int)
    parser.add_argument("--listen-after", type=float, default=0.0)
    parser.add_argument("--never-listen", action="store_true")
    parser.add_argument("--exit-early", type=int)
    parser.add_argument("--ignore-stop", action="store_true")
    parser.add_argument("--ignore-sigterm", action="store_true")
    parser.add_argument("--child", action="store_true")
    args = parser.parse_args()

    say(f"pid={os.getpid()}")
    say(f"cwd={Path.cwd()}")
    say(f"env={json.dumps(dict(os.environ), sort_keys=True)}")
    say("hello from stderr", fd=2)
    if args.exit_early is not None:
        for number in range(1, 51):
            say(f"line {number}")
        return int(args.exit_early)
    if args.child:
        say(f"child={fork_sleeper()}")
    if args.ignore_sigterm:
        signal.signal(signal.SIGTERM, lambda _signum, _frame: say("ignoring SIGTERM"))
    if not args.never_listen:
        listen(args.port, after=args.listen_after)
    console(ignore_stop=args.ignore_stop)
    return 0


if __name__ == "__main__":
    sys.exit(main())
