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
| `registry.py`, `data/registry.toml` | the Registry: `Entry`, `Registry`, `parse`, `official()` (ADR-0008) |
| `install.py` | Installations: `installed`, `install_entry`, `install_from` (ADR-0008) |
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
| `codec/schemas/play/recipes.py` | `update_recipes`: the property sets (each item set a recipe takes as input) and the stonecutter's recipes, each an ingredient holder set and a slot display (all 11 types of `minecraft:slot_display`, read through `registry_names`) |
| `codec/schemas/play/advancements.py` | `update_advancements`: the advancements to add (each an id, a parent, a display whose background texture follows only if its flags say so, requirements, and x and y), the ids to remove, and each advancement's progress by criterion, with when it was obtained |
| `codec/schemas/play/world_events.py` | the world event packets' schemas: `level_event`, `sound` and `sound_entity` (a `SOUND_EVENT`, a `SOUND_SOURCE` category and a random seed), `level_particles`, `game_event`, `explode` (its block particles a weighted list) |
| `codec/packets.py` | `Codec`: packet name ↔ id, field schemas, `encode` / `decode`, `entity_id_paths` |
| `codec/entity_ids.py` | where a value holds entity ids: `entity_id_paths` and `inner_types` walk a wire type, and a path's steps are keys, `EACH` and `Variant` |
| `codec/data/26.3/` | generated `packets.json` and `registry_names.json` (the data component, consume effect, command argument parser, entity type and slot display names in protocol id order). Committed, regenerated and checked by `mise run regen:packets` |
| `codec/registry_names.py` | `registry_names(version, registry)`: the committed name lists, where a name's position is its protocol id |
| `net.py` | `Endpoint`, `Connection` (asyncio, state machine, records to a Transcript) |
| `bot.py` | `Bot`: `status`, `join`, `expect`, `send`, `command` |
| `spec.py` | `ServerSpec` and its enums |
| `adapters/base.py` | `Adapter`, `Installation`, `LaunchPlan` |
| `adapters/fetch.py` | `https_get` → `Download(url, body)`: HTTPS on every hop, redirects followed |
| `adapters/vanilla.py`, `adapters/pumpkin.py` | one module per server |
| `adapters/nbt.py` | a minimal, strict NBT writer (`encode`, `gzipped`) for the world saves an Adapter writes |
| `runner.py` | `running(plan)` → `Instance`: launch, readiness (with ownership), stop, process stats; `free_endpoint` |
| `transcript.py` | `Transcript`, `Event`, `Mark`, JSON-lines (de)serialization |
| `group.py` | `@group`, `Group`, `GroupContext`, `GROUPS` (the registered Groups), `resolve`; `Control`, `OperatorBot`, `CommandMissing` |
| `groups/*.py` | the Groups themselves (`import mscts.groups` registers them) |
| `settle.py` | `until_no_player_online(endpoint, *, deadline_s)`: polls an Instance's status until no player is online, `PlayersStillOnline` if it never is. `run` waits with it before each Group |
| `run.py` | `run_group` → `Transcript`; `judge` → `Verdict`; `run`: Groups against a Reference and a Candidate `Server`, on Instances it launches; `selfcheck` |
| `compare.py` | `Mask`, canonicalization, `compare` → `Verdict` |
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
- `codec.regen`: `DATA_DIR`, `REGISTRY_NAME_LISTS`, `RegenError`, `compare_or_write`,
  `data_generator_argv`, `fresh_data`, `packets_json_path`, `regenerate`, `registry_names_json`,
  `registry_names_path`, `run_data_generator` — Mojang data regeneration.
- `codec.schemas.login`: `GAME_PROFILE` — login packet schema.
- `codec.schemas.play`: `merge_submodules` — Play schema assembly.
- `codec.schemas.play.commands`: `PROPERTIES`, `commands_schema` — command argument schemas.

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

class ConnectionClosedError(ConnectionError): ...   # closed by the server, or by close()
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
    # when the server closes (the message says if that was mid-frame), ConnectionResetError on
    # a reset, or the exception itself if the harness has a bug. A frame that fails to decode
    # is recorded before recv raises, as the Packet Codec.undecodable / undecodable_frame
    # builds (its bytes and decode_error), stamped on arrival like any frame; the reader then
    # stops, as the vanilla client disconnects on a frame it cannot decode.

