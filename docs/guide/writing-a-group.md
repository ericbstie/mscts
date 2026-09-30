# Writing a Group

A Group is an async Python function that drives one or more Bots against
a server. mscts runs it once against vanilla and once against the Candidate,
then compares what each Bot recorded.

A Group never states what the server should send. Vanilla's answer is the
expected value, so the script only has to do what a player's client would do.

## The shape of a Group

This is `status/ping`, one of the two Groups mscts ships:

```python
from mscts.group import GroupContext, group

PING_PAYLOAD = 20_260_926


@group("status/ping")
async def ping(context: GroupContext) -> None:
    """Ask for the status, then ping; the `status.rtt` span covers the ping and its pong."""
    bot = await context.bot("status")
    await bot.status()
    async with context.span("status.rtt"):
        await bot.ping(PING_PAYLOAD)
```

`@group` registers the function under an id. The part before the slash is
the mechanic, and the Report lists results under it. Put the module in
`src/mscts/groups/` and import it from `src/mscts/groups/__init__.py`.

## What a script can do

`context.bot(name)` connects a new Bot and returns it. Each Bot in a Group
needs a unique name, and Divergences name the Bot they came from.

| Bot method | What it does |
| --- | --- |
| `await bot.status()` | Sends the status handshake and request, and returns the parsed status JSON. |
| `await bot.ping(payload)` | Sends a ping with a Long payload and checks that the pong echoes it. |
| `await bot.join()` | Logs in offline and returns once the first chunk batch in play has finished. |
| `await bot.expect(name, timeout_s=..., where=...)` | Reads packets until one named `name` arrives, and returns it. |
| `await bot.close()` | Closes the connection. mscts closes every Bot at the end anyway. |

While it runs, each Bot answers the packets the vanilla client answers
without asking the player: keep-alives, the join teleport, chunk batch
acknowledgements, and the configuration steps. Your script does not need to
handle them.

Every Bot operation times out after 10 seconds. A timeout on the Candidate
becomes a `failed` Divergence. A timeout on vanilla makes the Verdict
`error`, because the Group itself is broken.

## Timing a span

`async with context.span("name"):` records a start Mark before the block and
an end Mark after it. The Report shows the time between them as a
Measurement called `name`. If the block raises, mscts records no end Mark and
no Measurement.

Name spans `<mechanic>.<what>`, for example `status.rtt`.

## Options

`@group` takes options after the id. This example is illustrative.
`join/basic` is not registered yet.

```python
@group(
    "join/basic",
    requires=("status/basic",),
    masks=(Mask("minecraft:login", "entity_id", reason="an entity id, assigned per session"),),
    spec=lambda spec: replace(spec, view_distance=4),
)
```

- `requires` lists Groups that must `match` first. If one does not, this
  Group is `blocked` and mscts does not play it.
- `masks` excludes fields that change between two runs of vanilla. Each
  `Mask` names a packet, a field path (or `*` for the whole packet) and a
  reason. The reason must show the field has no gameplay meaning. Reviews
  reject a Mask that hides something a player could see.
- `spec` changes the ServerSpec for this Group. Groups with different
  specs get their own server Instances.

## Make it deterministic

Both runs must send the same bytes, so a Group must not depend on the
clock, randomness, or the order of unrelated events. `status/ping` sends a
fixed payload for this reason, where the vanilla client sends its clock.

Then prove it with a Self-check: run the Group with vanilla on both sides.
It must `match` in 20 runs out of 20 before it counts. If it does not, find
the field that varies. Add a Mask only if that field has no gameplay meaning.
Otherwise the Group needs to control that value itself.

## Group kinds

Every Group today is `exact`, compared packet by packet. Two more kinds
are planned. `tick-exact` Groups will freeze the world and step it tick by
tick, for mechanics such as redstone. `statistical` Groups will run many
times and compare distributions, for random mechanics such as mob spawning.
