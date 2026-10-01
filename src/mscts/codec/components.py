"""The data component table and the patch that carries it (`DataComponentPatch`).

A component's value has no length on the wire: its layout has to be known to read past it.
`TABLE` maps every name in the Target's `minecraft:data_component_type` registry to its wire
type, in registry order, so a component's id is its position in the generated name list and
no id is ever typed by hand. A component the table has no layout for is a `WireError`
naming it, never a silent misread (docs/research/2026-09-30-item-stacks.md).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from mscts.codec.registry_names import registry_names
from mscts.codec.schema import (
    BOOL,
    FLOAT,
    IDENTIFIER,
    INT,
    VAR_INT,
    PrefixedArray,
    PrefixedOptional,
    Schema,
    SchemaError,
    String,
    WireType,
)
from mscts.codec.shapes import (
    COMPOUND_TAG,
    ENUM,
    GLOBAL_POS,
    HOLDER_SET,
    NBT_TAG,
    PAINTING_VARIANT,
    REGISTRY_ID,
    RESOLVABLE_PROFILE,
    SOUND_EVENT,
    TEXT_COMPONENT,
    UNIT,
    Deferred,
    Either,
    FixedArray,
    Holder,
    registry_dispatch,
)
from mscts.codec.wire import Reader, WireError, Writer
from mscts.target import TARGET

_REGISTRY = "minecraft:data_component_type"


class ComponentTable:
    """The data component types by id, and the wire type of each one's value.

    A layout of None marks a component the server does not send over the network; a name
    with no layout at all is one the table has not learned yet. Both are refused when read
    or written, each with its own message.
    """

    __slots__ = ("_ids", "_layouts", "_names")

    def __init__(
        self, names: Sequence[str], layouts: Mapping[str, WireType[object] | None]
    ) -> None:
        """Declare the types in id order, and the layouts by name.

        Raises:
            SchemaError: A layout is declared for a name that is not in `names`.
        """
        unknown = sorted(name for name in layouts if name not in names)
        if unknown:
            msg = f"layout for {', '.join(unknown)}, which is not a data component type"
            raise SchemaError(msg)
        self._names = tuple(names)
        self._ids = {name: type_id for type_id, name in enumerate(self._names)}
        self._layouts = dict(layouts)

    @property
    def names(self) -> tuple[str, ...]:
        """Every data component type's name, in id order."""
        return self._names

    def type_id(self, name: str) -> int:
        """The protocol id of the type `name`.

        Raises:
            WireError: There is no such data component type.
        """
        if name not in self._ids:
            msg = f"unknown data component type {name!r}"
            raise WireError(msg)
        return self._ids[name]

    def type_name(self, type_id: int) -> str:
        """The name of the type with protocol id `type_id`.

        Raises:
            WireError: There is no such data component type.
        """
        if not 0 <= type_id < len(self._names):
            msg = f"unknown data component type id {type_id}"
            raise WireError(msg)
        return self._names[type_id]

    def layout(self, name: str) -> WireType[object]:
        """The wire type of `name`'s value.

        Raises:
            WireError: There is no such type, or it is not sent over the network, or the
                table has no layout for it yet. The message names the component.
        """
        self.type_id(name)
        if name not in self._layouts:
            msg = f"data component {name} has no known layout"
            raise WireError(msg)
        layout = self._layouts[name]
        if layout is None:
            msg = f"data component {name} is not network-synchronised"
            raise WireError(msg)
        return layout


def _read_count(reader: Reader, what: str) -> int:
    count = reader.var_int()
    if count < 0:
        msg = f"{what} count {count} is negative"
        raise WireError(msg)
    return count


def _check_count(reader: Reader, what: str, count: int) -> None:
    # Every entry takes at least the byte of its type id.
    if count > reader.remaining:
        msg = f"{what} count {count} exceeds the {reader.remaining} byte(s) left"
        raise WireError(msg)


