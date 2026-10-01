"""The stacks a command can give, and how an operator Bot reads them back.

Research and tests only, never src/: an operator Bot sends `give` with `Bot.command`, and
the stack arrives as a `container_set_slot`.
Each `Give` is one `/give` argument and the data components vanilla 26.3 sends for it,
checked live on the Reference (tests/reference/test_item_stacks_reference.py). Every value
differs from its item's default: a component equal to the prototype's is not sent.
"""

import contextlib
import dataclasses
from collections.abc import AsyncIterator, Sequence
from typing import Any, cast

from mscts.bot import Bot
from mscts.codec.items import SLOT
from mscts.codec.packets import Packet
from mscts.codec.schema import SHORT, VAR_INT, Schema
from mscts.codec.wire import WireError
from mscts.runner import Instance
from mscts.target import TARGET
from mscts.transcript import Transcript
from support.wire import read_all

OPERATOR = "mscts_op"
"""The Bot a test's ServerSpec makes an operator."""

SET_SLOT = Schema(window_id=VAR_INT, state_id=VAR_INT, slot=SHORT, item=SLOT)
"""`ClientboundContainerSetSlotPacket`, as vanilla sends it: nothing follows the stack."""

NOT_GIVEABLE = frozenset(
    {
        "additional_trade_cost",
        "creative_slot_lock",
        "map_post_processing",
    }
)
"""The data components no `/give` takes: vanilla answers `arguments.item.component.unknown`,
because items do not encode them (they are synchronised but transient)."""


@dataclasses.dataclass(frozen=True, slots=True)
class Give:
    """One `/give` argument, and the components of the stack that arrives for it.

    Attributes:
        label: What the row is about, for a failure message.
        argument: What follows `give <operator> minecraft:`.
        added: The (unprefixed) names of the components the stack adds, sorted.
        removed: The names of the components it removes, with their namespace.
    """

    label: str
    argument: str
    added: tuple[str, ...]
    removed: tuple[str, ...] = ()


def _one(component: str, argument: str) -> Give:
    """A row whose stack adds just the component it is named for."""
    return Give(component, argument, (component,))


@contextlib.asynccontextmanager
async def operator_bot(instance: Instance, server: str) -> AsyncIterator[tuple[Bot, Transcript]]:
    """The operator, joined to `instance` (an operator there), and its Transcript."""
    transcript = Transcript(group_id="item-stacks", server=server)
    bot = await Bot.connect(
        instance.endpoint, TARGET, name=OPERATOR, transcript=transcript, timeout_s=30
    )
    try:
        await bot.join()
        yield bot, transcript
    finally:
        await bot.close()


async def given_slots(
    bot: Bot, transcript: Transcript, argument: str, *, wait_s: float = 10.0
) -> list[bytes]:
    """Give the operator `argument`; the payloads of the `container_set_slot`s it causes.

    It takes packets until one carries a stack (or `wait_s` passes, when the server sends
    none), then until the Bot's barrier (`sync`) answers, for whatever else the command
    sent. The barrier alone is not enough: Pumpkin runs a command after the tick it was
    sent in, so the barrier can answer first. The payloads are the transcript's, so a stack
    the Codec cannot decode is the caller's to report.
    """
    first = len(transcript.events)
    await bot.command(f"give {OPERATOR} minecraft:{argument}")
    with contextlib.suppress(TimeoutError):
        await bot.expect("minecraft:container_set_slot", timeout_s=wait_s, where=_a_stack)
    await bot.sync()
    return [
        event.packet.payload
        for event in transcript.events[first:]
        if event.packet.name == "minecraft:container_set_slot"
    ]


def _a_stack(packet: Packet) -> bool:
    """Whether the `container_set_slot` holds a stack, or bytes that are none (not empty)."""
    try:
        return bool(stacks_of(read_slots([packet.payload])))
    except WireError:
        return True


async def clear(bot: Bot) -> None:
    """Empty the operator's inventory, and wait for the server to be done with it."""
    await bot.command(f"clear {OPERATOR}")
    await bot.sync()


