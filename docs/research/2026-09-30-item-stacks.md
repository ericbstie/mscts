# Item stacks and data components — 2026-09-30

Facts behind the item stack codec (issue #19): the Slot layout, the data
component patch, the hashed slot and the wire shape of every data component
in the 26.3 registry. Everything marked **verified (javap)** was read from the
26.3 server jar (`META-INF/versions/26.3/server-26.3.jar` inside the bundler
`server.jar`, sha1 `33680f5f…`) with `scripts/research/layout.py`, which prints
the wire-relevant instructions of a method from `javap -v`:

```sh
mise exec -- uv run python scripts/research/layout.py server net.minecraft.core.component.DataComponentPatch '<METHOD-REGEX>'
```

The component rows were expanded from `DataComponents.<clinit>` through every
`STREAM_CODEC` it names, by hand-checking an abstract reading of the bytecode
against the classes themselves. The jar wins over the wiki wherever they
differ (see the last section).

## Notation

`VarInt`, `Bool`, `Int`, `Float`, `Double`, `String(n)` and `Id` (an
Identifier, `String(32767)`) are the codec's own types.

| Shape | Bytes |
|---|---|
| `unit` | nothing |
| `Text` | an NBT root tag of any type but END: a text component (`ComponentSerialization.STREAM_CODEC`, `fromCodecWithRegistries`) |
| `NBT` | the same bytes as `Text`, for a component with no network codec of its own |
| `Compound` | an NBT root tag that must be a compound (type 10): `ByteBufCodecs.COMPOUND_TAG` |
| `Reg(r)` | a VarInt id in registry `r`: `registry(r)` and `holderRegistry(r)` alike, no offset |
| `Holder(X…)` | VarInt n. 0: the inline fields `X…` follow. Otherwise registry id n - 1, nothing follows: `ByteBufCodecs.holder` |
| `Set(r)` | VarInt n. 0: a tag `Id` follows. Otherwise n - 1 VarInt ids: `ByteBufCodecs.holderSet` |
| `Opt(X)` | a Bool, then `X` when true |
| `Either(L, R)` | a Bool, then `L` when true, `R` when false |
| `List(X)`, `List≤n(X)` | VarInt count (over `n` is a `DecoderException`), then `X` that many times |
| `List4(X)` | exactly four `X`, no count: `fixedSizeList(4)` |
| `Map(K, V)` | VarInt size, then `K V` that many times |
| `Enum` | a plain VarInt: `idMapper`, no range check on read |
| `Sound` | `Holder(Id, Opt(Float))`: `SoundEvent.STREAM_CODEC` |
| `Template` | `Reg(item)`, VarInt count, `Patch` (below) |

## Slot

**verified (javap)** `ItemStack$1` (`ItemStack.OPTIONAL_STREAM_CODEC`), built
over `DataComponentPatch.STREAM_CODEC`:

| Field | Type | Notes |
|---|---|---|
| count | VarInt | `<= 0` decodes as the empty stack and **nothing follows**, negative counts included. The encoder writes `0` for empty |
| item | `Reg(item)` | `Item.STREAM_CODEC`, `holderRegistry(ITEM)` |
| patch | `Patch` | only when count > 0 |

`ItemStack.STREAM_CODEC` is the same but throws `DecoderException` ("Empty
ItemStack not allowed") on an empty stack. The untrusted variant
(`OPTIONAL_UNTRUSTED_STREAM_CODEC`, used for creative slots) wraps **each
component value** in a VarInt byte-length prefix (`DELIMITED_STREAM_CODEC`,
`registryFriendlyLengthPrefixed(MAX_INT)`). Nothing in the normal form has a
per-value length, so every component's layout has to be known to read past it.

## Patch

**verified (javap)** `DataComponentPatch$3`:

| Field | Type | Notes |
|---|---|---|
| added count | VarInt | no limit on read (the map's capacity is capped at 65536 only) |
| removed count | VarInt | |
| added | (`Reg(data_component_type)`, that component's value) × added count | map iteration order on encode, so the order is whatever the server had |
| removed | `Reg(data_component_type)` × removed count | |

Both counts 0 is an empty patch. The component type id is
`DataComponentType.STREAM_CODEC`, `registry(DATA_COMPONENT_TYPE)`.

## Template

**verified (javap)** `ItemStackTemplate.STREAM_CODEC` is a stack that cannot
be empty, used inside components and by particle item options
(`ItemParticleOption.streamCodec`): `Reg(item)`, VarInt count, `Patch`. It
is **not** the Slot layout: the count comes after the item, and there is no
"count 0 means empty".

## Hashed slot

**verified (javap)** `HashedStack.STREAM_CODEC`, the `slot` fields of the
serverbound click packets:

| Field | Type | Notes |
|---|---|---|
| present | Bool | `Opt`: the flag comes first, unlike Slot's count |
| item | `Reg(item)` | |
| count | VarInt | |
| added | `Map(Reg(data_component_type), Int)` | at most 256; the Int is a CRC32C of the value, not its encoding |
| removed | `List≤256(Reg(data_component_type))` | a `HashSet` on decode, so the order is lost there |

## Shared nested types

**verified (javap)** unless noted.

| Type | Bytes |
|---|---|
| `ConsumeEffect` | `Reg(consume_effect_type)` then by id: 0 `apply_effects` `List(MobEffectInstance)`, Float; 1 `remove_effects` `Set(mob_effect)`; 2 `clear_all_effects` `unit`; 3 `teleport_randomly` Float; 4 `play_sound` `Sound` |
| `MobEffectInstance` | `Reg(mob_effect)`, `Details` |
| `Details` | VarInt amplifier, VarInt duration, Bool ambient, Bool show_particles, Bool show_icon, `Opt(Details)` |
| `BlockPredicate` | `Opt(Set(block))`, `Opt(List(PropertyMatcher))`, `Opt(Compound)`, `DataComponentMatchers` |
| `PropertyMatcher` | `String` name, `Either(String exact, (Opt(String) min, Opt(String) max))` |
| `DataComponentMatchers` | `exact`: `List(TypedComponent)`, then `partial`: `List≤64(PartialPredicate)` |
| `TypedComponent` | `Reg(data_component_type)`, then **that component's value** (the table below recurses) |
| `PartialPredicate` | `Either(Reg(data_component_predicate_type), Reg(data_component_type))`, then an NBT tag in both cases (an any-value predicate is the empty compound `0a 00`) |
| `ItemAttributeModifiers.Entry` | `Reg(attribute)`, `Id`, Double amount, `Enum` operation, `Enum` slot group, `Display` |
| `Display` | `Enum` type: 0 default `unit`, 1 hidden `unit`, 2 override `Text` |
| `GameProfile` | UUID, `String(16)`, `Properties` |
| `Properties` | `List≤16(String(64) name, String(32767) value, Opt(String(1024)) signature)` |
| `ResolvableProfile` | `Either(GameProfile, Partial)`, `SkinPatch` |
| `Partial` | `Opt(String(16))`, `Opt(UUID)`, `Properties` |
| `SkinPatch` | `Opt(Id)` body, `Opt(Id)` cape, `Opt(Id)` elytra, `Opt(Bool)` model (`PlayerModelType`, a Bool mapped to wide or slim) |
| `ResolvableInt` | `Either(Int, Id)` |
| `ResolvableFloat` | `Either(Float, Id)` |
| `FireworkExplosion` | `Enum` shape, `List(Int)` colors, `List(Int)` fade colors, Bool trail, Bool twinkle |
| `GlobalPos` | `Id` dimension, Position |

## Every data component

Ids are the `minecraft:data_component_type` registry's protocol ids, from
the generated `reports/registries.json` (122 entries, 0 to 121). The last
column is the `net.minecraft.core.component.DataComponents` field.

**All 122 are network-synchronised.** `DataComponentType$Builder.build()`
sets `streamCodec = requireNonNullElseGet(streamCodec, () ->
ByteBufCodecs.fromCodecWithRegistries(requireNonNull(codec)))`, so the seven
whose builder never calls `networkSynchronized` (0, 22, 49, 59, 68, 81, 82)
go over the network as their persistent codec's NBT. `isTransient()` only
matters for saving. Three components have no persistent codec but are
synchronised: 20, 42 and 50.

| Id | Name | Wire shape | Field |
|---|---|---|---|
| 0 | custom_data | `NBT` | CUSTOM_DATA |
| 1 | max_stack_size | VarInt | MAX_STACK_SIZE |
| 2 | max_damage | VarInt | MAX_DAMAGE |
| 3 | damage | VarInt | DAMAGE |
| 4 | unbreakable | `unit` | UNBREAKABLE |
| 5 | use_effects | Bool can_sprint, Bool interact_vibrations, Float speed_multiplier | USE_EFFECTS |
| 6 | custom_name | `Text` | CUSTOM_NAME |
| 7 | minimum_attack_charge | Float | MINIMUM_ATTACK_CHARGE |
| 8 | damage_type | `Reg(damage_type)` | DAMAGE_TYPE |
| 9 | item_name | `Text` | ITEM_NAME |
| 10 | item_model | `Id` | ITEM_MODEL |
| 11 | lore | `List≤256(Text)` | LORE |
| 12 | rarity | `Enum` | RARITY |
| 13 | enchantments | `Map(Reg(enchantment), VarInt level)` | ENCHANTMENTS |
| 14 | can_place_on | `List(BlockPredicate)` | CAN_PLACE_ON |
| 15 | can_break | `List(BlockPredicate)` | CAN_BREAK |
| 16 | attribute_modifiers | `List(ItemAttributeModifiers.Entry)` | ATTRIBUTE_MODIFIERS |
| 17 | custom_model_data | `List(Float)`, `List(Bool)`, `List(String)`, `List(Int)` | CUSTOM_MODEL_DATA |
| 18 | tooltip_display | Bool hide_tooltip, `List(Reg(data_component_type))` hidden | TOOLTIP_DISPLAY |
| 19 | repair_cost | VarInt | REPAIR_COST |
| 20 | creative_slot_lock | `unit` | CREATIVE_SLOT_LOCK |
| 21 | enchantment_glint_override | Bool | ENCHANTMENT_GLINT_OVERRIDE |
| 22 | intangible_projectile | `NBT` | INTANGIBLE_PROJECTILE |
| 23 | food | VarInt nutrition, Float saturation, Bool can_always_eat | FOOD |
| 24 | consumable | Float seconds, `Enum` animation, `Sound`, Bool particles, `List(ConsumeEffect)` | CONSUMABLE |
| 25 | use_remainder | `Template` | USE_REMAINDER |
| 26 | use_cooldown | Float seconds, `Opt(Id)` group | USE_COOLDOWN |
| 27 | damage_resistant | `Set(damage_type)` | DAMAGE_RESISTANT |
| 28 | tool | `List(Rule)`, Float default_speed, VarInt damage_per_block, Bool creative_destroy; `Rule` is `Set(block)`, `Opt(Float)` speed, `Opt(Bool)` correct_for_drops | TOOL |
| 29 | weapon | VarInt damage_per_attack, Float disable_blocking_for | WEAPON |
| 30 | attack_range | six Floats: min_reach, max_reach, min_creative_reach, max_creative_reach, hitbox_margin, mob_factor | ATTACK_RANGE |
| 31 | enchantable | VarInt | ENCHANTABLE |
| 32 | equippable | `Enum` slot, `Sound`, `Opt(Id)` asset, `Opt(Id)` camera_overlay, `Opt(Set(entity_type))`, five Bools (dispensable, swappable, damage_on_hurt, equip_on_interact, can_be_sheared), `Sound` shearing | EQUIPPABLE |
| 33 | repairable | `Set(item)` | REPAIRABLE |
| 34 | glider | `unit` | GLIDER |
| 35 | tooltip_style | `Id` | TOOLTIP_STYLE |
| 36 | death_protection | `List(ConsumeEffect)` | DEATH_PROTECTION |
| 37 | blocks_attacks | Float, Float, `List(Reduction)`, Float threshold, Float base, Float factor, `Opt(Set(damage_type))`, `Opt(Sound)`, `Opt(Sound)`; `Reduction` is Float angle, `Opt(Set(damage_type))`, Float base, Float factor | BLOCKS_ATTACKS |
| 38 | piercing_weapon | Bool, Bool, `Opt(Sound)`, `Opt(Sound)` | PIERCING_WEAPON |
| 39 | kinetic_weapon | VarInt, VarInt, three `Opt(Condition)`, Float, Float, `Opt(Sound)`, `Opt(Sound)`; `Condition` is VarInt, Float, Float | KINETIC_WEAPON |
| 40 | attack_animation | `Enum` type, VarInt duration | ATTACK_ANIMATION |
| 41 | interact_animation | `Enum` type, VarInt duration | INTERACT_ANIMATION |
| 42 | additional_trade_cost | VarInt | ADDITIONAL_TRADE_COST |
| 43 | block_transformer | `Reg(block_transformer)` | BLOCK_TRANSFORMER |
| 44 | villager_food | VarInt | VILLAGER_FOOD |
| 45 | stored_enchantments | `Map(Reg(enchantment), VarInt level)` | STORED_ENCHANTMENTS |
| 46 | dye | `Enum` | DYE |
| 47 | dyed_color | Int | DYED_COLOR |
| 48 | map_id | VarInt | MAP_ID |
| 49 | map_decorations | `NBT` | MAP_DECORATIONS |
| 50 | map_post_processing | `Enum` | MAP_POST_PROCESSING |
| 51 | charged_projectiles | `List≤1024(Template)` | CHARGED_PROJECTILES |
| 52 | bundle_contents | `List(Template)` | BUNDLE_CONTENTS |
| 53 | potion_contents | `Opt(Reg(potion))`, `Opt(Int)` color, `List(MobEffectInstance)`, `Opt(String)` name | POTION_CONTENTS |
| 54 | potion_duration_scale | Float | POTION_DURATION_SCALE |
| 55 | suspicious_stew_effects | `List(Reg(mob_effect), VarInt duration)` | SUSPICIOUS_STEW_EFFECTS |
| 56 | writable_book_content | `List≤100(String(1024) raw, Opt(String(1024)) filtered)` | WRITABLE_BOOK_CONTENT |
| 57 | written_book_content | `String(32)`, `Opt(String(32))`, `String` author, VarInt generation, `List(Text raw, Opt(Text) filtered)`, Bool resolved | WRITTEN_BOOK_CONTENT |
| 58 | trim | `Holder(Id, Text)` material, `Holder(Id, Text, Bool)` pattern | TRIM |
| 59 | debug_stick_state | `NBT` | DEBUG_STICK_STATE |
| 60 | entity_data | `Reg(entity_type)`, `Compound` | ENTITY_DATA |
| 61 | bucket_entity_data | `Compound` | BUCKET_ENTITY_DATA |
| 62 | block_entity_data | `Reg(block_entity_type)`, `Compound` | BLOCK_ENTITY_DATA |
| 63 | instrument | `Holder(Sound, Float use_duration, Float range, VarInt durability_damage, Text)` | INSTRUMENT |
| 64 | provides_trim_material | `Holder(Id, Text)` | PROVIDES_TRIM_MATERIAL |
| 65 | ominous_bottle_amplifier | VarInt | OMINOUS_BOTTLE_AMPLIFIER |
| 66 | jukebox_playable | `Holder(Sound, Text, Float length, VarInt comparator_output)` | JUKEBOX_PLAYABLE |
| 67 | provides_banner_patterns | `Set(banner_pattern)` | PROVIDES_BANNER_PATTERNS |
| 68 | recipes | `NBT` | RECIPES |
| 69 | lodestone_tracker | `Opt(GlobalPos)`, Bool tracked | LODESTONE_TRACKER |
| 70 | firework_explosion | `FireworkExplosion` | FIREWORK_EXPLOSION |
| 71 | fireworks | VarInt flight_duration, `List≤256(FireworkExplosion)` | FIREWORKS |
| 72 | profile | `ResolvableProfile` | PROFILE |
| 73 | note_block_sound | `Id` | NOTE_BLOCK_SOUND |
| 74 | banner_patterns | `List(Holder(Id, String) pattern, Enum color)` | BANNER_PATTERNS |
| 75 | base_color | `Enum` | BASE_COLOR |
| 76 | pot_decorations | four `Opt(Template)`: back, left, right, front | POT_DECORATIONS |
| 77 | container | `List≤256(Opt(Template))` | CONTAINER |
| 78 | block_state | `Map(String, String)` | BLOCK_STATE |
| 79 | bees | `List(Reg(entity_type), Compound, VarInt ticks_in_hive, VarInt min_ticks_in_hive)` | BEES |
| 80 | sulfur_cube_content | `Template` | SULFUR_CUBE_CONTENT |
| 81 | lock | `NBT` | LOCK |
| 82 | container_loot | `NBT` | CONTAINER_LOOT |
| 83 | break_sound | `Sound` | BREAK_SOUND |
| 84 | compostable | `ResolvableInt` | COMPOSTABLE |
| 85 | cooking_fuel | `ResolvableInt` burn_time, `ResolvableFloat` speed_multiplier | COOKING_FUEL |
| 86 | brewing_fuel | `ResolvableInt` uses, `ResolvableFloat` speed_multiplier | BREWING_FUEL |
| 87 | mob_visibility | `Set(entity_type)`, Float | MOB_VISIBILITY |
| 88 | villager/variant | `Reg(villager_type)` | VILLAGER_VARIANT |
| 89 | wolf/variant | `Reg(wolf_variant)` | WOLF_VARIANT |
| 90 | wolf/sound_variant | `Reg(wolf_sound_variant)` | WOLF_SOUND_VARIANT |
| 91 | wolf/collar | `Enum` | WOLF_COLLAR |
| 92 | fox/variant | `Enum` | FOX_VARIANT |
| 93 | salmon/size | `Enum` | SALMON_SIZE |
| 94 | parrot/variant | `Enum` | PARROT_VARIANT |
| 95 | tropical_fish/pattern | `Enum` | TROPICAL_FISH_PATTERN |
| 96 | tropical_fish/base_color | `Enum` | TROPICAL_FISH_BASE_COLOR |
| 97 | tropical_fish/pattern_color | `Enum` | TROPICAL_FISH_PATTERN_COLOR |
| 98 | mooshroom/variant | `Enum` | MOOSHROOM_VARIANT |
| 99 | rabbit/variant | `Enum` | RABBIT_VARIANT |
| 100 | pig/variant | `Reg(pig_variant)` | PIG_VARIANT |
| 101 | pig/sound_variant | `Reg(pig_sound_variant)` | PIG_SOUND_VARIANT |
| 102 | cow/variant | `Reg(cow_variant)` | COW_VARIANT |
| 103 | cow/sound_variant | `Reg(cow_sound_variant)` | COW_SOUND_VARIANT |
| 104 | chicken/variant | `Reg(chicken_variant)` | CHICKEN_VARIANT |
| 105 | chicken/sound_variant | `Reg(chicken_sound_variant)` | CHICKEN_SOUND_VARIANT |
| 106 | zombie_nautilus/variant | `Reg(zombie_nautilus_variant)` | ZOMBIE_NAUTILUS_VARIANT |
| 107 | frog/variant | `Reg(frog_variant)` | FROG_VARIANT |
| 108 | horse/variant | `Enum` | HORSE_VARIANT |
| 109 | painting/variant | `Holder(VarInt width, VarInt height, Id, Opt(Text) title, Opt(Text) author)` | PAINTING_VARIANT |
| 110 | llama/variant | `Enum` | LLAMA_VARIANT |
| 111 | axolotl/variant | `Enum` | AXOLOTL_VARIANT |
| 112 | cat/variant | `Reg(cat_variant)` | CAT_VARIANT |
| 113 | cat/sound_variant | `Reg(cat_sound_variant)` | CAT_SOUND_VARIANT |
| 114 | cat/collar | `Enum` | CAT_COLLAR |
| 115 | sheep/color | `Enum` | SHEEP_COLOR |
| 116 | shulker/color | `Enum` | SHULKER_COLOR |
| 117 | provides_pottery_pattern | `Reg(decorated_pot_pattern)` | PROVIDES_POTTERY_PATTERN |
| 118 | sign_text_front | `List4(Text)`, `Opt(List4(Text))`, `Enum` color, Bool glowing | SIGN_TEXT_FRONT |
| 119 | sign_text_back | `List4(Text)`, `Opt(List4(Text))`, `Enum` color, Bool glowing | SIGN_TEXT_BACK |
| 120 | waxed | `unit` | WAXED |
| 121 | cushion/color | `Enum` | CUSHION_COLOR |

Four things the rows hide:

- **Enum reads never fail.** Every `Enum` (and the `ByIdMap` behind it)
  answers an out-of-range id with its `ZERO`, `CLAMP`, `WRAP` or sparse
  default instead of throwing, so any VarInt is a valid read.
- **A registry id is just a VarInt to the codec.** It has no registries, so
  it cannot tell a valid id from an out-of-range one.
- **The NBT components carry any non-END tag** on the network
  (`fromCodecWithRegistries`), even where the persistent codec only accepts a
  compound: a wrong root type fails later, in the codec, not in the read.
  `Compound` is the one place the read itself insists on type 10.
- **Text is NBT.** A text component is the codec's NBT root tag; the 2 MiB
  accounting quota vanilla applies while reading it is not modelled (as for
  registry data, see `2026-09-26-join.md`).

## Where the vanilla client is more lenient than the codec

The codec stays stricter so that a read always re-encodes to the same bytes:

- Bool: vanilla reads any nonzero byte as true; the codec's `BOOL` rejects
  anything but 0 and 1.
- A negative Slot count decodes as the empty stack in vanilla; the codec
  rejects it, because it cannot round-trip as the empty stack's `0`.
- A hashed slot's removed components are a set in vanilla (order and
  duplicates lost); the codec keeps the wire list.

## Differences from the wiki (the jar wins)

Compared against minecraft.wiki as raw wikitext at exact revisions:
*Java Edition protocol/Slot data* oldid **3763756** (2026-09-07T14:44:13Z) and
*Java Edition protocol/Data types* oldid **3763787** (2026-09-07T15:01:01Z).
*Data component format* (oldid 3784569) describes the NBT and JSON forms, not
these bytes, and was not used for layouts.

- **The component list.** The wiki has 111 names, with no ids and in no
  registry order. Two are not in the 26.3 registry (`map_color`,
  `swing_animation`). Thirteen registry names are missing from it:
  `attack_animation`, `interact_animation` (the wiki's one `swing_animation`
  layout fits both), `block_transformer`, `villager_food`, `compostable`,
  `cooking_fuel`, `brewing_fuel`, `mob_visibility`,
  `provides_pottery_pattern`, `sign_text_front`, `sign_text_back`, `waxed`
  and `cushion/color`.
- **Nested stacks are Templates, not Slots.** `use_remainder`,
  `charged_projectiles`, `bundle_contents` and `sulfur_cube_content` put the
  count after the item and cannot be empty. `container` is `List≤256` of
  `Opt(Template)`, not of Slot. `pot_decorations` is four `Opt(Template)`,
  not four item ids.
- **`attribute_modifiers`** has a trailing `Display` (type, then nothing or a
  text), which the wiki lacks.
- **`equippable`** has a fifth Bool, `equip_on_interact`, between
  `damage_on_hurt` and `can_be_sheared`; the wiki lists four.
- **`instrument`** has a `durability_damage` VarInt before the description.
- **`trim`**: the wiki's inline material (suffix, overrides, description) and
  pattern (asset name, template item, description, decal) are from an older
  version. Inline is now `Id` plus `Text` for a material and `Id`, `Text`,
  Bool for a pattern.
- **`jukebox_playable`**: the wiki warns that an inline song disconnects the
  client. The jar's codec is `holder`, with an inline form on the network
  (`Sound`, `Text`, Float, VarInt); whether the client copes is not a
  question for the codec.
- **`written_book_content`** pages are `List` with no maximum of 100, and
  each page is an NBT text with no string limit. (`writable_book_content`
  agrees with the wiki: `List≤100`, `String(1024)`.)
- **`recipes`** is a list of identifiers (`Recipe.KEY_CODEC.listOf()`), so
  the NBT tag is a list, not the wiki's compound. **`lock`** is an
  `ItemPredicate` (a compound), not the wiki's string tag.
- **Partial data component matcher.** The type is `Either(predicate type,
  component type)`: a Bool comes before the VarInt, and the wiki omits it.
  There are 15 predicate types (ids 0 to 14; the wiki stops at 13,
  `jukebox_playable`, and misses 14, `villager/variant`).
- **State property matcher.** A ranged match is two `Opt(String)`, each with
  its own Bool; the wiki's "Optional" does not show that.
- **Resolvable profile.** The kind is a Bool (true is the complete profile)
  and the skin model is `Opt(Bool)`, not VarInts. The bytes are the same for
  0 and 1.
- **Hashed slot.** Each of the added map and the removed list is capped at
  256 on read. The wiki gives no cap.
- **Slot itself agrees** with the wiki apart from those above.

## Two corrections to the plan

- **Particle item options use the Template layout**, not Slot
  (`ItemParticleOption.streamCodec` is `ItemStackTemplate.STREAM_CODEC`), so
  `codec/particles.py` takes `ITEM_STACK_TEMPLATE`, not `SLOT`. The item
  entity-data serializer (`EntityDataSerializers$1`) and equipment use Slot
  (`ItemStack.OPTIONAL_STREAM_CODEC`). The recorded payloads cannot tell the
  two apart on their own: `03 37 00 00` reads as either Slot (count 3, item
  55) or Template (item 3, count 55).
- **No component is "not network-synchronised".** The coverage test's
  second marker has no user.
