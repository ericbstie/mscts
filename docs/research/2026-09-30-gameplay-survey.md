# Gameplay survey — 2026-09-30

Evidence behind the test proposals (GitHub issues labelled `test`) and the
infrastructure they need (labelled `enabler`). Two kinds of fact:

- **verified**: observed first-hand in this container, against vanilla 26.3
  (the Reference) and Pumpkin nightly sha256 `b8382a8a…` (installed with
  `mscts adapter install pumpkin --from`; the Registry still pins
  `48cba7ee…`, so this build has no entry);
- **documented**: what another server's own documentation says it changes
  from vanilla. It says where servers are known to differ; it never decides
  what is correct.

## What a Group can use today

- A Bot can do `status`, `ping`, `join` and `expect`. There is no
  `Bot.command`, no `send` of play packets, and `ScenarioContext.control`
  raises `NotImplementedError` (M5).
- Play has schemas only for what the join needs (`login`,
  `player_position`, keep-alive, chunk batches, `update_tags`,
  `start_configuration`, `disconnect`). Every other play packet is compared
  by its raw payload, so an entity id inside it cannot be masked and a
  difference is reported for the whole payload.
- Only the `exact` kind runs. `run` raises `NotImplementedError` for
  `tick-exact` and `statistical` (M6a, M6b).
- A Transcript records only the packets a Bot takes. Nothing yet decides
  which play packets a Group compares. Vanilla keeps sending `set_time`
  while the world is frozen (the probe below saw it in every 1.5 s
  window), so how many `set_time` packets a Bot takes depends on wall-clock
  time, and differs between two vanilla runs (see the PLAN open question on
  ambient packets).

## Vanilla 26.3 facts for Fixtures — verified

From the data generator's `reports/commands.json` (run from the Reference
jar, sha1 `33680f5f…`):

- Game rules are snake_case ids, with and without the `minecraft:`
  prefix: `advance_time` (was `doDaylightCycle`), `advance_weather`,
  `random_tick_speed`, `spawn_mobs`, `spawn_monsters`, `mob_griefing`,
  `respawn_radius` (the join spawn spread), `max_entity_cramming`,
  `natural_health_regeneration`, `keep_inventory`, `immediate_respawn`,
  `fall_damage`, `fire_damage`, `drowning_damage`, `freeze_damage`, `pvp`,
  `send_command_feedback`, `water_source_conversion`,
  `lava_source_conversion`, `tnt_explodes`, `players_sleeping_percentage`,
  `projectiles_can_break_blocks`, `spawner_blocks_work` and more (118
  entries in all). Old camelCase names are not in the tree.
- Commands include `tick` (`freeze`, `unfreeze`, `step`, `sprint`,
  `query`, `rate`), `setblock`, `fill`, `clone`, `summon`, `damage`,
  `effect`, `attribute`, `data`, `execute`, `forceload`, `item`, `kill`,
  `setworldspawn`, `spawnpoint`, `time`, `weather`, `worldborder`,
  `random`, `stopwatch`, `swing`.

## Light data encoding — verified (javap)

`ClientboundLightUpdatePacketData.STREAM_CODEC` writes its four masks
with `ByteBufCodecs.BIT_SET`, which is `ByteBufCodecs$15`:
`FriendlyByteBuf.writeByteArray(bitSet.toByteArray())`. So each mask is a
VarInt length and then the BitSet's **little-endian bytes**, with trailing
zero bytes dropped. It is not the wiki's "Prefixed Array of Long" (oldid
3790659). Then come the sky and block light arrays, each a list of
2048-byte arrays. The first chunk (0, 0) of the default flat world decodes
exactly on both servers with this layout.

## Vanilla against Pumpkin, live — verified

Default ServerSpec (flat, seed 0, peaceful, view distance 2), one Bot. The
command probe ran as the operator `mscts_op`, with 1.5 s windows after each
command (`probe.py` in the session scratchpad; not committed). The windows
are wall-clock, so a packet can fall into the next window; only differences
that also hold across windows are listed.

**Join (configuration and play up to the first chunk batch):**

- Vanilla's first batch arrives after the whole player-state sequence
  (`login`, difficulty, abilities, `update_recipes`, `commands`,
  `player_position`, `server_data`, player info, border, `set_time`, spawn,
  `ticking_state`, `set_chunk_cache_center`, `post_effects`, inventory,
  `update_advancements`, health, experience) and holds 9 chunks
  (`PlayerChunkSender.START_CHUNKS_PER_TICK`). Pumpkin sends `login`, tick
  state, `entity_event`, difficulty, `commands`, `set_chunk_cache_center`,
  then a first batch of **1** chunk. `player_position` and the rest follow.
- The `commands` packet for a non-operator Bot is **265 bytes** on vanilla
  and **19,578 bytes** on Pumpkin.
- The first `level_chunk_with_light` is 7,259 bytes on vanilla and 52,368 on
  Pumpkin. Its heightmaps and section data (blocks, biomes) are equal. Its
  light differs: vanilla sends sky light for sections 1–2 only (sky mask
  `0b110`), marks section 0 as empty sky and sections 0–2 as empty block
  light, and sends nothing for the sections above. Pumpkin sends sky light
  for all 24 in-world sections (all 15 above the ground), marks sections 0
  and 25 as empty sky and every section as empty block light. Whether the
  vanilla client ends up with the same light in both cases is open: it
  depends on how the client fills sections that neither mask names.