class Bot:                          # what Groups use; answers keep_alive / teleports / chunk batches itself
    name: str
    failure: Exception | None       # what its last failed operation (status, ping, join,
                                    # expect, command, sync, drain) raised: which Bot a Group's failure
                                    # came from
    closed: bool                    # (property) close was called
    in_play: bool                   # (property) joined, and not closed: what sync needs
    @classmethod
    async def connect(cls, endpoint: Endpoint, target: Target, *, name: str,
                      transcript: Transcript, timeout_s: float) -> "Bot": ...  # Codec.for_target
    # connect opens the Connection with answer=Replies(): from then on the Bot answers by itself.
    async def status(self) -> Mapping[str, object]: ...                # parsed status JSON
    async def ping(self, payload: int) -> None: ...
    async def join(self) -> None: ...                                  # handshake → login → configuration → play
    async def expect(self, name: str, *, timeout_s: float,
                     where: Callable[[Packet], bool] | None = None) -> Packet: ...
    async def sync(self) -> None: ...                                  # the barrier (below)
    async def drain(self) -> None: ...                                 # take what has arrived
    async def send(self, name: str, /, **fields: object) -> None: ...
    async def command(self, command: str) -> None: ...                 # unsigned chat_command, no leading "/"
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
    # expect: takes (and so records) packets until one is called `name` and `where` holds for it.
    # A disconnect before it (login_disconnect, or configuration / play disconnect) or an
    # encryption request (login hello: online mode) → ProtocolError naming the Bot and the reason.
    # command: on a Bot in play (else ProtocolError, nothing sent), sends play chat_command
    # (String 32767) and returns at once; what the server answers arrives like any packet.
    # sync, the barrier: returns once the server has sent everything caused by what it
    # received before. On a Bot in play (else ProtocolError, nothing sent): a pair is
    # client_command (REQUEST_STATS) then expect(award_stats), twice, the second request only
    # after the first answer. Vanilla handles a request at the start of a tick, before that
    # tick sends what changed, but a request that arrives while a tick's pass over the
    # queue runs is handled in that pass, so both of a pair can be answered at one tick's
    # start (docs/research/2026-10-01-join-chunks.md). The pair proves a tick has passed
    # only if its two answers arrived at least TICK_GAP_S (0.005) apart (Connection.
    # last_arrival_ns); if they arrived closer, the Bot waits TICK_GAP_S, for that pass to
    # end, and sends another pair. After SYNC_MAX_TRIPS (6, three pairs) requests it
    # returns, leaving the Mark "sync:capped <name>" (SYNC_CAPPED): a server that never
    # shows a gap. Compare reads only "observe:" Marks, so the Mark changes no Verdict.
    # Observation windows call it when they close, and Control calls it after each
    # command's marker (OperatorBot).
    # drain: takes (records) every packet already queued, without waiting: recv(timeout_s=0)
    # until TimeoutError. A frame that does not decode, or a Connection that has ended with
    # nothing left to take, raises as recv does.

def offline_uuid(name: str) -> UUID: ...  # UUIDUtil.createOfflinePlayerUUID: MD5 v3 of "OfflinePlayer:" + name

CHUNKS_PER_TICK = 9.0               # what a Bot's chunk_batch_received asks for: vanilla's server start rate
BRAND = "vanilla"                   # the brand a Bot sends: ClientBrandRetriever.VANILLA_NAME
TICK_GAP_S = 0.005                  # two award_stats answers this far apart: a tick passed between them
SYNC_MAX_TRIPS = 6                  # the most requests sync makes (an even number: whole pairs)
SYNC_CAPPED = "sync:capped"         # the Mark label sync leaves, then " <name>", on reaching the cap
class Replies:                      # an Answer: what a Bot answers by itself, as each packet arrives
    async def __call__(self, connection: Connection, packet: Packet) -> None: ...
    # As the 26.3 client does (javap): login_finished → login_acknowledged, then configuration
    # custom_payload(minecraft:brand, the String BRAND) and client_information(CLIENT_INFORMATION),
    # all three before the next packet is handled; configuration
    # select_known_packs → the same packs back; code_of_conduct → accept_code_of_conduct;
    # finish_configuration → finish_configuration; keep_alive (configuration and play) → the
    # same id; play player_position → accept_teleportation with the pose it results in (flagged
    # parts add to the tracked pose, rotation summed in binary32, pitch clamped to ±90, a
    # non-finite rotation ignored); chunk_batch_finished → chunk_batch_received(CHUNKS_PER_TICK),
    # never a timing-dependent rate; start_configuration → configuration_acknowledged. Nothing
    # else is answered (not yet: custom_query). join, not Replies, sends player_loaded.

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
# registry.py: the Registry (ADR-0008), committed as src/mscts/data/registry.toml
@frozen
class Entry:
    adapter: str                    # "pumpkin"
    version: str                    # the --version label: "26.3", "nightly-b8382a8a"
    target: str                     # the Target's Minecraft version it speaks
    url: str                        # HTTPS only
    sha256: str | None = None       # at least one of sha256 / sha1
    sha1: str | None = None         # the publisher's hash (Mojang's)
    size: int | None = None
    note: str = ""                  # a pinned nightly says here that its URL moves
    def matches(self, body: bytes) -> bool: ...  # every pinned hash (and size) agrees
    # str(entry) == "pumpkin nightly-b8382a8a"