type Slot = dict[str, Any]
"""A decoded `SET_SLOT`: `window_id`, `state_id`, `slot` and `item` (a stack, or None)."""

type Stack = dict[str, Any]
"""A decoded `SLOT` that is not empty: `count`, `item` and `components`."""


def read_slots(payloads: Sequence[bytes]) -> list[Slot]:
    """Each payload as a `SET_SLOT`, all of it.

    Raises:
        WireError: A payload does not decode, or has bytes left after the stack.
    """
    return [cast("Slot", read_all(SET_SLOT, payload)) for payload in payloads]


def stacks_of(slots: Sequence[Slot]) -> list[Stack]:
    """The stacks of the slots that are not empty."""
    return [slot["item"] for slot in slots if slot["item"] is not None]


def added_names(stack: Stack) -> list[str]:
    """The names, without their namespace, of the components `stack` adds, sorted."""
    return sorted(
        entry["type"].removeprefix("minecraft:") for entry in stack["components"]["added"]
    )


GIVES: tuple[Give, ...] = (
    _one("custom_data", "stick[custom_data={foo:1}]"),
    _one("max_stack_size", "stick[max_stack_size=16]"),
    Give(
        "max_damage",
        "stick[max_stack_size=1,max_damage=100]",
        ("max_damage", "max_stack_size"),
    ),
    _one("damage", "diamond_sword[damage=3]"),
    _one("unbreakable", "diamond_sword[unbreakable={}]"),
    _one("use_effects", "stick[use_effects={can_sprint:true,speed_multiplier:0.5f}]"),
    _one("custom_name", 'stick[custom_name={text:"Magic Wand",color:"light_purple",italic:false}]'),
    _one("minimum_attack_charge", "stick[minimum_attack_charge=0.5f]"),
    _one("damage_type", 'stick[damage_type="minecraft:campfire"]'),
    _one("item_name", 'stick[item_name="Dirt"]'),
    _one("item_model", 'stick[item_model="minecraft:diamond_sword"]'),
    _one("lore", 'stick[lore=[{text:"x"},{text:"y",italic:false}]]'),
    _one("rarity", "stick[rarity=epic]"),
    _one("enchantments", "stick[enchantments={sharpness:5,knockback:2}]"),
    _one("can_place_on", 'stick[can_place_on={blocks:"sandstone"}]'),
    _one("can_break", 'stick[can_break={blocks:["black_concrete","coal_ore"]}]'),
    _one(
        "attribute_modifiers",
        (
            'stick[attribute_modifiers=[{type:"minecraft:scale",slot:"hand",'
            'id:"example:grow",amount:4,operation:"add_multiplied_base"}]]'
        ),
    ),
    _one(
        "custom_model_data",
        (
            'stick[custom_model_data={floats:[4.0f,5.6f],strings:["foo:bar"],'
            "colors:[8323327],flags:[true,false]}]"
        ),
    ),
    _one(
        "tooltip_display",
        ('stick[tooltip_display={hide_tooltip:true,hidden_components:["minecraft:enchantments"]}]'),
    ),
    _one("repair_cost", "stick[repair_cost=7]"),
    _one("enchantment_glint_override", "stick[enchantment_glint_override=false]"),
    _one("intangible_projectile", "arrow[intangible_projectile={}]"),
    _one("food", "stick[food={nutrition:3,saturation:1f,can_always_eat:true}]"),
    _one(
        "consumable",
        (
            'stick[consumable={consume_seconds:3.0f,animation:"drink",'
            'sound:"entity.generic.eat",has_consume_particles:false,'
            'on_consume_effects:[{type:"minecraft:clear_all_effects"}]}]'
        ),
    ),
    _one("use_remainder", 'stick[use_remainder={id:"minecraft:gunpowder",count:2}]'),
    _one("use_cooldown", 'stick[use_cooldown={seconds:10f,cooldown_group:"foo:bar"}]'),
    _one("damage_resistant", 'stick[damage_resistant={types:"#minecraft:is_fire"}]'),
    _one(
        "tool",
        (
            "stick[tool={default_mining_speed:1.5f,damage_per_block:2,"
            'rules:[{blocks:"#minecraft:mineable/pickaxe",speed:6f,'
            "correct_for_drops:true}]}]"
        ),
    ),
    _one("weapon", ("stick[weapon={disable_blocking_for_seconds:5f,item_damage_per_attack:10}]")),
    _one("attack_range", "stick[attack_range={max_reach:5f}]"),
    _one("enchantable", "stick[enchantable={value:15}]"),
    _one(
        "equippable",
        ('stick[equippable={slot:"head",equip_sound:"block.glass.break",dispensable:false}]'),
    ),
    _one("repairable", 'stick[repairable={items:"stick"}]'),
    _one("glider", "stick[glider={}]"),
    _one("tooltip_style", 'stick[tooltip_style="minecraft:custom"]'),
    _one(
        "death_protection",
        'stick[death_protection={death_effects:[{type:"minecraft:clear_all_effects"}]}]',
    ),
    _one(
        "blocks_attacks",
        (
            "stick[blocks_attacks={disable_cooldown_scale:0f,"
            "damage_reductions:[{type:[mob_attack,arrow,explosion],base:0f,"
            "factor:0.5f}],block_sound:block.anvil.place}]"
        ),
    ),
    _one(
        "piercing_weapon",
        (
            'stick[piercing_weapon={sound:"entity.blaze.hurt",'
            'hit_sound:"entity.lightning_bolt.impact"}]'
        ),
    ),
    _one(
        "kinetic_weapon",
        (
            "stick[kinetic_weapon={delay_ticks:20,"
            "damage_conditions:{max_duration_ticks:120},"
            "knockback_conditions:{max_duration_ticks:80},"
            'dismount_conditions:{max_duration_ticks:40},sound:"item.spear.use",'
            'hit_sound:"block.amethyst_block.hit"}]'
        ),
    ),
    _one("attack_animation", 'stick[attack_animation={type:"stab",duration:20}]'),
    _one("interact_animation", 'stick[interact_animation={type:"stab",duration:20}]'),
    _one("block_transformer", 'stick[block_transformer="shovel"]'),
    _one("villager_food", "stick[villager_food={nutrition:12}]"),
    _one("stored_enchantments", "enchanted_book[stored_enchantments={knockback:2}]"),
    _one("dye", 'stick[dye="red"]'),
    _one("dyed_color", "leather_helmet[dyed_color=8388403]"),
    _one("map_id", "filled_map[map_id=5]"),
    _one(
        "map_decorations",
        ('filled_map[map_decorations={"a":{type:"minecraft:player",x:1.0d,z:2.0d,rotation:0f}}]'),
    ),
    _one("charged_projectiles", 'crossbow[charged_projectiles=[{id:"spectral_arrow"}]]'),
    _one("bundle_contents", 'bundle[bundle_contents=[{id:"diamond",count:2}]]'),
    _one(
        "potion_contents",
        (
            'potion[potion_contents={potion:"swiftness",custom_color:255,'
            'custom_effects:[{id:"speed",amplifier:1,duration:100}],custom_name:"x"}]'
        ),
    ),
    _one("potion_duration_scale", "potion[potion_duration_scale=2f]"),
    _one(
        "suspicious_stew_effects",
        ('suspicious_stew[suspicious_stew_effects=[{id:"minecraft:speed",duration:100}]]'),
    ),
    _one(
        "writable_book_content",
        ('writable_book[writable_book_content={pages:["Hello",{raw:"a",filtered:"b"}]}]'),
    ),
    _one(
        "written_book_content",
        (
            'written_book[written_book_content={title:"T",author:"A",'
            'pages:[{text:"Hello"}],generation:1}]'
        ),
    ),
    _one("trim", 'leather_leggings[trim={pattern:"host",material:"emerald"}]'),
    _one("debug_stick_state", 'debug_stick[debug_stick_state={"minecraft:oak_fence":"west"}]'),
    _one("entity_data", 'armor_stand[entity_data={id:"armor_stand",Small:1b}]'),
    _one("bucket_entity_data", "axolotl_bucket[bucket_entity_data={Health:3.0f}]"),
    _one("block_entity_data", 'spawner[block_entity_data={id:"mob_spawner"}]'),
    _one("instrument", 'goat_horn[instrument="feel_goat_horn"]'),
    _one("provides_trim_material", 'stick[provides_trim_material="minecraft:emerald"]'),
    _one("ominous_bottle_amplifier", "ominous_bottle[ominous_bottle_amplifier=3]"),
    _one("jukebox_playable", 'stick[jukebox_playable="pigstep"]'),
    _one(
        "provides_banner_patterns",
        "stick[provides_banner_patterns='#minecraft:pattern_item/globe']",
    ),
    _one("recipes", 'knowledge_book[recipes=["minecraft:end_crystal"]]'),
    _one(
        "lodestone_tracker",
        ('compass[lodestone_tracker={target:{pos:[I;1,2,3],dimension:"overworld"},tracked:false}]'),
    ),
    _one(
        "firework_explosion",
        (
            'firework_star[firework_explosion={shape:"star",colors:[1],'
            "fade_colors:[2],has_trail:true,has_twinkle:true}]"
        ),
    ),
    _one(
        "fireworks",
        (
            'firework_rocket[fireworks={flight_duration:2,explosions:[{shape:"burst",'
            "colors:[255]}]}]"
        ),
    ),
    _one("profile", "player_head[profile=MinecraftWiki]"),
    _one("note_block_sound", 'stick[note_block_sound="entity.item.pickup"]'),
    _one("banner_patterns", 'black_banner[banner_patterns=[{pattern:"triangle_top",color:"red"}]]'),
    _one("base_color", 'shield[base_color="lime"]'),
    _one("pot_decorations", 'stick[pot_decorations={back:"brick",left:"minecraft:stick"}]'),
    _one("container", 'barrel[container=[{slot:0,item:{id:"apple"}}]]'),
    _one("block_state", 'bamboo_slab[block_state={type:"top"}]'),
    _one(
        "bees", ('bee_nest[bees=[{entity_data:{id:"bee"},min_ticks_in_hive:60,ticks_in_hive:0}]]')
    ),
    _one("sulfur_cube_content", 'stick[sulfur_cube_content={id:"stone"}]'),
    _one("lock", 'chest[lock={components:{"minecraft:custom_name":"K"}}]'),
    _one("container_loot", 'chest[container_loot={loot_table:"chests/desert_pyramid"}]'),
    _one("break_sound", 'stick[break_sound="item.wolf_armor.break"]'),
    _one("compostable", "stick[compostable={layers:1}]"),
    _one("cooking_fuel", "stick[cooking_fuel={burn_time:40,speed_multiplier:2f}]"),
    _one("brewing_fuel", "stick[brewing_fuel={uses:3,speed_multiplier:2f}]"),
    _one(
        "mob_visibility",
        ('stick[mob_visibility={targeting_entity_types:"minecraft:skeleton",visibility:0f}]'),
    ),
    _one("provides_pottery_pattern", 'stick[provides_pottery_pattern="danger"]'),
    _one(
        "sign_text_front",
        (
            'oak_sign[sign_text_front={messages:["","Hello there!","",""],'
            'color:"red",has_glowing_text:true}]'
        ),
    ),
    _one("sign_text_back", 'oak_sign[sign_text_back={messages:["a","","","d"]}]'),
    _one("waxed", "oak_sign[waxed={}]"),
    _one("cushion/color", 'stick[cushion/color="purple"]'),
    _one("axolotl/variant", 'stick[axolotl/variant="blue"]'),
    _one("cat/collar", 'stick[cat/collar="blue"]'),
    _one("cat/sound_variant", 'stick[cat/sound_variant="royal"]'),
    _one("cat/variant", 'stick[cat/variant="jellie"]'),
    _one("chicken/sound_variant", 'stick[chicken/sound_variant="picky"]'),
    _one("chicken/variant", 'stick[chicken/variant="cold"]'),
    _one("cow/sound_variant", 'stick[cow/sound_variant="moody"]'),
    _one("cow/variant", 'stick[cow/variant="cold"]'),
    _one("fox/variant", 'stick[fox/variant="snow"]'),
    _one("frog/variant", 'stick[frog/variant="cold"]'),
    _one("horse/variant", 'stick[horse/variant="chestnut"]'),
    _one("llama/variant", 'stick[llama/variant="gray"]'),
    _one("mooshroom/variant", 'stick[mooshroom/variant="brown"]'),
    _one("painting/variant", 'stick[painting/variant="plant"]'),
    _one("parrot/variant", 'stick[parrot/variant="blue"]'),
    _one("pig/sound_variant", 'stick[pig/sound_variant="big"]'),
    _one("pig/variant", 'stick[pig/variant="warm"]'),
    _one("rabbit/variant", 'stick[rabbit/variant="evil"]'),
    _one("salmon/size", 'stick[salmon/size="large"]'),
    _one("sheep/color", 'stick[sheep/color="blue"]'),
    _one("shulker/color", 'stick[shulker/color="red"]'),
    _one("tropical_fish/base_color", 'stick[tropical_fish/base_color="red"]'),
    _one("tropical_fish/pattern", 'stick[tropical_fish/pattern="snooper"]'),
    _one("tropical_fish/pattern_color", 'stick[tropical_fish/pattern_color="blue"]'),
    _one("villager/variant", 'stick[villager/variant="desert"]'),
    _one("wolf/collar", 'stick[wolf/collar="blue"]'),
    _one("wolf/sound_variant", 'stick[wolf/sound_variant="cute"]'),
    _one("wolf/variant", 'stick[wolf/variant="rusty"]'),
    _one("zombie_nautilus/variant", 'stick[zombie_nautilus/variant="warm"]'),
    Give(
        "headline",
        "diamond_sword[enchantments={sharpness:5},damage=3]",
        ("damage", "enchantments"),
    ),
    Give(
        "plain",
        "diamond 5",
        (),
    ),
    Give(
        "removed",
        "diamond_sword[!attribute_modifiers,!max_damage,damage=2]",
        ("damage",),
        ("minecraft:attribute_modifiers", "minecraft:max_damage"),
    ),
    Give(
        "consume effects",
        (
            'stick[consumable={on_consume_effects:[{type:"minecraft:apply_effects",'
            'effects:[{id:"minecraft:speed",amplifier:1,duration:100,ambient:true,'
            "show_particles:false,show_icon:false}],probability:0.5f},"
            '{type:"minecraft:remove_effects",effects:"minecraft:speed"},'
            '{type:"minecraft:clear_all_effects"},'
            '{type:"minecraft:teleport_randomly",diameter:8f},'
            '{type:"minecraft:play_sound",sound:"entity.generic.eat"}]}]'
        ),
        ("consumable",),
    ),
    Give(
        "direct sound",
        'stick[consumable={sound:{sound_id:"a:b",range:16f}}]',
        ("consumable",),
    ),
    Give(
        "hidden effect",
        (
            'potion[potion_contents={custom_effects:[{id:"speed",amplifier:1,'
            "duration:100,hidden_effect:{amplifier:2,duration:50}}]}]"
        ),
        ("potion_contents",),
    ),
    Give(
        "block predicate",
        (
            'stick[can_place_on={blocks:"#minecraft:logs",state:{facing:"north",'
            'age:{min:"1",max:"3"}},nbt:"{a:1}",components:{"minecraft:damage":3},'
            'predicates:{"minecraft:damage":{damage:{min:1}}}}]'
        ),
        ("can_place_on",),
    ),
    Give(
        "two block predicates",
        'stick[can_break=[{blocks:"stone"},{blocks:"dirt"}]]',
        ("can_break",),
    ),
    Give(
        "any value predicate",
        ('stick[can_break={blocks:"stone",predicates:{"minecraft:custom_name":{}}}]'),
        ("can_break",),
    ),
    Give(
        "template components",
        ('stick[use_remainder={id:"minecraft:bone",components:{custom_name:"Bone"},count:2}]'),
        ("use_remainder",),
    ),
    Give(
        "bundle in a bundle",
        (
            'bundle[bundle_contents=[{id:"bundle",count:1,'
            'components:{bundle_contents:[{id:"diamond",count:2}]}}]]'
        ),
        ("bundle_contents",),
    ),
    Give(
        "container with components",
        (
            'barrel[container=[{slot:0,item:{id:"stick",count:3,components:{damage:0,'
            'lore:[{text:"a"}]}}},{slot:5,item:{id:"apple"}}]]'
        ),
        ("container",),
    ),
    Give(
        "attribute display",
        (
            'stick[attribute_modifiers=[{type:"minecraft:scale",slot:"hand",'
            'id:"example:grow",amount:4,operation:"add_value",'
            'display:{type:"override",value:"Big"}},{type:"minecraft:scale",'
            'slot:"any",id:"example:g2",amount:1,operation:"add_value",'
            'display:{type:"hidden"}}]]'
        ),
        ("attribute_modifiers",),
    ),
    Give(
        "profile properties",
        (
            'player_head[profile={name:"Steve",properties:[{name:"textures",'
            'value:"abc",signature:"sig"}]}]'
        ),
        ("profile",),
    ),
    Give(
        "profile id",
        "player_head[profile={id:[I;1,2,3,4]}]",
        ("profile",),
    ),
    Give(
        "profile skin",
        (
            'player_head[profile={name:"x",'
            'texture:"minecraft:entity/player/wide/steve",model:"slim"}]'
        ),
        ("profile",),
    ),
    Give(
        "direct instrument",
        (
            'goat_horn[instrument={description:"prank!",'
            'sound_event:"entity.creeper.primed",use_duration:2f,range:30f}]'
        ),
        ("instrument",),
    ),
    Give(
        "direct trim",
        (
            'leather_leggings[trim={pattern:{asset_id:"a:b",description:"p",'
            'decal:true},material:{palette_id:"a:b",description:"m"}}]'
        ),
        ("trim",),
    ),
    Give(
        "equippable all",
        (
            'stick[equippable={slot:"chest",equip_sound:"item.armor.equip_chain",'
            'asset_id:"a:b",camera_overlay:"c:d",allowed_entities:["minecraft:pig"],'
            "swappable:false,damage_on_hurt:false,equip_on_interact:true,"
            'can_be_sheared:true,shearing_sound:"entity.sheep.shear"}]'
        ),
        ("equippable",),
    ),
    Give(
        "blocks_attacks all",
        (
            "stick[blocks_attacks={block_delay_seconds:1f,"
            "disable_cooldown_scale:0.5f,"
            "damage_reductions:[{horizontal_blocking_angle:45f,"
            'type:"#minecraft:is_fire",base:1f,factor:0.5f}],'
            "item_damage:{threshold:2f,base:1f,factor:0.5f},"
            'bypassed_by:"#minecraft:bypasses_shield",'
            'block_sound:"block.anvil.place",disable_sound:"block.anvil.land"}]'
        ),
        ("blocks_attacks",),
    ),
    Give(
        "lodestone no target",
        "compass[lodestone_tracker={tracked:true}]",
        ("lodestone_tracker",),
    ),
    Give(
        "written book filtered",
        (
            'written_book[written_book_content={title:{raw:"T",filtered:"F"},'
            'author:"A",pages:[{raw:{text:"a"},filtered:{text:"b"}}],resolved:true}]'
        ),
        ("written_book_content",),
    ),
    Give(
        "two components",
        "stick[custom_name='x',repair_cost=2,rarity=rare]",
        ("custom_name", "rarity", "repair_cost"),
    ),
)
