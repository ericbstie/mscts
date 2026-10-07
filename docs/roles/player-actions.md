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

- #300: Control is a player too. It joins at a random place, saved per Instance, and a Group's blocks can make it crawl or choke in another Bot's window. Move every player a Group's blocks can reach, not only the one that acts.