@frozen
class Registry:
    entries: tuple[Entry, ...]
    def resolve(self, adapter: str, target: Target, version: str | None = None) -> Entry: ...
    # `version`, else the adapter's only entry for target; RegistryError naming the choices

class RegistryError(ValueError): ...
def parse(text: str) -> Registry: ...  # strict: unknown key, missing key or hash, bad hex,
                                       # non-HTTPS url, duplicate (adapter, version) → RegistryError
def official() -> Registry: ...        # the committed data/registry.toml

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
class Source:                       # <root>/SOURCE.json: where the binary came from (ADR-0008)
    sha256: str                     # of the binary; every use verifies the binary by it
    size: int
    entry: str | None = None        # the Registry entry it hash-matches, "pumpkin nightly-b8382a8a"
    url: str | None = None          # downloaded from (the entry's URL) ...
    final_url: str | None = None    # ... which redirected here
    from_path: str | None = None    # or copied from this `--from` file (absolute)
    installed_at: str | None = None # ISO 8601, UTC

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
class PrepareError(RuntimeError): ...     # prepare cannot produce a LaunchPlan that meets the contract

class Adapter(Protocol):
    name: str
    binary: str                     # the one file an Installation holds: "server.jar", "pumpkin"
    # No provision: an Adapter never downloads (ADR-0008). install.py owns Installations, so
    # a third-party Adapter is name + binary + check + prepare, and gets `mscts adapter
    # install`, --from, the prompt and verification for free. Runs and tests call
    # install.require(adapter, target, cache_dir).
    def check(self, binary: Path, target: Target) -> None: ...
        # ProvisionError unless `binary` is a server it can run (vanilla: a jar speaking
        # target.protocol_version; Pumpkin: an ELF executable). Runs before any install lands.
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
#   only for some values live in one named table (adapters/pumpkin.py LIMITS), and so does
#   every range its config types can hold: a value it cannot read back is refused too.
#   (Pumpkin's LIMITS today: `world` honoured for the WorldPresets it can write a save for,
#   FLAT; every Difficulty is honoured.)
# - a setting the server's config cannot express is written as the server's own native
#   files instead (ADR-0007): PumpkinAdapter.prepare writes world/level.dat and
#   world/data/minecraft/world_gen_settings.dat (adapters/nbt.py) in Pumpkin's 26.2 format
#   (DataVersion 4903), carrying the spec's world, seed and difficulty; golden-tested, each
#   value Pumpkin's own new-world value or vanilla's for the spec, every substitution
#   documented in level_dat().
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

# install.py: Installations (ADR-0008)
@frozen
class Installed:
    installation: Installation
    changed: bool                   # False: installed and verified already; nothing was done
    message: str                    # exactly what it did, or why it did nothing
def installed(adapter, target, cache_dir) -> Installation | None: ...
    # verified by the recorded sha256; None if absent; ProvisionError naming the fix
    # ("delete <root> and run `mscts adapter install <adapter>` again") if unrecorded or changed
    # A legacy Installation (binary, no SOURCE.json) whose binary hash-matches a Registry entry
    # gets a SOURCE.json naming that entry only, and says so: a WARNING on the `mscts.install`
    # logger ("recorded <root>/SOURCE.json: <binary> predates recorded sources and
    # hash-matches the Registry entry <entry>"); the CLI prints it as its own output.
def install_entry(adapter, target, cache_dir, entry: Entry, fetch: Fetch) -> Installed: ...
    # downloads entry.url; entry.matches(body) or ProvisionError with the actual sha256, the
    # entry's note ("the nightly moved") and the `--from` command. Another build installed
    # already → ProvisionError naming the delete + install command; never replaced silently
