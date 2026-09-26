"""Status Scenarios: the server list ping, as the vanilla client performs it.

The vanilla client's `ServerStatusPinger` (26.3) sends the status handshake and a
`status_request`, and on the `status_response` a `ping_request`, whose `pong_response`
gives the latency it shows. These Scenarios do the same, with a fixed ping payload
instead of the client's clock, so every run sends the same bytes.

Neither has a Mask: nothing in a status exchange is an identifier without gameplay
meaning (ADR-0006), so a difference in it is a Divergence.
"""

from mscts.scenario import ScenarioContext, scenario

PING_PAYLOAD = 20_260_926
"""The Long `status/ping` sends. The vanilla client sends its clock; a Scenario must not."""


@scenario("status/basic")
async def basic(context: ScenarioContext) -> None:
    """Ask for the status once."""
    bot = await context.bot("status")
    await bot.status()


@scenario("status/ping", requires=("status/basic",))
async def ping(context: ScenarioContext) -> None:
    """Ask for the status, then ping; the `status.rtt` span covers the ping and its pong."""
    bot = await context.bot("status")
    await bot.status()
    async with context.span("status.rtt"):
        await bot.ping(PING_PAYLOAD)
