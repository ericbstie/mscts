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
requires a unique name, and Divergences name the Bot they came from.

| Bot method | What it does |
| --- | --- |
| `await bot.status()` | Sends the status handshake and request, and returns the parsed status JSON. |
| `await bot.ping(payload)` | Sends a ping with a Long payload and checks that the pong echoes it. |
| `await bot.join()` | Logs in offline and returns once the first chunk batch in play has finished. |
| `await bot.respawn()` | Respawns after death, as the respawn button does. It returns once the Bot has loaded the world again. |
| `await bot.expect(name, ..., timeout_s=..., where=...)` | Reads packets until one with any of the names given arrives, and returns it. |
| `await bot.command(text)` | Runs a command as this Bot's player, without the leading `/`. |
| `await bot.signed_command(text)` | Runs a command with a message argument (`/say`, `/me`, `/msg`, `/teammsg`) the way the vanilla client sends one. The client signs each message argument, and a Bot, which has no chat signing keys, signs none. |
| `await bot.chat(text)` | Says `text` in chat, the way the vanilla client says it without chat signing keys. |
| `await bot.chat_at_once(text, ...)` | Says each message as `chat` does, all sent together, in one write. The server can still tick between two of them. |
| `await bot.move(x, y, z, on_ground=True)` | Moves the Bot. If the vanilla client would send a position update, the Bot sends it too. |
| `await bot.look(yaw, pitch)` | Sends one rotation update. |
| `await bot.sprint(True)` / `await bot.sneak(True)` | Starts or stops sprinting or sneaking, as the vanilla client reports it. A sprinting Bot holds the forward key too, and a sneaking Bot can't start sprinting. |
| `await bot.jump()` | Presses the jump key for one tick, as the vanilla client reports it. It does not move the Bot. Send the jump's positions with `move`. |
| `await bot.tick()` | Sends what the vanilla client sends on a tick when the player does nothing. |
| `await bot.hold(slot)` | Selects a hotbar slot, from 0 to 8. After a respawn, slot 0 is selected again, as in the vanilla client. |
| `await bot.dig(x, y, z, face)` | Starts breaking a block from one face and swings the arm. In creative, this breaks the block. |
| `await bot.stop_digging(x, y, z, face)` | Finishes breaking a block and swings the arm. The Bot does not time the breaking: send this at the tick you want to test. |
| `await bot.cancel_digging(x, y, z)` | Stops breaking a block before it breaks. |
| `await bot.place(x, y, z, face, cursor=(0.5, 0.5, 0.5), off_hand=False)` | Uses the held item on a block face. It places a block, opens a door, or does what the item does to that block. |
| `await bot.use_item(off_hand=False)` / `await bot.release_item()` | Starts using the held item (eating, drawing a bow, raising a shield), or stops using it. |
| `await bot.attack(entity)` | Attacks an entity from `bot.entities`, as a left click does. On vanilla, an attack with a spear or another piercing weapon does nothing. |
| `await bot.interact(entity, at=(0.0, 0.0, 0.0), off_hand=False)` | Uses the held item on an entity, as a right click does. `at` is the point on the entity, relative to its position. When the Bot sneaks, the server sees the sneak key held. |
| `await bot.drop(all=False)` | Drops the held item (Q, or Ctrl+Q). With a container open it raises `ProtocolError`: close it first. |
| `await bot.swing()` | Swings the arm, as the vanilla client does when it attacks or digs. |
| `await bot.click(slot, button=0, mode="pickup")` | Clicks a slot in the open container or the inventory, as the vanilla client reports it. |
| `await bot.close_container()` | Closes the open container. |
| `bot.position` | Where the Bot's player is and which way it faces, after its last move. After `await bot.sync()`, it includes the server's last teleport. |
| `bot.entities` | The entities the server has told this Bot about: their type, position and data, as the vanilla client would track them. They change only as the Bot reads packets, so after a summon, call `await bot.sync()` before you look. A login, or a respawn into another dimension, clears them. |
| `bot.entities.find(type, near=None)` | Returns the entity of the given type, such as `"zombie"`. Entity ids differ from server to server, so find entities this way. When several have the type, give `near=(x, y, z)` to get the nearest one. It raises `LookupError` when it can't pick one. |
| `bot.chunks` | The chunks the server has sent this Bot and not told it to unload, as `(x, z)` pairs. Like `bot.entities`, they change only as the Bot reads packets, including the chunks `join` and `sync` read. A login, or a respawn into another dimension, clears them. The client drops a chunk more than 3 chunks beyond the server's view distance from the centre of its view, and drops them all during a reconfiguration. The Bot keeps them. |
| `bot.inventory` | The player's inventory and the open container. It changes only as the Bot reads packets, so after a give or a click, call `await bot.sync()` before you look. |
| `await bot.sync()` | Waits until a tick has passed on the server since it received what the Bot sent, so everything the server sent in response has arrived. Requires a Bot that has joined. |
| `await bot.drain()` | Reads every packet that has already arrived, without waiting for more. |
| `await bot.close()` | Closes the connection. mscts closes every Bot at the end anyway. |