def install_from(adapter, target, cache_dir, path: Path, registry: Registry) -> Installed: ...
    # records the file's sha256 and path, and an entry only if the file hash-matches it
def install_command(adapter: str, *, version=None, path=None) -> str: ...  # the exact command line
@frozen
class Terminal:
    stdin: TextIO                   # asked only if stdin.isatty()
    stdout: TextIO
def require(adapter, target, cache_dir, *, terminal: Terminal | None = None,
            fetch: Fetch = https_get) -> Installation: ...
    # The one way a Run or a test gets an Installation (ADR-0008 §2): installed(...) if there;
    # else, only with a terminal whose stdin is a TTY, asks "<adapter> <version> is not
    # installed. Download <entry> (Y) or provision it yourself (N)?" (entry: registry.official()
    # .resolve). Y: install_entry, announcing "downloading <url> ..." and printing its message.
    # N: prints and raises ProvisionError naming `mscts adapter install <a> --from <file>`.
    # Anything else re-asks ("Please answer y or n."); end of input refuses, naming both
    # commands. No terminal (the default) or no TTY: ProvisionError at once naming
    # `mscts adapter install <a>` and the --from form; stdin is never read. No registry entry:
    # ProvisionError naming the --from form only.

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
- `groups.status`: `PING_PAYLOAD` — status ping payload.
- `groups.blocks`: `BUILDER` — the operator Bot that runs each command itself; `FEEDBACK_TIMEOUT_S`
  — how long it waits for a command's feedback; `PACKETS` — what a window compares;
  `DROP_MASKS` — the random fields of a dropped item's `add_entity`; `setblock`, `fill` and
  `clone` — the `blocks/setblock`, `blocks/fill` and `blocks/clone` scripts.
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
    def observe(self, *names: str, until: str | None = None
                ) -> AbstractAsyncContextManager[None]: ...
                                    # an Observation window: Marks OBSERVE_OPEN (then the
                                    # names, each after a space) on entry; when the body
                                    # completes, every Bot in play passes Bot.sync (all at
                                    # once; the first error raises, as that Bot's failure),
                                    # then the OBSERVE_CLOSE Mark, then every Bot not closed
                                    # drains. A body that raises gets neither, so its window
                                    # runs to the Transcript's end. ValueError, nothing
                                    # marked: a window already open (no nesting), or a name
                                    # that is not one word.
                                    # With `until` (a packet name): no barrier. Every Bot not
                                    # closed drains, then OBSERVE_CLOSE is stamped 1 ns after
                                    # the Event.t_ns (the arrival, never the time a Bot took
                                    # the packet; #88) of the first clientbound play packet
                                    # of that name any Bot but Control received at or after
                                    # the open Mark (Control's receipts are never compared;
                                    # the earliest arrival over the Bots, whatever order
                                    # they were recorded in). The body must last until it
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
                                    # CANDIDATE_FAILURES), and no close Mark
    async def close(self) -> None: ...   # closes every Bot; idempotent
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
    requires: tuple[str, ...] = ()  # Group ids that must `match` first, else `blocked`
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
    # no step of a path): every Comparison numbers those instead, and the message says
    # so (#21). A path around one (`set_entity_data` / `entries`) is still a Mask.

class Outcome(StrEnum): MATCH, MISMATCH, BLOCKED, ERROR

class Observability(StrEnum):       # ADR-0007; values "gameplay", "network traffic"
    GAMEPLAY, NETWORK_TRAFFIC

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
    reference: object               # the packet's value, or ABSENT
    candidate: object
    test_case: str                  # the test case it was found in (test_case(): the
                                    # packet's for missing, unexpected and a whole payload;
                                    # the path's, the raw one for network traffic, for any
                                    # other field one); "" for bot and failed (Group-level)
    observability: Observability = Observability.GAMEPLAY
    # network traffic: a `field` Divergence between raw values whose canonical forms are
    #   equal (path and values are the raw ones); gameplay: every other Divergence, so every
    #   bot, missing, unexpected and failed one (run.judge's `failed` keeps the default).
    # bot: the Bot has Events (sent or received) in only one Transcript; reference and
    #   candidate are its Event counts, ABSENT on the other side. Its stream's Divergences
    #   follow, against an empty stream. (A Bot that only sent would otherwise go unseen.)
    # missing: a reference packet the alignment left unmatched (candidate is ABSENT);
    # unexpected: a candidate packet it left unmatched (reference is ABSENT);
    # field: a difference between two matched packets;
    # failed: the Group failed on the Candidate (made by run.judge, never by compare):
    #   bot the Bot the failure came out of (GroupError.bot; "" only if the script
    #   itself raised it), index 0, reference ABSENT, candidate the failure ("TimeoutError: ...").