def _mapping_with(value: object, keys: tuple[str, ...]) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        msg = f"expected a mapping of {' and '.join(keys)}, got {type(value).__name__}"
        raise WireError(msg)
    given = {str(key): item for key, item in value.items()}
    problems = [f"missing key {key}" for key in keys if key not in given]
    problems += [f"unexpected key {key}" for key in sorted(given) if key not in keys]
    if problems:
        raise WireError("; ".join(problems))
    return given


def _list_of(value: object, what: str) -> list[object]:
    if not isinstance(value, list | tuple):
        msg = f"{what}: expected a list or tuple, got {type(value).__name__}"
        raise WireError(msg)
    return list(value)


@dataclass(frozen=True, slots=True)
class Patch:
    """A `DataComponentPatch`: what a stack adds to, and removes from, its item's defaults.

    On the wire: the VarInt count of added components, the VarInt count of removed ones,
    each added component as its type id and its value, then each removed type id. Its value
    is `{"added": [{"type": name, "value": value}, ...], "removed": [name, ...]}`, in wire
    order: a repeated type is kept as it is. Errors are prefixed with `added: <index>: ` or
    `removed: <index>: `, and a value's with the component's name.

    Attributes:
        table: The types and the layout of each value.
    """

    table: ComponentTable

    def read(self, reader: Reader) -> dict[str, object]:
        """Consume both counts, then the added components, then the removed types."""
        added_count = _read_count(reader, "added")
        removed_count = _read_count(reader, "removed")
        _check_count(reader, "added", added_count)
        _check_count(reader, "removed", removed_count)
        added = []
        for index in range(added_count):
            try:
                added.append(self._read_added(reader))
            except WireError as exc:
                msg = f"added: {index}: {exc}"
                raise WireError(msg) from exc
        removed = []
        for index in range(removed_count):
            try:
                removed.append(self.table.type_name(reader.var_int()))
            except WireError as exc:
                msg = f"removed: {index}: {exc}"
                raise WireError(msg) from exc
        return {"added": added, "removed": removed}

    def write(self, writer: Writer, value: object) -> None:
        """Append `value`: both counts, then the added components, then the removed types."""
        given = _mapping_with(value, ("added", "removed"))
        added = _list_of(given["added"], "added")
        removed = _list_of(given["removed"], "removed")
        writer.var_int(len(added))
        writer.var_int(len(removed))
        for index, pair in enumerate(added):
            try:
                self._write_added(writer, pair)
            except WireError as exc:
                msg = f"added: {index}: {exc}"
                raise WireError(msg) from exc
        for index, name in enumerate(removed):
            try:
                writer.var_int(self.table.type_id(self._name(name)))
            except WireError as exc:
                msg = f"removed: {index}: {exc}"
                raise WireError(msg) from exc

    def _read_added(self, reader: Reader) -> dict[str, object]:
        name = self.table.type_name(reader.var_int())
        layout = self.table.layout(name)
        try:
            return {"type": name, "value": layout.read(reader)}
        except WireError as exc:
            msg = f"{name}: {exc}"
            raise WireError(msg) from exc

    def _write_added(self, writer: Writer, pair: object) -> None:
        given = _mapping_with(pair, ("type", "value"))
        name = self._name(given["type"])
        layout = self.table.layout(name)
        writer.var_int(self.table.type_id(name))
        try:
            layout.write(writer, given["value"])
        except WireError as exc:
            msg = f"{name}: {exc}"
            raise WireError(msg) from exc

    @staticmethod
    def _name(value: object) -> str:
        if not isinstance(value, str):
            msg = f"expected a str, got {type(value).__name__}"
            raise WireError(msg)
        return value


# A `Map` (`ByteBufCodecs.map`) is a list of its pairs, in wire order: a dict would lose a repeated
# key and the order the server wrote them in.
_ENCHANTMENTS = PrefixedArray(Schema(enchantment=REGISTRY_ID, level=VAR_INT))
_SWING_ANIMATION = Schema(type=ENUM, duration=VAR_INT)  # `SwingAnimation`
_BOOK_PAGE = Schema(raw=String(1024), filtered=PrefixedOptional(String(1024)))