The vanilla client sends the time with each chat message and signed
command, and a random number for its signature. A Bot sends the same
fixed values every time.

A Bot does not simulate physics, so a Group gives every position itself.
Each of these calls, from `move` to `swing`, is one tick of the vanilla
client. The Bot sends what changed, then the packet that ends
the client's tick. The Bot sends an unchanged position again every 20
calls, as the vanilla client does every 20 ticks. The Bot presses no
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

The server treats the player as moving until a client tick arrives with no move.
To stop the Bot, call `await bot.tick()` after its last move.

A face is one of `Face.DOWN`, `Face.UP`, `Face.NORTH`, `Face.SOUTH`,
`Face.WEST` and `Face.EAST`, imported from `mscts.bot`. The vanilla client
swings on every tick while it breaks a block. To break one in survival, a
Group starts digging, swings once per server tick, and finishes at the tick it
chooses:

<!-- not run: A fragment of a Group's function; it needs a Bot that has joined. -->
```python
await bot.dig(0, -61, 0, Face.UP)
for _ in range(ticks):
    await bot.sync()
    await bot.swing()
await bot.stop_digging(0, -61, 0, Face.UP)
```

`context.control` is an operator Bot that sets up the world before the part
of the Group that is compared.
`await context.control.run("setblock 0 -60 0 minecraft:stone")` runs a
command and waits until the server has answered it. What the server sends to
it is recorded but never compared. If the Candidate lacks the
command, the Candidate fails the Group, and its line names the command
(`Candidate failed: missing /tick`). If the Group had already failed and
the command was only there to undo its changes, the line names that first
failure instead.

`run` returns the chat messages the server sent Control while the command
ran, as `minecraft:system_chat` packets. Usually that is the command's
answer. Keep setup commands small and before the window. Your own Bots are
not operators, and none of them can be called `control`.

| Control method | What it does |
| --- | --- |
| `await context.control.run(command)` | Runs a command as Control's Bot, without the leading `/`, and returns once the server has answered it and a tick has passed. |
| `await context.control.leave()` | Closes Control's Bot. The next `run` joins a new one and waits as it did the first time, so a Group can set a Fixture up, let Control leave while its own Bot joins, and put the Fixture back afterwards. A server removes a closed Bot's player a moment later, so if the server must be empty, call `mscts.settle.until_no_player_online(context.endpoint)` before your Bot joins. |

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
below). Each Bot also waits the same way before the window opens. So,
provided the setup waited for its feedback (`context.control.run` does),
what your setup changed reaches every Bot before the window, not only
Control. A command a Bot sends without waiting for its feedback can still land inside
the window.
A Bot you make after the window ends is outside it. A window
never compares the few packets the server sends on a clock rather than
because of anything a Group did (keep-alives, the time of day and vanilla's
player latency updates). Separate Groups compare the keep-alives and the
time of day.

Each Bot's wait covers only what that Bot sent. When one Bot's action
causes something another Bot receives, and the window must hold it, wait
inside the block for the action's feedback (its chat message or block
update) before the block ends. Otherwise the other Bot's window can end
before it arrives.

To test a kick, take the server's disconnect inside the window with
`await bot.expect("minecraft:disconnect", timeout_s=...)`. That Bot then
skips the wait. A disconnect the Group did not take fails the Group if a
later wait or the Bot's next `expect` takes it. Otherwise, mscts takes
it when the Group ends, before it closes the Bots, but only if it has
arrived by then. One still on its way is missed. A Bot you closed yourself is not
checked. So take every disconnect your Group causes.

