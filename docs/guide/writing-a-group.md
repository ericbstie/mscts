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
| `await bot.command(text)` | Runs a command as this Bot's player, without the leading `/`. |
| `await bot.sync()` | Waits until the server has answered a request sent after everything else, so everything it sent because of what came before has arrived. Needs a Bot that has joined. |
| `await bot.drain()` | Reads every packet that has already arrived, without waiting for more. |
| `await bot.close()` | Closes the connection. mscts closes every Bot at the end anyway. |

`context.control` is an operator Bot that sets up the world before the part
of the Group that is compared.
`await context.control.run("setblock 0 -60 0 minecraft:stone")` runs a
command and waits until the server has answered it. What the server sends to
it is recorded but never compared. If the Candidate does not have the
command, the Group is reported as blocked, naming the command.

`run` returns the chat messages the server sent Control while the command
ran, as `minecraft:system_chat` packets. Usually that is the command's
answer. Keep setup commands before the window, and small. Your own Bots are
not operators, and none of them can be called `control`.

While it runs, each Bot sends and answers what the vanilla client sends and
answers without asking the player: its brand and client settings after
logging in, keep-alives, the join teleport, chunk batch acknowledgements,
the configuration steps, and a note that it has loaded the world once the
first chunk batch has arrived. Your script does not need to handle them.

Every Bot operation times out after 10 seconds. A timeout on the Candidate
becomes a `failed` Divergence. A timeout on vanilla makes the Verdict
`error`, because the Group itself is broken.

## Choosing what is compared

Only what a Bot receives inside `async with context.observe():` is
compared. Set the world up before it and clean up after it. When the block
ends, each Bot first waits until the server has answered a request sent
after everything else, then takes what has arrived. A few packets the
server sends on a clock rather than because of anything a Group did
(keep-alives and the time of day) are never compared inside a window.
Groups of their own compare them. To compare only some packets, name them:
`context.observe("minecraft:block_update")`.

A Group with no window compares everything its Bots receive. With one,
what a Bot receives before it is in the world (the status, logging in and
configuration) is still compared whole.

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
  reject a Mask that hides something a player could see. Fields vanilla
  picks at random every time, such as a login's session id, are already
  left out for every Group, so list only what your Group adds.
- `spec` changes the ServerSpec for this Group. Groups with different
  specs get their own server Instances.

## Make it deterministic

Both runs must send the same bytes, so a Group must not depend on the
clock, randomness, or the order of unrelated events. `status/ping` sends a
fixed payload for this reason, where the vanilla client sends its clock.

Vanilla also sends some packets on a clock that a window still compares,
because the same packets carry real changes too: every player's latency,
about every 30 seconds, and where each entity a Bot can see is, every 3
seconds, even if it has not moved. If a window can catch one of these,
name the packets the Group is about.

Then prove it with a Self-check: run the Group with vanilla on both sides.
It must `match` in 20 runs out of 20 before it counts. The `selfcheck` tier
does this for every registered Group, 3 runs each. For 20 runs of your own,
run `MSCTS_SELFCHECK_REPEAT=20 uv run pytest -m selfcheck -k '<mechanic>/'`.
If it does not match, find the field that varies. Add a Mask only if that
field has no gameplay meaning. Otherwise the Group needs to control that
value itself.

## Group kinds

Every Group today is `exact`, compared packet by packet. Two more kinds
are planned. `tick-exact` Groups will freeze the world and step it tick by
tick, for mechanics such as redstone. `statistical` Groups will run many
times and compare distributions, for random mechanics such as mob spawning.