# A record of one field is that field's value, with no wrapper (`Enchantable`, `DyedItemColor`,
# `DamageResistant`, `JukeboxPlayable`, ...).
_RESOLVABLE_INT = Either("constant", INT, "reference", IDENTIFIER)  # `ResolvableInt`
_RESOLVABLE_FLOAT = Either("constant", FLOAT, "reference", IDENTIFIER)  # `ResolvableFloat`

# Holders of a record: a registry id, or the record itself.
_TRIM_MATERIAL = Holder(Schema(palette_id=IDENTIFIER, description=TEXT_COMPONENT))
_TRIM_PATTERN = Holder(
    Schema(asset_id=IDENTIFIER, description=TEXT_COMPONENT, decal=BOOL),
)
_INSTRUMENT = Holder(
    Schema(
        sound_event=SOUND_EVENT,
        use_duration=FLOAT,
        range=FLOAT,
        durability_damage=VAR_INT,
        description=TEXT_COMPONENT,
    )
)
_JUKEBOX_SONG = Holder(
    Schema(
        sound_event=SOUND_EVENT,
        description=TEXT_COMPONENT,
        length_in_seconds=FLOAT,
        comparator_output=VAR_INT,
    )
)
_BANNER_PATTERN = Holder(Schema(asset_id=IDENTIFIER, translation_key=String(32767)))

# An entity or block entity of a registry type and its data (`entity_data`, `block_entity_data`).
_TYPED_DATA = Schema(type=REGISTRY_ID, tag=COMPOUND_TAG)
_FIREWORK_EXPLOSION = Schema(
    shape=ENUM,
    colors=PrefixedArray(INT),
    fade_colors=PrefixedArray(INT),
    has_trail=BOOL,
    has_twinkle=BOOL,
)
_TOOL_RULE = Schema(
    blocks=HOLDER_SET, speed=PrefixedOptional(FLOAT), correct_for_drops=PrefixedOptional(BOOL)
)
_DAMAGE_REDUCTION = Schema(
    horizontal_blocking_angle=FLOAT, type=PrefixedOptional(HOLDER_SET), base=FLOAT, factor=FLOAT
)
_KINETIC_CONDITION = Schema(max_duration_ticks=VAR_INT, min_speed=FLOAT, min_relative_speed=FLOAT)
_BOOK_TITLE = Schema(raw=String(32), filtered=PrefixedOptional(String(32)))
_WRITTEN_PAGE = Schema(raw=TEXT_COMPONENT, filtered=PrefixedOptional(TEXT_COMPONENT))

# A mob effect's details hold the hidden effect it replaces, which has details of its own
# (`StreamCodec.recursive`).
_MOB_EFFECT_DETAILS: Schema = Schema(
    amplifier=VAR_INT,
    duration=VAR_INT,
    ambient=BOOL,
    show_particles=BOOL,
    show_icon=BOOL,
    hidden_effect=PrefixedOptional(Deferred(lambda: _MOB_EFFECT_DETAILS)),
)
_MOB_EFFECT_INSTANCE = Schema(effect=REGISTRY_ID, details=_MOB_EFFECT_DETAILS)

# `ConsumeEffect`: the id of a type in `minecraft:consume_effect_type`, then that type's fields.
_CONSUME_EFFECT = registry_dispatch(
    registry_names(TARGET.minecraft_version, "minecraft:consume_effect_type"),
    {
        "minecraft:apply_effects": Schema(
            effects=PrefixedArray(_MOB_EFFECT_INSTANCE), probability=FLOAT
        ),
        "minecraft:remove_effects": HOLDER_SET,
        "minecraft:clear_all_effects": None,
        "minecraft:teleport_randomly": Schema(diameter=FLOAT, directional_particles=BOOL),
        "minecraft:play_sound": SOUND_EVENT,
    },
)
_SIGN_LINES = FixedArray(TEXT_COMPONENT, 4)
_SIGN_TEXT = Schema(
    messages=_SIGN_LINES,
    filtered_messages=PrefixedOptional(_SIGN_LINES),
    color=ENUM,
    has_glowing_text=BOOL,
)