@frozen
class Verdict:
    group_id: str
    outcome: Outcome
    divergences: tuple[Divergence, ...] = ()
    detail: str = ""
    test_cases: tuple[str, ...] = ()  # every test case compared, matched or not, sorted
                                    # and unique (Comparison semantics step 5); () when
                                    # blocked or error. run.judge keeps compare's.
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
                                    # "observe:open minecraft:block_update"
OBSERVE_CLOSE = "observe:close"     # the Mark that closes it
HEARTBEAT: Mapping[str, str]        # packet name -> reason: the play packets a window never
                                    # compares (keep_alive, set_time, award_stats; evidence in
                                    # docs/research/2026-09-30-observation-window.md)
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
                                    # (#106)
ENTITY_UUIDS: Mapping[str, str]     # "<packet>.<path>" -> reason: the fields that hold an
                                    # entity's UUID, which every Comparison numbers by first
                                    # appearance, but not a player's (#21):
                                    # minecraft:add_entity.entity_uuid

def compare(reference: Transcript, candidate: Transcript,
            masks: Sequence[Mask]) -> Verdict: ...
    # Numbers each Bot's entity ids and ENTITY_UUIDS `#1`, `#2`, ... in the order they first
    # appear in the packets it compares, never those outside the windows (Comparison
    # semantics, between steps 2 and 3), so Divergence paths and values show `#<n>` where
    # the packets had ids.
    # Masks the RANDOM_FIELDS, then applies `masks`. Every Bot is compared but Control's
    # (spec.CONTROL_PLAYER): its Events stay in the Transcript.
    # ValueError if the Transcripts are of different Groups; TypeError if fields hold
    # a value outside the codec value model. Divergences are grouped by Bot in name order,
    # then in stream order, and within a packet in path order: its gameplay Divergences
    # first, then its network traffic ones.
    # A packet's value (for missing / unexpected) is its fields, or its payload as hex.
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

class PlayersStillOnline(Exception):  # str(): "2 players still online after waiting 2 s: watcher, control"
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
    # one Instance; closes every Bot however it ends; GroupError if the Group raised
CANDIDATE_FAILURES = (CodecError, ProtocolError, TimeoutError, ConnectionError,
                      PlayersStillOnline)
def judge(group: Group, reference: Transcript | GroupError,
          candidate: Transcript | GroupError) -> Verdict: ...
    # The Verdict rule (audit H3): a Candidate failure (its GroupError's cause is one of
    # CANDIDATE_FAILURES) is `mismatch`: a `failed` Divergence first, then what compare
    # finds in the Transcripts so far (e.g. the undecodable frame, by payload), whatever the
    # Masks. CommandMissing on the Candidate (it lacks a command Control needs) is
    # `blocked`, detail "needs /<root>". `error` only if the Reference failed (CommandMissing
    # included), the Group raised anything else on the Candidate (a harness bug), or compare
    # raised. Else compare(reference, candidate, masks).
def blocked(group: Group, verdicts: Mapping[str, Verdict]) -> Verdict | None: ...
    # blocked ("prerequisite X was mismatch" / "was not run") unless every `requires` matched
