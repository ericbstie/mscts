"""Short titles for the test case reference and Report (#12)."""

from collections.abc import Mapping
from types import MappingProxyType

TITLES: Mapping[str, str] = MappingProxyType(
    {
        "add_entity": "Entity appearing",
        "add_entity.entity_uuid": "Entity UUID",
        "block_entity_data": "Block entity data",
        "block_update": "Single block change",
        "block_update.block_state": "Single block change state",
        "block_update.pos.x": "Single block change x",
        "block_update.pos.y": "Single block change y",
        "block_update.pos.z": "Single block change z",
        "change_difficulty": "Difficulty",
        "chunk_batch_finished": "End of a chunk batch",
        "chunk_batch_finished.batch_size": "Chunks in a batch",
        "chunk_batch_start": "Start of a chunk batch",
        "commands.nodes[]": "Command node",
        "commands.nodes[].children[]": "Command node child",
        "commands.nodes[].flags": "Command node flags",
        "commands.nodes[].name": "Command node name",
        "commands.nodes[].parser": "Command argument type",
        "commands.nodes[].properties": "Command argument properties",
        "commands.nodes[].properties.behavior": "Command string argument behaviour",
        "commands.nodes[].properties.flags": "Command argument flags",
        "commands.nodes[].properties.max": "Command argument maximum",
        "commands.nodes[].properties.min": "Command argument minimum",
        "commands.nodes[].redirect_node": "Command redirect",
        "commands.nodes[].suggestions_type": "Command suggestions source",
        "commands.root_index": "Command tree root",
        "configuration:custom_payload.channel": "Configuration plugin message channel",
        "configuration:custom_payload.data": "Configuration plugin message data",
        "configuration:update_tags.tagged_registries[].registry": "Tagged registry name",
        "configuration:update_tags.tagged_registries[].tags[]": "Tag",
        "configuration:update_tags.tagged_registries[].tags[].entries[]": "Tag member",
        "configuration:update_tags.tagged_registries[].tags[].tag_name": "Tag name",
        "container_close": "Window closing",
        "container_close.window_id": "Window to close",
        "container_set_content": "Inventory contents",
        "container_set_content.carried_item": "Item on the cursor",
        "container_set_content.carried_item.components.added": "Cursor item components",
        "container_set_content.carried_item.components.added[]": "Cursor item component",
        "container_set_content.carried_item.components.added[].type": "Cursor item component name",
        "container_set_content.carried_item.components.added[].value": "Cursor item component data",
        "container_set_content.carried_item.components.removed": "Cursor item removed components",
        "container_set_content.carried_item.components.removed[]": "Cursor item removed component",
        "container_set_content.carried_item.count": "Cursor item count",
        "container_set_content.carried_item.item": "Cursor item type",
        "container_set_content.slot_data": "Inventory slot items",
        "container_set_content.slot_data[]": "Inventory slot item",
        "container_set_content.slot_data[].components.added": "Slot item components",
        "container_set_content.slot_data[].components.added[]": "Slot item component",
        "container_set_content.slot_data[].components.added[].type": "Slot item component name",
        "container_set_content.slot_data[].components.added[].value": "Slot item component data",
        "container_set_content.slot_data[].components.removed": "Slot item removed components",
        "container_set_content.slot_data[].components.removed[]": "Slot item removed component",
        "container_set_content.slot_data[].count": "Slot item count",
        "container_set_content.slot_data[].item": "Slot item type",
        "container_set_content.state_id": "Inventory state number",
        "container_set_content.window_id": "Inventory window",
        "container_set_data": "Window property",
        "container_set_data.property": "Window property number",
        "container_set_data.value": "Window property value",
        "container_set_data.window_id": "Window of a property",
        "container_set_slot": "Inventory slot change",
        "container_set_slot.slot": "Inventory slot number",
        "container_set_slot.slot_data": "Item in a changed slot",
        "container_set_slot.slot_data.components.added": "Changed slot item components",
        "container_set_slot.slot_data.components.added[]": "Changed slot item component",
        "container_set_slot.slot_data.components.added[].type": "Changed slot item component name",
        "container_set_slot.slot_data.components.added[].value": "Changed slot item component data",
        "container_set_slot.slot_data.components.removed": "Changed slot item removed components",
        "container_set_slot.slot_data.components.removed[]": "Changed slot item removed component",
        "container_set_slot.slot_data.count": "Changed slot item count",
        "container_set_slot.slot_data.item": "Changed slot item type",
        "container_set_slot.state_id": "Inventory slot change state number",
        "container_set_slot.window_id": "Window of a slot change",
        "disguised_chat": "Disguised chat message",
        "entity_event.entity_id": "Entity receiving an event",
        "entity_event.event_id": "Entity event type",
        "forget_level_chunk": "Chunk unloaded",
        "game_event": "Game event",
        "game_event.event": "Game event type",
        "game_event.value": "Game event value",
        "initialize_border": "World border",
        "level_chunk_with_light": "Chunk",
        "level_chunk_with_light.chunk_x": "Chunk x",
        "level_chunk_with_light.chunk_z": "Chunk z",
        "level_chunk_with_light.heightmaps[].data[]": "Chunk heightmap data",
        "level_chunk_with_light.heightmaps[].type": "Chunk heightmap type",
        "level_chunk_with_light.light.block[]": "Block light in a chunk section",
        "level_chunk_with_light.light.sky[]": "Sky light in a chunk section",
        "level_chunk_with_light.sections[].biomes": "Biomes in a chunk section",
        "level_chunk_with_light.sections[].block_count": "Non-air blocks in a chunk section",
        "level_chunk_with_light.sections[].block_states": "Blocks in a chunk section",
        "level_chunk_with_light.sections[].fluid_count": "Fluid blocks in a chunk section",
        "level_event": "World event",
        "level_event.event_id": "World event type",
        "light_update": "Light update",
        "light_update.data.block[]": "Block light update",
        "light_update.data.sky[]": "Sky light update",
        "login.death_location": "Last death location",
        "login.dimension_name": "Joined dimension",
        "login.dimension_names[]": "Available dimension name",
        "login.dimension_type": "Joined dimension type",
        "login.do_limited_crafting": "Limited crafting",
        "login.enable_respawn_screen": "Death screen enabled",
        "login.enforces_secure_chat": "Secure chat required",
        "login.entity_id": "Player entity at join",
        "login.game_mode": "Game mode at join",
        "login.hashed_seed": "Biome seed",
        "login.is_debug": "Debug world flag",
        "login.is_flat": "Flat world flag",
        "login.is_hardcore": "Hardcore world flag",
        "login.max_players": "Player limit at join",
        "login.online_mode": "Online mode at join",
        "login.portal_cooldown": "Portal cooldown at join",
        "login.previous_game_mode": "Previous game mode",
        "login.reduced_debug_info": "Reduced debug information",
        "login.sea_level": "Sea level",
        "login.simulation_distance": "Simulation distance at join",
        "login.view_distance": "View distance at join",
        "login_compression.threshold": "Compression threshold",
        "login_finished.profile.username": "Player name at login",
        "login_finished.profile.uuid": "Player UUID at login",
        "mount_screen_open": "Mount inventory opening",
        "mount_screen_open.entity_id": "Mount whose inventory opens",
        "mount_screen_open.inventory_columns": "Mount chest columns",
        "mount_screen_open.window_id": "Mount inventory window",
        "open_screen": "Window opening",
        "open_screen.window_id": "Opened window number",
        "open_screen.window_title": "Opened window title",
        "open_screen.window_type": "Opened window type",
        "play:disconnect": "Kick",
        "play:disconnect.reason": "Kick reason",
        "play:post_effects": "Screen effects",
        "player_abilities": "Player abilities",
        "player_chat": "Chat message from a player",
        "player_chat.chat_type.reference": "Chat message type",
        "player_chat.filter.bits": "Filtered characters in a chat message",
        "player_chat.filter.type": "Chat message filtering",
        "player_chat.global_index": "Chat message count",
        "player_chat.index": "Sender's chat message count",
        "player_chat.message": "Chat message text from a player",
        "player_chat.previous_messages": "Earlier chat messages a signature covers",
        "player_chat.salt": "Chat message salt",
        "player_chat.sender": "Chat message sender",
        "player_chat.sender_name": "Chat message sender name",
        "player_chat.signature": "Chat message signature",
        "player_chat.target_name": "Chat message recipient name",
        "player_chat.unsigned_content": "Chat message text the server changed",
        "player_info_remove": "Player list removal",
        "player_info_remove.uuids[]": "Player leaving the list",
        "player_info_update": "Player list update",
        "player_info_update.actions[]": "Player list update part",
        "player_info_update.players[].chat_session": "Player chat session",
        "player_info_update.players[].display_name": "Player list display name",
        "player_info_update.players[].game_mode": "Player game mode in the list",
        "player_info_update.players[].hat_visible": "Player hat in the list",
        "player_info_update.players[].listed": "Player shown in the list",
        "player_info_update.players[].name": "Player name in the list",
        "player_info_update.players[].ping": "Player connection delay in the list",
        "player_info_update.players[].priority": "Player list order",
        "player_info_update.players[].uuid": "Player UUID in the list",
        "player_position": "Player position",
        "player_position.flags": "Relative player position parts",
        "player_position.pitch": "Player pitch",
        "player_position.teleport_id": "Teleport number",
        "player_position.velocity_x": "Player velocity x",
        "player_position.velocity_y": "Player velocity y",
        "player_position.velocity_z": "Player velocity z",
        "player_position.x": "Player position x",
        "player_position.y": "Player position y",
        "player_position.yaw": "Player yaw",
        "player_position.z": "Player position z",
        "recipe_book_add": "Recipes in the recipe book",
        "recipe_book_settings": "Recipe book settings",
        "registry_data.entries[]": "Registry entry",
        "registry_data.entries[].data": "Registry entry data",
        "registry_data.entries[].entry_id": "Registry entry name",
        "registry_data.registry_id": "Registry name",
        "section_blocks_update": "Block changes in a section",
        "section_blocks_update.blocks[]": "Block change in a section",
        "section_blocks_update.blocks[].state": "Block state in a section change",
        "section_blocks_update.blocks[].x": "Block x in a section change",
        "section_blocks_update.blocks[].y": "Block y in a section change",
        "section_blocks_update.blocks[].z": "Block z in a section change",
        "section_blocks_update.section.y": "Section height",
        "select_known_packs.known_packs[].id": "Known pack ID",
        "select_known_packs.known_packs[].namespace": "Known pack namespace",
        "select_known_packs.known_packs[].version": "Known pack version",
        "server_data": "Server description in play",
        "set_chunk_cache_center": "View centre",
        "set_chunk_cache_center.chunk_x": "View centre chunk x",
        "set_chunk_cache_center.chunk_z": "View centre chunk z",
        "set_cursor_item": "Cursor item change",
        "set_cursor_item.slot_data": "New cursor item",
        "set_cursor_item.slot_data.components.added": "New cursor item components",
        "set_cursor_item.slot_data.components.added[]": "New cursor item component",
        "set_cursor_item.slot_data.components.added[].type": "New cursor item component name",
        "set_cursor_item.slot_data.components.added[].value": "New cursor item component data",
        "set_cursor_item.slot_data.components.removed": "New cursor item removed components",
        "set_cursor_item.slot_data.components.removed[]": "New cursor item removed component",
        "set_cursor_item.slot_data.count": "New cursor item count",
        "set_cursor_item.slot_data.item": "New cursor item type",
        "set_default_spawn_position": "World spawn point",
        "remove_entities": "Entities disappearing",
        "remove_entities.entity_ids[]": "Entity disappearing",
        "take_item_entity": "Item picked up",
        "take_item_entity.collected_entity_id": "Item entity picked up",
        "take_item_entity.collector_entity_id": "Entity picking an item up",
        "take_item_entity.pickup_item_count": "Number of items picked up",
        "set_entity_data": "Entity data",
        "set_entity_data.entity_id": "Entity receiving data",
        "set_entity_data.entries[].index": "Entity data field",
        "set_entity_data.entries[].serializer": "Entity data type",
        "set_entity_data.entries[].value": "Entity data value",
        "set_entity_motion": "Entity velocity",
        "set_experience": "Experience",
        "set_experience.experience_bar": "Experience bar progress",
        "set_experience.level": "Experience level",
        "set_experience.total_experience": "Total experience points",
        "set_health": "Health and food",
        "set_health.food": "Food level",
        "set_health.health": "Health",
        "set_health.saturation": "Food saturation",
        "set_held_slot": "Selected hotbar slot",
        "set_held_slot.slot": "Selected hotbar slot number",
        "set_player_inventory": "Player inventory slot change",
        "set_player_inventory.slot": "Player inventory slot number",
        "set_player_inventory.slot_data": "Item in a player inventory slot",
        "set_player_inventory.slot_data.components.added": "Inventory item components",
        "set_player_inventory.slot_data.components.added[]": "Inventory item component",
        "set_player_inventory.slot_data.components.added[].type": "Inventory item component name",
        "set_player_inventory.slot_data.components.added[].value": "Inventory item component data",
        "set_player_inventory.slot_data.components.removed": "Inventory item removed components",
        "set_player_inventory.slot_data.components.removed[]": "Inventory item removed component",
        "set_player_inventory.slot_data.count": "Inventory item count",
        "set_player_inventory.slot_data.item": "Inventory item type",
        "status:pong_response.timestamp": "Server list ping response",
        "status_response.description": "Server list description",
        "status_response.description.text": "Server list description text",
        "status_response.enforceSecureChat": "Unused secure chat flag",
        "status_response.favicon": "Server list icon",
        "status_response.players.max": "Player limit",
        "status_response.players.online": "Online players",
        "status_response.players.sample": "Server list player sample",
        "status_response.players.sample[].id": "Server list player UUID",
        "status_response.players.sample[].name": "Server list player name",
        "status_response.version.name": "Server version name",
        "status_response.version.protocol": "Protocol version",
        "system_chat": "Chat message from the server",
        "system_chat.content": "Chat message text",
        "system_chat.overlay": "Whether a message shows above the hotbar",
        "ticking_state": "Tick rate and freeze state",
        "ticking_step": "Tick steps",
        "update_advancements": "Advancements",
        "update_advancements.advancements[].display": "Advancement display",
        "update_advancements.advancements[].id": "Advancement id",
        "update_advancements.advancements[].parent_id": "Advancement parent",
        "update_advancements.advancements[].requirements[][]": "Advancement requirements",
        "update_advancements.advancements[].sends_telemetry_data": "Advancement telemetry flag",
        "update_advancements.advancements[].x": "Advancement x position",
        "update_advancements.advancements[].y": "Advancement y position",
        "update_advancements.progress[].criteria[].criterion": "Advancement progress criterion",
        "update_advancements.progress[].id": "Advancement receiving progress",
        "update_advancements.reset": "Advancement reset",
        "update_advancements.show_advancements": "Advancement notifications enabled",
        "update_attributes": "Entity attributes",
        "update_attributes.attributes[].attribute": "Entity attribute name",
        "update_attributes.attributes[].base": "Entity attribute base value",
        "update_attributes.entity_id": "Entity receiving attributes",
        "update_enabled_features.feature_flags[]": "Enabled feature flag",
        "update_recipes": "Recipe data",
        "update_recipes.property_sets[].items[]": "Recipe input item",
        "update_recipes.property_sets[].property_set_id": "Recipe property set name",
        "update_recipes.stonecutter_recipes[].ingredients.ids[]": "Stonecutter input item",
        "update_recipes.stonecutter_recipes[].slot_display.type": "Stonecutter result display type",
        "update_recipes.stonecutter_recipes[].slot_display.value.count": "Stonecutter result count",
        "update_recipes.stonecutter_recipes[].slot_display.value.item": "Stonecutter result item",
        # Blocks a player breaks and places (#36).
        "add_entity.data": "Entity spawn data",
        "add_entity.entity_id": "Entity number",
        "add_entity.head_yaw": "Entity head direction",
        "add_entity.pitch": "Entity up-down angle",
        "add_entity.type": "Entity type",
        "add_entity.velocity.scale": "Entity motion scale",
        "add_entity.velocity.y": "Entity upward speed",
        "block_changed_ack": "Block action acknowledgement",
        "block_changed_ack.sequence": "Acknowledged action number",
        "level_event.data": "World event data",
        "level_event.global_event": "World event heard everywhere",
        "level_event.pos.x": "World event x",
        "level_event.pos.y": "World event y",
        "level_event.pos.z": "World event z",
        "set_entity_data.entries[].value.count": "Item count in entity data",
        "set_entity_data.entries[].value.item": "Item type in entity data",
        # melee (#53)
        "damage_event": "Damage taken",
        "damage_event.entity_id": "Entity taking damage",
        "damage_event.source_type": "Damage type",
        "damage_event.source_cause_id": "Entity that caused the damage",
        "damage_event.source_direct_id": "Entity that dealt the damage",
        "damage_event.source_position": "Damage source position",
        "set_entity_motion.entity_id": "Entity receiving a velocity",
        "set_entity_motion.velocity.scale": "Velocity scale",
        "set_entity_motion.velocity.x": "Velocity x",
        "set_entity_motion.velocity.y": "Velocity y",
        "set_entity_motion.velocity.z": "Velocity z",
        "hurt_animation": "Hurt animation",
        "hurt_animation.entity_id": "Entity playing the hurt animation",
        "hurt_animation.yaw": "Hurt animation direction",
        "sound": "Sound",
        "sound.sound.reference": "Sound to play",
        "sound.category": "Sound category",
        "sound.x": "Sound x",
        "sound.y": "Sound y",
        "sound.z": "Sound z",
        "sound.volume": "Sound volume",
        # critical (#53)
        "animate": "Entity animation",
        "animate.entity_id": "Entity playing an animation",
        "animate.action": "Animation type",
        "level_particles": "Particles",
        "level_particles.particle.type": "Particle type",
        "level_particles.x": "Particles x",
        "level_particles.y": "Particles y",
        "level_particles.z": "Particles z",
        "level_particles.count": "Particle count",
        # player (#56)
        "player_combat_kill": "Death",
        "player_combat_kill.message": "Death message",
        "player_combat_kill.player_id": "Player that died",
        "respawn": "Respawn",
        "respawn.data_kept": "Respawn data kept",
        "respawn.game_mode": "Respawn game mode",
        # game modes (#59)
        "update_attributes.attributes[].modifiers": "Entity attribute modifiers",
        "update_attributes.attributes[].modifiers[].amount": "Attribute modifier amount",
        "update_attributes.attributes[].modifiers[].id": "Attribute modifier name",
        "update_attributes.attributes[].modifiers[].operation": "Attribute modifier operation",
        "waypoint": "Locator bar change",
        # death (#59)
        "add_entity.x": "Entity x",
        "add_entity.y": "Entity y",
        "add_entity.z": "Entity z",
        "set_entity_data.entries[].value.components.added": "Item components added",
        "set_entity_data.entries[].value.components.removed": "Item components removed",
        # respawn (#59)
        "set_entity_data.entries[]": "Entity data entry",
        "respawn.death_location.death_dimension_name": "Respawn death dimension",
        "respawn.death_location.death_location.x": "Respawn death location x",
        "respawn.death_location.death_location.y": "Respawn death location y",
        "respawn.death_location.death_location.z": "Respawn death location z",
        "respawn.dimension_name": "Respawn dimension",
        "respawn.dimension_type": "Respawn dimension type",
        "respawn.hashed_seed": "Respawn biome seed",
        "respawn.is_debug": "Respawn debug world flag",
        "respawn.is_flat": "Respawn flat world flag",
        "respawn.portal_cooldown": "Portal cooldown at respawn",
        "respawn.previous_game_mode": "Respawn previous game mode",
        "respawn.sea_level": "Respawn sea level",
        # player hunger (#57)
        "update_mob_effect": "Effect given",
        "update_mob_effect.entity_id": "Entity given the effect",
        "update_mob_effect.effect": "Effect type",
        "update_mob_effect.amplifier": "Effect amplifier",
        "update_mob_effect.duration": "Effect duration",
        "update_mob_effect.flags": "Effect display flags",
        "remove_mob_effect": "Effect ended",
        "remove_mob_effect.entity_id": "Entity losing the effect",
        "remove_mob_effect.effect": "Effect that ended",
        "place_ghost_recipe": "Ghost recipe",
        "place_ghost_recipe.window_id": "Ghost recipe window",
        "recipe_book_add.entries": "Recipe book entries",
        "recipe_book_add.entries[]": "Recipe book entry",
        "recipe_book_add.entries[].contents.id": "Recipe display id",
        "recipe_book_add.entries[].contents.group": "Recipe book group",
        "recipe_book_add.entries[].contents.category": "Recipe book category",
        "recipe_book_add.entries[].contents.crafting_requirements": "Recipe requirements",
        "recipe_book_add.entries[].contents.crafting_requirements[].tag": "Recipe requirement tag",
        "recipe_book_add.entries[].contents.crafting_requirements[].ids": (
            "Recipe requirement items"
        ),
        "recipe_book_add.entries[].contents.crafting_requirements[].ids[]": (
            "Recipe requirement item"
        ),
        "recipe_book_add.entries[].flags": "Recipe book entry flags",
        "recipe_book_add.replace": "Recipe book replaced",
        "recipe_book_remove": "Recipes taken from the recipe book",
        "recipe_book_remove.recipes": "Display ids removed",
        "recipe_book_remove.recipes[]": "Display id removed",
        "place_ghost_recipe.recipe_display.type": "Ghost recipe type",
        "place_ghost_recipe.recipe_display.value.width": "Ghost recipe width",
        "place_ghost_recipe.recipe_display.value.height": "Ghost recipe height",
        "place_ghost_recipe.recipe_display.value.ingredients": "Ghost recipe ingredients",
        "place_ghost_recipe.recipe_display.value.duration": "Ghost recipe cooking time",
        "place_ghost_recipe.recipe_display.value.experience": "Ghost recipe experience",
        "place_ghost_recipe.recipe_display.value.ingredients[]": "Ghost recipe ingredient",
        "place_ghost_recipe.recipe_display.value.ingredients[].type": (
            "Ghost recipe ingredient display type"
        ),
        "place_ghost_recipe.recipe_display.value.ingredients[].value": (
            "Ghost recipe ingredient display data"
        ),
        "place_ghost_recipe.recipe_display.value.ingredients[].value.tag": (
            "Ghost recipe ingredient tag"
        ),
        "place_ghost_recipe.recipe_display.value.ingredients[].value.ids": (
            "Ghost recipe ingredient items"
        ),
        "place_ghost_recipe.recipe_display.value.ingredients[].value.ids[]": (
            "Ghost recipe ingredient choice"
        ),
        "place_ghost_recipe.recipe_display.value.ingredient": "Ghost recipe furnace input",
        "place_ghost_recipe.recipe_display.value.ingredient.type": (
            "Ghost recipe furnace input display type"
        ),
        "place_ghost_recipe.recipe_display.value.ingredient.value": (
            "Ghost recipe furnace input display data"
        ),
        "place_ghost_recipe.recipe_display.value.fuel": "Ghost recipe fuel",
        "place_ghost_recipe.recipe_display.value.fuel.type": "Ghost recipe fuel display type",
        "place_ghost_recipe.recipe_display.value.fuel.value": "Ghost recipe fuel display data",
        "place_ghost_recipe.recipe_display.value.input": "Ghost recipe stonecutter input",
        "place_ghost_recipe.recipe_display.value.input.type": (
            "Ghost recipe stonecutter input display type"
        ),
        "place_ghost_recipe.recipe_display.value.input.value": (
            "Ghost recipe stonecutter input display data"
        ),
        "place_ghost_recipe.recipe_display.value.template": "Ghost recipe smithing template",
        "place_ghost_recipe.recipe_display.value.template.type": (
            "Ghost recipe smithing template display type"
        ),
        "place_ghost_recipe.recipe_display.value.template.value": (
            "Ghost recipe smithing template display data"
        ),
        "place_ghost_recipe.recipe_display.value.base": "Ghost recipe smithing base",
        "place_ghost_recipe.recipe_display.value.base.type": (
            "Ghost recipe smithing base display type"
        ),
        "place_ghost_recipe.recipe_display.value.base.value": (
            "Ghost recipe smithing base display data"
        ),
        "place_ghost_recipe.recipe_display.value.addition": "Ghost recipe smithing addition",
        "place_ghost_recipe.recipe_display.value.addition.type": (
            "Ghost recipe smithing addition display type"
        ),
        "place_ghost_recipe.recipe_display.value.addition.value": (
            "Ghost recipe smithing addition display data"
        ),
        "place_ghost_recipe.recipe_display.value.result.type": "Ghost recipe result display type",
        "place_ghost_recipe.recipe_display.value.result.value": "Ghost recipe result display data",
        "place_ghost_recipe.recipe_display.value.result.value.item": "Ghost recipe result item",
        "place_ghost_recipe.recipe_display.value.result.value.count": "Ghost recipe result count",
        "place_ghost_recipe.recipe_display.value.result.value.components.added": (
            "Ghost recipe result components"
        ),
        "place_ghost_recipe.recipe_display.value.result.value.components.removed": (
            "Ghost recipe result removed components"
        ),
        "place_ghost_recipe.recipe_display.value.crafting_station.type": (
            "Ghost recipe crafting station display type"
        ),
        "place_ghost_recipe.recipe_display.value.crafting_station.value": (
            "Ghost recipe crafting station display data"
        ),
        "recipe_book_add.entries[].contents.display.type": "Recipe book recipe type",
        "recipe_book_add.entries[].contents.display.value.width": "Recipe book recipe width",
        "recipe_book_add.entries[].contents.display.value.height": "Recipe book recipe height",
        "recipe_book_add.entries[].contents.display.value.ingredients": "Recipe book ingredients",
        "recipe_book_add.entries[].contents.display.value.duration": "Recipe book cooking time",
        "recipe_book_add.entries[].contents.display.value.experience": "Recipe book experience",
        "recipe_book_add.entries[].contents.display.value.ingredients[]": "Recipe book ingredient",
        "recipe_book_add.entries[].contents.display.value.ingredients[].type": (
            "Recipe book ingredient display type"
        ),
        "recipe_book_add.entries[].contents.display.value.ingredients[].value": (
            "Recipe book ingredient display data"
        ),
        "recipe_book_add.entries[].contents.display.value.ingredients[].value.tag": (
            "Recipe book ingredient tag"
        ),
        "recipe_book_add.entries[].contents.display.value.ingredients[].value.ids": (
            "Recipe book ingredient items"
        ),
        "recipe_book_add.entries[].contents.display.value.ingredients[].value.ids[]": (
            "Recipe book ingredient choice"
        ),
        "recipe_book_add.entries[].contents.display.value.ingredient": "Recipe book furnace input",
        "recipe_book_add.entries[].contents.display.value.ingredient.type": (
            "Recipe book furnace input display type"
        ),
        "recipe_book_add.entries[].contents.display.value.ingredient.value": (
            "Recipe book furnace input display data"
        ),
        "recipe_book_add.entries[].contents.display.value.ingredient.value.tag": (
            "Recipe book furnace input tag"
        ),
        "recipe_book_add.entries[].contents.display.value.ingredient.value.ids[]": (
            "Recipe book furnace input choice"
        ),
        "recipe_book_add.entries[].contents.display.value.fuel": "Recipe book fuel",
        "recipe_book_add.entries[].contents.display.value.fuel.type": (
            "Recipe book fuel display type"
        ),
        "recipe_book_add.entries[].contents.display.value.fuel.value": (
            "Recipe book fuel display data"
        ),
        "recipe_book_add.entries[].contents.display.value.input": "Recipe book stonecutter input",
        "recipe_book_add.entries[].contents.display.value.input.type": (
            "Recipe book stonecutter input display type"
        ),
        "recipe_book_add.entries[].contents.display.value.input.value": (
            "Recipe book stonecutter input display data"
        ),
        "recipe_book_add.entries[].contents.display.value.input.value.ids[]": (
            "Recipe book stonecutter input choice"
        ),
        "recipe_book_add.entries[].contents.display.value.template": (
            "Recipe book smithing template"
        ),
        "recipe_book_add.entries[].contents.display.value.template.type": (
            "Recipe book smithing template display type"
        ),
        "recipe_book_add.entries[].contents.display.value.template.value": (
            "Recipe book smithing template display data"
        ),
        "recipe_book_add.entries[].contents.display.value.template.value.ids[]": (
            "Recipe book smithing template choice"
        ),
        "recipe_book_add.entries[].contents.display.value.base": "Recipe book smithing base",
        "recipe_book_add.entries[].contents.display.value.base.type": (
            "Recipe book smithing base display type"
        ),
        "recipe_book_add.entries[].contents.display.value.base.value": (
            "Recipe book smithing base display data"
        ),
        "recipe_book_add.entries[].contents.display.value.base.value.tag": (
            "Recipe book smithing base tag"
        ),
        "recipe_book_add.entries[].contents.display.value.base.value.ids[]": (
            "Recipe book smithing base choice"
        ),
        "recipe_book_add.entries[].contents.display.value.addition": (
            "Recipe book smithing addition"
        ),
        "recipe_book_add.entries[].contents.display.value.addition.type": (
            "Recipe book smithing addition display type"
        ),
        "recipe_book_add.entries[].contents.display.value.addition.value": (
            "Recipe book smithing addition display data"
        ),
        "recipe_book_add.entries[].contents.display.value.addition.value.tag": (
            "Recipe book smithing addition tag"
        ),
        "recipe_book_add.entries[].contents.display.value.result.type": (
            "Recipe book result display type"
        ),
        "recipe_book_add.entries[].contents.display.value.result.value": (
            "Recipe book result display data"
        ),
        "recipe_book_add.entries[].contents.display.value.result.value.item": (
            "Recipe book result item"
        ),
        "recipe_book_add.entries[].contents.display.value.result.value.count": (
            "Recipe book result count"
        ),
        "recipe_book_add.entries[].contents.display.value.result.value.components.added": (
            "Recipe book result components"
        ),
        "recipe_book_add.entries[].contents.display.value.result.value.components.removed": (
            "Recipe book result removed components"
        ),
        "recipe_book_add.entries[].contents.display.value.crafting_station.type": (
            "Recipe book crafting station display type"
        ),
        "recipe_book_add.entries[].contents.display.value.crafting_station.value": (
            "Recipe book crafting station display data"
        ),
        # entities (#43)
        "add_entity.velocity.x": "Entity east-west speed",
        "add_entity.velocity.z": "Entity north-south speed",
        "add_entity.yaw": "Entity facing",
        "bundle_delimiter": "Packet bundle edge",
        "rotate_head": "Entity head turning",
        "set_entity_data.entries[].value.level": "Villager level",
        "set_entity_data.entries[].value.profession": "Villager profession",
        "set_entity_data.entries[].value.type": "Villager type",
        "set_equipment.entity_id": "Entity receiving equipment",
        "set_equipment.equipment[].item.count": "Equipped item count",
        "set_equipment.equipment[].item.item": "Equipped item type",
        "set_equipment.equipment[].slot": "Equipment slot",
    }
)
"""Known test case name → the short title checked against the docs reference."""
