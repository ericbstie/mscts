"""The one generic runner: launch any LaunchPlan, wait until it is ready, always stop it.

Server-agnostic by design (ADR-0004): it never parses logs, and readiness is decided by
an injected probe (in a Run, the status ping).
"""

import socket

LOOPBACK = "127.0.0.1"


def free_port() -> int:
    """A TCP port on 127.0.0.1 that nothing had bound a moment ago.

    The kernel picks it from its ephemeral range, so it is never a well-known port such as
    25565, and consecutive calls rarely repeat.

    It is racy by nature (time of check to time of use): the port is released before this
    returns, so another process, such as another worker's server, can take it before the
    Instance binds it. The Instance then fails to bind and exits before it is ready, or,
    worse, the readiness probe reaches the other process. Keep the gap short: take the
    port right before `prepare` and launch at once.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as placeholder:
        placeholder.bind((LOOPBACK, 0))
        return int(placeholder.getsockname()[1])
