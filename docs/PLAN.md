# mscts plan

What we are building, the contracts between its parts, and the order it
gets built in. Vocabulary is defined in [`CONTEXT.md`](../CONTEXT.md).
Decisions are recorded in [`docs/adr/`](adr/). Current state and the next
step are in [`PROGRESS.md`](PROGRESS.md).

## Goals

Each goal is a check we can run, not an aspiration.

| # | Goal | Done when |
| --- | --- | --- |
| G1 | **Server-agnostic** | Adding a Candidate means adding one Adapter module and its unit tests. No Group changes. |
| G2 | **Trustworthy** | Every Group's Self-check is `match` in 20 out of 20 repeated runs. |
| G3 | **Actionable** | Every Divergence names the Group, the Bot, the packet, the field path, and both values, and it reproduces on re-run. |
| G4 | **Timed** | Every Group reports Measurements for the Reference and the Candidate over N repetitions (median, p95), plus Instance startup time. |
| G6 | **Smooth DX** (ADR-0008) | Every command is idempotent and honest about what it did; every error names its fix. A server developer can write an Adapter from the authoring guide and prove it with `mscts adapter check` without reading mscts internals. |
| G5 | **Fast loop** | `mise run check` takes under 10 s. `mise run test:reference` takes under 90 s on a warm cache. It runs no Group's Self-check: those are the `selfcheck` tier (#84), which has a budget of its own, below. |

G5 as measured on 2026-10-01 and 02 (4 CPUs, warm cache, one run at a time, with
`scripts/time_tier.py` or `mise run`). Runs differ by 20% on this machine, so each figure is
the range over the runs:

- `mise run test:reference`, without the status Groups' Self-check, took 210 s to 259 s in 5
  runs. Two of them were `mise run test:reference` twice in a row, both green (19 tests). The
  90 s is not met. The slowest tests were 50 to 58 s (the
  Observation window test that plays one Group 20 times), 40 to 46 s (item stacks) and 30 s
  (a keep-alive cycle).
- `mise run test:selfcheck` took 18 to 22 s for the two status Groups, and 24 to 31 s for a
  joining Group (the probe Group in `tests/support/probe.py`: it joins two Bots and sets a
  block). Every run starts with the two Reference boots, once for the tier: 13 to 17 s, plus
  about 2 s to stop them. After that a Group costs its runs: 0.02 to 0.1 s per run for a
  status Group, and 2.6 to 3.7 s per run for the joining Group. A Group that changes the
  ServerSpec launches two Instances of its own, which took 20 s.

Non-goals for now: Bedrock, online-mode auth and encryption, more than one
Target (ADR-0003), and server-side-only behaviour such as disk format
(ADR-0001).

## Architecture

```
            ┌───────────── Run ──────────────┐
Group ─────►│ GroupContext → Bot(s) ─────────┼──► Instance (Reference)  ─► Transcript R ─┐
            │   Control (Operator Bot)       │                                          ├─► Comparison ─► Verdict
            │   spans → Marks                ├──► Instance (Candidate)  ─► Transcript C ─┘        │
            └────────────────────────────────┘                                    Measurements ─► Report
install.require → Installation;  Adapter.prepare(ServerSpec) → LaunchPlan;  runner(LaunchPlan) → Instance
```

Package layout (`src/mscts/`). Each module is created only when the first
test needs it:

| Module | Owns |
| --- | --- |
| `target.py` | `Target`, `TARGET` (the pinned 26.3 / 777) |
| `cache.py` | `cache_dir()`: the download cache shared by every worktree and session |
| `install.py` | Installations: `installed`, `install_release`, `install_from`, `require` (ADR-0008) |
| `codec/wire.py` | primitive wire types: `Reader`, `Writer` |
| `codec/framing.py` | length-prefixed frames and the compression envelope |
| `codec/schema.py` | the schema mechanism: `WireType`, `Schema`, the field types |
| `codec/movement.py` | the movement field types of the entity packets: `MOVE_DELTA`, `POSITION_PATH` |
| `codec/entity_data.py` | entity metadata: the value types (optional block state and unsigned int, optional global pos; the painting variant and resolvable profile live in `codec/shapes.py`), the serializer table `SERIALIZERS` and the entries list `ENTITY_DATA` |
| `codec/particles.py` | `PARTICLE` (all 128 types of 26.3 and their options) and `POSITION_SOURCE` |
| `codec/equipment.py` | `EquipmentList`, `EQUIPMENT`, `SLOTS`: the slots of `set_equipment`, each with an item stack |
| `codec/shapes.py` | the wire shapes the data components and the entity metadata share: `UNIT`, `NBT_TAG`, `COMPOUND_TAG`, `TEXT_COMPONENT`, `REGISTRY_ID`, `ENUM`, `OrdinalEnum`, `SOUND_SOURCE`, `FixedArray`, `Deferred`, `registry_dispatch`, `Holder`, `Either`, `HOLDER_SET`, `SECTION_POSITION`, `VEC3`, `SOUND_EVENT`, `GLOBAL_POS`, `PAINTING_VARIANT`, `RESOLVABLE_PROFILE` |
| `codec/components.py` | the data component table: `ComponentTable`, `TABLE` (every name of `minecraft:data_component_type`, in id order, with its value's wire type), `ComponentType` and `COMPONENT_TYPE` (a type by name), `TypedComponent` and `TYPED_COMPONENT` (a type id and its value), `Patch` and `PATCH` (`DataComponentPatch`), `ITEM_STACK_TEMPLATE` |
| `codec/items.py` | `SLOT`, the item stack field, and `HASHED_SLOT`, the hashed stack a client sends (the wire type only) |
| `codec/schemas/<state>.py` | the Target's packet schemas, one module per State; play is a package, one module per mechanic |
| `codec/schemas/play/entities.py` | the entity packets' schemas: spawn, movement, metadata, attributes, events, removal |
| `codec/schemas/play/commands.py` | `chat_command`, `system_chat` and `commands`: the command tree as `CommandNode`s (every 26.3 parser, its id read through `registry_names`), and `root_literals(tree)`, the commands a player may run |
| `codec/schemas/play/blocks.py` | the block packets' schemas: `block_update`, `section_blocks_update` (its blocks decode to `{x, y, z, state}`), `block_entity_data`, `block_event`, `block_destruction` |
| `codec/schemas/play/chunks.py` | the chunk packets' schemas: `level_chunk_with_light` (its sections decoded, each block state and biome container a `PalettedContainer`: `{bits, palette, data}`), `light_update`, `forget_level_chunk`, `set_chunk_cache_center`, `set_chunk_cache_radius`, `chunks_biomes` |
| `codec/schemas/play/recipes.py` | `update_recipes`: the property sets (each item set a recipe takes as input) and the stonecutter's recipes, each an ingredient holder set and a slot display (all 11 types of `minecraft:slot_display`, read through `registry_names`) |
| `codec/schemas/play/advancements.py` | `update_advancements`: the advancements to add (each an id, a parent, a display whose background texture follows only if its flags say so, requirements, and x and y), the ids to remove, and each advancement's progress by criterion, with when it was obtained |
| `codec/schemas/play/world_events.py` | the world event packets' schemas: `level_event`, `sound` and `sound_entity` (a `SOUND_EVENT`, a `SOUND_SOURCE` category and a random seed), `level_particles`, `game_event`, `explode` (its block particles a weighted list) |
| `codec/schemas/play/inventory.py` | the container packets' schemas: `open_screen`, `mount_screen_open` (its entity id an Int), `container_set_content`, `container_set_slot`, `container_set_data`, `container_close` (both ways), `set_cursor_item`, `set_player_inventory`, and the client's `container_click` (its changed slots each a `HASHED_SLOT`, at most 128) |
| `codec/packets.py` | `Codec`: packet name ↔ id, field schemas, `encode` / `decode`, `entity_id_paths` |
| `codec/entity_ids.py` | where a value holds entity ids: `entity_id_paths` and `inner_types` walk a wire type, and a path's steps are keys, `EACH` and `Variant` |
| `codec/data/26.3/` | generated `packets.json`, `registry_names.json` (the data component, consume effect, command argument parser, entity type, item, menu and slot display names in protocol id order), `block_states.json` (how many block states there are) and `items.json` (each item's stack size but 64, and each equippable item's slot). Committed, regenerated and checked by `mise run regen:packets` |
| `codec/registry_names.py` | `registry_names(version, registry)`: the committed name lists, where a name's position is its protocol id; `block_state_count(version)`, the size of the global block state palette; `max_stack_sizes(version)` and `equipment_slots(version)`, the items' defaults by name |
| `net.py` | `Endpoint`, `Connection` (asyncio, state machine, records to a Transcript) |
| `bot.py` | `Bot`: `status`, `join`, `expect`, `send`, `command` |
| `entities.py` | `EntityTracker`: the entities a Bot's server told it about (`Entities`, `Entity`) |
| `inventory.py` | `InventoryTracker`: the player's inventory and the open container (`Inventory`, `Stack`) |
| `spec.py` | `ServerSpec` and its enums |
| `adapters/base.py` | `Adapter`, `Build`, `Release`, `Installation`, `LaunchPlan`; `Download(url, body)` and `Fetch` (how a URL is read) |
| `adapters/fetch.py` | `https_get` → `Download`: HTTPS on every hop, redirects followed |
| `adapters/<name>/` | one folder per server, registered by an import and one entry in `cli.py`'s `ADAPTERS`; its tests in `tests/adapters/<name>/`. `adapters/vanilla/`: `MANIFEST_URL` (Mojang's version manifest). `adapters/pumpkin/`: `NIGHTLY_URL` and `TAGS_URL` (the ref advertisement naming the `nightly` tag's commit), and its pinned first-run `pumpkin.toml` with `SOURCE.md` |
| `adapters/nbt.py` | a minimal, strict NBT writer (`encode`, `gzipped`) for the world saves an Adapter writes |
| `adapters/fixture_world.py` | what every Adapter writes into the Fixture world: its game rules (ADR-0013) |
| `runner.py` | `running(plan)` → `Instance`: launch, readiness (with ownership), stop, process stats; `free_endpoint` |
| `transcript.py` | `Transcript`, `Event`, `Mark`, JSON-lines (de)serialization |
| `timeline.py` | `timeline(transcript)` → text: each Event and Mark in time order, whether a window takes each received Packet, and each `award_stats` gap; the live tiers write it for a play that did not match (#162) |
| `group.py` | `@group`, `Group`, `GroupContext`, `GROUPS` (the registered Groups), `resolve`; `Control`, `OperatorBot`, `CommandMissing` |
| `groups/*.py` | the Groups themselves (`import mscts.groups` registers them) |
| `settle.py` | `until_no_player_online(endpoint, *, deadline_s)`: polls an Instance's status until no player is online, `PlayersStillOnline` if it never is. `run` waits with it before each Group |
| `run.py` | `run_group` → `Transcript`; `judge` → `Verdict`; `run`: Groups against a Reference and a Candidate `Server`, on Instances it launches; `selfcheck` |
| `compare.py` | `Mask`, canonicalization, `compare` → `Verdict`; `window_takes` |
| `measure.py` | `Measurement`, span extraction, stats |
| `report.py`, `cli.py` | `Report`, the `mscts` command |

## Interfaces

These are the contracts to implement. Changing one means updating this
section in the same commit, and writing an ADR if the change reverses a
decision. Signatures are Python 3.13. `@frozen` means
`@dataclass(frozen=True, slots=True)`.

### Target and codec

- `codec.framing`: `FrameDecoder`, `FrameError`, `MAX_DATA_LENGTH`, `encode_frame` — frame encoding
  and decoding.
- `codec.packets`: `PacketIds`, `Schemas` — Codec lookup table types.
- `codec.regen`: `DATA_DIR`, `REGISTRY_NAME_LISTS`, `RegenError`, `block_states_json`,
  `block_states_path`, `compare_or_write`, `data_generator_argv`, `fresh_data`, `items_json`,
  `items_path`, `packets_json_path`, `regenerate`, `registry_names_json`, `registry_names_path`,
  `run_data_generator` — Mojang data regeneration.
- `codec.schemas.login`: `GAME_PROFILE` — login packet schema.
- `codec.schemas.play`: `merge_submodules` — Play schema assembly.
- `codec.schemas.play.commands`: `PROPERTIES`, `commands_schema` — command argument schemas.
- `codec.schemas.play.chunks`: `PalettedContainer` (`read`, `write`, `values(container)`: the id
  at each entry), `BLOCK_STATES`, `BIOMES`, `SECTION`, `LIGHT_DATA` — chunk and light schemas.

```python
@frozen
class Target:
    minecraft_version: str          # "26.3"
    protocol_version: int           # 777
    java_major: int                 # 25 — the Reference's JVM

class State(StrEnum):      HANDSHAKE, STATUS, LOGIN, CONFIGURATION, PLAY   # values: "handshake", …
class Direction(StrEnum):  CLIENTBOUND, SERVERBOUND

@frozen
class Packet:
    state: State
    direction: Direction
    name: str                       # "minecraft:status_response"
    packet_id: int
    payload: bytes                  # bytes after the packet id
    fields: Mapping[str, object] | None   # None ⇔ no schema yet for this packet, or undecodable
    decode_error: str | None = None # why the Codec rejected this received frame; None if it did not
    # An undecodable frame keeps its bytes as evidence (audit H3). Its name is the packet's
    # name if its id is known, "unknown:<state>:0x2a" if not, and "corrupt:<state>" (packet_id
    # -1, payload = the frame's bytes as far as they could be delimited) if not even a packet
    # id could be read: a corrupt frame length or compressed payload, or empty data. It is one
    # Packet, not a separate Event variant, so a Comparison needs no new case: its fields are
    # None, so it is compared by payload, and an unknown or corrupt name never aligns with a
    # Reference packet. (M2: a decode_error on the Candidate side is a `mismatch`, and must
    # survive a `*` Mask on its name: `run.judge` leads with a `failed` Divergence.)

class CodecError(ValueError): ...   # bad packet data, an unknown packet, or fields that do not fit
class UnknownPacketError(CodecError): ...   # packet_id / packet_name / decode: no such name or id

class Codec:                        # one per Target; loaded from codec/data/<version>/
    def __init__(self, packet_ids: Mapping[tuple[State, Direction], Mapping[str, int]],
                 schemas: Mapping[tuple[State, Direction], Mapping[str, Schema]] | None = None,
                 ) -> None: ...
    @classmethod
    def load(cls, minecraft_version: str) -> Codec: ...     # codec/data/<version>/packets.json
                                                            # + that version's codec/schemas
    @classmethod
    def for_target(cls, target: Target) -> Codec: ...        # load(target.minecraft_version)
    def packet_id(self, state: State, direction: Direction, name: str) -> int: ...
    def packet_name(self, state: State, direction: Direction, packet_id: int) -> str: ...
    def names(self, state: State, direction: Direction) -> tuple[str, ...]: ...  # in id order; () if none
    def entity_id_paths(self, state: State, direction: Direction,
                        name: str) -> tuple[EntityIdPath, ...]: ...
    # where the packet's fields hold entity ids, in wire order, found in its schema by type
    # (codec.entity_ids); () for a packet with none, no schema, or no such packet. Cached.
    def encode(self, state: State, direction: Direction, name: str,
               fields: Mapping[str, object]) -> bytes: ...          # VarInt id ‖ payload
    def decode(self, state: State, direction: Direction, data: bytes) -> Packet: ...
    # decode is strict: if a schema exists it must consume the payload exactly, else CodecError.
    def undecodable(self, state: State, direction: Direction, data: bytes,
                    error: str) -> Packet: ...  # the Packet (decode_error=error) for data decode rejected

def undecodable_frame(state: State, direction: Direction, raw: bytes,
                      error: str) -> Packet: ...  # "corrupt:<state>" for bytes that were no frame data
```

The schema mechanism (`codec/schema.py`) is how every packet's fields are
declared. Each field type is a `WireType`, and composite types wrap other
`WireType`s, so the whole protocol is described by one small interface:

```python
class WireType[T](Protocol):       # how one value is read from / written to the wire
    def read(self, reader: Reader) -> T: ...                    # WireError on bad bytes
    def write(self, writer: Writer, value: object) -> None: ... # WireError on a value it cannot
                                                                # encode (wrong Python type, range)
VAR_INT: WireType[int]             # also VAR_LONG, USHORT, LONG; more primitives as packets need them
                                   # (ints reject bool)
BOOL: WireType[bool]               # writes only a bool (not 1 or "")
UUID: WireType[uuid.UUID]          # writes only a UUID (not its str, bytes or int)
BYTE: WireType[int]; SHORT: WireType[int]; INT: WireType[int]   # signed 8 / 16 / 32 bits
UBYTE: WireType[int]               # Unsigned Byte, 0 to 255 (writes nothing outside it)
FLOAT: WireType[float]             # binary32; writes only a float it holds exactly (not 0.1, not 1)
DOUBLE: WireType[float]            # binary64; writes only a float
REST: WireType[bytes]              # the rest of the packet as bytes (a plugin message's data)
@frozen
class String:                      # WireType[str]: String (n) on the wiki
    max_length: int                # n in UTF-16 code units; SchemaError unless 1 <= n <= 32767

class Schema:                      # WireType[dict[str, object]]: ordered, named fields
    def __init__(self, **fields: WireType[object]) -> None: ...   # in wire order
    # e.g. Schema(protocol_version=VAR_INT, server_address=String(255), ...)
    # Field names are the snake_case of the wiki field names. write() needs exactly the
    # declared names (WireError lists missing / unexpected ones). Errors are prefixed with
    # the field name, so a nested failure reads "entries: 3: name: ...".
    @property
    def fields(self) -> dict[str, WireType[object]]: ...          # name → type, in wire order (a copy)

IDENTIFIER: WireType[str]          # String (32767), the Identifier's wire form (not validated)

@frozen
class PrefixedArray[T]:            # WireType[list[T]]: VarInt length, then the elements
    element: WireType[T]
    max_length: int | None = None  # WireError past it; a length over the bytes left is refused
                                   # too (no element takes under a byte); writes a list or tuple
@frozen
class PrefixedOptional[T]:         # WireType[T | None]: Boolean (strict), then T if present
    element: WireType[T]
class Tagged:                      # WireType[dict[str, object]]: a VarInt that picks a named variant
    def __init__(self, tag_key: str, value_key: str,
                 variants: Sequence[tuple[str, WireType[object] | None]]) -> None: ...
    # The value is {tag_key: variant name, value_key: payload}; a variant's id is its position,
    # a variant with no wire type has the payload None. An id no variant has is a WireError,
    # and so is a name no variant has when writing. `names` lists them in id order, and
    # `variants` pairs each name with its wire type, so a walk of the fields can reach inside;
    # `tag_key` and `value_key` are the two keys.
NBT: WireType[bytes]               # one network NBT tag, as its exact bytes, checked structurally
                                   # (tag types, lengths, 512 deep); not decoded into values yet
POSITION: WireType[dict[str, int]] # {x, y, z} packed 26/26/12 bits into a Long
LP_VEC3: WireType[dict[str, int]]  # {scale, x, y, z}: an entity's velocity, as vanilla's LpVec3 packs it:
                                   # a scale and three 15-bit quanta, kept as the integers (not the
                                   # float they stand for), so every encoding reads back byte for byte

@frozen
class EntityId:                    # WireType[int | None]: an entity id, told apart by its type
    wire: WireType[int]            # VAR_INT or INT: how the id is carried
    optional: bool = False         # the id + 1 on the wire, 0 = no entity (reads as None)
    zero_is_none: bool = False     # the id on the wire, but 0 = no entity (reads as None);
                                   # not both (SchemaError)
ENTITY_ID: EntityId                # VarInt: spawn, movement, metadata, passengers, …
ENTITY_ID_INT: EntityId            # Int: login, entity_event, set_entity_link's attached entity
ENTITY_ID_INT_OR_NONE: EntityId    # Int, 0 = none: set_entity_link's holder (0 detaches the lead;
                                   # the client takes no holder for 0, Leashable.getLeashHolder)
ENTITY_ID_OPTIONAL: EntityId       # VarInt, id + 1: a damage event's source ids
# Every field that holds an entity id is one of these, so a Comparison finds them all by
# type (the renumbering, which needs no list of packets). Nothing
# else in a schema is an EntityId. "No entity" reads as None, which the renumbering leaves
# alone.

# codec/entity_ids.py: where a value holds entity ids, walked from its wire type (#21).
@frozen
class Each: ...                    # the type of EACH (repr "EACH")
EACH: Each                         # the step to every element of a list, in order
@frozen
class Variant:                     # the step that goes on only where value[key] == name: one
    key: str                       # variant of a Tagged value (the next step is its value key)
    name: str
type Step = str | Each | Variant   # a mapping key, every element, or one variant
type EntityIdPath = tuple[Step, ...]   # from a value to an entity id in it; () is the value itself
def inner_types(wire_type: WireType[object]) -> tuple[tuple[EntityIdPath, WireType[object]], ...]
    # what a wire type is made of, each with the steps to its value: a Schema's fields by name,
    # an array's element (PrefixedArray, FixedArray) under EACH, an optional's value and a
    # Deferred's type in place, each Tagged variant's payload under Variant(tag_key, name) and
    # value_key, a Holder's direct value under "direct", an Either's sides under their keys,
    # and ENTITY_DATA as a list of SERIALIZERS values. Anything else is read whole: ().
def entity_id_paths(wire_type: WireType[object]) -> tuple[EntityIdPath, ...]
    # every path to an EntityId, in wire order; a Deferred met again inside itself is cut,
    # and ValueError if such a cycle holds an entity id (its paths would never end).
# e.g. set_entity_data: ("entity_id",), and ("entries", EACH, Variant("serializer",
# "particle"), "value", Variant("type", "minecraft:vibration"), "options", "destination",
# Variant("type", "minecraft:entity"), "value", "entity_id"), and the same under "particles"
# with one more EACH. tests/codec/test_entity_ids.py walks every schema: each wire type a
# packet reaches is walked, an EntityId, or listed with the reason it holds none (an item
# stack's data components, the command tree, NBT, ...).

# codec/movement.py: each owns its discriminator (the number of steps, the path type); a
# value names its variant by its key, exactly one of `linear` and `stepped`.
MOVE_DELTA: WireType[dict[str, object]]     # {on_ground, linear: {x, y, z}} | {on_ground, stepped: [{ticks, x, y, z}]}
POSITION_PATH: WireType[dict[str, object]]  # {linear: {x, y, z}} | {stepped: [{x, y, z, tick_offset}]}

# codec/particles.py: both are Tagged. A particle is {type: "minecraft:dust", options: {...}},
# options None for a type with none (22 of the 128 have them, the item particle's are an
# ITEM_STACK_TEMPLATE: {item, count, components}); a position source is
# {type: "minecraft:block", value: {x, y, z}} or
# {type: "minecraft:entity", value: {entity_id, y_offset}} (its entity_id is an ENTITY_ID).
PARTICLE: Tagged
POSITION_SOURCE: Tagged

# codec/entity_data.py: value types of the entity metadata serializers. Ids of enums and
# registries (a direction, a pose, a variant, a block state) stay VarInts, not range checked
# (the client maps an out-of-range enum id to the first, wraps or clamps it).
OPTIONAL_BLOCK_STATE: WireType[int | None]    # VarInt, 0 = None (so a present 0 is refused on write)
OPTIONAL_UNSIGNED_INT: WireType[int | None]   # VarInt of value + 1, 0 = None
OPTIONAL_GLOBAL_POS: WireType[dict | None]    # {dimension, pos: {x, y, z}} | None
# PAINTING_VARIANT and RESOLVABLE_PROFILE are in codec/shapes.py (the data components use them
# too); entity_data imports them for SERIALIZERS.
# All 44 serializers of `EntityDataSerializers`, in registration order (the position is the id),
# named by their lower-case Java constants ("byte", "int", "float", "optional_component", ...).
SERIALIZERS: Tagged                           # {serializer: "float", value: 10.0}
# The entries of set_entity_data: a list of {index, serializer, value} in wire order. An entry
# is a u8 index (0..254: 0xFF ends the list) and a serializer id with its value. The
# item_stack serializer's value is a SLOT.
ENTITY_DATA: WireType[list[dict[str, object]]]
# Limit: an entity id inside a metadata value (a firework's shooter, an attached entity) or in
# add_entity's `data` depends on the entity type, so it is a plain VarInt, not an `ENTITY_ID`.
# Only a vibration source's target is one.

# codec/equipment.py: set_equipment's slots. A value is [{slot: "mainhand", item: ...}], never
# empty; each slot is a byte of its id, plus 0x80 on every one but the last.
SLOTS: tuple[str, ...]             # the 8 EquipmentSlot constants in ordinal order (id = position)
@frozen
class EquipmentList:               # WireType[list[dict[str, object]]]
    item: WireType[object]         # how each slot's item is carried
EQUIPMENT: WireType[list[dict[str, object]]]  # EquipmentList(SLOT): each slot's item is a stack or None

# codec/shapes.py: the shapes the data components are built from.
UNIT: WireType[None]             # no bytes (StreamCodec.unit): reads None, writes only None
NBT_TAG: WireType[bytes]         # an NBT root tag of any type but END, as its exact bytes
COMPOUND_TAG: WireType[bytes]    # NBT_TAG whose root must be a compound (type 10), as its exact bytes
TEXT_COMPONENT: WireType[bytes]  # NBT_TAG: a text component is kept as its NBT bytes, not decoded
@frozen
class FixedArray:                # exactly `size` elements, no count (fixedSizeList): a list
    element: WireType[object]; size: int
@frozen
class Deferred:                  # a wire type defined later, for one that contains itself;
    resolve: Callable[[], WireType[object]]  # nested too deeply is a WireError, not a RecursionError
def registry_dispatch(names, layouts, tag_key="type", value_key="value") -> Tagged: ...
                                 # a Tagged with a variant per registry entry, id = position in names
REGISTRY_ID: WireType[int]       # a registry entry by protocol id: a plain VarInt, not range checked
ENUM: WireType[int]              # an enum by ordinal: a plain VarInt, not range checked
@frozen
class OrdinalEnum:               # an enum by ordinal that fails past its last constant (readEnum): a VarInt in 0..count-1
    count: int
SOUND_SOURCE: WireType[int]      # OrdinalEnum(11): a sound category, MASTER 0 ... UI 10
@frozen
class Holder:                    # VarInt 0 + the value, else registry id + 1: {direct: v} | {reference: id}
    direct: WireType[object]
@frozen
class Either:                    # a Bool, then the left (true) or right type: {left_key: v} | {right_key: v}
    left_key: str; left: WireType[object]; right_key: str; right: WireType[object]
HOLDER_SET: WireType[dict]       # VarInt 0 + a tag, else n + 1 and n ids: {tag: "minecraft:logs"} | {ids: [id, ...]}
SECTION_POSITION: WireType[dict[str, int]]  # {x, y, z} of a chunk section, packed 22/20/22 bits into a Long
VEC3: Schema                     # {x, y, z}: three Doubles
SOUND_EVENT: Holder              # {reference: id} | {direct: {location, fixed_range: float | None}}
GLOBAL_POS: Schema               # {dimension, pos: {x, y, z}}
PAINTING_VARIANT: WireType[dict] # Holder: {reference: id} | {direct: {width, height, asset_id, title, author}}
RESOLVABLE_PROFILE: Schema       # {profile: {game_profile: {...}} | {partial: {...}}, skin_patch: {...}}

# codec/components.py. A data component's value has no length on the wire, so each one's layout
# must be known to read past it: a component with no layout, or an id past the registry, is a
# WireError naming it. Ids come from the generated name list, never hand-typed.
class ComponentTable:              # names, without_layout, type_id(name), type_name(id), layout(name)
TABLE: ComponentTable
@frozen
class ComponentType:               # WireType[str]: a type's VarInt id on the wire, its name as a value
    table: ComponentTable
COMPONENT_TYPE: ComponentType      # ComponentType(TABLE)
@frozen
class TypedComponent:              # WireType[dict[str, object]]: a type id, then that type's value
    table: ComponentTable
TYPED_COMPONENT: TypedComponent    # TypedComponent(TABLE): {type: "minecraft:damage", value: 5}. The exact
                                   # matchers of can_place_on and can_break read it, so they recurse
@frozen
class Patch:                       # WireType[dict[str, object]]
    table: ComponentTable
# A patch is {added: [{type: "minecraft:damage", value: 5}, ...], removed: ["minecraft:max_stack_size"]},
# in wire order (a repeated type is kept). Errors read "added: 0: minecraft:damage: ...".
PATCH: Patch                       # Patch(TABLE)
ITEM_STACK_TEMPLATE: Schema        # a stack inside a component or a particle: {item, count, components}.
                                   # Item, then count, then patch: not SLOT's order, and never empty

# codec/items.py
SLOT: WireType[dict[str, object] | None]  # None (a count of 0) | {count, item, components: <a patch>}
# The stack a client sends (HashedStack): the wire type only. The hashes are Ints the caller gives
# and are written as they are; computing a component's hash is #28's.
HASHED_SLOT: WireType[dict[str, object] | None]
                                          # None | {item, count, components: {added: [{type, hash}], removed: [type]}}

class SchemaError(ValueError): ... # a declaration that can never be valid, raised when defined

# codec/schemas/<state>.py: the Target's schemas, keyed by packet name. Each module records
# the minecraft.wiki revision its layouts come from; packets.py maps them to (State, Direction).
SERVERBOUND: Mapping[str, Schema]
CLIENTBOUND: Mapping[str, Schema]
# codec/schemas/configuration.py also holds the values a Bot sends, each with its source:
CLIENT_INFORMATION: Mapping[str, object]  # a fresh vanilla client's client_information:
                                          # Options.buildPlayerInformation() on a new options.txt
```

Rules for the field types still to come (NBT, text components, BitSet,
Position, …), which the composites above follow:

- Each one is a `WireType`. A composite takes its element type as an
  argument, for example `PrefixedArray(Schema(...))`, and a `Schema` nests
  as a compound field.
- Wire types are **context-free**: a field never reads its siblings. When a
  field's presence, length or shape depends on another field (an Optional
  keyed on an earlier Boolean, an action enum that selects the fields
  after it, a bit mask), a single composite `WireType` owns both the
  discriminator and the dependent fields.
- Decoded values are plain Python values: `int`, `str`, `bool`, `bytes`,
  `UUID`, `list`, `dict`, or `None`.

**Where the Codec is stricter than the vanilla client.** The Codec reads the
protocol as the wiki defines it and vanilla's own encoders write it. In a few
places the vanilla client tolerates bytes outside that definition, and the
Codec deliberately does not: the vanilla server never sends them, so a
Candidate that does differs from vanilla in the bytes it sends, and ADR-0006
catalogues every difference. Strictness can only produce a visible false
`mismatch` (with the frame recorded as evidence), never a false `match`. The cases (verified
with `javap` on the 26.3 jars, docs/research/2026-09-26-join.md):

- **Bool**: only `0x00` and `0x01`. The client's `readBoolean` is
  `readByte() != 0`, so it reads `0x02` as true.
- **String**: malformed UTF-8 is an error. The client's `Utf8String.read`
  decodes with `ByteBuf.toString(UTF_8)`, which replaces it with U+FFFD.
- **Compressed frame**: the zlib stream must be complete and inflate to
  exactly the declared data-length, which must be in 1‥8 388 608. The
  client inflates into a buffer of exactly the declared size, so it keeps
  the first bytes of a longer stream and never reads a missing trailer, and
  it only fails a data-length above 8 388 608 if it cannot allocate it.
- **LpVec3**: a continuation flag (bit 2 of the first byte) followed by a zero
  scale extension is an error. The client reads it as a scale of 0 to 3 with
  the flag ignored, so the same vector has two spellings, and only the
  flagless one is what vanilla writes.
- **Position path**: an unknown type is an error. The client's `ByIdMap` reads
  an id out of range as type 0 (linear), so a Candidate's packet with type 7
  would read as a linear path there.

Where the client's reading is the protocol's own definition, the Codec reads
the same way: a VarInt's unused 5th-byte bits (VarLong: 10th) are dropped
(the wiki allows over-long encodings), bytes after a zlib stream are ignored,
and a compressed frame whose data-length is below the threshold is accepted
(only vanilla's *server* checks that).

### Network and Bot

```python
@frozen
class Endpoint:
    host: str
    port: int

class ConnectionClosedError(ConnectionError): ...   # closed by the server or close(), or lost
type Answer = Callable[[Connection, Packet], Awaitable[None]]
class ProtocolError(Exception): ...  # breaks the protocol sequence: unknown intent, unexpected answer

class Connection:                   # one TCP connection; owns framing, compression, State
    @classmethod
    async def open(cls, endpoint: Endpoint, codec: Codec, *, bot: str, transcript: Transcript,
                   answer: Answer | None = None) -> "Connection": ...   # TCP_NODELAY (asyncio's default)
    # answer: awaited by the background reader for each Packet it decodes, in wire order, as
    # it arrives, before the next frame is taken; it may send. So a Bot answers keep-alives
    # and teleports whether or not a Group is reading, as the vanilla client does. The
    # Packet is queued for recv once its answer has returned (whoever takes it knows the
    # answer was sent). A send that fails because the connection is lost is ignored (the
    # reader reads on to the end of the stream); anything else it raises stops the reader,
    # and recv raises it right after the Packet it was answering.
    state: State                    # read-only: the State send encodes in
    transcript: Transcript          # read-only: the Transcript it records to
    last_arrival_ns: int | None     # read-only: when the Packet recv last returned arrived, as the
                                    # Transcript stamps it (not when it was taken); None before the first
    async def caught_up(self) -> None: ...  # once the reader has stamped the backlog on entry
                                    # (FIONREAD + the stream buffer; later bytes not waited for),
                                    # or has ended; sync awaits it before stamping a request
    # The directions switch as the vanilla client switches them (26.3 javap: the terminal
    # packets, whose isTerminal() is true). Sending the intention moves both (intent 1 →
    # STATUS, 2 or 3 (transfer) → LOGIN, else ProtocolError). After that, what is *received*
    # switches as the terminal packet arrives, so the very next frame is decoded in the new
    # State even before the ack: login_finished → CONFIGURATION, finish_configuration → PLAY,
    # start_configuration → CONFIGURATION. What is *sent* (`state`) switches once the ack has
    # been sent: login_acknowledged → CONFIGURATION, finish_configuration → PLAY,
    # configuration_acknowledged → CONFIGURATION. Each received Packet carries the State it
    # was decoded in. A login_compression that arrives sets the threshold both ways from the
    # next frame (frames are split one at a time); a negative threshold means uncompressed.
    async def send(self, name: str, /, **fields: object) -> None: ...  # records an Event
    async def send_all(self, packets: Sequence[tuple[str, Mapping[str, object]]]) -> None: ...
                                    # each (name, fields) in order, in one write, then one drain,
                                    # each recorded at the time before the write (#65);
                                    # ValueError for none, or for a packet that changes the State
    async def recv(self, *, timeout_s: float) -> Packet: ...           # records an Event
    async def close(self) -> None: ...                                 # idempotent; aborts after 1 s
    # A background reader task reads the socket continuously from open until close: it stamps
    # each complete frame when the read that completed it returned, decodes it in the State
    # current then, and queues it. recv takes the next queued Packet and records it with that
    # arrival stamp, so the Transcript holds the frames the Bot took, independent of TCP
    # segmentation, each stamped when it arrived however late it is taken. The frames one read
    # completed are stamped a nanosecond apart, in order (the first at the read's time), so a
    # Mark can fall between any two of them. close cancels the
    # reader and waits for it to finish, and a recv still waiting raises ConnectionClosedError.
    # `name` is positional-only, so a packet field called `name` (login `hello`) fits in **fields.
    # Timeouts are named `timeout_s`: ruff's ASYNC109 flags a parameter named `timeout`, and its
    # docs endorse renaming it for functions that wrap asyncio.timeout.
    # send: CodecError if the fields do not fit, ConnectionClosedError if the connection was lost
    # (asyncio would silently discard the write) before the write or while draining it; none
    # of these records or moves the State. The Event holds the Packet decoded from the exact
    # bytes written, stamped immediately before the write, and is recorded (and the State moved
    # on) only once the write has drained, or when send is cancelled while draining (the frame
    # is queued and will go out).
    # recv: TimeoutError leaves the Connection usable. Whatever stopped the reader is raised
    # once the frames before it are taken, and again by every later recv: CodecError for a
    # corrupt frame, an unknown packet id or a strict-decode failure, ConnectionClosedError
    # when the server closes or the connection is lost: any OSError, e.g. a reset, a TCP
    # timeout or a failed write (the message says which, with the system's reason, and if that
    # was mid-frame; every frame that arrived before the loss is still taken, even the ones
    # still in the socket; a write that fails after the server's close reads as the close),
    # or the exception itself if the harness has a bug. A frame that fails to decode
    # is recorded before recv raises, as the Packet Codec.undecodable / undecodable_frame
    # builds (its bytes and decode_error), stamped on arrival like any frame; the reader then
    # stops, as the vanilla client disconnects on a frame it cannot decode.

class Bot:                          # what Groups use; answers keep_alive / teleports / chunk batches itself
    name: str
    failure: Exception | None       # what its last failed operation (status, ping, join,
                                    # expect, command, a movement, sync, drain) raised: which Bot a
                                    # Group's failure came from
    closed: bool                    # (property) close was called
    in_play: bool                   # (property) joined, and not closed: what sync needs
    disconnected: bool              # (property) expect has returned the server's disconnect
                                    # (a Group that tests a kick takes it so)
    position: Position              # (property) where the player is and faces: the last
                                    # teleport's pose, or where it moved since (a copy)
    entities: Entities              # (property, #27) the entities its server told it about,
                                    # by entity id (Replies.tracker; below)
    chunks: frozenset[tuple[int, int]]  # (property, #33) the chunks (x, z) its server sent
                                    # and has not told it to forget, in this level (Replies.chunks;
                                    # a copy)
    inventory: Inventory            # (property, #28) the player's inventory and the open
                                    # container: a snapshot (Replies.inventory; below)
    @classmethod
    async def connect(cls, endpoint: Endpoint, target: Target, *, name: str,
                      transcript: Transcript, timeout_s: float) -> "Bot": ...  # Codec.for_target
    # connect opens the Connection with answer=Replies(): from then on the Bot answers by itself.
    # The Bot keeps both (AnsweredConnection(connection, replies)); Replies.saw_disconnect says
    # whether the server's disconnect has arrived, taken or not.
    async def status(self) -> Mapping[str, object]: ...                # parsed status JSON
    async def ping(self, payload: int) -> None: ...
    async def join(self) -> None: ...                                  # handshake → login → configuration → play
    async def respawn(self) -> None: ...                               # PERFORM_RESPAWN → player_loaded
    async def expect(self, name: str, /, *others: str, timeout_s: float,
                     where: Callable[[Packet], bool] | None = None) -> Packet: ...
    async def sync(self) -> None: ...                                  # the barrier (below)
    async def drain(self) -> None: ...                                 # take what has arrived
    async def refuse_queued_disconnect(self) -> None: ...              # drain if a disconnect waits
    async def send(self, name: str, /, **fields: object) -> None: ...
    async def command(self, command: str) -> None: ...                 # unsigned chat_command, no leading "/"
    async def signed_command(self, command: str) -> None: ...          # chat_command_signed, no signature (#65)
    async def chat(self, message: str) -> None: ...                    # chat, no signature (#65)
    async def chat_at_once(self, *messages: str) -> None: ...          # each as chat, one write (#65)
    async def move(self, x: float, y: float, z: float, *, on_ground: bool = True) -> None: ...
    async def look(self, yaw: float, pitch: float) -> None: ...
    async def move_unchecked(self, position: Position) -> None: ...  # pos_rot as given, keeps nothing (#278)
    async def sprint(self, sprinting: bool) -> None: ...               # holds forward and sprint, + the command
    async def sneak(self, sneaking: bool) -> None: ...                 # holds the sneak key
    async def jump(self) -> None: ...                                  # the jump key, for this tick only
    async def tick(self) -> None: ...                                  # a tick with no change
    async def hold(self, slot: int) -> None: ...                       # hotbar slot 0-8
    async def dig(self, x: int, y: int, z: int, face: Face) -> None: ...  # start breaking, + punch
    async def stop_digging(self, x: int, y: int, z: int, face: Face) -> None: ...  # finish, + punch
    async def cancel_digging(self, x: int, y: int, z: int) -> None: ...   # abort, face down
    async def place(self, x: int, y: int, z: int, face: Face,
                    cursor: tuple[float, float, float] = (0.5, 0.5, 0.5), *,
                    off_hand: bool = False) -> None: ...                 # use_item_on
    async def use_item(self, *, off_hand: bool = False) -> None: ...
    async def release_item(self) -> None: ...
    async def swing(self) -> None: ...                                  # punch
    async def attack(self, entity: Entity) -> None: ...                # attack, + punch
    async def interact(self, entity: Entity, at: tuple[float, float, float] = (0.0, 0.0, 0.0),
                       *, off_hand: bool = False) -> None: ...         # interact
    async def drop(self, *, all: bool = False) -> None: ...            # player_action DROP_ITEM / DROP_ALL_ITEMS
    async def click(self, slot: int, button: int = 0, mode: str = "pickup") -> None: ...  # container_click
    async def close_container(self) -> None: ...                       # container_close, outside a tick
    async def close(self) -> None: ...                                 # idempotent
    # Every operation (connect included) is bounded by timeout_s → TimeoutError.
    # status / ping send the handshake (intent 1, Target protocol, Endpoint host and port) first
    # unless already sent. status: status_request → status_response, whose json_response must be
    # a JSON object. ping: ping_request → pong_response echoing the payload. Any other answer →
    # ProtocolError, with the answer still recorded.
    # join (offline only): on a fresh Connection (else ProtocolError, nothing sent), the handshake
    # (intent 2) and hello(name, offline_uuid(name)), then expect(play chunk_batch_finished), then
    # player_loaded: it returns once the server's first chunk batch has finished, Replies having
    # answered the rest. player_loaded goes once, right after that batch's chunk_batch_received:
    # the vanilla client's moment depends on its renderer, and none could be ready earlier.
    # respawn (#27): on a Bot in play (else ProtocolError, nothing sent), client_command
    # PERFORM_RESPAWN (0), then expect(play respawn), then expect(chunk_batch_finished), then
    # player_loaded, as join does: the client waits to load its world again after a respawn
    # (handleRespawn), and the server ignores attack and interact until it has
    # (hasClientLoaded). A server ignores the request from a live player → TimeoutError.
    # expect: takes (and so records) packets until one is called any of `names` (the first such
    # ends it, #270) and `where` holds for it (it sees a packet of any of the names); ValueError for a name given twice.
    # A disconnect before it (login_disconnect, or configuration / play disconnect) or an
    # encryption request (login hello: online mode) → ProtocolError naming the Bot and the reason.
    # command: on a Bot in play (else ProtocolError, nothing sent), sends play chat_command
    # (String 32767) and returns at once; what the server answers arrives like any packet.
    # chat / signed_command (#65): on a Bot in play (else ProtocolError, nothing sent), send
    # play chat (the message) or chat_command_signed (the command, no argument signatures) as
    # the 26.3 client does with no chat session (ClientPacketListener.sendChat / sendCommand,
    # javap): CHAT_TIMESTAMP_MS and CHAT_SALT where the client sends its clock and a random
    # salt, no signature, message_count 0, acknowledged 3 zero bytes, checksum 1 (an empty
    # last-seen set's). The client sends a command with a message argument (/say, /me, /msg,
    # /teammsg) as chat_command_signed, any other as chat_command; the Group picks.
    # sync, the barrier: returns once the server has sent everything caused by what it
    # received before. On a Bot in play (else ProtocolError, nothing sent): client_command
    # (REQUEST_STATS) then expect(award_stats), SYNC_REQUESTS (3) times, always.
    # Vanilla handles a request at the start of a tick, before that tick sends what
    # changed, but a request that arrives while a tick's pass over the queue runs is
    # handled in that pass, and a pass lasts under TICK_GAP_S (0.005)
    # (docs/research/2026-10-01-join-chunks.md). So each request after the first is sent
    # only once TICK_GAP_S has passed since the last answer arrived
    # (Connection.last_arrival_ns): it lands after that pass, and its answer comes from a
    # later tick. The wait is the proof (ADR-0010, #115 amendment); a stall in the Bot's
    # loop only lengthens it. Two requests are the barrier; the third keeps it when one
    # award_stats sent unasked is taken as an answer (ADR-0010, #169 amendment).
    # Observation windows call it when they close, and Control calls it after each
    # command's marker (OperatorBot).
    # drain: takes (records) every packet already queued, without waiting: recv(timeout_s=0)
    # until TimeoutError. A frame that does not decode, or a Connection that has ended with
    # nothing left to take, raises as recv does. A disconnect it takes → ProtocolError, as
    # in expect (a Group that tests a kick takes the disconnect itself, with expect).
    # move / look / sprint / sneak / jump / tick (#25): on a Bot in play (else ProtocolError,
    # nothing sent or changed), each is one scripted client tick, sent at once with no wait
    # (a Group paces them, e.g. with sync between): the change, then what the 26.3 client
    # sends on a tick (Minecraft.tick, LocalPlayer.sendChanges / sendPosition, javap), in
    # order: player_input if the keys held changed (forward 0x01, jump 0x10, sneak 0x20,
    # sprint 0x40; sprint holds forward with sprint, as no client sprints without it, and
    # refuses to start while sneaking: LocalPlayer.canStartSprinting / shouldStopRunSprinting);
    # player_command START_SPRINTING (1) / STOP_SPRINTING (2) with the player's entity id
    # (play login; sprint refuses before it) if sprinting changed; then one movement packet:
    # move_player_pos_rot if the position moved more than 2.0E-4 (squared length, strictly)
    # or 20 ticks passed since the last position report, and the rotation changed;
    # move_player_pos or move_player_rot if only one did; move_player_status_only if neither
    # but on-ground changed; else none; then client_tick_end (vanilla kicks a second position
    # in one client tick: ServerGamePacketListenerImpl.receivedPositionThisTick). What was
    # last reported starts as a fresh LocalPlayer's (pose 0, off the ground, no keys, not
    # sprinting); a correction (player_position) moves the pose but not what was reported,
    # so the next tick reports the corrected position. A Bot starts on the ground; look
    # rounds to binary32, takes pitch % 360 then holds it to -90..90, and ignores a
    # non-finite value (Entity setYRot / setXRot). jump holds the key for its tick only; the
    # next call releases it.
    # The server keeps the player's known movement at its last step until a client tick
    # with no movement (handleClientTickEnd), so a Bot moves to the server until a tick()
    # after its last move. The Bot presses no direction keys, but forward while sprinting.
    # hold / dig / stop_digging / cancel_digging / place / use_item / release_item / swing
    # (#26): on a Bot in play (else ProtocolError), each is one client tick like the above,
    # with set_carried_item first if the selected slot differs from the one last sent
    # (MultiPlayerGameMode.tick → ensureHasSentCarriedItem; hold refuses a slot outside 0-8,
    # ValueError), then the action (handleKeybinds), then the movement packets and
    # client_tick_end. dig: player_action START_DESTROY_BLOCK (0) then punch
    # (Minecraft.startAttack); stop_digging: STOP_DESTROY_BLOCK (3) then punch (the last tick
    # of continueDestroyBlock); cancel_digging: ABORT_DESTROY_BLOCK (2), face down, sequence 0
    # (stopDestroyBlock); place: use_item_on (hand, the block, face, cursor, inside and world
    # border false); use_item: use_item (hand, sequence, the pose's yaw and pitch);
    # release_item: RELEASE_USE_ITEM (6) at 0 0 0, face down, sequence 0; swing: punch (26.3
    # has no swing packet with a hand). START, STOP, use_item_on and use_item carry the next
    # block-change sequence (BlockStatePredictionHandler: +1, then sent, from 0 per level).
    # The Bot times no breaking: a Group sends stop_digging at the tick it tests.
    # attack / interact (#27): one client tick each, as above. attack: attack with the
    # entity's id, then punch (Minecraft.startAttack, MultiPlayerGameMode.attack); interact:
    # interact (the entity's id, hand, `at` relative to the entity's position as LpVec3.write
    # encodes it, sneaking = the sneak key held), no punch (MultiPlayerGameMode.interact).
    # interact refuses a NaN or infinite `at` (ValueError, nothing sent). Like place, it does
    # not go on to use_item when the use does nothing.
    # drop (#28): one client tick, as above: Inventory.removeFromSelected on the held slot
    # (one item, or the stack with all=True), then player_action DROP_ITEM (5) or
    # DROP_ALL_ITEMS (4) at 0 0 0, face down, sequence 0, sent with an empty hand too
    # (MultiPlayerGameMode.dropItem); refused with a container open (ProtocolError: the client
    # reads the drop key only with no screen). close_container (#28): back to the inventory menu,
    # then container_close with the old menu's window id (0 with none open: the inventory
    # screen), sent at once and not in a tick (LocalPlayer.closeContainer). click (#28): on a
    # Bot in play, InventoryTracker.click predicts the click, then container_click goes at
    # once, not in a tick (a mouse or key callback); a refused click sends nothing (ValueError).
    # The Bot follows no game mode: click predicts a survival or adventure player, and drop
    # sends what a spectator's client never would (the guide says so).
    # Face is an IntEnum: DOWN 0, UP 1, NORTH 2, SOUTH 3, WEST 4, EAST 5.
    # The Bot simulates no physics: the Group gives each position; move refuses a NaN or
    # infinite coordinate (ValueError, nothing sent). Horizontal collision is never reported.
    # move_unchecked (#278): on a Bot in play (else ProtocolError), one tick of exactly
    # move_player_pos_rot with the Position's five values and the on-ground flag of the last
    # move, then client_tick_end, in one write. It checks and rounds nothing the wire can carry
    # (a value that is not a float, or a rotation no binary32 holds → ValueError before any
    # send, so no Bot.failure), and changes neither the pose nor what the Bot last reported. For Groups that test moves no client sends (movement/invalid).
    # refuse_queued_disconnect (#184): on a Bot not closed whose expect has not returned the
    # disconnect, catches up with the socket (Connection.caught_up), then drains only if its
    # Replies have seen the server's disconnect (Replies.saw_disconnect), so the drain refuses
    # it; otherwise it takes and records nothing. GroupContext.end calls it on every Bot.

def offline_uuid(name: str) -> UUID: ...  # UUIDUtil.createOfflinePlayerUUID: MD5 v3 of "OfflinePlayer:" + name

@frozen
class Position:                     # Bot.position: where its player is and faces
    x: float
    y: float                        # the feet
    z: float
    yaw: float                      # degrees
    pitch: float                    # degrees, -90 (up) to 90 (down)

class Face(IntEnum):                # a block face: Direction.get3DDataValue
    DOWN = 0; UP = 1; NORTH = 2; SOUTH = 3; WEST = 4; EAST = 5

# entities.py (#27): what a Bot knows of the entities around it, as ClientPacketListener
# tracks them (docs/research/2026-10-03-bot-entities.md).
@frozen
class Entity:                       # one entity, as the server last described it
    id: int                         # its entity id: it differs from server to server
    uuid: UUID
    type: str                       # "minecraft:zombie"; "#<id>" for an id outside the registry
    x: float; y: float; z: float    # where the server last put it
    data: Mapping[int, object]      # its entity data so far, by index

class Entities(Mapping[int, Entity]):  # a read-only view by entity id: each lookup a snapshot
    def find(self, type: str, *, near: tuple[float, float, float] | None = None) -> Entity: ...
    # type "minecraft:zombie" or "zombie". The only entity of the type, or with near the one
    # nearest to it (squared distance). LookupError: none of the type (the message counts the
    # types there are), two or more without near, or two or more equally near: which comes
    # first would depend on the server's ids.

# inventory.py (#28): the player's inventory and the open container, as ClientPacketListener
# keeps them (docs/research/2026-10-04-bot-inventory.md).
PLAYER_INDEXES = 43                 # Inventory's indexes: hotbar 0-8, 9-35, feet..head 36-39,
                                    # off hand 40, body 41, saddle 42
@frozen
class Stack:                        # a stack of items, as the server last described it
    item: str                       # "minecraft:stone"; "#<id>" for an id outside the registry
    count: int
    components: Mapping[str, object] = {"added": [], "removed": []}  # the patch, as decoded

@frozen
class Inventory:                    # Bot.inventory: one moment's snapshot
    window_id: int                  # the open menu's; 0 for the player's own inventory menu
    menu: str | None                # "minecraft:generic_9x3"; None for the player's own; a
                                    # mount's entity type ("minecraft:horse") for its inventory
    slots: tuple[Stack | None, ...] # the open menu's slots, by slot number (what a click names)
    carried: Stack | None           # the cursor's stack
    state_id: int                   # the last one the server sent for the open menu
    player: tuple[Stack | None, ...]  # by Inventory index, PLAYER_INDEXES of them

class InventoryTracker:
    enchantments: tuple[str, ...] | None  # the minecraft:enchantment registry by network id, from
                                          # the last configuration's registry_data (Replies)
    def follow(
        self, name: str, fields: Mapping[str, object], entities: Mapping[int, Entity] | None = None
    ) -> None: ...
    # container_set_content / container_set_slot: window 0 → the inventory menu (even with a
    # container open), the open menu's id → that menu, any other id or a slot the menu does not
    # have → nothing. set_cursor_item → the open menu's carried stack; set_player_inventory →
    # an Inventory index (out of range: nothing); open_screen → a new open menu;
    # mount_screen_open → a new open menu if `entities` holds the entity as a horse (saddle,
    # body, 3 rows of the columns) or a nautilus (saddle, body), else nothing; container_close
    # → the inventory menu again. Every menu lays out its player slots as the Inventory: the
    # inventory menu (46 slots), and every other menu its own slots (javap of its constructor),
    # then the 27 and the hotbar; the crafter's result comes last, and the lectern has only
    # its book. The server sends inventory changes through the open window only.
    def view(self) -> Inventory: ...
    def clear(self) -> None: ...      # a new player: nothing anywhere, no container open
    def close(self) -> None: ...      # back to the inventory menu (Player.closeContainer)
    def remove_from_selected(self, selected: int, *, whole: bool) -> None: ...  # one, or the stack
    def click(self, slot: int, button: int, mode: str) -> dict[str, object]: ...  # container_click fields
    # As AbstractContainerMenu.doClick on the client, in the inventory menu and the chest,
    # dispenser, hopper and shulker box menus, for a survival or adventure player (clone, and
    # a drag of a stack to each slot, change nothing): pickup
    # (button 0 all, 1 half; slot OUTSIDE drops the cursor), quick_move (the menu's
    # quickMoveStack, repeated while it moves some), swap (button 0-8 or 40: that Inventory
    # index), throw (button 0 one, any other the stack, 1 repeated), quick_craft (button = header | type << 2:
    # start 0, add 1, end 2; type 0 even, 1 one each), pickup_all (from slot 0, or the end with
    # any button but 0; full stacks last). Slot rules: armor slots take their equippable items,
    # one, and give up nothing enchanted with curse of binding (mayPickup; its id from
    # `enchantments`, an enchanted armor stack refused while they are None); a shulker box's
    # slots no shulker box; stack sizes from items.json. Returns window id,
    # state id, slot, button, mode, the slots whose stack changed (ItemStack.matches) hashed
    # in Int2ObjectOpenHashMap() order (fastutil: table 32, linear probing, grown past 3/4;
    # key 0 first, then positions down), and the hashed cursor. ValueError, nothing changed:
    # an unknown mode, a slot outside a Short or a button outside a Byte, a slot the click
    # must name that the menu lacks, a menu other than the inventory's, a chest's, a
    # dispenser's, a hopper's or a shulker box's (_CLICK_MENUS), the crafting result, a bundle, a
    # swap whose slot stack would go back through Inventory.add, or a changed slot or cursor
    # stack with a component patch (its hash needs the component's encoding).
CLICK_MODES: Mapping[str, int]      # pickup 0, quick_move 1, swap 2, clone 3, throw 4, quick_craft 5, pickup_all 6
OUTSIDE = -999                      # the slot of a click outside the menu

def java_round(value: float) -> int: ...  # Java's Math.round: half up, exact (VecDeltaCodec, LpVec3)

class EntityTracker:
    entities: Entities
    def clear(self) -> None: ...      # forget every entity; `entities` stays the same view
    def follow(self, name: str, fields: Mapping[str, object]) -> None: ...
    # add_entity adds (replacing the id); other packets for an unknown id change nothing.
    # move_entity_pos(_rot) decodes against the entity's base (VecDeltaCodec: an axis with a
    # 0 delta keeps the base's value, any other is (Math.round(base * 4096) + delta) / 4096; a
    # stepped delta step by step) and puts both the entity and the base at the end;
    # entity_position_sync puts both at the path's end; teleport_entity adds each flagged
    # axis to the position and replaces the others, and leaves the base.
    # set_entity_data sets each entry's value by its index; remove_entities drops each id.

CHUNKS_PER_TICK = 9.0               # what a Bot's chunk_batch_received asks for: vanilla's server start rate
BRAND = "vanilla"                   # the brand a Bot sends: ClientBrandRetriever.VANILLA_NAME
CHAT_TIMESTAMP_MS = 1_790_000_000_000  # the time every chat and signed command of a Bot carries
CHAT_SALT = 0                       # the salt they carry
TICK_GAP_S = 0.005                  # sync's wait from an answer's arrival to its next request
SYNC_REQUESTS = 3                   # how many statistics requests sync sends (#169)
SYNC_PASSED_OVER = "sync:passed-over"  # the Mark (+ " <Bot name>") for an award_stats stamped before its request
class Replies:                      # an Answer: what a Bot answers by itself, as each packet arrives
    async def __call__(self, connection: Connection, packet: Packet) -> None: ...
    # As the 26.3 client does (javap): login_finished → login_acknowledged, then configuration
    # custom_payload(minecraft:brand, the String BRAND) and client_information(CLIENT_INFORMATION),
    # all three before the next packet is handled; configuration
    # select_known_packs → the same packs back; code_of_conduct → accept_code_of_conduct;
    # finish_configuration → finish_configuration; keep_alive (configuration and play) → the
    # same id; play player_position → accept_teleportation with the pose it results in (flagged
    # parts add to the tracked pose, rotation summed in binary32, pitch clamped to ±90, a
    # non-finite rotation ignored), which becomes Replies.pose; play login → Replies.entity_id
    # (no answer); play login or respawn → Replies.reported starts again as a fresh player's
    # (a new LocalPlayer; respawn with data_kept bit 1 keeps its keys and sprinting; no
    # answer); play login, or respawn into another dimension → the block-change sequence
    # starts at 0 again (a new ClientLevel), login also the held slots (a new
    # MultiPlayerGameMode); respawn → slot 0 selected (a new Inventory), the last sent slot
    # kept, so the next tick sends 0 if it differs; play set_held_slot (0-8) → selected, sent back on the next tick
    # (no answer); every play packet → Replies.tracker (EntityTracker), cleared in place
    # (EntityTracker.clear, so a kept Bot.entities view follows) on play login or respawn into
    # another dimension (a new ClientLevel; no answer); every play packet → Replies.inventory
    # (InventoryTracker, with Replies.tracker's entities), cleared on play login or any
    # respawn (a new LocalPlayer; no answer); configuration registry_data for
    # minecraft:enchantment → its entry names collected, set as Replies.inventory.enchantments
    # on finish_configuration (each configuration collects afresh; no answer of its own);
    # chunk_batch_finished → chunk_batch_received(CHUNKS_PER_TICK),
    # never a timing-dependent rate; start_configuration → configuration_acknowledged. Nothing
    # else is answered (not yet: custom_query). join and respawn, not Replies, send player_loaded.

PROBE_TIMEOUT_S = 1.0               # bot.py, since it reuses Bot.status (net cannot import bot)
def status_probe(target: Target, *, timeout_s: float = PROBE_TIMEOUT_S
                 ) -> Callable[[Endpoint], Awaitable[bool]]: ...   # readiness, for runner.running
    # One short status exchange per call. True: the status names Target.protocol_version.
    # False, not ready yet: refused / reset / closed, or no answer within timeout_s.
    # Raises, a wrong server: ProtocolError (another protocol, or none), CodecError (garbled).
    # Closes its connection on every path, cancellation included.
```

### Servers

- `adapters.fetch`: `HttpsOnlyRedirects`, `MAX_REDIRECTS` — HTTPS redirects.
- `adapters.pumpkin`: `BINARY`, `INVARIANTS`, `LEVEL_DAT`, `OPERATOR_LEVEL`, `Toml`, `TomlValue`,
  `VANILLA_EQUIVALENTS`, `WORLD_DATA_VERSION`, `WORLD_GEN_SETTINGS`, `WORLD_LEVEL_VERSION`,
  `ops_json`, `pumpkin_config`, `pumpkin_defaults`, `pumpkin_toml`, `toml_document` — launch
  configuration and native files.
- `adapters.vanilla`: `HEAP`, `HOST_INDEPENDENCE`, `INVARIANTS`, `JAR`, `JAVA_ENV`, `LAUNCH_ENV`,
  `NO_NETWORK`, `OPERATOR_LEVEL`, `VANILLA_DEFAULTS`, `java_properties`, `java_version`, `ops_json`,
  `resolve_java`, `server_properties` — launch configuration and Java selection.
- `cache`: `CACHE_ENV` — cache environment variable.
- `install`: `describe`, `root_of` — Installation paths and descriptions.
- `runner`: `PROC` — Linux process information.

```python
class WorldPreset(StrEnum): FLAT                                # VOID only once verified on the Reference
class GameMode(StrEnum):    SURVIVAL, CREATIVE, ADVENTURE, SPECTATOR
class Difficulty(StrEnum):  PEACEFUL, EASY, NORMAL, HARD

@frozen
class ServerSpec:                   # invariants (not fields): offline, no encryption, no whitelist,
                                    # no pause-when-empty, no telemetry, no server icon, spawn protection 0,
                                    # no outbound (non-loopback) network connection, and
                                    # CONTROL_PLAYER ("control", Control's Bot) is an operator
    host: str                       # (host, port) is the Endpoint, and the server binds exactly it.
    port: int                       # host: a host address of spec.LOOPBACK (127.0.0.0/8, not its network
                                    # or broadcast address) as a dotted quad, else ValueError at
                                    # construction (and on dataclasses.replace). No default: a Run takes
                                    # both from runner.free_endpoint(), one per Instance
    motd: str = "mscts"
    max_players: int = 20
    view_distance: int = 2          # at most MAX_VIEW_DISTANCE (12, what a Bot's client_information
                                    # asks for: the server uses the smaller of the two), else
                                    # SpecError (a ValueError) at construction and on replace
    simulation_distance: int = 2
    world: WorldPreset = WorldPreset.FLAT
    seed: int = 0
    game_mode: GameMode = GameMode.SURVIVAL
    difficulty: Difficulty = Difficulty.PEACEFUL
    operators: tuple[str, ...] = ()
    compression_threshold: int = 256
    all_operators: tuple[str, ...]  # property: CONTROL_PLAYER, then `operators`, each once:
                                    # what every Adapter makes an operator (level 4), each with
                                    # its server's offline UUID (Pumpkin: sha256(name)[:16])

@frozen
class Build:                        # one build of a server, named as its publisher names it
    version: str                    # "26.3"; Pumpkin's own "0.2.0+26.3-26.51"; "nightly"
    commit: str | None = None       # the full commit, where the publisher names one
    # str(): "26.3", or "nightly 4426d11" (the commit's first 7 characters)

@frozen
class Release:                      # a build its publisher offers for download
    build: Build
    url: str                        # HTTPS
    sha1: str | None = None         # the publisher's own hash, where it publishes one (Mojang)
    size: int | None = None         # bytes, where the publisher states it

type Fetch = Callable[[str], Download]  # fetch.https_get, or a fake in tests

@frozen
class Source:                       # <root>/SOURCE.json: where the binary came from (ADR-0008)
    sha256: str                     # of the binary; every use verifies the binary by it
    size: int
    version: str | None = None      # its Build's; None only in a SOURCE.json from before #156,
    commit: str | None = None       # whose Build installed() reads from the binary (adapter.check)
    url: str | None = None          # downloaded from (its Release's URL) ...
    final_url: str | None = None    # ... which redirected here
    from_path: str | None = None    # or copied from this `--from` file (absolute)
    installed_at: str | None = None # ISO 8601, UTC
    build: Build | None             # property: Build(version, commit), None without a version

@frozen
class Installation:
    adapter: str                    # "vanilla"
    target: Target
    root: Path                      # <cache>/<adapter>/<minecraft_version>, absolute, immutable
    source: Source | None = None    # None only for one built by hand (tests)

@frozen
class LaunchPlan:
    argv: tuple[str, ...]
    cwd: Path
    env: Mapping[str, str]
    endpoint: Endpoint
    stop_stdin: bytes | None        # graceful stop via stdin (b"stop\n"); None → SIGTERM

class ProvisionError(RuntimeError): ...   # an Installation is missing, unverifiable, or not installable
class ShortCommitError(ProvisionError): ...  # a commit name of fewer than 7 characters (#206);
                                           # kept unchanged, without a --from hint
# The two refusals an Adapter reports with facts, worded once by mscts (#158):
class UnsupportedError(ProvisionError):  # (subject, *, target, actual=None)
    # "<subject> is not supported: [it is <actual>, and ]this mscts tests Minecraft <v>."
class UnavailableError(ProvisionError):  # (adapter, version, *, latest: Build)
    # "<a>@<v> is not available for download. The latest is <a> <latest>.\n"
    # + build_it_yourself(a)
def build_it_yourself(adapter: str) -> str: ...  # "Build it yourself and install it with:\n
                                    #   mscts adapter install <a> --from <file>"
def install_command(adapter: str, *, version=None, path=None) -> str: ...  # the exact command line
                                    # `mscts adapter install pumpkin@4426d11`, `... --from <file>`
class PrepareError(RuntimeError): ...     # prepare cannot produce a LaunchPlan that meets the contract

class Adapter(Protocol):
    name: str
    binary: str                     # the one file an Installation holds: "server.jar", "pumpkin"
    # No provision: an Adapter never installs (ADR-0008). It says where its builds are
    # (release) and what a file is (check); install.py owns Installations, so a third-party
    # Adapter is name + binary + release + check + prepare, and gets `mscts adapter install`,
    # --from, the prompt and verification for free. Runs and tests call
    # install.require(adapter, target, cache_dir).
    latest_aliases: frozenset[str]  # versions meaning the latest build, as None does: Pumpkin's
                                    # {"nightly"}; install_release maps them to None first
    def release(self, target: Target, version: str | None, fetch: Fetch) -> Release: ...
        # The latest build for target (version None), or the one `<name>@<version>` names,
        # read only through `fetch`. Facts only: install.py adds the --from hint to any other
        # ProvisionError. Otherwise ShortCommitError, UnsupportedError or UnavailableError: vanilla:
        # "vanilla@26.4 is not supported: this mscts tests Minecraft 26.3." (nothing fetched),
        # else the jar Mojang's version manifest lists for target (its version JSON checked
        # by the manifest's sha1); Pumpkin: the nightly, Build("nightly", <the commit the
        # `nightly` tag names>) whatever `version` is: only the file says whether it is the
        # build `version` names (install.py checks it). A commit of 1-6 hex characters is
        # refused with ShortCommitError before anything is fetched.
    def check(self, binary: Path, target: Target) -> Build: ...
        # The Build the file names, or ProvisionError unless `binary` is a server it can run
        # for target. A build for another Minecraft version: UnsupportedError, "<binary> is not
        # supported: it is vanilla 26.4, and this mscts tests Minecraft 26.3." (vanilla: the
        # jar's version.json id and protocol_version; Pumpkin: an ELF executable whose
        # "<version> (Commit: <short>/" string names target.minecraft_version after "+", and
        # the full commit, or None if built without one). Runs before any install lands.
    def prepare(self, installation: Installation, spec: ServerSpec,
                workdir: Path) -> LaunchPlan: ...                             # writes COMPLETE native config

# Adapter contract, checked by each Adapter's unit tests:
# - prepare writes into an empty or new workdir (creating it) and refuses a non-empty one
#   with PrepareError, before writing anything, so no stale
#   world/ban/icon state leaks between Instances;
# - the complete-config test is a golden file derived from the server's own pristine
#   first-run output, with every substitution documented;
# - argv[0] is an absolute path to the exact runtime (e.g. Java 25), never a bare name.
# - the server binds IPv4 only (Java Candidates: -Djava.net.preferIPv4Stack=true), because
#   readiness ownership reads /proc/net/tcp.
#   VanillaAdapter(*, java=None) takes the java launcher from `java`, else
#   $MSCTS_JAVA, else `java` on the harness PATH, with symlinks resolved. Its runtime image's
#   `release` file must name Target.java_major (read, not run: prepare stays hermetic), or
#   prepare raises PrepareError and writes nothing;
# - the server binds exactly (spec.host, spec.port), its only listener, and the LaunchPlan's
#   endpoint is Endpoint(spec.host, spec.port) (readiness proves the Instance owns it);
# - invariants live in one visibly named table, applied last;
# - a ServerSpec value the server cannot honour is refused with PrepareError naming the
#   field, before anything is written, never approximated. The fields a server honours
#   only for some values live in one named table (adapters/pumpkin/ LIMITS), and so does
#   every range its config types can hold: a value it cannot read back is refused too.
#   (Pumpkin's LIMITS today: `world` honoured for the WorldPresets it can write a save for,
#   FLAT; every Difficulty is honoured.)
# - a setting the server's config cannot express is written as the server's own native
#   files instead (ADR-0007): PumpkinAdapter.prepare writes world/level.dat and
#   world/data/minecraft/world_gen_settings.dat (adapters/nbt.py) in Pumpkin's 26.2 format
#   (DataVersion 4903), carrying the spec's world, seed and difficulty; golden-tested, each
#   value Pumpkin's own new-world value or vanilla's for the spec, every substitution
#   documented in level_dat().
# - the Fixture world has natural mob spawning off from the first tick (ADR-0013): prepare
#   writes fixture_world.game_rules() to fixture_world.GAME_RULES_DAT, stamped with the
#   server's DataVersion; tests/adapters/test_fixture_world.py checks every Adapter.
# - an Installation is written only by install.py (one rename, complete or not at all), is
#   never refreshed, and records its Source; install.py fetches only through the `fetch` it
#   is given (https_get by default), so unit tests stay hermetic.

# adapters/nbt.py: writes Java NBT files (never reads them). A Tag is Byte | Int | Long | Float |
# Double (frozen wrappers of one value) | str | List(items: tuple[Tag, ...]) | IntArray(values) |
# Mapping[str, Tag] (a Compound, in its key order). NbtError (a ValueError) for a value its tag
# cannot hold: out of range, a bool, a float not exactly a binary32, a mixed List, a string
# with U+0000 or outside the BMP or over 65535 bytes.
def encode(root: Compound) -> bytes: ...   # the root compound, named ""
def gzipped(root: Compound) -> bytes: ...  # one gzip member, mtime 0: the bytes depend on root alone

# adapters/fixture_world.py: the Fixture world's game rules, the same for every Adapter (ADR-0013)
WORLD_FOLDER = "world"  # the world folder every Adapter names in its config, under its cwd
GAME_RULES_DAT = f"{WORLD_FOLDER}/data/minecraft/game_rules.dat"
def game_rules(data_version: int) -> Compound: ...  # minecraft:spawn_mobs false; others default

# install.py: Installations (ADR-0008)
@frozen
class Installed:
    installation: Installation
    changed: bool                   # False: installed and verified already; nothing was done
    message: str                    # exactly what it did, or why it did nothing
def installed(adapter, target, cache_dir) -> Installation | None: ...
    # verified by the recorded sha256; None if absent; ProvisionError naming the fix
    # ("delete <root> and run `mscts adapter install <adapter>` again") if unrecorded or changed
type Clock = Callable[[], datetime]       # the time now, timezone-aware; utc_now() outside tests,
                                          # passed in from cli.main(..., now=) (function design)
def install_release(adapter, target, cache_dir, version: str | None, fetch: Fetch, *,
                    now: Clock = utc_now) -> Installed: ...
    # adapter.release(target, version, fetch), then fetch(release.url): the publisher's sha1
    # and size checked where it lists them; adapter.check in staging. Records the Release's
    # version with the commit the file names (the release's commit only finds the file; a
    # file naming none, where the release names one, is refused), and UnavailableError if
    # that is not the build `version` names. An UnsupportedError from check names what was
    # asked ("pumpkin's latest build (<url>)"), never the staging path, plus the --from hint.
    # Installed already:
    # a no-op when `version` is None or names the installed Build (its version, or 7+ first
    # characters of its commit), saying "To check for a newer build, delete <root> and install again.";
    # another version → ProvisionError naming the delete + `mscts adapter install <a>@<v>`, after
    # the Adapter's refusal of <v> first (vanilla@26.4 is not supported), never the binary.
    # A failed fetch (OSError, or an http.client.HTTPException such as a body
    # cut off midway) → ProvisionError naming the --from command.
def install_from(adapter, target, cache_dir, path: Path, *, now: Clock = utc_now) -> Installed: ...
    # records the file's sha256, path and the Build adapter.check reads from it
# install_command: adapters/base.py, re-exported here.
@frozen
class Terminal:
    stdin: TextIO                   # asked only if stdin.isatty()
    stdout: TextIO
def require(adapter, target, cache_dir, *, terminal: Terminal | None = None,
            fetch: Fetch = https_get, now: Clock = utc_now) -> Installation: ...
    # The one way a Run or a test gets an Installation (ADR-0008 §2): installed(...) if there;
    # else, only with a terminal whose stdin is a TTY, asks "<adapter> <version> is not
    # installed. Download its latest build (Y) or provision it yourself (N)?". Y:
    # install_release with the given clock, announcing each "downloading <url> ..."
    # and printing its message.
    # N: prints and raises ProvisionError naming `mscts adapter install <a> --from <file>`.
    # Anything else re-asks ("Please answer y or n."); end of input refuses, naming both
    # commands. No terminal (the default) or no TTY: ProvisionError at once naming
    # `mscts adapter install <a>` and the --from form; stdin is never read.

@frozen
class Instance:
    endpoint: Endpoint
    pid: int
    launched_ns: int
    ready_ns: int                   # monotonic ns just before the probe that made it ready started
    # instance.startup = ready_ns - launched_ns. ready_ns is taken just before the runner starts
    # the first probe that answers True with ownership, so none of that probe's own round trip
    # (connect, handshake, status) counts as startup (audit L6). The Instance was not ready when
    # the previous probe ran, so it became ready at most one poll (the previous probe plus
    # 20 ms) before ready_ns. Vanilla 26.3 never holds a status request while booting: it
    # fails the probe within a few ms, and the successful probe took 7 ms (worker L, measured).
    # A server that held its answer until ready would be credited up to that probe's
    # timeout_s early, the same rule for Reference and Candidate.
    log_path: Path

@asynccontextmanager
async def running(plan: LaunchPlan, *, ready: Callable[[Endpoint], Awaitable[bool]],
                  ready_timeout: float, stop_timeout: float = 10.0) -> AsyncIterator[Instance]: ...
# Readiness is an injected probe, polled until it returns True. In a Run it is the status
# ping answering Target.protocol_version (ADR-0004); tests inject simpler probes.
# An answer counts only if the Instance provably gave it (ownership): there are IPv4
# sockets listening at exactly the Endpoint, the same ones before and after that probe,
# and each is open in a process of the Instance's process group (any member, not just
# the leader). Otherwise polling goes on, and a RunnerError at ready_timeout names who held
# the socket ("held by pid N (name)") or says nothing listened at exactly the Endpoint.
# Read from /proc/net/tcp and /proc/<pid>/fd, so Linux only: elsewhere running raises
# RunnerError before launching; a non-IPv4 Endpoint host raises ValueError before launching.
# Not counted as the Instance's: wildcard (0.0.0.0) and IPv6 listeners (no /proc/net/tcp6
# here), and a socket shared through SO_REUSEPORT with any process outside the group.
# Stop, however the body ends (normally, exception, cancellation): stop_stdin + close stdin
# → SIGTERM → SIGKILL to the process group, each after stop_timeout (no stop_stdin: SIGTERM
# at once); then SIGKILL whatever is left of the group. A second cancellation while
# stopping SIGKILLs at once, and waits (at most 1 s) for the exit to be seen, so nothing,
# not even an unclosed transport, outlives running() when the event loop ends right after.
# How it stopped is logged on `mscts.runner`.
# Parent death (#3): a per-Instance record in cache_dir()/instances is locked by the
# harness before spawning. The child gets only plan.env plus MSCTS_INSTANCE_TOKEN,
# a fresh identity inherited by descendants; the record then stores pid and starttime.
# A SIGKILLed harness releases its lock. The next running() with the same cache sweeps
# unlocked records, SIGKILLing a group only after proving its session/group id, the
# leader's recorded starttime if it still exists, and an exact token in a member's
# /proc environ with stable starttime across that read. A surviving descendant must
# be no older than the recorded leader. Empty records cover death between spawn and
# recording the leader: the exact token and stable process identity prove the group.
# Locked records are skipped (including another Instance in the same harness).
# Normal shutdown removes the record. No watcher or preexec_fn is used.

class RunnerError(RuntimeError):    # could not launch, exited before ready, or not ready in time
    reason: str
    exit_code: int | None           # None: never launched; negative: killed by that signal
    log_path: Path
    log_tail: tuple[str, ...]       # the last 40 console lines

CONSOLE_LOG = "mscts-console.log"   # the Instance's console, in the plan's cwd
LOG_TAIL_LINES = 40
def log_tail(log_path: Path) -> tuple[str, ...]: ...  # the last LOG_TAIL_LINES lines of a console
    # (read from its last 64 KiB), or () if it cannot be read. RunnerError quotes it, and the
    # reference and candidate tiers show it for every Instance a failing test used.

def free_endpoint() -> Endpoint: ... # one Instance's own Endpoint: a random host 127.A.B.C
    # (A 1..254, B 0..255, C 1..254: ~16.5 million, none in 127.0.0.0/16) and a port free on
    # it a moment ago. Racy too, but two Instances share a host with odds of 1 in 16.5 million
    # (then they need the same port too), and ownership keeps a collision from ever making one
    # Instance answer for another.
```

### Groups, Transcripts, Comparison

- `compare`: `DivergenceKind` — Divergence classification.
- `groups.status`: `PING_PAYLOAD` — status ping payload; `STATUS_CACHE_S` — the longest vanilla
  keeps a built status (a join drops it sooner); `CACHE_WAIT_S` — how long `status/with-player`
  waits after the join (that interval plus one second, a margin for a lazy cache); its window compares no play packet (`observe(play=False)`);
  `with_player` — the `status/with-player` script.
- `groups.blocks`: `BUILDER` — the operator Bot that runs each command itself; `BUILDER_AT` —
  where Control puts it, clear of every block the Groups set; `CONTROL_AT` — where Control
  puts itself, likewise; `FEEDBACK_TIMEOUT_S`
  — how long it waits for a command's feedback; `PACKETS` — what a window compares;
  `DROP_MASKS` — the random fields of a dropped item's `add_entity`; `setblock`, `fill` and
  `clone` — the `blocks/setblock`, `blocks/fill` and `blocks/clone` scripts.
- `groups.blocks_player`: `DIGGER` — the Bot that digs and places; `WATCHER` — the Bot that
  receives the cracks and particles of a dig; `DIGGER_AT`, `WATCHER_AT` and `CONTROL_AT` — where
  the three stand, clear of every block a Group sets; `PACKETS` — what a window compares;
  `PLACE_CASES` and `ATTACHED_CASES` — what the placements of the two place Groups are;
  `dig_creative`, `place` and `place_attached` — the `blocks/dig-creative`, `blocks/place` and
  `blocks/place-attached` scripts.
- `groups.players`: `FIRST` — the player in the world first, who watches; `SECOND` — the
  player who joins, changes game mode and leaves next to it; `PACKETS` — what a window
  compares; `join_seen`, `leave_seen`, `mode_seen` and `server_full` — the
  `players/join-seen`, `players/leave-seen`, `players/mode-seen` and `players/server-full`
  scripts.
- `groups.movement`: `PACKETS` — what a window compares (`player_position`, `disconnect`);
  `LANDER_BARRIERS` — how
  many barriers the Bot that must not be kicked floats for; `too_fast`, `into_blocks`, `flying` and
  `before_teleport` — the `movement/too-fast`, `movement/into-blocks`, `movement/flying` and
  `movement/before-teleport` scripts.
- `groups.combat`: `FIGHTER` — the Bot that hits; `PACKETS` — what a window compares;
  `SPRINT_PACKETS` — what a sprinting hit's window compares; `SWEEP_PACKETS` — what the sweep's
  window compares; `PITCH_MASK` — the random pitch of a hurt mob's sound; `melee_mob`,
  `critical`, `knockback` and `sweep` — the `combat/melee-mob`, `combat/critical`,
  `combat/knockback` and `combat/sweep` scripts; `STRIKER` and `TAPPER` — the two Bots of
  `combat/immunity`; `ATTACKER` and `VICTIM` — the two Bots of `combat/pvp`; `PVP_PACKETS` and
  `PVP_SPRINT_PACKETS` — what its windows compare; `immunity` and `pvp` — the `combat/immunity`
  and `combat/pvp` scripts.
- `groups.combat_damage`: `VICTIM` — the Bot that is hurt; `PACKETS` — what a window compares;
  `Source` — one kind of damage (its damage type, and whether the marker deals it); `SOURCES` —
  the twelve kinds of damage the Groups compare; `damage_command` — the `/damage` command for
  a victim, a source and an amount; `damage_types` — the `combat/damage-types` script;
  `ARMOR_REDUCED` — the kinds of damage armor reduces; `Armor` — a set of armor (a material, an
  enchantment and the kinds of damage it meets); `ARMORS` — the six sets;
  `wear_commands` — the commands that put a set on a victim; `armor` — the `combat/armor` script;
  `Effect` — a status effect, its amplifier and the kinds of damage it meets; `EFFECTS` — the five the Group gives; `effect_command` — the
  command that gives one to a victim; `effects` — the `combat/effects` script;
  `Death` — a lethal source and the `show_death_messages` rule it is played with; `DEATHS` — the four
  the Group plays; `death` — the `combat/death` script.
- `groups.player`: `PACKETS` — what a window compares (the damage, the health, the entity data, sounds, `player_position`, the death and the respawn); `clock` — the clock that times the gap between a hit and the next window; `HIT_PACKETS` — what a window compares for a hit after the first; `FREEZING_PACKETS` — what a window compares for freezing (the hits and `player_position`); `FIRE_MASKS` — the Mask on the sounds' pitch; `fall`, `drowning`, `suffocation`, `void`, `fire` and `freezing` — the `player/fall`, `player/drowning`, `player/suffocation`, `player/void`, `player/fire` and `player/freezing` scripts.
- `groups.player_modes`: `MODE_PACKETS` — what a window compares for a game mode switch (the abilities, the game mode event, the tab list, and the entity data, attributes and locator bar change the watcher is sent); `DEATH_PACKETS` — what a window compares for a death; `DROP_MASKS` — the Masks on how a dropped item or orb moves and faces; `game_modes` and `death` — the `player/game-modes` and `player/death` scripts.
- `groups.chunks`: `WALKER` — the Bot whose chunks are compared; `PACKETS` — what a window
  compares (the walker waits `run.GROUP_TIMEOUT_S` for its view); `HELD_SYNCS` — how
  many barriers a window lasts after the walker holds its view; `VIEW_DISTANCE` and
  `FAR_VIEW_DISTANCE` — the view distances the Groups set (2, and 5 for
  `chunks/view-distance`); `SPAWN` and `SPAWN_AT` — the chunk and the place a joining player
  is put; `FAR` and `FAR_AT` — the chunk and the place `chunks/teleport` moves the walker to;
  `WALK` — the x of each step of `chunks/walk`; `Chunk` — a chunk's (x, z); `view` — the chunks
  vanilla sends for a view centre and distance (`ChunkTrackingView`); `join_view`,
  `view_distance`, `teleport` and `walk` — the `chunks/join-view`, `chunks/view-distance`,
  `chunks/teleport` and `chunks/walk` scripts.
- `groups._world`: `pin_joins` — set `respawn_radius` 0 and turn `player_movement_check` off,
  through Control, pushing their undos onto the Group's `AsyncExitStack` (`join/basic`, the
  `players` and `chunks` Groups). `CONTROL_AT` — where Control
  puts itself, out of the Bot's view; `SPAWN_AT` — where each Bot is put when its Group ends;
  `join_at_spawn` — join a Bot and push the `tp` that puts it back at the spawn; `fresh` — kill a
  Bot and respawn it, with full health and food and no immunity (the `player` and `combat_damage`
  Groups).
- `groups.chat`: `LISTENER` — the Bot in the world for every case, sent what the others say;
  `SPEAKER` — the Bot that speaks in `chat/player` and, as an operator, runs `chat/commands`;
  `JOINER` — the Bot that joins and leaves in `chat/join-leave`; `TALKER`, `OPERATOR` — the
  Bots of `chat/limits` that say the longest message and spam as an operator; `LONG`,
  `SECTION`, `SPAMMER` — the Bots it kicks; `SPAM_MESSAGES` — how many messages a Bot sends
  in one write to be kicked for spam, past the 10 that kick within one tick; `CHATTER` — the
  Bot that is not an operator and sends `UNDER_SPAM_MESSAGES` (9) in one write, never kicked
  for them; `FEEDBACK_TIMEOUT_S` — how long a Bot
  waits for a message or its kick; `PACKETS` — what a window compares; `player`, `commands`,
  `join_leave` and `limits` — the `chat/player`, `chat/commands`, `chat/join-leave` and
  `chat/limits` scripts.
- `run`: `status_version` — status version extraction.

```python
@frozen
class Event:
    t_ns: int                       # monotonic, relative to Transcript start
    bot: str
    packet: Packet                  # packet.direction tells sent vs received

@frozen
class Mark:
    t_ns: int
    label: str                      # a span's "<name>:start" / "<name>:end", or an
                                    # Observation window's OBSERVE_OPEN (then its names,
                                    # each after a space) / OBSERVE_CLOSE

@dataclass
class Transcript:                   # a plain data holder: no I/O
    group_id: str
    server: str                     # adapter name
    events: list[Event] = []        # (default_factory=list)
    marks: list[Mark] = []
    start_ns: int = time.monotonic_ns()   # (default_factory) the origin of every t_ns;
                                          # compare=False, it only anchors this process's clock
    def now_ns(self) -> int: ...    # monotonic ns since start_ns
    def record(self, bot: str, packet: Packet, *, t_ns: int) -> Event: ...
    # record keeps events ordered by t_ns, equal times in recording order (a received
    # frame is stamped on arrival but recorded when the Bot takes it); ValueError unless
    # 0 <= t_ns <= now_ns(). Connection is the only writer of events.
    # to_jsonl() / from_jsonl() — payload as hex, fields as JSON

class GroupContext:
    def __init__(self, endpoint: Endpoint, transcript: Transcript, *, timeout_s: float) -> None: ...
    endpoint: Endpoint
    control: Control                # an OperatorBot (ADR-0001), the same one on every read;
                                    # its Bot is one of the context's Bots (closed, synced
                                    # and drained with them, and named by raised_by)
    async def bot(self, name: str) -> Bot: ...   # Bot.connect(endpoint, TARGET, timeout_s=...),
                                                 # recording to the transcript; ValueError on a
                                                 # second Bot of the same name, or on
                                                 # CONTROL_PLAYER (Control's Bot)
    def span(self, name: str) -> AbstractAsyncContextManager[None]: ...   # Marks "<name>:start"/"<name>:end"
                                    # (no end Mark if the body raises: no Measurement)
    def observe(self, *names: str, until: str | tuple[str, ...] | None = None,
                bot: Bot | None = None, play: bool = True
                ) -> AbstractAsyncContextManager[None]: ...
                                    # an Observation window: on entry, every Bot in play
                                    # and not disconnected passes Bot.sync (all at once, so
                                    # what setup caused has arrived at every Bot, if the
                                    # setup waited for its feedback, as Control.run does;
                                    # #141), then
                                    # Marks OBSERVE_OPEN (then the names, each after a space;
                                    # play=False: OBSERVE_NO_PLAY, and no names or until);
                                    # when the body completes, every Bot in play and not
                                    # disconnected passes Bot.sync again (all at once; the
                                    # first error raises, as that Bot's failure), then a Mark
                                    # "OBSERVE_CLOSE <Bot name>"
                                    # per Bot, 1 ns after its barrier's last answer's arrival
                                    # (a Bot that passed none: once every barrier returned),
                                    # then an unnamed OBSERVE_CLOSE at that same time (it ends
                                    # the window of a Bot made later), then every Bot neither
                                    # closed nor disconnected drains (Bot.disconnected: the
                                    # Group's expect returned the server's disconnect, so a
                                    # kick it tests is no error; one the barrier or the drain
                                    # takes fails that Bot). A barrier covers what its own
                                    # Bot sent: a window that must hold another Bot's effect
                                    # waits for that effect's feedback before closing. A body that raises gets neither, so its window
                                    # runs to the Transcript's end. ValueError, nothing
                                    # marked: a window already open (no nesting), or a name
                                    # (in names or until) that is not in
                                    # Codec.names(PLAY, CLIENTBOUND) or is in HEARTBEAT.
                                    # With `until` (a packet name, or several: whichever
                                    # arrives first ends it, #270; none is a ValueError):
                                    # no barrier. Every Bot not
                                    # closed drains, then OBSERVE_CLOSE is stamped 1 ns after
                                    # the Event.t_ns (the arrival, never the time a Bot took
                                    # the packet; #88) of the first clientbound play packet
                                    # of those names `bot` (if given), else any Bot but Control,
                                    # received at or after the open Mark (Control's receipts
                                    # are never compared; the earliest arrival over the Bots,
                                    # whatever order they were recorded in). ValueError:
                                    # `bot` without `until`, or not one of this Group's Bots.
                                    # The body must last until it
                                    # has arrived: one that ends sooner fails as below.
                                    # Compare puts a packet stamped at a Mark's time
                                    # after the Mark, so the extra nanosecond keeps that
                                    # packet inside the window; the frames of one socket
                                    # read are stamped a nanosecond apart (Connection), so
                                    # the next frame, even of the same read, is outside, and
                                    # so is everything after it. None arrived:
                                    # ProtocolError naming the
                                    # packet (a Candidate's is a `mismatch` with a `failed`
                                    # Divergence, the Reference's an `error`, as for every
                                    # exception a Group raises), and no close Mark
    async def freeze(self) -> None: ...  # #23: control.run("tick freeze"); ValueError if the
                                    # Group froze already. end() unfreezes (a failure fails
                                    # the Group); after a failed Group, close() tries, and
                                    # logs a failure. CommandMissing (nothing sent): not
                                    # frozen, so nothing to unfreeze (#290)
    async def step(self, ticks: int = 1) -> None: ...   # #23: per tick, control.run(
                                    # "tick step 1") (marker, then barrier), then every Bot in
                                    # play passes Bot.sync at once, then Marks
                                    # "TICK_MARK<k> <Bot name>" 1 ns after each Bot's
                                    # barrier's last answer (a Bot that passed none: now) and
                                    # an unnamed "TICK_MARK<k>" now; k counts from 1 since the
                                    # freeze. Vanilla sends nothing when a step ends
                                    # (docs/research/2026-10-03-tick-step.md). ValueError:
                                    # ticks < 1, or not frozen
    async def end(self) -> None: ...     # #23: control.run("tick unfreeze") if frozen (raises,
                                    # setting left_frozen: #228); then #184:
                                    # Bot.refuse_queued_disconnect on every Bot
    async def close(self) -> None: ...   # unfreezes if still frozen (logged, not raised, and
                                    # sets left_frozen: #228), then closes every Bot; idempotent
    left_frozen: bool               # #228: end() or close() could not unfreeze the world
    def raised_by(self, error: BaseException) -> str: ...   # the Bot `error` came out of: the
                                    # one whose bot() connect raised it, or whose `failure`
                                    # it is; "" if none (the script itself raised it)

class Control(Protocol):
    async def run(self, command: str) -> tuple[Packet, ...]: ...   # the system_chats it answered
    async def leave(self) -> None: ...   # close Control's Bot, if it has joined; the next run
                                         # joins a new one (see OperatorBot)

class OperatorBot:                  # Control through a Bot called CONTROL_PLAYER, an operator
    def __init__(self, connect: Callable[[str], Awaitable[Bot]], transcript: Transcript,
                 *, timeout_s: float) -> None: ...
    async def run(self, command: str) -> tuple[Packet, ...]: ...
    # run(command), the command without its slash:
    # 1. ValueError, nothing sent, unless it starts with its name (not "", "/…" or " …").
    # 2. On first use, and the first after leave(): connect(CONTROL_PLAYER), join, sync, so
    #    nothing the join caused is taken for an answer.
    # 3. root_literals of the last `commands` tree the Bot received since it connected
    #    (else expect one: a Bot that left is not the one that counts): its
    #    name, then "tellraw", must be there, else CommandMissing(name), nothing sent. A
    #    tree root_literals refuses → ProtocolError, as the Bot's failure.
    # 4. send the command, then the marker `tellraw @s "<MARKER_PREFIX><n>"`
    #    (n counts this OperatorBot's runs from 1), then expect the system_chat whose raw
    #    bytes hold the token (text components are not decoded yet), then sync. Returns
    #    every system_chat that arrived from sending the command to the end of that sync,
    #    but the marker's answer, () if none: evidence for the Group (it can hold others'
    #    messages, such as a join message), never compared. Pumpkin often answers a
    #    command after its marker, but before the sync ends.
    # Vanilla runs a player's commands in order on one queue, so the marker answers after
    # the command has run; Pumpkin runs each command as its own task, so a command that
    # takes more than about a tick longer than the marker can land after run returns
    # (ADR-0010, amendment; docs/research/2026-10-01-control.md).
    async def leave(self) -> None: ...
    # leave(): close the Bot, if one has joined (else nothing, so twice is the same as
    # once); the next run joins a new Bot called CONTROL_PLAYER, which replaces the closed
    # one in the context (GroupContext.raised_by then names the new one). The marker
    # count goes on. The server drops the closed Bot's player a tick later: a Group that
    # needs it gone (an observed Bot joins an empty server) waits with
    # settle.until_no_player_online. A Fixture is then undone by a run that rejoins.

class GroupKind(StrEnum):           # ADR-0006; values "exact", "tick-exact", "statistical"
    EXACT, TICK_EXACT, STATISTICAL

type Script = Callable[[GroupContext], Awaitable[None]]

@frozen
class Group:
    id: str                         # "status/basic"
    run: Script
    requires: tuple[str, ...] = ()  # Group ids that must pass first (run.prerequisite_verdict)
    masks: tuple[Mask, ...] = ()
    spec: Callable[[ServerSpec], ServerSpec] = identity
    kind: GroupKind = GroupKind.EXACT

GROUPS: Mapping[str, Group]         # the registered Groups, by id, in registration order:
                                    # a read-only view; mscts.groups registers its own on import
def group(id: str, *, requires=(), masks=(), spec=identity,
          kind=GroupKind.EXACT) -> Callable[[Script], Script]: ...
    # the decorator: registers Group(id, the function, ...) and returns the function;
    # ValueError if `id` is registered already
def resolve(group_ids: Iterable[str], groups: Mapping[str, Group] = GROUPS
            ) -> tuple[Group, ...]: ...
    # the named Groups plus their prerequisites, each once, every one after its
    # prerequisites, else in the order given; KeyError (unknown id), ValueError (a cycle)

WHOLE_PACKET = "*"

@frozen
class Mask:
    packet: str                     # "minecraft:sound", in whatever State
    path: str                       # "pitch", "json_response.players.sample", or
                                    # WHOLE_PACKET (drop the packet); "[*]" is every index
                                    # of a list ("players.sample[*].id")
    reason: str
    # ValueError at construction: an empty packet or reason (blank counts as empty), a
    # malformed path, or a path not spelled exactly as a Divergence path would be (the
    # message gives the spelling), so a path copied from a Divergence is always valid.
    # Also a path that is an entity id of the clientbound packet in any State, or a
    # list of them (`Codec.entity_id_paths`; a list index fits EACH, and a Variant is
    # no step of a path): every Comparison names or numbers those instead, and the message
    # says so (#21, #116). A path around one (`set_entity_data` / `entries`) is still a Mask.

class Outcome(StrEnum): MATCH, MISMATCH, BLOCKED, ERROR

class Observability(StrEnum):       # ADR-0007; values "gameplay", "network traffic"
    GAMEPLAY, NETWORK_TRAFFIC
NETWORK_TRAFFIC_ONLY_PASSES = True  # the one place ADR-0007's rule is applied: the Report's
                                    # test cases and Score, and run.prerequisite_verdict
                                    # (#221), read it

ABSENT: Absent                      # the value on the side that has no such packet (or field)
MASKED = "<masked>"                 # what a field Mask shows in place of a value (not None),
                                    # on both sides, so presence still counts (step 3)

@frozen
class Divergence:
    bot: str
    index: int                      # position in the Bot's normalized stream, from 0: the
                                    # reference stream for missing and field, the candidate
                                    # stream for unexpected; 0 for bot
    kind: Literal["bot", "missing", "unexpected", "field", "failed"]
    packet: str                     # the packet name ("" for bot and failed)
    path: str | None                # None: the whole payload (and always for bot/missing/unexpected)
    reference: object               # the packet's value, or ABSENT (a chunk, light update
    candidate: object               # or forgotten chunk one side has: "chunk <x> <z>", step 4)
    test_case: str                  # the test case it was found in (test_case(): the
                                    # packet's for missing, unexpected and a whole payload;
                                    # the path's, the raw one for network traffic, for any
                                    # other field one); "" for bot and failed (Group-level)
    observability: Observability = Observability.GAMEPLAY
    # network traffic: a `field` Divergence between raw values whose canonical forms are
    #   equal (path and values are the raw ones), or a missing or unexpected
    #   chunk_batch_start or chunk_batch_finished (step 1); gameplay: every other Divergence,
    #   so every bot and failed one (run.judge's `failed` keeps the default; __post_init__
    #   raises ValueError for a bot or failed one that is network traffic, #221).
    # bot: the Bot has Events (sent or received) in only one Transcript; reference and
    #   candidate are its Event counts, ABSENT on the other side. Its stream's Divergences
    #   follow, against an empty stream. (A Bot that only sent would otherwise go unseen.)
    # missing: a reference packet the alignment left unmatched (candidate is ABSENT);
    # unexpected: a candidate packet it left unmatched (reference is ABSENT);
    # field: a difference between two matched packets, or (path TICK_PATH, the two ticks
    #   as int values, the packet's test case) one packet a tick-exact Group got on
    #   different ticks (#23), followed by the two packets' differences;
    # failed: the Group failed on the Candidate (made by run.judge, never by compare):
    #   bot the Bot the failure came out of (GroupError.bot; "" only if the script
    #   itself raised it), index 0, reference ABSENT, candidate the failure ("TimeoutError: ...").

@frozen
class Verdict:
    group_id: str
    outcome: Outcome
    divergences: tuple[Divergence, ...] = ()
    detail: str = ""
    test_cases: tuple[str, ...] = ()  # every test case compared, matched or not, and each
                                      # field of a missing reference packet (#101), sorted
                                    # and unique (Comparison semantics step 5); () when
                                    # error or blocked. run.judge keeps compare's. Not a
                                    # test case no compared pair names (#330).
    omitted: int = 0                # Divergences a report.json left out (#254); 0 from compare
    @property
    def gameplay(self) -> tuple[Divergence, ...]: ...     # the gameplay Divergences, in
                                    # order: what compliance scores count. A Verdict whose
                                    # Divergences are all network traffic is still `mismatch`
    @property
    def differing(self) -> dict[str, Observability]: ... # each test case with a
                                    # Divergence: GAMEPLAY if any of its Divergences is,
                                    # else NETWORK_TRAFFIC. Every other one is the same.

OBSERVE_OPEN = "observe:open"       # the Mark that opens an Observation window; a window
                                    # narrowed to packets has their names after it:
                                    # "observe:open minecraft:block_update"; a window
                                    # that compares no play packet has OBSERVE_NO_PLAY
                                    # ("-") after it
OBSERVE_NO_PLAY = "-"               # what follows OBSERVE_OPEN when observe(play=False):
                                    # no packet has this name, so no play packet is taken
TICK_PATH = "(tick)"                # #23: the path of the field Divergence of a packet
                                    # a tick-exact Group got on different ticks; the Report
                                    # shows it before the values ("(tick): vanilla sends 1, ...");
                                    # no field path holds a parenthesis
TICK_MARK = "tick:"                 # #23: "tick:<k>" ends tick k of a tick-exact Group:
                                    # for one Bot with its name after it ("tick:3 alice"),
                                    # without for every Bot with no Mark of its own
OBSERVE_CLOSE = "observe:close"     # the Mark that closes it: for one Bot with its name
                                    # after it ("observe:close alice"), without for every Bot
                                    # with no close Mark of its own in that window
HEARTBEAT: Mapping[str, str]        # packet name -> reason: the play packets a window never
                                    # compares (keep_alive, set_time, award_stats; evidence in
                                    # docs/research/2026-09-30-observation-window.md)
HEARTBEAT_PAYLOADS: Mapping[tuple[str, bytes], str] # (packet name, first payload bytes) ->
                                    # reason: the play packets a window never compares
                                    # when their payload starts with those bytes, though
                                    # their name alone does not make them heartbeat
                                    # packets: vanilla's latency-only player_info_update
                                    # (actions byte 0x10; docs/research/
                                    # 2026-10-03-latency-broadcast.md)
def is_heartbeat(packet: Packet) -> bool: ... # HEARTBEAT names it, or HEARTBEAT_PAYLOADS
                                    # names it with the bytes its payload starts with
UNORDERED: Mapping[str, str]        # packet name -> reason: the packets (any State) whose
                                    # unordered lists every Comparison sorts first, stably, by
                                    # the key of the client's map or set, so their order is no
                                    # Divergence at all: update_tags (vanilla's order changes per
                                    # boot; docs/research/2026-10-01-control.md), login's
                                    # dimension_names, update_attributes' attributes,
                                    # update_recipes' property sets and update_advancements'
                                    # removed ids and progress (#30, #106)
RANDOM_FIELDS: Mapping[str, str]    # "<packet>.<path>" -> reason: the fields vanilla draws at
                                    # random, or reads from its clock, on every run, whose
                                    # values no exact Group compares (ADR-0011):
                                    # minecraft:login_finished.session_id (same evidence),
                                    # minecraft:sound.seed and minecraft:sound_entity.seed
                                    # (docs/research/2026-10-01-block-world-events.md), and
                                    # update_advancements' progress[*].criteria[*].obtained
                                    # (#106), and minecraft:player_chat.timestamp
                                    # (docs/research/2026-10-04-chat.md)
ENTITY_UUIDS: Mapping[str, str]     # "<packet>.<path>" -> reason: the fields that hold an
                                    # entity's UUID, which every Comparison numbers by first
                                    # appearance, but not a player's (#21):
                                    # minecraft:add_entity.entity_uuid

def window_takes(transcript: Transcript, event: Event) -> bool | None: ...
    # Whether the Comparison takes a clientbound Event by the windows its Bot sees;
    # None if it sees none (then every Packet is compared). For timeline (#162).

def compare(reference: Transcript, candidate: Transcript,
            masks: Sequence[Mask]) -> Verdict: ...
    # Names each Bot's entity ids whose add_entity came outside the windows by type and
    # position at its first add_entity before the window (`pig@(1.5, -60.0, 7.5)`, after
    # the Masks), a player by UUID
    # (`player <uuid>`), and numbers its other entity ids and
    # ENTITY_UUIDS `#1`, `#2`, ... in the order they first appear in the packets it
    # compares, never those outside the windows (Comparison semantics, between steps 2
    # and 3), so Divergence paths and values show a name or `#<n>` where the packets had ids.
    # Masks the RANDOM_FIELDS, then applies `masks`. Every Bot is compared but Control's
    # (spec.CONTROL_PLAYER): its Events stay in the Transcript.
    # ValueError if the Transcripts are of different Groups; TypeError if fields hold
    # a value outside the codec value model. Divergences are grouped by Bot in name order,
    # then in stream order, and within a packet in path order: its gameplay Divergences
    # first, then its network traffic ones.
    # A packet's value (for missing / unexpected) is its fields, or its payload as hex.
    # Payload hex shows at most PAYLOAD_SHOWN_BYTES (256) bytes, then `(N more bytes)`
    # (#151); every byte is still compared. Those are the first bytes, except in a `field`
    # Divergence of two payloads both longer than that: both then start PAYLOAD_LEAD_BYTES
    # (16) before the first byte that differs, down to a multiple of 16, after
    # `(N bytes before)`.
    # Field paths: identifier keys joined by dots, list indices in brackets, and any other
    # key as a JSON string in brackets: `players.sample[0].name`, `m["a.b"]`.

def test_case(state: State, packet: str, path: str | None) -> str: ...
    # The name of the test case that compares `path` (spelled as a Divergence path; None
    # for the packet as a whole) of the clientbound `packet` in `state`, by the scheme in
    # Comparison semantics: `status_response.players.sample[].name`, `play:keep_alive.id`.
    # ValueError if `path` is malformed or not spelled as a Divergence path would be.
```

Waiting for the players of a Group to leave (`settle.py`, #97). `Bot.close()` only
closes the socket and a server removes the player later (vanilla: on its next tick), so
whatever plays on an Instance after Bots left it (a Run before its next Group, a Group
after its Control Bot left) waits first. It asks only the status, so it works the same
on every Candidate (ADR-0001), and it imports no Group or Run, so `group.py` can use it
(the evidence is `docs/research/2026-10-02-settle.md`):

```python
SETTLE_INTERVAL_S = 0.02            # between status polls while players are still online
SETTLE_TIMEOUT_S = 2.0              # an Instance's time to have none (~10x vanilla's worst, 197 ms)

class PlayersStillOnline(Exception):  # str(): "2 players still online after waiting 2 s: 'watcher', 'control'"
    online: int                     # what the last status said
    names: tuple[str, ...]          # the `players.sample` names it listed, if any
    deadline_s: float

async def until_no_player_online(endpoint: Endpoint, *,
                                 deadline_s: float = SETTLE_TIMEOUT_S) -> None: ...
    # Polls the status (a Bot's status request, as status/basic sends it, on a connection of
    # its own) every SETTLE_INTERVAL_S until `players.online` is 0. PlayersStillOnline once
    # deadline_s has passed with players still online. A status that cannot be read (refused,
    # closed, late, not a status, no integer players.online) counts as empty: whatever plays
    # next meets the same failure and reports it. The deadline is checked between polls, not
    # by cancelling one, and each poll bounds itself by deadline_s, so a server that never
    # answers costs two. A poll cancelled from outside still leaves no socket open (#133).
```

Running Groups (`run.py`):

```python
GROUP_TIMEOUT_S = 10.0              # each Bot operation (Bot timeout_s)
READY_TIMEOUT_S = 120.0             # an Instance's readiness (a cold vanilla boot)
STOP_TIMEOUT_S = 30.0               # each stop step

class GroupError(Exception):        # the Group raised against one Instance; __cause__ is
    transcript: Transcript          # what it raised; str() describes it ("TimeoutError: ...")
    bot: str = ""                   # the Bot it came out of (GroupContext.raised_by)
    left_frozen: bool = False       # #228: GroupContext.left_frozen: the Instance is unusable

@frozen
class Server:                       # one side of a Run
    adapter: Adapter
    installation: Installation
    name: str                       # property: adapter.name, as Transcripts record it

@frozen
class Attached:                     # one side of a Run: an Instance someone else launched,
    name: str                       # owns and stops (e.g. a test session's shared Reference);
    spec: ServerSpec                # the ServerSpec it was launched from
    endpoint: Endpoint              # property: spec's host and port

type Side = Server | Attached

async def run_group(group: Group, endpoint: Endpoint, *, server: str,
                    timeout_s: float = GROUP_TIMEOUT_S) -> Transcript: ...
    # one Instance; closes every Bot however it ends; GroupError if the Group raised, or if
    # GroupContext.end (called once the Group completes, before closing) refused a disconnect
def judge(group: Group, reference: Transcript | GroupError,
          candidate: Transcript | GroupError) -> Verdict: ...
    # The Verdict rule (audit H3): a Candidate failure (a GroupError on the Candidate and
    # none on the Reference, whatever its cause's type, #222) is `mismatch`: a `failed`
    # Divergence first, then what compare finds in the Transcripts so far (e.g. the
    # undecodable frame, by payload), whatever the Masks. CommandMissing on the Candidate
    # (it lacks a command Control needs, in setup or from an undo callback) is that
    # `mismatch` too, its `failed` Divergence "missing /<root>" (#284). If compare
    # raised (any Exception, so the Run goes on to the next Group, #174), compare(reference,
    # reference, masks) decides: it does not raise, so the Candidate's data did, and it is
    # `mismatch` led by a `failed` Divergence from no Bot, "the Comparison failed:
    # OverflowError: ..." (#239); it raises too, so it is `error` with that detail. `error`
    # also if the Reference failed (CommandMissing included). Else compare(reference,
    # candidate, masks). A Candidate failure's Verdict lists the test cases of
    # compare(reference, reference, masks) besides what compare found (#262), which the
    # Report fails; if that self-comparison raises, it is `error` naming it, whichever
    # way the Candidate failed. The trade: a
    # mscts bug that shows only on the Candidate is that Candidate's `mismatch`; the
    # Self-check is what catches it.
def prerequisite_verdict(group: Group, verdicts: Mapping[str, Verdict]) -> Verdict | None: ...
    # None if every `requires` passed: a `match`, or a `mismatch` with Divergences, none
    # gameplay (ADR-0007, #221). Else, naming the prerequisite that decides: `error`
    # ("prerequisite X was error", audit L2) if one is an `error`; `blocked` ("... was not
    # run" / "was blocked") if one was not run or is blocked; else, each a `mismatch`, a
    # `mismatch` led by a `failed` Divergence from no Bot, "prerequisite X was mismatch"
    # (#285, review B), the detail "the Candidate failed: " and that.
async def run(groups: Sequence[Group], reference: Side, candidate: Side, *,
              workdir: Path, repeat: int = 1) -> list[Verdict]: ...
    # one Verdict per Group per repetition, repetition after repetition, in the order
    # given; a Group is not played on the Candidate unless its prerequisites passed
    # earlier in the same repetition (prerequisite_verdict). #285: if that is a
    # `mismatch`, it is played on the Reference alone, as for #266 below, and lists that
    # play's test cases (the Report fails them); an `error` one is played on neither side.
    # A Run makes no `blocked` Verdict: each prerequisite must be listed before (below).
    # One Instance pair per distinct ServerSpec the Groups' `spec`
    # make, each side at its own free_endpoint(), launched together when first needed,
    # readiness by status_probe, kept for every repetition, stopped however the Run ends.
    # An Attached side is played at its endpoint for every Group, never started or
    # stopped; the same code path otherwise (judge, prerequisite_verdict, repetitions).
    # Settling (#97): before a Group plays, both Instances are waited on at once with
    # `until_no_player_online(endpoint, deadline_s=SETTLE_TIMEOUT_S)` (settle.py, above).
    # A side that is still not empty means the Group is not played there, and its
    # Verdict says who is still online. The Reference's failure is `error`, and neither side
    # is played: "the Reference
    # had 2 players still online after waiting 2 s: 'watcher', 'control'" (the Candidate's
    # sentence after a "; " if it had players too). The Candidate's alone is `mismatch`
    # (audit H3: a Candidate failure is never `error`): a `failed` Divergence (bot "",
    # candidate "2 players still online after waiting 2 s: 'watcher', 'control'"), detail
    # "the Candidate failed: ...". A wait that raises anything else (#114) is never raised
    # out of the Run, and the other side's wait runs to its end (gather with
    # return_exceptions): on the Reference it is `error`, "the Reference failed: the wait
    # for no player online failed: <Type>: <message>"; on the Candidate alone it is
    # `mismatch` as above, whatever its type (#222, as in judge), with "the wait for no
    # player online failed: <Type>: <message>" as the `failed` Divergence's candidate and
    # after "the Candidate failed: ". If both
    # sides fail, the detail joins both sentences with "; ": "the Reference had ...; the
    # Candidate failed: the wait ...". A BaseException that is not an Exception (a
    # cancellation from inside a wait) is raised once both waits are done. The wait is
    # not part of `elapsed_s`.
    # #228: an Instance a Group left frozen (GroupError.left_frozen) plays no later Group,
    # decided before the wait. The Reference's: each is `error`, "the Reference is
    # unusable: <group id> left its world frozen" (the Candidate's likewise,
    # after a "; " if both are). Only the Candidate's: each is `mismatch`, led by a
    # `failed` Divergence "<group id> left its world frozen", so the Score
    # counts it (an `error` is not scored, and would reward breaking the world); only
    # the Reference is waited on then.
    # #266: when only the Candidate's side is not compared (unusable, or not empty), the
    # Group is played on the Reference alone, and its `mismatch` lists the test cases of
    # compare(reference, reference, masks), which the Report fails, as for #262; the
    # Reference raising, or that self-comparison raising, is `error` as in judge. Its
    # Measurements and `elapsed_s` are the Reference's play; no Transcripts are kept.
    # NotImplementedError for a statistical Group (M6b); ValueError for one
    # listed twice, listed before a Group it requires or requiring one not listed (resolve
    # orders them; review B LOW-R2), or whose `spec` does not give an Attached side's spec
    # (host and port aside: it would run against the wrong config), before anything
    # starts; RunnerError
    # if an Instance cannot start.
async def selfcheck(group_ids: Sequence[str], *, reference: Server, workdir: Path,
                    repeat: int = 20, attached: Attached | None = None) -> list[Verdict]: ...
    # run(resolve(group_ids), attached or reference, reference, ...): two Reference
    # Instances (one of them `attached`, if given, which must be of reference's Adapter:
    # ValueError), the prerequisites included; KeyError (unknown id) before anything
    # starts. G2: all `match`.
    # (The `mscts selfcheck` command wraps it; the caller gets `reference`'s Installation with install.require.)
```

Comparison semantics. Start strict and relax only when a Self-check
proves it necessary:

1. Take clientbound packets per Bot, in order. A packet's key is its
   (State, name): same-named packets of different States (`disconnect`,
   `custom_payload`) are different packets; the key of a packet about
   one chunk (`level_chunk_with_light`, `light_update`,
   `forget_level_chunk`) adds its position (step 4). Not compared, on
   purpose:
   - serverbound packets. They are the Group's own actions and the
     Bot's automatic answers. They differ between Instances by design
     (the handshake names each Instance's own Endpoint), and any
     difference a server caused in them shows up first in what that
     server sent;
   - timestamps and Marks, which are timing data for Measurements;
   - the interleaving of different Bots' packets, which is timing too;
   - everything Control's Bot (`spec.CONTROL_PLAYER`, `control`)
     received: it sets the world up as an operator, and its Events stay
     in the Transcript;
   - in a Transcript with **Observation windows**, the play packets they
     do not observe. A window opens at an `observe:open` Mark and ends, for
     a Bot, at its first `observe:close <that Bot>` Mark before the next
     `observe:open` Mark; with none, at its first `observe:close` Mark
     naming no Bot; with neither, at the next `observe:open` Mark, or at
     the end of the Transcript if none follows (the Group raised inside
     it). It observes
     every play packet that arrived (`t_ns`) at or after its open Mark and
     before its end, except the heartbeat packets (`compare.is_heartbeat`),
     and only the packets it names if its open Mark names any. Status,
     login and configuration packets are compared whole, and a Transcript
     with no window is compared whole. Each side is windowed by its own
     Marks. A packet a window leaves out is no test case, and a Bot with
     Events only outside the windows still counts as present;
   - the order of the lists `compare.UNORDERED` names, which every copy
     of a packet (raw and canonical) has sorted before anything else, so
     their order is no Divergence at all, and paths, Masks included,
     count the sorted lists. `configuration` and `play` /
     `minecraft:update_tags`: `tagged_registries` is sorted by
     `registry`, and each registry's `tags` by `tag_name`, both stably;
     each tag's `entries` keep their order. Vanilla sends both in an
     order that changes from one boot to the next (#17: the registry
     order changed in 2 of 5 boots and the tag order in 9 of 15
     registries between two; `javap` on the 26.3 server:
     `TagNetworkSerialization.serializeTagsToNetwork` collects with
     `Collectors.toMap`, a `HashMap` keyed by the registry's
     `ResourceKey`, and `serializeToNetwork(registry)` fills a
     `HashMap<Identifier, IntList>` from `registry.getTags()`; entries
     come from `TagLoader.tryBuildTag`'s `LinkedHashSet` in tag-file
     order, so they are the same every boot). The client decodes both
     into maps. Evidence, with `javap -c -p -constants -v` on the same client
     jar: `ClientboundUpdateTagsPacket.STREAM_CODEC` is
     `ByteBufCodecs.map(IdentityHashMap::new,
     ResourceKey.REGISTRY_STREAM_CODEC, NetworkPayload.STREAM_CODEC)`,
     and `TagNetworkSerialization$NetworkPayload.STREAM_CODEC` is
     `ByteBufCodecs.map(HashMap::new, Identifier.STREAM_CODEC,
     ID_LIST_STREAM_CODEC)` with `ID_LIST_STREAM_CODEC` =
     `VAR_INT.apply(collection(IntArrayList::new))`. `ByteBufCodecs.map`'s
     decoder (`ByteBufCodecs$28.decode`) reads the count, then `Map.put`s
     each key and value in turn, so a repeated name keeps its last value.
     Registry keys come from `ResourceKey.createRegistryKey`, which
     interns them (`ResourceKey.create` through a `computeIfAbsent`
     cache), so the `IdentityHashMap` is keyed by name. Both maps compare
     by `Map.equals`, order-free, while an `IntArrayList` compares in
     order. A stable sort keeps each name's values in their order, so two
     encodings with equal sorted forms give each name the same last
     value, and decode to equal maps. (Not every equal pair is caught: a
     name repeated on one side only stays a Divergence.)
     `play` / `minecraft:login`: `dimension_names` is sorted by name.
     Vanilla sends them in an order fixed per boot (#30: the nether and
     the end swapped between two Instances; `javap` on the 26.3 server:
     `MinecraftServer.createLevels` puts the overworld first, then
     iterates `MappedRegistry.byKey`, a `HashMap` keyed by `ResourceKey`,
     which defines no `hashCode`). The client reads them into a `HashSet`
     (`ClientboundLoginPacket.STREAM_CODEC`: `ByteBufCodecs.collection(
     Sets::newHashSetWithExpectedSize)`).
     `play` / `minecraft:update_attributes`: `attributes` is sorted by
     `attribute`, stably; each attribute's `modifiers` keep their order.
     Vanilla sends them in an order that changes from one join to the
     next (#30: 14 of 20 plays; `javap` on the 26.3 server: `AttributeMap`
     keeps them in fastutil hash collections, `attributesToSync` an
     `ObjectOpenHashSet` of `AttributeInstance`, which defines no
     `hashCode`, and `attributes` an `Object2ObjectOpenHashMap` that
     `getSyncableAttributes` iterates). The client reads a list, but
     applies each entry to the entity's instance of its attribute
     (`ClientPacketListener.handleUpdateAttributes`:
     `AttributeMap.getInstance`, then `setBaseValue`, `removeModifiers`,
     and `addTransientModifier` for each modifier), so a repeated
     attribute ends with its last entry, which the stable sort keeps last.
     `play` / `minecraft:update_recipes`: `property_sets` is sorted by
     `property_set_id`, and each set's `items` by item id, both stably;
     `stonecutter_recipes` keep their order. Vanilla sends both in an
     order fixed per boot (#30: two Instances sent the same 9 sets in
     another order, and another item order in 8 of them, while their 351
     stonecutter recipes came in the same order; `javap` on the 26.3
     server: `RecipeManager` collects the sets with
     `Collectors.toUnmodifiableMap` and `RecipePropertySet.create` each
     set's items with `Collectors.toUnmodifiableSet`, whose iteration
     order is salted per JVM, and `Item` defines no `hashCode`). The
     client reads them into a map of sets
     (`ClientboundUpdateRecipesPacket.STREAM_CODEC`:
     `ByteBufCodecs.map(HashMap::new, ...)`, and
     `RecipePropertySet.STREAM_CODEC` maps the item list through
     `Set.copyOf`), so a repeated set ends with its last items.
     `play` / `minecraft:update_advancements`: `removed` is sorted by id,
     and `progress` by `id`, with each one's `criteria` by `criterion`,
     all stably; the added `advancements` keep their order. Vanilla
     sends them in hash order (`javap` on the 26.3 server:
     `PlayerAdvancements.flushDirty` collects the removed ids into a
     `HashSet` and the progress into a `HashMap` keyed by `Identifier`,
     and `AdvancementProgress` keeps its criteria in a `HashMap`). The
     client reads them into a set and maps
     (`ClientboundUpdateAdvancementsPacket.STREAM_CODEC`: the removed ids
     into a `LinkedHashSet`, the progress with `ByteBufCodecs.map(
     HashMap::new, ...)`, and `AdvancementProgress.STREAM_CODEC` the
     criteria the same way), so a repeated id or criterion ends with its
     last value. The added advancements are read into a list.
     `play` / `minecraft:level_chunk_with_light` (#22): `heightmaps` is
     sorted by the type the client reads (an id it does not know reads as
     0, `WORLD_SURFACE_WG`: `Heightmap$Types` decodes through
     `ByIdMap.continuous` with `OutOfBoundsStrategy.ZERO`), and
     `block_entities` by position (y, z, x), both stably. Vanilla sends
     both in hash order (#30: two Instances sent the heightmaps in another
     order; `javap` on 26.3: `ClientboundLevelChunkPacketData` collects
     the heightmaps with `Collectors.toMap`, a `HashMap` keyed by the
     enum, and iterates `LevelChunk.getBlockEntities()`, an
     `Object2ObjectOpenHashMap` keyed by `BlockPos`). The client reads
     the heightmaps into an `EnumMap` (`ByteBufCodecs.map(EnumMap::new,
     ...)`), so a type sent twice ends with its last value, and keeps
     block entities in a map keyed by `BlockPos`:
     `LevelChunk.replaceWithPacketData` loads each one sent in turn, so
     those sent for one position keep their order.
   - the order of packets about different chunks, and where they fall
     among packets whose handling reads no chunk. A *chunk packet* is a
     `level_chunk_with_light`, `light_update` or `forget_level_chunk`:
     the client applies each to the chunk at its position (a chunk with
     `ClientChunkCache.replaceWithPacketData`, light with
     `ClientLevel.queueLightUpdate`, a forgotten chunk with
     `ClientChunkCache.drop` and `queueLightRemoval`). A *run* is the packets
     between two that are neither chunk packets nor in
     `compare._CHUNK_NEUTRAL`:
     `chunk_batch_start` and `chunk_batch_finished` (their handlers feed
     only `ChunkBatchSizeCalculator`), the heartbeat packets (with the
     latency broadcast, `compare.is_heartbeat`, whose handler only sets
     each player's latency) and `pong_response`, and the entity packets whose handlers set the
     entity's fields (`add_entity`, `move_entity_pos`, `move_entity_pos_rot`,
     `move_entity_rot`, `rotate_head`, `set_entity_motion`,
     `update_attributes`, `remove_entities`, `bundle_delimiter`; an
     entity's chunk being loaded decides only whether it ticks, and
     either order ends with the same), `set_health` and `set_experience`
     (they set the player's health, food and experience bar), and
     `set_entity_data` with no sleeping position (entry 14; #294, since
     Pumpkin sends these three between its batches). The `move_entity_*` handlers do
     read blocks once (`Entity.setOnGround` → `checkSupportingBlock`, the
     block the entity stands on until it next moves); keeping them
     neutral is an accepted trade-off, since ending runs there brings
     back false mismatches between racing batches. Each run becomes its chunk
     packets, sorted by position, x then z, stably, so the packets about
     one chunk keep their order, then its other packets in their order
     (`compare._by_position`), so a neutral packet lands in the same place
     whether it came before the run's first chunk or after it (#122's
     re-review); indices count the sorted stream. So a
     chunk never moves across a packet about its own position, nor
     across any packet whose effect on the client depends on the order:
     every other packet ends a run, among them `entity_position_sync` and
     `teleport_entity` (their handlers snap or interpolate by
     `ClientLevel.isTickingEntity`), `set_entity_data` with a sleeping
     position (the entity's position comes from the bed block there,
     `LivingEntity.setPosToBed`), `entity_event`, the block packets and
     `chunks_biomes`. The runs are found in a Bot's whole clientbound
     stream, before windows, their narrowing or a `*` Mask leave anything
     out, since the client applies every packet in turn. Vanilla sends a
     batch's chunks nearest first, those at one distance in the
     iteration order of a `LongOpenHashSet` of pending chunks, and which
     of them are ready for a batch races between two Instances (`javap`
     on the 26.3 server: `PlayerChunkSender.sendNextChunks`); it sends the
     light updates of one tick in the iteration order of
     `ServerChunkCache.chunkHoldersToBroadcast`, a `ReferenceOpenHashSet`
     (`docs/research/2026-10-02-chunks-light.md`). So which chunks a batch
     holds is network traffic: a `chunk_batch_start` or
     `chunk_batch_finished` only one side sent is a network traffic
     Divergence, and so is another `batch_size`, which the canonical form
     of `chunk_batch_finished` leaves out (step 2). The client feeds it
     only to the rate it asks the server for
     (`ChunkBatchSizeCalculator.onBatchFinished`, then
     `chunk_batch_received`).
2. **Canonicalize** values the vanilla client treats as equal: text
   component `"x"` ≡ `{"text": "x"}`, JSON key order, and similar.
   Canonicalization encodes a protocol equivalence. It is not a Mask,
   and it is a classifier, not an eraser (ADR-0007): the raw fields are
   diffed too, and a raw difference whose canonical values (before the
   Masks) are equal at its path is reported as a **network traffic** `field`
   Divergence, with the raw path and values. Where the canonical form is
   shaped unlike the raw fields (a chunk's sections), the canonical value
   compared is the one the raw path is part of (`compare._COVERS`). A raw field holding JSON
   text (`_JSON_TEXT`: the status `json_response`) is diffed as its parsed,
   not yet canonical JSON value, so such a Divergence has its JSON path
   and values (`json_response.enforceSecureChat`, absent vs `true`);
   only when the two parsed values are equal (a pure JSON spelling: key
   order, whitespace, escapes) is it the whole text. Where the canonical
   values at a path differ, the gameplay Divergences under it (or a
   Mask) stand for it, so a re-spelling inside a field that also has a
   gameplay or masked difference is not reported separately (nor is a
   JSON spelling beside a difference of JSON value). Masks
   apply to the raw fields too, where their paths reach. Every other
   Divergence is **gameplay**. The canonical table lives in
   `compare.py` (`_CANONICAL`), keyed by (State, packet name) of a
   clientbound packet. An entry is admitted only when
   the Reference's own decoder reads both encodings into equal values
   *by definition of the format*, never merely through lenient error
   handling, and it cites its evidence. Anything else stays strict: a
   false mismatch is visible, a false match is not. Entries:
   - `status` / `minecraft:status_response`: `json_response` is parsed
     into its JSON value, so JSON key order, whitespace and string
     escapes no longer matter (RFC 8259: objects are unordered). Only
     strict JSON is parsed: invalid JSON, a repeated key, `NaN` or
     `Infinity`, or nesting deeper than 255 (the default nesting limit
     of the client's Gson 2.14.0 `JsonReader`, verified with `javap`)
     leaves the raw string, compared as a string. If it is an object,
     only the **members the client reads** are kept: in the status
     object, `description`, `players`, `version`, `favicon` and
     `enforcesSecureChat`; in its `players` object, `max`, `online` and
     `sample`; in its `version` object, `name` and `protocol`; and in
     those three objects a member whose value is JSON `null` is dropped.
     So Pumpkin's misspelled `"enforceSecureChat": true` and its
     `"favicon": null` read as vanilla's absent ones. Evidence
     (`docs/research/2026-09-26-comparison.md`, *Unknown keys and JSON
     null*, `javap` on the client jar and its DFU 10.0.21 and Gson
     2.14.0): `ServerStatus.CODEC`, `ServerStatus$Players.CODEC` and
     `ServerStatus$Version.CODEC` are `RecordCodecBuilder` codecs naming
     exactly those fields; the status is decoded through `RegistryOps`
     over `JsonOps.INSTANCE` (uncompressed), so `MapDecoder.
     compressedDecode` is `getMap` then the record's fields, each of
     which reads only `MapLike.get(name)` (`FieldDecoder`,
     `OptionalFieldCodec`); and `JsonOps$1.get` returns null for a
     `JsonNull` member, which `OptionalFieldCodec.decode` turns into
     `Optional.empty()` exactly as for a missing key. Text components
     (`description`) and `players.sample` entries keep every member:
     their codecs are not shown to read by name only. Then the text
     components in it are canonical: a plain string `"x"` is written
     `{"text": "x"}`. Evidence: minecraft.wiki *Text component format*
     (raw wikitext, oldid 3749600: "`"A"` and `{text: "A"}` are
     equivalent"), and the 26.3 jar, where
     `ComponentSerialization.createCodec` decodes a string with
     `Component.literal` and an object with only `text` into the same
     literal with an empty style and no siblings. The text components
     are exactly: `json_response.description` (a text component in
     `ServerStatus.CODEC`, verified with `javap`), each element of a
     text component in list form, and each element of a text
     component's `extra`, recursively. `version.name` and
     `players.sample[].name` are plain strings, not text components.
     Last, the **declared defaults** are dropped: a field holding exactly
     the value the client reads when it is absent is the same as its
     absence. They are `json_response.description` equal to `{"text":
     ""}` (after the step above, so `""` too), `json_response.
     enforcesSecureChat` equal to `false` (a JSON boolean, not `0`), and
     `json_response.players.sample` equal to `[]` (only inside a
     `players` object). Evidence, with `javap -c -p -constants` on the
     26.3 **client** jar (sha1 e877b6a07acd633fb3bb475002175cec036e7b87,
     from Mojang's manifest) and its DataFixerUpper 10.0.21 (sha1
     b6b2ae770c02e0c1eb90f9985b151e9085a38d0b, the version JSON's
     library; byte-identical to the server bundle's):
     `ClientboundStatusResponsePacket`'s stream codec is
     `ByteBufCodecs.lenientJson(32767)` then `fromCodec(ServerStatus.
     CODEC)`; `ServerStatus.CODEC` reads `description` with
     `ComponentSerialization.CODEC.lenientOptionalFieldOf("description",
     CommonComponents.EMPTY)`, `enforcesSecureChat` with
     `Codec.BOOL.lenientOptionalFieldOf("enforcesSecureChat",
     Boolean.valueOf(false))`, and `ServerStatus$Players.CODEC` reads
     `sample` with `NameAndId.CODEC.listOf().lenientOptionalFieldOf(
     "sample", List.of())`. DFU's `lenientOptionalFieldOf(name, default)`
     is `optionalFieldOf(name, default, true)`: an `OptionalFieldCodec`
     whose `decode` returns `Optional.empty()` when `MapLike.get(name)`
     is null (the key is absent), `xmap`ped through
     `Optional.orElse(default)`. The defaults equal what the explicit
     values decode to: `CommonComponents.EMPTY` is `Component.empty()`,
     `MutableComponent.create(PlainTextContents.EMPTY)`, and
     `Component.literal("")` and the object `{"text": ""}` both go
     through `PlainTextContents.create("")`, which returns
     `PlainTextContents.EMPTY` for an empty string, into a
     `MutableComponent` with an empty sibling list and `Style.EMPTY`
     (`MutableComponent.equals` compares exactly contents, style and
     siblings); an empty JSON list decodes to an empty list, equal to
     `List.of()` by `List.equals`; `false` decodes to `Boolean.FALSE`.
     The same `lenientOptionalFieldOf` also turns a present but
     undecodable value into the default; that is lenient error handling,
     so it is not encoded (`"enforcesSecureChat": 0` stays strict;
     `"sample": null` is dropped as a null member above, which is not
     error handling: `JsonOps` reads it as missing). `players`, `version` and `favicon` are optional with
     no default, so their absence is significant; `players.max`,
     `players.online`, `version.name` and `version.protocol` are
     required (`fieldOf`).
   - `play` / `minecraft:level_chunk_with_light` (#22): `heightmaps`
     become the ones the client keeps, the last sent of each type it
     reads (an unknown id as 0), by type: it puts them into an `EnumMap`,
     so a type sent twice, or an unknown id where vanilla sends 0, is
     network traffic only. Each section's
     `block_states` and `biomes` become the id at each entry: one id if
     every entry has it, else all of them, packed so that two are equal
     exactly when their ids are. So the palette that spelled them (a
     single value, a list or hash palette in any order, the global
     palette, or a list palette sent with fewer bits than the client
     reads it at) is network traffic only, and a block state or biome
     that differs is a gameplay Divergence at `sections[<i>].block_states`
     or `sections[<i>].biomes`. The order of a list or hash palette in
     a chunk's sections is no Divergence at all (#172; not in
     `chunks_biomes`, which has no canonical form, below): every copy of the fields, raw ones too,
     has each such palette in ascending order of id and its entries'
     indexes changed to match (`compare._ONE_SPELLING`), since vanilla
     sends a container it holds in memory in the order its values were
     set and one it read back from disk in entry order
     (`PalettedContainer.pack`;
     `docs/research/2026-10-03-vanilla-chunk-spellings.md`). A container
     with an entry past its palette stays as sent, and so does a hash
     palette longer than its bits have slots for (the client reads one of
     any length, but sorted, an index might not fit), and so do the bits
     and the slots after the last entry. An entry that indexes past its palette is
     a value of its own: the client reads it, and fails only when it
     looks it up (`valueFor`). Evidence
     (`docs/research/2026-10-02-chunks-light.md`, `javap` on the 26.3
     client): `LevelChunk.replaceWithPacketData` reads each section with
     `LevelChunkSection.read`, which keeps the counts as sent and reads
     each container with `PalettedContainer.read`; that reads the palette
     the bits pick (`Strategy.getConfigurationForBitCount`) and unpacks
     the entries at the palette's width, so the client keeps the id at
     each entry, not its spelling. A raw difference inside a section's
     container is network traffic only when the two containers hold the
     same ids (`compare._COVERS` names the canonical value a raw path is
     part of). A gameplay Divergence of a container shows, on each side,
     the chunk and the first three positions that differ, in world
     coordinates, with that side's id there (`chunk 2 -1: 37 -62 -9 is
     10`), then how many more differ; a biome cell is named by its lowest
     block. y counts from -64 when both sides send 24 sections and from 0
     when both send 16 (the heights of the vanilla dimension types, from
     the 26.3 server jar's `data/minecraft/dimension_type`); otherwise it
     counts from the world's bottom, and the text says so. Against a
     container that is not ids (one the client cannot read), each side
     is said whole: `all 41`, `ids 3 to 41` (and `entries past the
     palette` if it has any), or what is wrong with it.
     A direct biome container is read as the client reads it, which the
     codec cannot do alone: the client reads its entries at `Mth.ceillog2`
     of the biomes the server sent it (`Strategy.<init>`,
     `Configuration$Global`), whatever bits per entry are sent, but the
     codec reads one packet at a time and reads it at the bits sent. So
     the Comparison takes that width from the same Bot's `registry_data`
     for `minecraft:worldgen/biome` in the same Transcript: the entries of
     every such packet in the last configuration before the chunk, counted
     (`compare._Context`; each configuration has a new
     `RegistryDataCollector`, whose `ContentsCollector.append` adds the
     entries of each packet for a registry). Data as long as that
     width takes is read at that width, so the bits sent are network
     traffic and the biomes compare as above. Data of another length is
     not what the client reads (it reads that many Longs and the rest of
     the packet is shifted): it is a value of its own, a gameplay
     Divergence that shows the bits, the width the client reads and the
     data (`chunk 0 0, y -64 to -49: 6 bits per entry where the client
     reads 7: …`). A Transcript with no such `registry_data` (one recorded
     from play, without configuration) is read at the bits sent. The
     vanilla server writes its storage's bits, so a direct container's
     byte is that width.
     Its `light`, and the `data` of a `play` / `minecraft:light_update`,
     become what the client applies to each light section in each layer
     (`light.sky[<i>]`, `light.block[<i>]`): the next array if the mask
     has the section's bit, else an empty section if the empty mask has
     it, else nothing sent, which leaves the client's light as it was
     (`ClientPacketListener.readSectionList`; light section `i` is world
     section `i - 1`). So the mask wins over the empty mask, and bits past
     the light section count, and arrays past the mask's bits, are never
     read: network traffic only. The count is the sections plus two
     (`LevelLightEngine.getLightSectionCount`); a `light_update` does not
     say how high its level is, so it is 256, the most any level has
     (`DimensionType`'s height is at most `Y_SIZE`, `(1 <<
     BlockPos.PACKED_Y_LENGTH) - 32` = 4064 blocks). So every copy of a
     chunk keeps at most 254 sections, and of its light, or a light
     update's, at most 256 arrays a layer; the rest become one value
     that counts them (`19746 more sections`, `compare._CAPS`): the
     client reads no more (`LevelChunk.replaceWithPacketData` reads one
     section for each section of its level), and a chunk of 20,000
     sections is then a few hundred Divergences, not 60,000. An empty section
     and an array of 2048 zero bytes are equal for block light, and for
     sky light only in light section 0, below the world:
     `SkyLightEngine.setLightEnabled` fills an empty stored sky section
     with 15 within the world, and no other client code tells the two
     apart (`docs/research/2026-10-02-chunks-light.md`). Below the world
     it is no Divergence at all (#172): vanilla sends either, so every
     copy of the fields, raw ones too, has sky light section 0 sent as
     2048 zero bytes written as an empty section instead
     (`compare._ONE_SPELLING`;
     `docs/research/2026-10-03-vanilla-chunk-spellings.md`). A section not
     sent never equals one sent, empty or not, so Pumpkin's explicit sky
     arrays where vanilla names no section are a gameplay difference. A
     mask bit with no array left, or an array of another length, is a
     value of its own: the client fails. A gameplay Divergence of a light
     section shows the positions that differ, with each side's level, when
     both sides send an array, and otherwise what each side's section is
     (`chunk 0 0, y -32 to -17: not sent` against `all 15`; `no such
     light section` past a side's light section count).
   - `play` / `minecraft:container_set_content` and
     `minecraft:container_set_slot` (#283): no `state_id`. The client
     passes it to `AbstractContainerMenu.initializeContents` and `setItem`
     (`ClientPacketListener.handleContainerContent`,
     `handleContainerSetSlot`), which store it in `stateId`, and the one
     client code that reads that field is `MultiPlayerGameMode.
     handleContainerInput`, which copies it into the
     `ServerboundContainerClickPacket` (`javap` on the 26.3 client jar). A
     different `state_id` is network traffic only.

   Considered and **not** encoded (strict until evidence says otherwise;
   see Open questions): the list form `["a", "b"]` ≡
   `{"text": "a", "extra": ["b"]}`; an explicit `"type": "text"`; style
   values equal to the defaults (`"bold": false`); a present but
   undecodable value that `lenientOptionalFieldOf` replaces by its
   default; and the client's lenient parsing (the status
   JSON is read by Gson's `JsonParser.parseString`, in lenient mode,
   which accepts unquoted keys and single quotes; and DFU's
   `JsonOps.getNumberValue` accepts any JSON number, so `20.0` where an
   int is expected; both verified with `javap`). JSON numbers, booleans
   and `null` keep their types (except a `null` member of the status,
   `players` or `version` object, dropped above). `favicon` presence
   (a non-null value) is significant: the
   client shows the icon when there is one, and ServerSpec's invariant
   is "no server icon".

   Then **number the entities** (#21), in every copy of a packet (raw
   and canonical) alike. Vanilla gives entity ids from one counter for
   the whole server, and every mob a random UUID (the `Entity`
   constructor takes `Mth.createInsecureUUID` of a new `RandomSource`),
   so the same entities on two servers have other ids and UUIDs. An
   entity id whose `add_entity` the Bot received outside the windows
   becomes that entity's name (#116): its entity type and its position
   at its first `add_entity` before the window, `pig@(1.5, -60.0, 7.5)`
   (a later `add_entity` for the id keeps the first name unless a
   `remove_entities` came in between: vanilla resends one only after
   that, or after the client's world is reset; the type's registry name without
   `minecraft:`, then `x`, `y` and `z` as Python writes floats, with
   -0.0 written 0.0 and no rounding). The `add_entity`'s fields go
   through the Group's Masks first, so an axis a Mask hides (an item
   dropped at a random position) reads `<masked>` in the name, and a `*`
   Mask on `add_entity` names no entity (each is numbered). A player
   is named by its UUID instead, `player <uuid>`: where a player joins
   is random or shared, and its UUID comes from its name or account.
   The Group's own setup fixes the type and position (with `tick
   freeze`, or `NoAI:1b` for a mob and `NoGravity:1b` with no `Motion`
   for any other entity, so it does not move), however many other
   entities arrived first, so an action inside a window on the wrong
   one of two entities spawned before it is a Divergence. A name an
   earlier entity already took (two of one type at one position, or
   names a Mask made equal) gets a suffix in the order the Bot heard of
   them, `pig@(1.5, -60.0, 7.5) #2`, so a Mask never makes two entities
   one. Every other
   entity id becomes `#<n>`: the n-th entity in the packets the
   Comparison takes for the Bot (step 1, less the packets a `*` Mask
   drops), in wire order. Packets outside the windows take no number:
   how many chunk batches, world-generation mobs and natural spawns a
   Bot heard of before a window opened is timing, and counting them
   would shift every number inside it. So what is not compared never
   shifts what is; without windows, the Bot's own player (`login`) is
   `#1`, and with them, an id with no `add_entity` before the window
   (the Bot's own player) takes the number of its first appearance in
   one. The Codec names
   where a packet holds entity ids (`Codec.entity_id_paths`, found in
   the schemas by type, so no list of packets is kept); an id of no
   entity (None) stays None. Each field `compare.ENTITY_UUIDS` names
   becomes `#<n>` too, counted on its own, except in a packet whose
   `type` is the player's entity type: a player's UUID comes from its
   name or account, so it takes no number and is compared as it is
   (unless an entity that is not a player has the same UUID, whose
   number it then shows, so the reuse is a Divergence). Each Bot is numbered
   on its own (Control's is not compared). So the same entities compare
   equal, a packet about another entity is still a `field` Divergence
   (`entity_id`, `#2` against `#3`), and entities sent in another order
   differ in their other fields. Not numbered (they stay raw, so they
   compare as vanilla sent them): an entity id inside `add_entity.data`
   (a projectile's owner) or inside a metadata value (a firework's
   shooter), each a plain VarInt in the schema (see `ENTITY_DATA`), and
   the UUIDs of other packets. A `remove_entities` the Bot received,
   compared or not, ends the name or number of each id it removes, as
   the client forgets those entities: a later `add_entity` with the same
   id is a new entity, so a Candidate that gives a removed entity's id
   to a new one shows no difference vanilla would not (#116). An id
   first seen in a `remove_entities` takes no number: the entity is
   gone, and a number would shift every later one. It is written `#?`
   there, as its value is the server's counter.
3. Apply **Masks**, which hide identifiers with no gameplay meaning, or
   ambient packets (ADR-0006: never anything a player could notice). A `*` Mask drops every packet of that name (in any
   State) from both streams before alignment; indices count the stream
   after dropping, so they stay the same across re-runs that differ in
   how many ambient packets arrived. A Bot's presence (the `bot`
   Divergence) counts its Events before any Mask. A field Mask hides
   the value at its path in every packet of that name (in any State),
   on both sides, wherever the path is present: the value becomes
   `MASKED`, unless it is None, which stays. A Mask hides a value, never
   whether it is there: whether a value is there is gameplay (an
   advancement criterion obtained or not, #106), so a field one side
   lacks, or holds None in, is still a Divergence. A path ending in a
   list index hides that element where it stands, so the list keeps its
   length. `[*]` in a Mask's path (never in a Divergence's) is every
   index of the list there, so a Mask reaches a field of each element
   (`players.sample[*].id`) wherever an element stands (#106). Paths apply to the canonical form (step 2), so a value the
   client reads as absent (a status's empty `players.sample`) is absent
   there. No Mask is on an entity id, which the
   numbering above already makes comparable: `Mask` refuses one. Before its Group's own Masks, every
   Comparison masks the **random fields** (`compare.RANDOM_FIELDS`,
   ADR-0011), which vanilla draws at random, or reads from its clock, on
   every run, so no exact Group compares their values (a statistical
   Group compares their distribution): `login_finished.session_id`, which vanilla draws with
   `UUID.randomUUID()` when its first connection opens
   (`ServerConnectionListener.getSessionId`, reset when no connection
   is left) and the client only passes to its telemetry
   (`ClientTelemetryManager.createWorldSessionManager`; `javap` on 26.3,
   #17), and the `seed` of `sound` and `sound_entity`, which vanilla
   draws for every sound from `Level.soundSeedGenerator`, seeded from
   `RandomSupport.generateUniqueSeed()` and not from the world seed
   (`javap` on 26.3, and two vanilla runs that differ in it; #29), and
   `update_advancements`' `progress[*].criteria[*].obtained`, which
   `CriterionProgress.grant` sets to `Instant.now()` when the player
   obtains the criterion (`javap` on 26.3, and two vanilla joins that
   differ only in it; #106). A
   sound's pitch is not one: most sounds have a fixed pitch, so a Group
   that plays a sound with a random pitch (a door's, `nextFloat() * 0.1 +
   0.9`) masks `pitch` of `sound` itself. A
   Mask that matches nothing is not an error, since a Mask may name
   packets a Group never sees; a field Mask on a packet with no
   fields does nothing, so its payload still differs and the Self-check
   says a schema is needed.
4. Align the two streams with a sequence diff and report `missing`,
   `unexpected` and `field` Divergences. A packet with no schema is
   compared by raw payload. A Self-check failure on such a packet is the
   signal to write its schema and a Mask.

   The alignment is a **longest common subsequence** of the packet keys
   (State and name, and the position of a chunk, light update or
   forgotten chunk: two at different positions are never one packet sent
   two ways, so each is `missing` or `unexpected`, and shows
   `chunk <x> <z>` rather than its fields; a chunk the codec cannot
   read has the position of its first two Ints, if it has 8 bytes),
   so as few packets as possible are reported `missing` or `unexpected`.
   Of the longest ones, the choice is fixed so that swapping the sides
   mirrors it: match the common prefix and suffix as they stand (so of
   repeated packets the prefix matches the earliest and the suffix the
   latest: `[a]` against `[b, a, a]` matches the last `a`); between
   them, trace from the front, matching equal keys, otherwise skipping
   the key whose skipping keeps the longer subsequence, and on a tie
   the smaller key, whichever side it is on. Between two matched pairs,
   `missing` comes before `unexpected`. In a tick-exact Group (#23), each play
   packet holds the tick it arrived on: the number of the Bot's `tick:<k>`
   Marks before its arrival (its own, else the unnamed one), plus one. The
   tick is not part of the key, so a run of packets each a tick late still
   matches one for one; two matched packets on different ticks give one
   `field` Divergence at `TICK_PATH`, then the two packets' differences.
   For a chunk batch marker that Divergence is network traffic, as a
   marker only one side sent is (#330, review A).
   When both streams have ticks, they break ties (#229): of the longest
   alignments, the one with the most pairs on the same tick, so the copy
   of a repeated packet on a tick the other side lacks is the one left
   unmatched (prefix and suffix match on key and tick; a tie skips the
   smaller key and tick).
   A unit test checks every pair of
   key sequences up to length 4 over 3 keys: ordered, longest, and
   mirrored by a swap (an exhaustive run up to length 5 found no
   exception either). Not `difflib.SequenceMatcher`: it matches the
   longest *contiguous* block first, so it can leave more packets
   unmatched than necessary, and its tie-breaking depends on which side
   is `a`, so a swap does not mirror it. The cost is O(n·m) time and
   memory between the common prefix and suffix, about 0.15 s for 1000
   against 1000 unrelated packets.

   Matched packets with fields are diffed recursively over the codec
   value model. Mappings are compared key by key in sorted order (key
   order is never significant: schema order is fixed, and JSON and NBT
   objects are unordered), and a key on one side only is `ABSENT` on the
   other. Lists are compared index by index, with `ABSENT` past the end
   of the shorter one. Leaves are equal only with the same exact type
   (`True` is not `1`, `1` is not `1.0`), and floats bit for bit (`-0.0`
   is not `0.0`, and a NaN equals itself, so a Self-check never trips on
   one). A value outside the model is a harness bug, so it raises
   TypeError rather than becoming a Divergence. If either packet has no
   fields, the pair is compared by payload, byte for byte; a Divergence
   shows 256 bytes of each payload as hex and counts the rest
   (`… (N more bytes)`, #151): the first 256, or, if both payloads are
   longer, the same 256 of each from 16 bytes before the first that
   differs, down to a multiple of 16 (`(N bytes before) …`), so the
   difference is in view. `compare` never mutates its
   inputs: it diffs copies.
5. **Test cases** (#8). Every field the Comparison compares is a test
   case, named from vanilla's own packet id and the field's path
   (`test_case`), so no one maintains a list of names:
   - `<packet>.<path>`: the packet id without `minecraft:`, then the
     path as a Divergence spells it (`set_health.food`). A key that is
     not an identifier keeps its JSON string in brackets
     (`set_health.m["a.b"]`).
   - List elements share one test case: every index is written `[]`
     (`status_response.players.sample[].name`). Repeated packets share
     one too: the third `set_health` is still `set_health.health`.
     Which element, which occurrence and which Bot differ is in the
     Divergence.
   - A packet compared as a whole (with no schema, so by payload;
     missing; unexpected) is the test case `<packet>`.
   - The status response's only field, `json_response`, is JSON text
     (`_JSON_TEXT`), so its paths are named from inside the JSON
     (`status_response.description`), and the text as a whole is
     `status_response`.
   - A packet id that the Target's `packets.json` has in more than one
     State, clientbound, starts with the State in every State:
     `configuration:keep_alive`, `play:keep_alive.id`,
     `status:pong_response.timestamp`. The Comparison asks the Codec,
     so the set is never listed by hand.

   Every Divergence names its test case (`Divergence.test_case`). A
   network traffic Divergence is in the test case of its raw path
   (`status_response.description` for Pumpkin's `{"text": "mscts"}`
   against vanilla's `"mscts"`). The `bot` and `failed` Divergences are
   about the Group, not one field, so they are in none ("").

   A Verdict lists its test cases (`Verdict.test_cases`): the test case
   of every pair of leaves compared in matched packets, after Masks and
   canonicalization, whether the two were equal or not, the test
   case of every gameplay Divergence, and (#101) the test case of each unmasked
   leaf of a reference packet the alignment left `missing` as gameplay, as a match
   with itself would name it, so leaving a packet out fails each field
   sending it wrong would. Likewise (#225) a reference list or mapping
   the candidate sent as something else, or left out, adds the test case
   of each of its unmasked leaves. Likewise (#230) a reference packet
   with fields matched to a candidate packet that did not decode adds the
   test case of each of its unmasked leaves, and the Report fails them for
   that packet's Divergence. In all three, an empty list or mapping
   counts as a leaf. A dropped packet and a packet an
   Observation window leaves out are in none, and neither is a pair of
   values at a masked path that are the same (two `MASKED`, or two
   None): a masked field is a test case only where it diverges. Each is the same, different in gameplay, or different in
   network traffic only (`Verdict.differing`). A network traffic
   Divergence names the test case of its raw path. Where no compared
   pair names that test case too, it is not in `Verdict.test_cases`
   (#330): listing it would claim a comparison that was never made,
   and would give a Candidate that spells it differently one more test
   case. Nor are the fields of a chunk batch marker left `missing`.

### Measurements and Report

- `cli`: `ADAPTERS`, `DEFAULT_GROUPS`, `DEFAULT_REPEAT`, `REFERENCE` — CLI defaults.

```python
@frozen
class Measurement:
    name: str                       # "status.rtt"
    unit: Literal["ms", "bytes", "count"]
    value: float

def measurements(transcript: Transcript) -> list[Measurement]: ...        # from span Marks
# measure.py. A span is `<name>:start` and the next `<name>:end` (ms); an unmatched start
# (its body raised) or end yields nothing; listed in start order.

@frozen
class Stats:
    n: int
    median: float
    p95: float                      # nearest rank

def stats(values: Sequence[float]) -> Stats: ...   # ValueError on no values

# run.py: run_results(groups, reference, candidate, *, workdir, repeat=1,
#                     keep_transcripts=False) -> RunResult
# plays exactly as run() does (run() returns its .verdicts); a repetition the Candidate
# was not played in measures nothing on it, and a blocked one nothing at all (#285).
@frozen
class GroupResult:
    group_id: str
    verdicts: tuple[Verdict, ...]                    # one per repetition
    reference: tuple[tuple[Measurement, ...], ...]   # one tuple per repetition
    candidate: tuple[tuple[Measurement, ...], ...]
    elapsed_s: tuple[float, ...] = () # both plays and Comparison per repetition (the
                                      # Reference's alone if the Candidate's was not); 0 if
                                      # neither was
    transcripts: tuple[tuple[Transcript, Transcript] | None, ...] = ()  # only with
                                      # run_results(..., keep_transcripts=True), off by default
                                      # (reference, candidate) per repetition whose Verdict
                                      # is not match and both sides played, else None (#162)

@frozen
class SideSummary:
    name: str                       # adapter name
    version: str | None             # version.name of its first status_response (lenient)
    startup: tuple[Measurement, ...]  # instance.startup (ms, ready_ns - launched_ns) per
                                      # launched Instance; none for an Attached side
    installed_version: str | None = None # "nightly 4426d11 (sha256 b8382a8a…)": its Installation's
                                         # Build and short sha256; the full sha256 without a Build

@frozen
class RunResult:
    results: tuple[GroupResult, ...]
    reference: SideSummary
    candidate: SideSummary
    verdicts: tuple[Verdict, ...]   # property: repetition after repetition

@frozen
class Report:                       # report.py
    target: Target
    reference: SideSummary          # name, status version.name, startup Measurements
    candidate: SideSummary
    results: tuple[GroupResult, ...]
    notes: tuple[str, ...]          # plain remarks, e.g. what the Report leaves out
    elapsed_s: float               # launch through shutdown, excluding install prompts
    # Report.of(run_result, *, target, notes, elapsed_s); repeat (property)
    # later: compliance = matches / (groups − errors)

# report.py, #101: each test case of each Group passes or fails.
class LineResult(StrEnum): PASS; FAIL; NOT_TESTED; ERROR; NOT_SCORED  # "not scored", #330
@frozen
class CaseResult:                   # a test case's line
    group_id: str
    test_case: str
    result: LineResult              # PASS, FAIL or NOT_SCORED
    network_traffic_only: bool = False
@frozen
class GroupLine:                    # a Group's own line
    group_id: str
    result: LineResult              # FAIL, NOT_TESTED or ERROR
    reasons: str                    # "Not tested: …; Error: …"
type Line = CaseResult | GroupLine
@frozen
class Totals:                       # failed counts not_tested; errors are not scored
    passed: int; failed: int; not_tested: int; errors: int
    # scored = passed + failed; score = passed / scored, or None if 0
def report_lines(report: Report) -> tuple[Line, ...]: ...
# Groups in play order; each Group's compared test cases sorted, each once across
# repetitions (a `missing` packet's Divergence makes its packet's test case and each of
# its fields' differ, and so does a gameplay `field` Divergence whose reference is a list
# or mapping, for its test case and each of its leaves', #225; a `failed` Divergence in
# any repetition makes every test case of the Group differ, #262, #266, #285): FAIL if it
# differs in gameplay in any repetition, PASS (marked
# network_traffic_only) if it differs only in network traffic, else PASS. One that no
# compared pair names (network traffic Divergences name it, no gameplay one does, and
# no repetition's Verdict.test_cases lists it; _never_compared, #330) is NOT_SCORED
# (marked network_traffic_only) while NETWORK_TRAFFIC_ONLY_PASSES, whatever else
# makes it differ, and FAIL with the switch off, as run.prerequisite_verdict judges
# its Verdict; totals counts NOT_SCORED nowhere. Then one
# Group line if any repetition was blocked or errored, the Candidate failed, or a bot's
# packet count differed: FAIL if the Candidate failed or a count differed, else
# NOT_TESTED if blocked, else ERROR.
def totals(results: Iterable[Line]) -> Totals: ...

# report_json.py: report.json, the whole Report (#190). dumps(report) -> str: the Report's
# fields nested as in Report (target, reference, candidate, results, notes, elapsed_s),
# with lines (each report_lines line: group_id, result, then test_case and
# network_traffic_only, or a Group line's reasons) and totals (passed, failed, not_tested, errors, scored, score: fraction or null)
# after candidate (#101); loads ignores both, as they follow from results. Indent 2, a final newline, strict JSON. A Divergence value JSON cannot hold is an object
# with one tag key: {"absent": true}, {"bytes": hex}, {"uuid": str}, {"float": "nan" |
# "inf" | "-inf"}; a server object whose only key is a tag (or "dict") is {"dict": {...}}.
# Any other value type is a TypeError. loads(text) -> Report reads it back: the Report
# written, but with at most 20 Divergences of a test case in each Verdict (see below);
# ReportJsonError (a ValueError) names where malformed text differs.
# A Verdict keeps at most MAX_PER_TEST_CASE (20) Divergences of a test case in the file
# (#254, ADR-0006): the first 20 in order, then any later one that is the first of its test
# case with its kind, observability and kind of value (a list or mapping): the lines read
# nothing else from a Divergence. A Divergence of no test case is never left out. Each
# verdict has `omitted` (after divergences), the count left out, which Verdict.omitted
# holds when read back; dumps(loads(text)) == text. loads reads a missing `omitted` as 0
# (a file from before #254 kept every Divergence) and refuses a negative or non-integer one.
MAX_PER_TEST_CASE: int
def dumps(report: Report) -> str: ...
def loads(text: str) -> Report: ...
class ReportJsonError(ValueError): ...

def render_text(report: Report, *, verbose: bool = False, color: bool = False) -> str: ...
# color (#101): each mark in its ANSI colour, ✓ green (32), ✗ red (31), ! yellow (33),
# · grey (90, #330).
def render_markdown(report: Report, *, verbose: bool = False) -> str: ...
# report.md (#190): what render_text says, as Markdown. "# <first line>"; the build line
# (#156) as a paragraph; the verbose header as "Label: value" lines joined by hard breaks;
# each line "- <✓|✗|·> `<group>/<test case>` <title>" (no list when there is no line),
# its verbose values nested ("  - "), with values and paths as code spans; "## Group
# times" and a list; the totals, score and total time last, one paragraph joined by hard
# breaks. Blocks are separated by a blank line. Text mscts did
# not write is shown as it is: code spans fence it with more backticks than it holds, and
# prose escapes \ ` * _ [ ] < > & | ~ and shows a line break as \n or \r, so server text
# never starts a line of its own. Both renderers write one _Document.
# case_titles.py: TITLES: Mapping[str, str], test case name → short title.
# docs/reference/test-cases.md has one entry per title, checked against the table.
# Unknown test cases are still reported; the table never filters Comparisons.
# ADR-0012 / #9: first line "Running tests against <candidate adapter name>[ <installed_version>]"
# (the build, when known; 2026-10-04 amendment, replacing #156's second line);
# #101 (amends ADR-0012): one line per report_lines line whose result is in _LISTED
# (every result today): "<✓|✗|·> <group>/<test case>" (· for NOT_SCORED) (no title since 2026-10-04),
# " (network traffic only)" when it passed that way, " (network traffic only, not
# scored)" for NOT_SCORED (#330); a Group line is
# "✗ <group> <reasons>", or "! <group> <reasons>" for an ERROR, which is not scored. Then
# "<p> passed, <f> failed[ (<n> not tested)]. (<percent>%)" with the percent rounded down
# to tenths (".0" dropped), and no "(…%)" when nothing was scored; then
# "<e> error[s] (not scored)" when there are errors; and last "Took <seconds> s", rounded
# to tenths, including launch and
# shutdown. No section headings, Notes, legend or per-Measurement timing table.
# #10: verbose adds the Reference's installed version, Target and repetitions at the top, distinct
# pairs of actual values directly under each line that differs, and total time per Group
# across repetitions (play both sides + Comparison; excludes startup/shutdown).
# Blocked Groups (only in an older report.json) say "not played"; one played on the
# Reference alone shows that play's time (#266, #285); older results without durations
# say "not recorded".
```

CLI (`src/mscts/cli.py`, stdlib argparse; `[project.scripts] mscts = "mscts.cli:main"`;
`main(argv=None, *, fetch=https_get, now=utc_now, color=None) -> int`; color None means
stdout is a terminal and NO_COLOR is unset or empty, per no-color.org). Every command says exactly what it did or
would do; an error is one `mscts: <message>` line on stderr naming its fix, exit 1:

```
mscts adapter install <adapter>[@<version>] [--from PATH]
    # install.install_release: the latest build for the Target, or the one @<version> names
    # (ADAPTERS is a static map of names to Adapters; an unknown name is a usage error, exit
    # 2). "downloading <url> ..." for every fetch, then "installed <adapter> <build> from <url>
    # into <root>", or "<adapter> <build> is already installed at <root> (sha256 …): nothing
    # to do. To check for a newer build, delete <root> and install again.". --from: install_from,
    # "installed <path> (<adapter> <build>, sha256 …) into <root>". @<version> with --from:
    # "name a version or a file, not both". The Adapter's refusals, as mscts words them:
    # "vanilla@26.4 is not supported: this mscts tests Minecraft 26.3.", "pumpkin@8f3c2a1 is
    # not available for download. …".
mscts adapter list                  # ADAPTER VERSION TARGET STATE, one row per Adapter: its
                                    # installed Build or "-", and installed | not installed |
                                    # unusable: see `mscts adapter status <a>`
mscts adapter status <adapter>      # root, version, commit (if any), sha256, size, from,
                                    # installed; exit 1 and the install command when nothing is
                                    # installed
mscts selfcheck [--group GLOB] [--repeat N]
mscts run --candidate <adapter> [--group GLOB] [--repeat N] [-v | --verbose] [--out DIR]
    # --group: fnmatch over the registered exact Group ids, prerequisites added
    # (default status/*); --repeat default 5. --out DIR: made (parents too) before the
    # Run, else exit 1 "cannot create the --out folder DIR: <strerror>"; after the Report,
    # writes DIR/report.json (report_json.dumps) and DIR/report.md (render_markdown, same
    # verbose), replacing both, then says "Report written to DIR/report.json and
    # DIR/report.md".
    # Plays in a fresh temp dir, removed afterwards (kept, and named, when an Instance could
    # not start). Progress ("starting vanilla and pumpkin ...", "running status/basic (1 of
    # 5) ...", run.LOG at INFO) on stderr; the Report (render_text) on stdout; exit 0 when
    # the Run completed, Divergences or not.
    # selfcheck and run get each Installation with install.require(adapter, TARGET,
    # cache_dir(), terminal=Terminal(sys.stdin, sys.stdout)): the prompt on a TTY, else a
    # failure naming the install commands. Never a silent download.
```

## Development tiers

| Tier | Marker | Needs | Command |
| --- | --- | --- | --- |
| unit | (default) | nothing external: localhost sockets and short helper processes only | `mise run check` (lint, format, types, bandit, unit tests) |
| reference | `@pytest.mark.reference` | Java 25; vanilla installed (`mise run install:reference`, which the web SessionStart hook runs) | `mise run test:reference` |
| selfcheck | `@pytest.mark.selfcheck` | Java 25; vanilla installed. One test per registered Group (`tests/selfcheck/`, parametrised from `GROUPS`): its Self-check on two Reference Instances booted once for the tier, 3 times by default (`MSCTS_SELFCHECK_REPEAT`); `-k` picks Groups by id | `mise run test:selfcheck` |
| candidate | `@pytest.mark.candidate` | a Candidate installed (`mscts adapter install pumpkin [--from PATH]`) | `mise run test:candidate` |
| statistical | `@pytest.mark.statistical` | live servers, many repetitions (slow) | `mise run test:statistical` (opt-in; ADR-0006) |

Cache: there is one per user, outside any checkout, and every worktree and
session shares it, so each download happens once. `mscts.cache.cache_dir()`
is `$MSCTS_CACHE` (absolute) if set, else `$XDG_CACHE_HOME/mscts`, else
`~/.cache/mscts`. It holds jars, binaries and generated reports, keyed by
adapter and Target (`vanilla/26.3/server.jar`). Writes into it are atomic
renames, because sessions share it concurrently.

No tier and no tool installs anything (ADR-0008): tests, `regen:packets` and Runs get
their Installation through `install.require`, which, without a TTY, fails at once naming
`mscts adapter install <adapter>` and its `--from` form.

## Milestones

Each milestone is a vertical slice that ends in a working state. Each
bullet is roughly one commit. Split any bullet that cannot be expressed as
a single failing test.

**M0 — Harness.** Docs, ADRs, skills, SessionStart hook, toolchain,
`mise run check` green with a first real unit test.

**M1 — Talk to vanilla (status).**
1. `wire`: VarInt/VarLong encode and decode, including negatives and
   5-byte limits.
2. `wire`: String (with max length), UShort, Long, UUID, Bool.
3. `framing`: frame encode/decode, including partial reads.
4. Data: commit the generated `packets.json` for 26.3, plus the regen
   script.
5. `Codec`: name ↔ id for every state and direction.
6. `Codec` schemas: handshake `intention`, `status_request`,
   `status_response`, `ping_request`, `pong_response`.
7. `ServerSpec` and `VanillaAdapter.prepare`: `server.properties` holds the
   invariants and `eula.txt` (unit).
8. `VanillaAdapter.provision`: manifest → jar, with sha1 verification and a
   cache (unit with canned manifest; a reference-tier test does the real
   download).
9. `runner.running`: launch, status-ping readiness, graceful stop
   (reference tier).
10. `Connection` + `Bot.status` against the Reference returns protocol 777
    (reference tier).

**M2 — First Comparison and Self-check.** `Transcript` recording,
`@group` registration, `status/basic` and `status/ping` Groups, `compare`
with canonicalization, `mscts selfcheck` → `match`. First Measurements
(`status.rtt`, `instance.startup`).

**M3 — First Candidate.** `PumpkinAdapter` (nightly provision, complete
`pumpkin.toml`), `mscts run --candidate pumpkin`, and a first Report whose
Divergences are readable. Add **Paper** as a high-parity sanity Candidate:
false mismatches against a vanilla fork point at harness bugs.

**M4 — Join.** Compression, login, configuration (known packs), play up to
the first chunk batch. `join/basic` Group. Masks for keep-alive ids
only (entity ids are numbered, #21); spawn position is pinned by a Fixture here and
measured statistically in M6b (ADR-0006). The Self-check must pass 20/20. Measurements:
`join.to_play`, `join.to_first_chunk`.

**M5 — Control and Fixtures.** Operator Bot, `command()`, `system_chat`
feedback, and `blocked` Verdicts through `requires`.

**M6 — Gameplay breadth.** One exact Group per gameplay mechanic:
block place and break, movement correction, chat, inventory, entities,
commands. Each one only after its prerequisites match on the Reference.

**M6a — Tick-exact mechanics (ADR-0006).** Research how `/tick freeze`
and `/tick step` show up over the protocol, then add tick-indexed
observation anchored on world age. Then redstone Groups (repeaters,
comparators, observers, piston timing, quasi-connectivity) and vanilla
glitch Groups (headless-piston bedrock breaking, pearl phasing through
the nether roof, …).

**M6b — Statistical mechanics (ADR-0006).** The `statistical` tier and Run
profile, a distribution test with a stated confidence level, and a
per-kind Self-check. Then join spawn position, mob spawn rates, loot
tables and random ticks.

**M7 — Performance.** Repetitions with statistics, multi-Bot load (N
concurrent joins, chunk throughput), and process metrics (RSS, CPU).

**M8 — Reports.** JSON plus a Markdown/HTML summary: a catalogue of
Divergences grouped by mechanic, each linked to its reproducible
Group, with no declared deviations (ADR-0006). Also a compliance
score, failure counts per missing command, and history across Candidate
versions.

**M3a — Installs (ADR-0008).**
- `mscts adapter install <adapter>[@<version>]` / `--from <path>`, plus
  `list` and `status`, all idempotent;
- the honest TTY prompt, and a non-TTY failure naming the command;
- each Adapter finds its own latest build (#156; this replaced a committed
  registry pinned by checksum).

**M9 — Adapter DX (ADR-0008).** An Adapter authoring guide with a
template, and `mscts adapter check <adapter>`, a conformance kit that
runs the Adapter contract against a live Instance.

**Later.** A second Target, and more Candidates (Minestom launcher,
FerrumC).

## Open questions

Resolve each one with evidence (a Self-check or a Reference observation),
then record the answer in an ADR:

- Which packet reorderings are legitimate? Is vanilla's join order
  deterministic across runs?
- Which ambient packets (such as `set_time` every 20 ticks, `keep_alive`)
  need Masks, and should Comparisons be scoped to windows between Marks?
  **Decided (ADR-0010):** none need Masks. A Group compares play packets
  inside Observation windows, and the heartbeat packets
  (`compare.HEARTBEAT`: `keep_alive`, `set_time`, the barrier's
  `award_stats`) are never compared inside one.
- How do Groups for the time of day compare `set_time`, which no window
  compares (ADR-0010)? And should a position resend that carries no
  movement (vanilla's `move_entity_pos` for every tracked entity every 60
  ticks) be a heartbeat packet? Telling it from a real move needs the
  packet's schema, which `move_entity_pos` has since #20. Until this is
  decided, a window that can catch one names the packets it tests.
  **Decided for the latency-only `player_info_update` (every 601 ticks;
  #165, ADR-0010 amendment):** it is a heartbeat packet
  (`compare.HEARTBEAT_PAYLOADS`), told apart by its first byte, the set of
  actions, with no schema.
- How should chunk data be compared: decode the palette into block states,
  or compare raw? **Decided (#22):** decode. The codec decodes each
  section's paletted containers (`codec/schemas/play/chunks.py`), and
  the Comparison compares the block state at each position, the biome of
  each cell and the light of each light section as the client keeps them
  (Comparison semantics, steps 1 and 2), so another encoding is network
  traffic only. Considered and not encoded:
  - a section past the level's section count, which the client never
    reads, still differs from none, since the Comparison does not know
    the level's height; vanilla and Pumpkin sent exactly the level's
    sections in the recorded joins. Past 254 sections, the most any
    level has, the rest are one value that counts them;
  - a `light_update`'s bits from the level's light section count up to
    256 are compared, for the same reason;
  - a chunk whose sections buffer ends with bytes that are not a whole
    section, which the client never reads, is one the codec refuses, so
    it is compared by payload (at the position of its first two Ints);
  - `chunks_biomes` has no canonical form: its biome containers are
    compared as sent, so another encoding of the same biomes is a
    gameplay Divergence (no Group receives it yet);
  - a chunk's block and fluid counts are compared as sent: the client
    keeps them, and the light engine reads a block count of 0 as an
    empty section.
- Transcripts record a frame when the Bot *takes* it (stamped when it
  arrived, by the Connection's background reader), so they do not depend
  on TCP segmentation, but packets never taken are absent. Should
  Comparisons be scoped to windows between Marks, with a drain at each
  window end? **Decided (ADR-0010):** yes. A window ends with a barrier
  (`Bot.sync`) on every Bot in play, then a drain (`Bot.drain`).
- Should `Packet.fields` be deeply immutable (MappingProxyType, tuples) so
  Packets are hashable in Transcripts and Comparisons? **Not needed for
  Comparison** (decided with the Comparison engine): alignment keys are
  (State, name) string pairs, and the field diff works on copies that
  `compare` makes of the fields (and checks against the value model), so
  it never hashes or mutates a Packet. Still open for Transcripts.
- Network traffic Divergences are reported per differing raw leaf, so a
  reordered `update_tags` (≈59 KB) yields one for every shifted leaf.
  Should the Report group them per packet, or should `compare` report
  the shallowest canonically equal path instead? **Decided with #9:** the
  default Report lists each test case once;
  `compare` keeps reporting every leaf.
  (Since #17 `update_tags` is sorted before anything, so its order
  yields none.)
- ADR-0007 requires a Self-check with no network traffic Divergences, on the
  premise that vanilla sends identical bytes each run. The server writes
  `update_tags` from hash maps (worker P); if its order varies between
  runs, the join Self-check will show network traffic Divergences. Check it
  when the join Group's Self-check runs, before relaxing anything.
  **Decided (#17):** it varies from boot to boot, so `compare.UNORDERED`
  sorts it before anything and its order is no Divergence (Comparison
  semantics, step 1).
- Should the text component **list form** (`["a", "b"]` ≡
  `{"text": "a", "extra": ["b"]}`, wiki oldid 3749600; the jar's
  `createFromList` is `first.copy().append(rest)`) be canonical? No
  Candidate has shown it yet. Likewise an explicit `"type": "text"`
  (optional by the wiki), and the text components nested in `with`,
  `separator` and hover events, which are not canonicalized yet.
- Alignment matches on (State, name) only, so two same-named packets in a
  different order are matched pairwise and report `field` Divergences,
  not a move. A content-aware alignment (e.g. matching on masked field
  equality) could read better; decide once a Self-check or Candidate
  shows a case.
- A Divergence names the packet but not its State; `index` locates it,
  but a report might want the State shown for same-named packets
  (`custom_payload` in configuration and play).