async def run(groups: Sequence[Group], reference: Side, candidate: Side, *,
              workdir: Path, repeat: int = 1) -> list[Verdict]: ...
    # one Verdict per Group per repetition, repetition after repetition, in the order
    # given; a Group is blocked (not played) unless its prerequisites matched earlier in
    # the same repetition. One Instance pair per distinct ServerSpec the Groups' `spec`
    # make, each side at its own free_endpoint(), launched together when first needed,
    # readiness by status_probe, kept for every repetition, stopped however the Run ends.
    # An Attached side is played at its endpoint for every Group, never started or
    # stopped; the same code path otherwise (judge, blocked, repetitions).
    # Settling (#97): before a Group plays, both Instances are waited on at once with
    # `until_no_player_online(endpoint, deadline_s=SETTLE_TIMEOUT_S)` (settle.py, above).
    # A side that is still not empty means the Group is played on neither side, and its
    # Verdict says who is still online. The Reference's failure is `error`: "the Reference
    # had 2 players still online after waiting 2 s: watcher, control" (the Candidate's
    # sentence after a "; " if it had players too). The Candidate's alone is `mismatch`
    # (audit H3: a Candidate failure is never `error`): a `failed` Divergence (bot "",
    # candidate "2 players still online after waiting 2 s: watcher, control"), detail
    # "the Candidate failed: ...". A wait that raises anything else (#114) is never raised
    # out of the Run, and the other side's wait runs to its end (gather with
    # return_exceptions): on the Reference it is `error`, "the Reference failed: the wait
    # for no player online failed: <Type>: <message>"; on the Candidate, one of
    # CANDIDATE_FAILURES is `mismatch` as above, with "the wait for no player online
    # failed: <Type>: <message>" as the `failed` Divergence's candidate and after "the
    # Candidate failed: ", and anything else is a harness bug, `error`, "the harness failed
    # on the Candidate: the wait for no player online failed: ...", as in judge. If both
    # sides fail, the detail joins both sentences with "; ": "the Reference had ...; the
    # Candidate failed: the wait ...". A BaseException that is not an Exception (a
    # cancellation from inside a wait) is raised once both waits are done. The wait is
    # not part of `elapsed_s`.
    # NotImplementedError for a Group that is not exact (M6a/M6b); ValueError for one
    # listed twice, or whose `spec` does not give an Attached side's spec (host and port
    # aside: it would run against the wrong config), before anything starts; RunnerError
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
   `custom_payload`) are different packets. Not compared, on purpose:
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
     do not observe. A window opens at an `observe:open` Mark and ends at
     the next `observe:open` or `observe:close` Mark, or at the end of the
     Transcript if none follows (the Group raised inside it). It observes
     every play packet that arrived (`t_ns`) at or after its open Mark and
     before its end, except the heartbeat packets (`compare.HEARTBEAT`),
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
2. **Canonicalize** values the vanilla client treats as equal: text
   component `"x"` ≡ `{"text": "x"}`, JSON key order, and similar.
   Canonicalization encodes a protocol equivalence. It is not a Mask,
   and it is a classifier, not an eraser (ADR-0007): the raw fields are
   diffed too, and a raw difference whose canonical values (before the
   Masks) are equal at its path is reported as a **network traffic** `field`
   Divergence, with the raw path and values. A raw field holding JSON
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
   so the same entities on two servers have other ids and UUIDs. Each
   entity id becomes `#<n>`: the n-th entity in the packets the
   Comparison takes for the Bot (step 1, less the packets a `*` Mask
   drops), in wire order. Packets outside the windows take no number:
   how many chunk batches, world-generation mobs and natural spawns a
   Bot heard of before a window opened is timing, and counting them
   would shift every number inside it. So what is not compared never
   shifts what is; without windows, the Bot's own player (`login`) is
   `#1`. The Codec names
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
   the UUIDs of other packets. A Candidate that gives a removed entity's id
   to a new one would show differences vanilla would not, since an id
   keeps its first number.
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

   The alignment is a **longest common subsequence** of the packet keys,
   so as few packets as possible are reported `missing` or `unexpected`.
   Of the longest ones, the choice is fixed so that swapping the sides
   mirrors it: match the common prefix and suffix as they stand (so of
   repeated packets the prefix matches the earliest and the suffix the
   latest: `[a]` against `[b, a, a]` matches the last `a`); between
   them, trace from the front, matching equal keys, otherwise skipping
   the key whose skipping keeps the longer subsequence, and on a tie
   the smaller key, whichever side it is on. Between two matched pairs,
   `missing` comes before `unexpected`. A unit test checks every pair of
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
   fields, the pair is compared by payload. `compare` never mutates its
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
   canonicalization, whether the two were equal or not, and the test
   case of every Divergence. A dropped packet and a packet an
   Observation window leaves out are in none, and neither is a pair of
   values at a masked path that are the same (two `MASKED`, or two
   None): a masked field is a test case only where it diverges. Each is the same, different in gameplay, or different in
   network traffic only (`Verdict.differing`). A network traffic test
   case appears only where the two formats differed: its raw path is
   not a compared field otherwise, and listing it as the same would
   claim a comparison that was never made.

### Measurements and Report