# In registry order. Each entry cites the `DataComponents` field that registers the name, and the
# layout is the one in docs/research/2026-09-30-item-stacks.md. A component with no network codec
# of its own (custom_data, intangible_projectile, map_decorations, debug_stick_state, recipes,
# lock, container_loot) goes over the network as the NBT of its persistent codec.
_LAYOUTS: dict[str, WireType[object] | None] = {
    "minecraft:custom_data": NBT_TAG,  # CUSTOM_DATA
    "minecraft:max_stack_size": VAR_INT,  # MAX_STACK_SIZE
    "minecraft:max_damage": VAR_INT,  # MAX_DAMAGE
    "minecraft:damage": VAR_INT,  # DAMAGE
    "minecraft:unbreakable": UNIT,  # UNBREAKABLE
    "minecraft:use_effects": Schema(  # USE_EFFECTS
        can_sprint=BOOL, interact_vibrations=BOOL, speed_multiplier=FLOAT
    ),
    "minecraft:custom_name": TEXT_COMPONENT,  # CUSTOM_NAME
    "minecraft:minimum_attack_charge": FLOAT,  # MINIMUM_ATTACK_CHARGE
    "minecraft:damage_type": REGISTRY_ID,  # DAMAGE_TYPE
    "minecraft:item_name": TEXT_COMPONENT,  # ITEM_NAME
    "minecraft:item_model": IDENTIFIER,  # ITEM_MODEL
    "minecraft:lore": PrefixedArray(TEXT_COMPONENT, max_length=256),  # LORE
    "minecraft:rarity": ENUM,  # RARITY
    "minecraft:enchantments": _ENCHANTMENTS,  # ENCHANTMENTS
    "minecraft:custom_model_data": Schema(  # CUSTOM_MODEL_DATA
        floats=PrefixedArray(FLOAT),
        flags=PrefixedArray(BOOL),
        strings=PrefixedArray(String(32767)),
        colors=PrefixedArray(INT),
    ),
    "minecraft:tooltip_display": Schema(  # TOOLTIP_DISPLAY
        hide_tooltip=BOOL, hidden_components=PrefixedArray(REGISTRY_ID)
    ),
    "minecraft:repair_cost": VAR_INT,  # REPAIR_COST
    "minecraft:creative_slot_lock": UNIT,  # CREATIVE_SLOT_LOCK
    "minecraft:enchantment_glint_override": BOOL,  # ENCHANTMENT_GLINT_OVERRIDE
    "minecraft:intangible_projectile": NBT_TAG,  # INTANGIBLE_PROJECTILE
    "minecraft:food": Schema(  # FOOD
        nutrition=VAR_INT, saturation=FLOAT, can_always_eat=BOOL
    ),
    "minecraft:consumable": Schema(  # CONSUMABLE
        consume_seconds=FLOAT,
        animation=ENUM,
        sound=SOUND_EVENT,
        has_consume_particles=BOOL,
        on_consume_effects=PrefixedArray(_CONSUME_EFFECT),
    ),
    "minecraft:use_cooldown": Schema(  # USE_COOLDOWN
        seconds=FLOAT, group=PrefixedOptional(IDENTIFIER)
    ),
    "minecraft:damage_resistant": HOLDER_SET,  # DAMAGE_RESISTANT
    "minecraft:tool": Schema(  # TOOL
        rules=PrefixedArray(_TOOL_RULE),
        default_mining_speed=FLOAT,
        damage_per_block=VAR_INT,
        can_destroy_blocks_in_creative=BOOL,
    ),
    "minecraft:weapon": Schema(  # WEAPON
        damage_per_attack=VAR_INT, disable_blocking_for=FLOAT
    ),
    "minecraft:attack_range": Schema(  # ATTACK_RANGE
        min_reach=FLOAT,
        max_reach=FLOAT,
        min_creative_reach=FLOAT,
        max_creative_reach=FLOAT,
        hitbox_margin=FLOAT,
        mob_factor=FLOAT,
    ),
    "minecraft:enchantable": VAR_INT,  # ENCHANTABLE
    "minecraft:equippable": Schema(  # EQUIPPABLE
        slot=ENUM,
        equip_sound=SOUND_EVENT,
        asset_id=PrefixedOptional(IDENTIFIER),
        camera_overlay=PrefixedOptional(IDENTIFIER),
        allowed_entities=PrefixedOptional(HOLDER_SET),
        dispensable=BOOL,
        swappable=BOOL,
        damage_on_hurt=BOOL,
        equip_on_interact=BOOL,
        can_be_sheared=BOOL,
        shearing_sound=SOUND_EVENT,
    ),
    "minecraft:repairable": HOLDER_SET,  # REPAIRABLE
    "minecraft:glider": UNIT,  # GLIDER
    "minecraft:tooltip_style": IDENTIFIER,  # TOOLTIP_STYLE
    "minecraft:death_protection": PrefixedArray(_CONSUME_EFFECT),  # DEATH_PROTECTION
    "minecraft:blocks_attacks": Schema(  # BLOCKS_ATTACKS
        block_delay_seconds=FLOAT,
        disable_cooldown_scale=FLOAT,
        damage_reductions=PrefixedArray(_DAMAGE_REDUCTION),
        item_damage=Schema(threshold=FLOAT, base=FLOAT, factor=FLOAT),
        bypassed_by=PrefixedOptional(HOLDER_SET),
        block_sound=PrefixedOptional(SOUND_EVENT),
        disable_sound=PrefixedOptional(SOUND_EVENT),
    ),
    "minecraft:piercing_weapon": Schema(  # PIERCING_WEAPON
        deals_knockback=BOOL,
        dismounts=BOOL,
        sound=PrefixedOptional(SOUND_EVENT),
        hit_sound=PrefixedOptional(SOUND_EVENT),
    ),
    "minecraft:kinetic_weapon": Schema(  # KINETIC_WEAPON
        contact_cooldown_ticks=VAR_INT,
        delay_ticks=VAR_INT,
        dismount_conditions=PrefixedOptional(_KINETIC_CONDITION),
        knockback_conditions=PrefixedOptional(_KINETIC_CONDITION),
        damage_conditions=PrefixedOptional(_KINETIC_CONDITION),
        forward_movement=FLOAT,
        damage_multiplier=FLOAT,
        sound=PrefixedOptional(SOUND_EVENT),
        hit_sound=PrefixedOptional(SOUND_EVENT),
    ),
    "minecraft:attack_animation": _SWING_ANIMATION,  # ATTACK_ANIMATION
    "minecraft:interact_animation": _SWING_ANIMATION,  # INTERACT_ANIMATION
    "minecraft:additional_trade_cost": VAR_INT,  # ADDITIONAL_TRADE_COST
    "minecraft:block_transformer": REGISTRY_ID,  # BLOCK_TRANSFORMER
    "minecraft:villager_food": VAR_INT,  # VILLAGER_FOOD
    "minecraft:stored_enchantments": _ENCHANTMENTS,  # STORED_ENCHANTMENTS
    "minecraft:dye": ENUM,  # DYE
    "minecraft:dyed_color": INT,  # DYED_COLOR
    "minecraft:map_id": VAR_INT,  # MAP_ID
    "minecraft:map_decorations": NBT_TAG,  # MAP_DECORATIONS
    "minecraft:map_post_processing": ENUM,  # MAP_POST_PROCESSING
    "minecraft:potion_contents": Schema(  # POTION_CONTENTS
        potion=PrefixedOptional(REGISTRY_ID),
        custom_color=PrefixedOptional(INT),
        custom_effects=PrefixedArray(_MOB_EFFECT_INSTANCE),
        custom_name=PrefixedOptional(String(32767)),
    ),
    "minecraft:potion_duration_scale": FLOAT,  # POTION_DURATION_SCALE
    "minecraft:suspicious_stew_effects": PrefixedArray(  # SUSPICIOUS_STEW_EFFECTS
        Schema(effect=REGISTRY_ID, duration=VAR_INT)
    ),
    "minecraft:writable_book_content": PrefixedArray(  # WRITABLE_BOOK_CONTENT
        _BOOK_PAGE, max_length=100
    ),
    "minecraft:written_book_content": Schema(  # WRITTEN_BOOK_CONTENT
        title=_BOOK_TITLE,
        author=String(32767),
        generation=VAR_INT,
        pages=PrefixedArray(_WRITTEN_PAGE),
        resolved=BOOL,
    ),
    "minecraft:trim": Schema(  # TRIM
        material=_TRIM_MATERIAL, pattern=_TRIM_PATTERN
    ),
    "minecraft:debug_stick_state": NBT_TAG,  # DEBUG_STICK_STATE
    "minecraft:entity_data": _TYPED_DATA,  # ENTITY_DATA
    "minecraft:bucket_entity_data": COMPOUND_TAG,  # BUCKET_ENTITY_DATA
    "minecraft:block_entity_data": _TYPED_DATA,  # BLOCK_ENTITY_DATA
    "minecraft:instrument": _INSTRUMENT,  # INSTRUMENT
    "minecraft:provides_trim_material": _TRIM_MATERIAL,  # PROVIDES_TRIM_MATERIAL
    "minecraft:ominous_bottle_amplifier": VAR_INT,  # OMINOUS_BOTTLE_AMPLIFIER
    "minecraft:jukebox_playable": _JUKEBOX_SONG,  # JUKEBOX_PLAYABLE
    "minecraft:provides_banner_patterns": HOLDER_SET,  # PROVIDES_BANNER_PATTERNS
    "minecraft:recipes": NBT_TAG,  # RECIPES
    "minecraft:lodestone_tracker": Schema(  # LODESTONE_TRACKER
        target=PrefixedOptional(GLOBAL_POS), tracked=BOOL
    ),
    "minecraft:firework_explosion": _FIREWORK_EXPLOSION,  # FIREWORK_EXPLOSION
    "minecraft:fireworks": Schema(  # FIREWORKS
        flight_duration=VAR_INT,
        explosions=PrefixedArray(_FIREWORK_EXPLOSION, max_length=256),
    ),
    "minecraft:profile": RESOLVABLE_PROFILE,  # PROFILE
    "minecraft:note_block_sound": IDENTIFIER,  # NOTE_BLOCK_SOUND
    "minecraft:banner_patterns": PrefixedArray(  # BANNER_PATTERNS
        Schema(pattern=_BANNER_PATTERN, color=ENUM)
    ),
    "minecraft:base_color": ENUM,  # BASE_COLOR
    "minecraft:block_state": PrefixedArray(  # BLOCK_STATE
        Schema(name=String(32767), value=String(32767))
    ),
    "minecraft:bees": PrefixedArray(  # BEES
        Schema(entity_data=_TYPED_DATA, ticks_in_hive=VAR_INT, min_ticks_in_hive=VAR_INT)
    ),
    "minecraft:lock": NBT_TAG,  # LOCK
    "minecraft:container_loot": NBT_TAG,  # CONTAINER_LOOT
    "minecraft:break_sound": SOUND_EVENT,  # BREAK_SOUND
    "minecraft:compostable": _RESOLVABLE_INT,  # COMPOSTABLE
    "minecraft:cooking_fuel": Schema(  # COOKING_FUEL
        burn_time=_RESOLVABLE_INT, speed_multiplier=_RESOLVABLE_FLOAT
    ),
    "minecraft:brewing_fuel": Schema(  # BREWING_FUEL
        uses=_RESOLVABLE_INT, speed_multiplier=_RESOLVABLE_FLOAT
    ),
    "minecraft:mob_visibility": Schema(  # MOB_VISIBILITY
        targeting_entity_types=HOLDER_SET, visibility=FLOAT
    ),
    "minecraft:villager/variant": REGISTRY_ID,  # VILLAGER_VARIANT
    "minecraft:wolf/variant": REGISTRY_ID,  # WOLF_VARIANT
    "minecraft:wolf/sound_variant": REGISTRY_ID,  # WOLF_SOUND_VARIANT
    "minecraft:wolf/collar": ENUM,  # WOLF_COLLAR
    "minecraft:fox/variant": ENUM,  # FOX_VARIANT
    "minecraft:salmon/size": ENUM,  # SALMON_SIZE
    "minecraft:parrot/variant": ENUM,  # PARROT_VARIANT
    "minecraft:tropical_fish/pattern": ENUM,  # TROPICAL_FISH_PATTERN
    "minecraft:tropical_fish/base_color": ENUM,  # TROPICAL_FISH_BASE_COLOR
    "minecraft:tropical_fish/pattern_color": ENUM,  # TROPICAL_FISH_PATTERN_COLOR
    "minecraft:mooshroom/variant": ENUM,  # MOOSHROOM_VARIANT
    "minecraft:rabbit/variant": ENUM,  # RABBIT_VARIANT
    "minecraft:pig/variant": REGISTRY_ID,  # PIG_VARIANT
    "minecraft:pig/sound_variant": REGISTRY_ID,  # PIG_SOUND_VARIANT
    "minecraft:cow/variant": REGISTRY_ID,  # COW_VARIANT
    "minecraft:cow/sound_variant": REGISTRY_ID,  # COW_SOUND_VARIANT
    "minecraft:chicken/variant": REGISTRY_ID,  # CHICKEN_VARIANT
    "minecraft:chicken/sound_variant": REGISTRY_ID,  # CHICKEN_SOUND_VARIANT
    "minecraft:zombie_nautilus/variant": REGISTRY_ID,  # ZOMBIE_NAUTILUS_VARIANT
    "minecraft:frog/variant": REGISTRY_ID,  # FROG_VARIANT
    "minecraft:horse/variant": ENUM,  # HORSE_VARIANT
    "minecraft:painting/variant": PAINTING_VARIANT,  # PAINTING_VARIANT
    "minecraft:llama/variant": ENUM,  # LLAMA_VARIANT
    "minecraft:axolotl/variant": ENUM,  # AXOLOTL_VARIANT
    "minecraft:cat/variant": REGISTRY_ID,  # CAT_VARIANT
    "minecraft:cat/sound_variant": REGISTRY_ID,  # CAT_SOUND_VARIANT
    "minecraft:cat/collar": ENUM,  # CAT_COLLAR
    "minecraft:sheep/color": ENUM,  # SHEEP_COLOR
    "minecraft:shulker/color": ENUM,  # SHULKER_COLOR
    "minecraft:provides_pottery_pattern": REGISTRY_ID,  # PROVIDES_POTTERY_PATTERN
    "minecraft:sign_text_front": _SIGN_TEXT,  # SIGN_TEXT_FRONT
    "minecraft:sign_text_back": _SIGN_TEXT,  # SIGN_TEXT_BACK
    "minecraft:waxed": UNIT,  # WAXED
    "minecraft:cushion/color": ENUM,  # CUSHION_COLOR
}

TABLE = ComponentTable(registry_names(TARGET.minecraft_version, _REGISTRY), _LAYOUTS)
"""The Target's data components and the wire type of each one's value."""

PATCH = Patch(TABLE)
"""The patch of data components a stack carries (`DataComponentPatch.STREAM_CODEC`)."""
