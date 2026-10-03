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
| `await bot.move(x, y, z, on_ground=True)` | Moves the Bot, and sends the position update the vanilla client would send, if any. |
| `await bot.look(yaw, pitch)` | Sends one rotation update. |
| `await bot.sprint(True)` / `await bot.sneak(True)` | Starts or stops sprinting or sneaking, as the vanilla client reports it. A sprinting Bot holds the forward key too, and a sneaking Bot can't start sprinting. |
| `await bot.jump()` | Presses the jump key for one tick, as the vanilla client reports it. It does not move the Bot. Send the jump's positions with `move`. |
| `await bot.tick()` | Sends what the vanilla client sends on a tick when the player does nothing. |
| `bot.position` | Where the Bot's player is and which way it faces, after its last move. After `await bot.sync()`, it includes the server's last teleport. |
| `await bot.sync()` | Waits until a tick has passed on the server since it received what the Bot sent before, so everything it sent because of that has arrived. Needs a Bot that has joined. |
| `await bot.drain()` | Reads every packet that has already arrived, without waiting for more. |
| `await bot.close()` | Closes the connection. mscts closes every Bot at the end anyway. |

A Bot does not simulate physics, so a Group gives every position itself.
Each call to `move`, `look`, `sprint`, `sneak`, `jump` or `tick` is one tick
of the vanilla client. The Bot sends what changed, then the packet that ends
the client's tick. A position that has not changed is sent again every 20
calls, as the vanilla client sends it every 20 ticks. The Bot presses no
direction keys, except forward while it sprints. No call waits for the
server. To move once per server tick, `await bot.sync()` between calls:

<!-- not run: A fragment of a Group's function; it needs a Bot that has joined. -->
```python
for step in range(1, 26):
    await bot.move(0.5 + 0.2 * step, -60.0, 0.5)
    await bot.sync()
```

When the server refuses a move, it sends the Bot back, and `bot.position`
then says where it put the Bot.

The server takes the player to be moving until a client tick without a move.
To stop the Bot, call `await bot.tick()` after its last move.

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

| Control method | What it does |
| --- | --- |
| `await context.control.run(command)` | Runs a command as Control's Bot, without the leading `/`, and returns once the server has answered it and a tick has passed. |
| `await context.control.leave()` | Closes Control's Bot. The next `run` joins a new one and waits as it did the first time, so a Group can set a Fixture up, let Control leave while its own Bot joins, and put the Fixture back afterwards. A server removes a closed Bot's player a moment later: call `mscts.settle.until_no_player_online(context.endpoint)` before your Bot joins if the server has to be empty. |

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
ends, each Bot waits until a tick has passed on the server since it
received everything the Bot sent. Its window ends there, whatever the other
Bots are still waiting for (a window with `until` waits for nothing: see
below). Each Bot also waits the same way before the window opens, so what
your setup changed reaches every Bot before the window, not only Control,
provided the setup waited for its feedback (`context.control.run` does). A
command a Bot sends without waiting for its feedback can still land inside
the window.
A Bot you make after the window ends is outside it. A few
packets the server sends on a clock rather than because of anything a Group
did (keep-alives, the time of day and vanilla's player latency updates)
are never compared inside a window.
Groups of their own compare the keep-alives and the time of day.

Each Bot's wait covers only what that Bot sent. When one Bot's action
causes something another Bot receives, and the window must hold it, wait
inside the block for the action's feedback (its chat message or block
update) before the block ends. Otherwise the other Bot's window can end
before it arrives.

To test a kick, take the server's disconnect inside the window with
`await bot.expect("minecraft:disconnect", timeout_s=...)`. That Bot then
skips the wait. A disconnect the Group did not take fails the Group if a
later wait or the Bot's next `expect` takes it. Otherwise, the Group's
end takes it before closing the Bots, but only if it has arrived by
then; one still on its way is missed. A Bot you closed yourself is not
checked. So take every disconnect your Group causes.