| Window option | What it does |
| --- | --- |
| `context.observe("minecraft:block_update", ...)` | Compares only the packets named. |
| `context.observe(play=False)` | Compares no play packets, only the login, configuration and status packets. Use it when the play packets vary and the Group tests something else, as `status/with-player` does. It takes no names and no `until`. |
| `context.observe(until="minecraft:chunk_batch_finished")` | Ends the window when the first packet with that name arrives at any of your Bots (not Control's) after the window opened, or at the Bot you name with `bot=`, and waits for nothing: no barrier. The window holds that packet and what arrived before it, and nothing the server sends after it. Keep the block open until the packet has arrived (a Bot's `join` does this for a join's packets). If none has arrived when the block ends, the Group fails and says which. With more than one Bot, name the Bot: when the window ends for the others then depends on timing. |
| `context.observe(until=("minecraft:player_chat", "minecraft:disguised_chat"))` | The same, but the window ends when the first packet with any of those names arrives. |

A packet name must be one the server sends in play, with its namespace
(`minecraft:block_update`). Keep-alives, the time of day and the
statistics a Bot asks for while it waits (`minecraft:award_stats`) are
never compared, so they can't be named. Any other name stops the Group with an
error.

Give `until` or `bot.expect` several names when a server could send what you wait for
in another packet. Vanilla answers a chat message with `minecraft:player_chat`, but
another server might answer with `minecraft:disguised_chat`. If the Group waits for
only one, it fails on that server and plays none of its later cases: `bot.expect` times
out, and `until` fails at once with "no ... arrived" when the block ends before the
packet came. If it waits for either, it goes on, and the Report shows the other packet
as a difference, if the window compares it. A window narrowed with names doesn't compare
other packets, so put every packet you wait for in the names too: `observe` refuses an
`until` with several names that its names leave out, and `bot.expect` can't see the
window, so a packet outside it shows no difference.

Use `until` when what the server keeps sending after the part you compare
would differ between two runs, such as the later chunk batches after a join
and the mobs that wander into view. Put the Bot's join inside the window:

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

- `requires` lists Groups that must `match` first. If one does not, mscts
  does not play this Group on the Candidate. If the Candidate failed the
  Group it requires, mscts still plays this one on vanilla, and the
  Candidate fails it and each of its test cases. If it was an `error`,
  this one is an `error` too. `mscts run` adds the Groups it requires and
  plays them first.
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
  hears of it. The same entities then compare equal on both servers, and a
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
clock, randomness, or the order of unrelated events. For this reason,
`status/ping` sends a fixed payload where the vanilla client sends its clock.

Mobs do not spawn on their own: every server starts with the
`spawn_mobs` game rule off. A Group that tests natural spawning turns it
on with `await context.control.run("gamerule spawn_mobs true")`, and off
again when it is done.

Vanilla also sends some packets on a clock that a window still compares,
because the same packets carry real changes too. It sends the position of
each entity a Bot can see every 3 seconds, even if it has not moved. If a window can catch one of these,
name the packets the Group is about.

Then prove it with a Self-check: run the Group with vanilla on both sides.
It must `match` in 20 runs out of 20 before it counts. The `selfcheck` tier
does this for every registered Group, 3 runs each. For 20 runs of your own,
run `MSCTS_SELFCHECK_REPEAT=20 uv run pytest -m selfcheck -k '<mechanic>/'`.
If it does not match, find the field that varies. Add a Mask only if that
field has no gameplay meaning. Otherwise the Group must control that
value itself.

## Group kinds

A Group is `exact` unless it says otherwise, and mscts compares it packet by
packet. A `tick-exact` Group freezes the world and advances it one tick at a
time, so that what happens on each tick is compared, whatever the servers'
speed:

```python
from mscts.group import GroupContext, GroupKind, group


@group("redstone/repeater-delay", kind=GroupKind.TICK_EXACT)
async def repeater_delay(context: GroupContext) -> None:
    observer = await context.bot("observer")
    await observer.join()
    await context.control.run("tp observer 0.5 -60 14.5")
    await context.freeze()
    await context.control.run("gamerule random_tick_speed 0")
    await context.control.run("setblock 2 -60 4 minecraft:repeater[facing=west,delay=2]")
    async with context.observe("minecraft:block_update", "minecraft:section_blocks_update"):
        await context.control.run("setblock 1 -60 4 minecraft:redstone_block")
        await context.step(8)
    await context.control.run("fill 1 -60 4 2 -60 4 minecraft:air")
    await context.control.run("gamerule random_tick_speed 3")
```

`await context.freeze()` freezes the world with `/tick freeze`. mscts
unfreezes it when the Group ends, even if the Group failed. If the server
does not answer the unfreeze, the Group fails and the server stays frozen.
mscts then plays no later Group on either server. If vanilla stays frozen,
each later Group is an error. If the Candidate stays frozen, each
later Group fails.
`await context.step(n)` advances the world `n` ticks, one `/tick step 1` at
a time, and returns once the server has finished them. Inside a window,
packets are compared tick by tick: the same packet arriving one tick later
on the Candidate is a difference. With `--verbose`, the Report shows the
tick each server sent it on. Name the packets your Group tests in its
window, and leave out light updates (`minecraft:light_update`): vanilla
computes light separately from the tick, so a light update can arrive on
a later tick than the change that caused it. A stepped tick also runs
random ticks, and each server picks its own blocks to tick, so turn them
off while the Group steps (`gamerule random_tick_speed 0`) and back on
(`3`) when it ends. A Candidate without `/tick` fails the Group, and its
line names the command.

`statistical` Groups are planned. They will run many times and compare
distributions, for random mechanics such as mob spawning.