- Known from earlier sessions: `registry_data` with full NBT (≈172 KB for
  the first entry), `login` `is_flat` false and `sea_level` 63, a
  different offline UUID scheme (`sha256(name)[:16]`), no spawn radius.

**After commands (vanilla | Pumpkin):**

| Command | Vanilla | Pumpkin |
| --- | --- | --- |
| `tick freeze`, `tick step 5` | `ticking_state`, `ticking_step` | the same packets: Pumpkin has `/tick` |
| `setblock`, `fill` | feedback `system_chat` **before** `block_update` / `section_blocks_update` | the block packet **before** the feedback |
| `summon pig` | wrapped in two `bundle_delimiter`s, 2 × `set_entity_data` | no bundle, `rotate_head`, 1 × `set_entity_data` |
| `damage mscts_op 2` | `damage_event`, 3 × `set_health`, no `hurt_animation` | `hurt_animation`, `damage_event`, `sound`, 7 × `set_health` |
| `effect give … speed` | `update_mob_effect`, `set_entity_data`, `update_attributes` | `update_attributes` first, no `set_entity_data` |
| `give … diamond_sword` | an item entity is added, a pickup `sound`, then `container_set_slot` | `container_set_slot` only |
| `gamemode creative` | 2 × `player_abilities`, `set_entity_data`, `update_attributes` | 1 × `player_abilities` |
| `weather rain` while frozen | nothing until `tick unfreeze`, then the rain-level `game_event`s | `game_event` at once, while frozen |

## Other servers' documented differences — documented

Paper (`config/paper-world-defaults.yml`, `config/paper-global.yml`;
[world](https://docs.papermc.io/paper/reference/world-configuration),
[global](https://docs.papermc.io/paper/reference/global-configuration),
[bug fixes](https://docs.papermc.io/paper/misc/paper-bug-fixes/)), by
default unless it says "option":

- Exploits off by default: headless pistons and bedrock/end portal frame
  breaking (`allow-headless-pistons`, `allow-permanent-block-break-exploits`),
  TNT, carpet and rail duplication (`allow-piston-duplication`), gravity
  block duplication through end portals
  (`allow-unsafe-end-portal-teleportation`), tripwire hook duplication.
- Collisions: `max-entity-collisions` 8; options for cramming damage and
  climbing entities.
- Spawning: `per-player-mob-spawns` true; options for despawn range shape,
  per-category despawn ranges, monster spawn light level, iron golems
  spawning in air.
- Redstone: option `redstone-implementation` (vanilla, Eigencraft,
  Alternate Current), which changes dust update order.
- Items: options `only-merge-items-horizontally`,
  `fix-items-merging-through-walls`, arrow despawn rates, item despawn
  rates.
- Other options: `disable-unloaded-chunk-enderpearl-exploit`,
  `legacy-ender-pearl-behavior`, `disable-relative-projectile-velocity`,
  `disable-player-crits`, `disable-sprint-interruption-on-attack`,
  `skip-vanilla-damage-tick-when-shield-blocked`, `void-damage-amount`,
  `water-over-lava-flow-speed`, `portal-search-radius`,
  `portal-create-radius`, `prevent-moving-into-unloaded-chunks`,
  `update-pathfinding-on-block-update`.
- Chunk sending is rate-limited per player
  (`chunk-loading-basic.player-max-chunk-send-rate` 75); a packet limiter
  kicks above 500 packets per 7 s.

Spigot (`spigot.yml`, [configuration](https://www.spigotmc.org/wiki/spigot-configuration/)):

- Entity activation range (animals 32, monsters 32, misc 16 blocks):
  entities farther from a player tick less.
- Entity tracking range (players, animals, monsters 48; misc 32 blocks):
  entities farther away are not sent.
- Item merge radius 2.5 and experience orb merge radius 3.0 blocks.
- Mob spawn range 6 chunks; growth modifiers, hunger exhaustion values,
  hopper timings, arrow and item despawn rates are configurable, at vanilla
  values by default.

Pumpkin ([README](https://github.com/Pumpkin-MC/Pumpkin) and its
first-run `pumpkin.toml`):

- Marked implemented: lighting, entity spawning, inventory, experience,
  hunger, eating, entity effects, chat.
- Marked not implemented or in progress: chunk generation, redstone,
  liquid physics, mobs and bosses, entity AI, combat, commands.
- `[pvp]` switches `hurt_animation`, `protect_creative`, `knockback` and
  `swing`; `[world] lighting` (`default`); `[chat] format
  "<{DISPLAYNAME}> {MESSAGE}"`; `[chat.anti_spam]` threshold 200, cost 20,
  decay 1 per tick, `ops_bypass`. The Adapter already sets the options
  that have a vanilla counterpart (`VANILLA_EQUIVALENTS`).

Folia ([region logic](https://docs.papermc.io/folia/reference/region-logic)):
regions tick independently and in parallel, so anything that depends on a
single global tick order (redstone across regions, entities moving
between regions) can differ.