| Window option | What it does |
| --- | --- |
| `context.observe("minecraft:block_update", ...)` | Compares only the packets named. |
| `context.observe(until="minecraft:chunk_batch_finished")` | Ends the window when the first packet with that name arrives at any of your Bots (not Control's) after the window opened, or at the Bot you name with `bot=`, and waits for nothing: no barrier. The window holds that packet and what arrived before it, and nothing the server sends after it. Keep the block going until the packet has arrived (a Bot's `join` does for a join's packets): if none had when the block ended, the Group fails and says which. With more than one Bot, name the Bot: when the window ends for the others then depends on timing. |

A packet name must be one the server sends in play, with its namespace
(`minecraft:block_update`). Keep-alives, the time of day and the
statistics a Bot asks for while it waits (`minecraft:award_stats`) are
never compared, so they can't be named. Any other name stops the Group with an
error.

Use `until` when what the server keeps sending after the part you compare
would differ between two runs: after a join, later chunk batches and the
mobs that wander into view. Put the Bot's join inside the window:

<!-- not run: A fragment of a Group's function; it needs a context and a Bot. -->
```python
async with context.observe(until="minecraft:chunk_batch_finished"):
    await bot.join()
```

A joining player hears every mob within 16 blocks of where it spawns,
even before the server has sent it any chunks. Mob spawning is already
off, so only the mobs your Group spawns are there.

A Group with no window compares everything its Bots receive. With one,
what a Bot receives before it is in the world (the status, logging in and
configuration) is still compared whole.

Change blocks only in chunks a Bot has had since it joined. Vanilla sends a
player no `block_update` for a chunk it has not yet sent them: the change
arrives in the chunk data instead. Pumpkin sends the update anyway, so a
block changed in a chunk the Bot does not have yet would differ between the
two servers for a reason that has nothing to do with the block. `bot.join()`
returns once the first chunk batch has finished, and that batch holds
chunk (0, 0) on vanilla and on Pumpkin: the blocks with x and z from 0 to
15. Keep a Group's blocks there.

## Timing a span

`async with context.span("name"):` records a start Mark before the block and
an end Mark after it. The Report shows the time between them as a
Measurement called `name`. If the block raises, mscts records no end Mark and
no Measurement.

Name spans `<mechanic>.<what>`, for example `status.rtt`.

## Options

`@group` takes options after the id. This example is illustrative.
`door/open` is not registered yet.

<!-- not run: Decorator fragment; it needs imports and an async Group function. -->
```python
@group(
    "door/open",
    requires=("status/basic",),
    masks=(Mask("minecraft:sound", "pitch", reason="a door's sound has a random pitch"),),
    spec=lambda spec: replace(spec, view_distance=4),
)
```

- `requires` lists Groups that must `match` first. If one does not, this
  Group is `blocked` and mscts does not play it.
- `masks` excludes fields that change between two runs of vanilla. Each
  `Mask` names a packet, a field path (or `*` for the whole packet) and a
  reason. The reason must show the field has no gameplay meaning. Reviews
  reject a Mask that hides something a player could see. A Mask hides
  only the value: a field one server leaves out is still a difference.
  In a path, `[*]` stands for every element of a list, as in
  `players.sample[*].id`. Fields vanilla
  picks at random every time, such as a login's session id, are already
  left out for every Group, so list only what your Group adds. Entity ids
  and the random UUIDs of mobs need no Mask. mscts names each entity by its
  type and where it spawned, or numbers it in the order each Bot first
  hears of it, so the same entities compare equal on both servers, and a
  packet about a different entity still shows up as a difference. Two
  entities of the same type spawned at the same position are told apart
  only by the order the client heard of them, so spawn them apart. If an
  entity spawns at a random position,
  such as an item a block drops, a Mask on that `add_entity` field hides
  that part of its name too.
- `spec` changes the ServerSpec for this Group. Groups with different
  specs get their own server Instances.

## Make it deterministic

Both runs must send the same bytes, so a Group must not depend on the
clock, randomness, or the order of unrelated events. `status/ping` sends a
fixed payload for this reason, where the vanilla client sends its clock.

Mobs do not spawn on their own: every server starts with the
`spawn_mobs` game rule off. A Group that tests natural spawning turns it
on with `await context.control.run("gamerule spawn_mobs true")`, and off
again when it is done.

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
