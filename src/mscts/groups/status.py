"""Status Groups: the server list ping, as the vanilla client performs it.

The vanilla client's `ServerStatusPinger` (26.3) sends the status handshake and a
`status_request`, and on the `status_response` a `ping_request`, whose `pong_response`
gives the latency it shows. These Groups do the same, with a fixed ping payload
instead of the client's clock, so every run sends the same bytes.

Neither has a Mask: nothing in a status exchange is an identifier without gameplay
meaning (ADR-0006), so a difference in it is a Divergence.
"""

from mscts.group import GroupContext, group

PING_PAYLOAD = 20_260_926
"""The Long `status/ping` sends. The vanilla client sends its clock; a Group must not."""


@group("status/basic")
async def basic(context: GroupContext) -> None:
    """Ask for the status once."""
    bot = await context.bot("status")
    await bot.status()


@group("status/ping")
async def ping(context: GroupContext) -> None:
    """Ask for the status, then ping; the `status.rtt` span covers the ping and its pong.

    It requires nothing: a Candidate whose status differs still gets its round trip timed.
    """
    bot = await context.bot("status")
    await bot.status()
    async with context.span("status.rtt"):
        await bot.ping(PING_PAYLOAD)