- `cli`: `ADAPTERS`, `DEFAULT_GROUPS`, `DEFAULT_REPEAT`, `REFERENCE`, `RUN_NOTES` — CLI defaults and
  Run notes.

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

# run.py: run_results(groups, reference, candidate, *, workdir, repeat=1) -> RunResult
# plays exactly as run() does (run() returns its .verdicts); a blocked repetition measures
# nothing on either side.
@frozen
class GroupResult:
    group_id: str
    verdicts: tuple[Verdict, ...]                    # one per repetition
    reference: tuple[tuple[Measurement, ...], ...]   # one tuple per repetition
    candidate: tuple[tuple[Measurement, ...], ...]
    elapsed_s: tuple[float, ...] = () # both plays and Comparison per repetition; blocked 0

@frozen
class SideSummary:
    name: str                       # adapter name
    version: str | None             # version.name of its first status_response (lenient)
    startup: tuple[Measurement, ...]  # instance.startup (ms, ready_ns - launched_ns) per
                                      # launched Instance; none for an Attached side
    installed_version: str | None = None # Registry version or sha256; unknown without Source

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
    # later: compliance = matches / (groups − errors); to_json(), to_markdown()

def render_text(report: Report, *, verbose: bool = False) -> str: ...
# test_cases.py: TITLES: Mapping[str, str], test case name → short title.
# docs/reference/test-cases.md has one entry per title, checked against the table.
# Unknown test cases are still reported; the table never filters Comparisons.
# ADR-0012 / #9: first line "Running tests against <candidate adapter name>";
# one plain line per differing test case, deduplicated across Groups and repetitions,
# with its TITLES title and name, or its bare name when unknown. Gameplay and network
# traffic share the list. Then blocked, error and failed Groups, with id and reason;
# Group-level bot differences are retained too. "No differences." only if the list
# is empty and every Group was compared. Last line "Took <seconds> s", rounded to
# tenths, including launch and shutdown. No values, section headings, Notes, legend,
# counts or per-Measurement timing table.
# #10: verbose adds installed versions, Target and repetitions at the top, distinct
# pairs of actual values directly under each difference, and total time per Group
# across repetitions (play both sides + Comparison; excludes startup/shutdown).
# Blocked Groups say "not played"; older results without durations say "not recorded".
```

CLI (`src/mscts/cli.py`, stdlib argparse; `[project.scripts] mscts = "mscts.cli:main"`;
`main(argv=None, *, fetch=https_get) -> int`). Every command says exactly what it did or
would do; an error is one `mscts: <message>` line on stderr naming its fix, exit 1:

```
mscts adapter install <adapter> [--version V | --from PATH]
    # the Target's Registry entry (or --version V): "downloading <url> ...", then
    # "installed <entry> from <url> into <root>", or "<entry> is already installed at <root>
    # (sha256 …): nothing to do". --from: "installed <path> (sha256 …; the Registry entry
    # <entry> | no Registry entry, …) into <root>". Another build installed: refused, naming
    # the delete-and-install command. A download that is not the entry: its sha256, the
    # entry's note ("the nightly moved") and the --from command.
mscts adapter list                  # ADAPTER VERSION TARGET STATE, one row per Registry entry,
                                    # plus a row for an installed build that is no entry
mscts adapter status <adapter>      # root, entry, sha256, size, from, installed; exit 1 and
                                    # the install command when nothing is installed
mscts selfcheck [--group GLOB] [--repeat N]
mscts run --candidate <adapter> [--group GLOB] [--repeat N] [-v | --verbose] [--out DIR]
    # --group: fnmatch over the registered exact Group ids, prerequisites added
    # (default status/*); --repeat default 5; --out not implemented yet.
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
score, `blocked` counts per missing command, and history across Candidate
versions.

**M3a — Installs and the registry (ADR-0008).**
- `mscts adapter install <adapter> [--version]` / `--from <path>`, plus
  `list` and `status`, all idempotent;
- the honest TTY prompt, and a non-TTY failure naming the command;
- a committed registry pinned by checksum.

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
  ticks) or a latency-only `player_info_update` (every 601 ticks) be
  heartbeat packets? Telling them from a real move or player list change
  needs those packets' schemas: `move_entity_pos` has one since #20,
  `player_info_update` none yet. Until this is decided, a window that can
  catch them names the packets it tests.
- How should chunk data be compared: decode the palette into block states,
  or compare raw?
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
