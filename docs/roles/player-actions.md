# Player actions specialist

**Lane:** the Bot behaving like a real client: digging, placing,
attacking, clicking inventory slots. **Model:** sonnet, opus for #60 and
#71.

**Issues** (`lane:player-actions`): #26 dig and place, #27 attack and
interact, #28 inventory clicks (after the helper's #25 movement), then #36
breaking and placing, #53 melee, #54 damage and armor, #55 shields and
bows, #56 environment damage, #59 game modes and respawn, #60 movement
checks, #61 inventory, #69 ender pearls, #70 nether portals, #71 protocol
limits.

New Bot actions go in `bot.py`, which the timing specialist owns: the
lead routes each change and both review it.

## What this lane knows

- The Bot sends what the vanilla client sends (#16): brand, client
  information and `player_loaded`.
- The game rule `player_movement_check` decides whether vanilla sends
  repeated `player_position` corrections (#30's measurement).
- A Group gives only item stacks whose components are outside
  `MALFORMED` in `tests/adapters/pumpkin/test_pumpkin_item_stacks.py`,
  unless the component is what it tests: on Pumpkin a Bot fails on such a
  stack before the Group compares anything (#312).

## Log

Newest first: one line per lesson, with the issue it came from.

- #61: after `bot.close_container()`, pass `bot.sync()` before Control's next command: they travel on two connections, and vanilla can run them in either order, which leaves the Bot's InventoryTracker stale (#62 hit the same with a crafting table and `/clear`).
- #61: a `/give` over one stack makes two item entities in one tick, and the end-of-tick resend of their data follows entity-id hash order: that window leaves `set_entity_data` out. A `context.step` costs about 0.3 s, so four 41-tick windows came to 106 s, over the Self-check's 90 s.
- #61: a Candidate that never opens a container makes the Bot's next click land in its own inventory menu. The Group checks for `open_screen` first and fails naming the container.
- #59: a respawning player reaches other Bots in view a tick or two late, and the delay differed between Instances. With view distance 2, keep Bots 6 chunks apart.
- #59: one drop entity per death window: one tick's new entities are resent in raw-id order, which differs per Instance. Drop motion and yaw are random (`ItemEntity` and `ExperienceOrb` constructors), so they take a Mask. An orb is an `add_entity` of type 50, not a packet of its own.
- #59: `/give` leaves an item entity behind in a frozen world. A cleanup that kills only the Group's drops tags what is there before the kit is given, or that item survives (9 of 20 respawn plays failed).
- #59: `immediate_respawn` sends game event 11, but the server still waits for the client's respawn request: the Bot always asks after a death window, or the next play's join hangs. `/spawnpoint` cannot be cleared, so give it to a Bot of its own.
- #54: `/damage <bot> <n> <type> by <entity>` with a `minecraft:marker` as the source: no client is told of it and it leaves no corpse, yet it gives the hit a direction (`hurt_animation`, `set_entity_motion`).
- #54: with `keep_inventory` true, armor survives a `kill`; clear the Bot's stacks and effects in the undo, because the server saves them with the player and the next Group that uses the name inherits them.
- #54: damage type tags are in the 26.3 jar (`data/minecraft/tags/damage_type/*.json`): `bypasses_armor` is generic, fall, magic, wither, out_of_world and starve; `bypasses_resistance` is out_of_world; `bypasses_effects` is starve. With `show_death_messages` off there is no `system_chat` and `player_combat_kill`'s message is empty.
- #53, #56: a player ticks in real time in a frozen world: its attack charge, hurt cooldown, dig progress and environment damage follow the wall clock. Step only for what a packet drives; end a window for time-driven damage on the `set_health` or death it waits for, and fail the Group (an `error` on the Reference) when a window opens later than the next hit.
- #56: a player is immune for 10 ticks after a hit; a second source inside that gap hurts only by the excess, with no `damage_event`. Make the Bot fresh (`kill`, then `respawn`) between two sources.
- #53, #56: a server saves a player's place, health, food and saturation across plays. Put every Bot back at the spawn before the block restores, and heal and feed it before its first hit.
- #56: never set a rule the Fixture world already has off (`spawn_mobs`, ADR-0013), and never kill entities the Group did not make.
- #56: a packet that carries an entity id must be decoded before a Self-check can pass: fresh-Instance probes hide id drift, which only the 20-play Self-check on one pair of Instances shows.
- #53: `data get entity` answers name the entity by UUID, which differs per Instance. Copy the values to command storage and read the storage. A `Silent` mob makes no hurt sound, so no Mask on its random voice pitch is needed.
- #53: waiting for tracking must not step the world: one extra step shifts every later tick-exact packet.
- #36: vanilla accepted an early survival dig finish only from a player in for a while (#347). Pin such a rule from javap before a Group rests on it.
- #278: `Bot.move_unchecked` sends a move no client sends and ends its tick, because vanilla kicks a second position before `client_tick_end`. Vanilla kicks a NaN coordinate or a non-finite rotation before any other check; an infinite coordinate is clamped and then sent back as too long a move.
- #300: Control is a player too. It joins at a random place, saved per Instance, and a Group's blocks can make it crawl or choke in another Bot's window. Move every player a Group's blocks can reach, not only the one that acts.
