# Comparison research — 2026-09-26

Facts about how the vanilla 26.3 client reads what a server sends, found
while building `mscts.compare`. They decide which encodings the Comparison
may treat as equal (Canonicalization). Everything marked **verified** was
read first-hand from the 26.3 server jar in the shared cache (the bundled
`server-26.3.jar`, sha256 `a362163e…`, and its libraries) with
`javap -c -p -constants` from Temurin 25. The 26.x jars are not
obfuscated, so class and method names are the real ones.

## The status response JSON — verified

- `ClientboundStatusResponsePacket` reads its JSON through
  `ByteBufCodecs.lenientJson(32767)`, then `ServerStatus.CODEC` over
  `JsonOps`. `LenientJsonParser.parse(String)` is Gson's
  `JsonParser.parseString`, which reads in Gson's lenient mode.
- `ServerStatus.CODEC` fields, all `lenientOptionalFieldOf` (a wrong value
  reads as absent):
  - `description`: `ComponentSerialization.CODEC`, default
    `CommonComponents.EMPTY` (the empty literal, `""`);
  - `players`: `ServerStatus.Players.CODEC`, optional;
  - `version`: `ServerStatus.Version.CODEC`, optional;
  - `favicon`: `ServerStatus.Favicon.CODEC`, optional;
  - `enforcesSecureChat`: `Codec.BOOL`, default `false`.
- `Players`: `max` and `online` are required `Codec.INT`; `sample` is
  `NameAndId.CODEC.listOf()`, default `List.of()`. `Version`: `name` is a
  required `Codec.STRING`, `protocol` a required `Codec.INT`. So only
  `description` holds a text component; `version.name` and the sample
  names are plain strings.
- DFU 10.0.21 (the bundled datafixerupper): `OptionalFieldCodec.decode`
  reads a missing field as empty and, when lenient, a field that fails to
  parse as empty too. `Codec.optionalFieldOf(name, default)` encodes
  `Objects.equals(a, default) ? Optional.empty() : Optional.of(a)`, so a
  value equal to its default is omitted. That is why vanilla's own answer
  has no `sample` (with no players) and no `enforcesSecureChat`.
- DFU 10.0.21's `JsonOps.getNumberValue` accepts any JSON number
  (Gson's `getAsNumber`), so `20.0` where `Codec.INT` is expected. It
  rejects a boolean, and takes a string only in compressed mode (never
  for `JsonOps.INSTANCE`). A rejected value in a `lenientOptionalFieldOf`
  field reads as absent (above).
- Gson 2.14.0 is the bundled Gson. Its `JsonReader` has
  `DEFAULT_NESTING_LIMIT = 255` and sets it in the constructor.
  `push()` throws `MalformedJsonException("Nesting limit 255 reached")`
  when a 256th container opens, so at most 255 nested arrays or objects
  are read.

## Unknown keys and JSON `null` in the status JSON — verified

Read with `javap -c -p -constants` (Temurin 25.0.4) on the 26.3 **client**
jar (sha1 e877b6a07acd633fb3bb475002175cec036e7b87, via
`scripts/research/javap.py client`) and on the DataFixerUpper 10.0.21
(sha1 b6b2ae770c02e0c1eb90f9985b151e9085a38d0b) and Gson 2.14.0 (sha1
efc0e34ede4e3204eaefb84a00e55e8c86634382) jars bundled in the 26.3 server
jar's `META-INF/libraries/`. Found while checking two Pumpkin status
Divergences: `"enforceSecureChat": true` and `"favicon": null`.

- **The ops.** `ClientboundStatusResponsePacket.<clinit>`:
  `OPS = RegistryAccess.EMPTY.createSerializationContext(JsonOps.INSTANCE)`,
  then `ByteBufCodecs.lenientJson(32767).apply(ByteBufCodecs.fromCodec(OPS,
  ServerStatus.CODEC))`. `RegistryOps` extends `DelegatingOps` and does not
  override `getMap`; `DelegatingOps.getMap(T)` is
  `delegate.getMap(input)`, so maps are read by `JsonOps`.
- **The field names.** `ServerStatus.lambda$static$0` (the
  `RecordCodecBuilder.create` body of `ServerStatus.CODEC`) names exactly
  five fields, each with `lenientOptionalFieldOf`: `ldc "description"`,
  `"players"`, `"version"`, `"favicon"`, `"enforcesSecureChat"` (with an
  `s`), then `Instance.group(5 apps)` and `Products$P5.apply`. The string
  `enforceSecureChat` (no `s`) appears nowhere in
  `net/minecraft/network/protocol/status/`. `ServerStatus$Players.CODEC`
  names `max`, `online` (`fieldOf`) and `sample`
  (`lenientOptionalFieldOf(…, List.of())`); `ServerStatus$Version.CODEC`
  names `name` and `protocol` (`fieldOf`). All three are
  `RecordCodecBuilder.create`.
- **Unknown keys are never read.** `MapCodec$MapCodecCodec.decode` is
  `codec.compressedDecode(ops, input)`; `MapDecoder.compressedDecode`, with
  `compressMaps()` false (as for `JsonOps.INSTANCE`), is
  `ops.getMap(input).flatMap(map -> decode(ops, map))`. A record's fields
  read the map only by name: `FieldDecoder.decode` and
  `OptionalFieldCodec.decode` both start `MapLike.get(name)`. No decoder
  on the path calls `MapLike.entries()` (grep of the dumped classes: only
  `JsonOps` itself does, in unrelated methods). So a key none of the
  five (three, two) names spells is not read at all, **by definition of
  the record codec**, not through error handling: the object decodes as
  if the key were absent. So Pumpkin's `"enforceSecureChat": true` reads
  exactly as vanilla's absent `enforcesSecureChat`: the default `false`.
- **A JSON `null` member reads as absent.** `JsonOps.getMap(JsonElement)`
  wraps a `JsonObject` in `JsonOps$1`, whose `get(String)` is
  `JsonObject.get(key)`, then `instanceof JsonNull` → `aconst_null;
  areturn`. `OptionalFieldCodec.decode` then falls through its `ifnonnull 22`
  and returns `DataResult.success(Optional.empty())`: the same
  instructions (0–21) as for a missing key, before any element codec or
  lenient handling runs. (This corrects PLAN's earlier reading that
  `"sample": null` becomes the default only through lenient error
  handling.) Gson's parser produces a `JsonNull` for `null`
  (`JsonParser.parseString` → `parseReader` → `Streams.parse` →
  `JsonElementTypeAdapter.read`, whose `readTerminal` maps `NULL` to
  `nextNull(); JsonNull.INSTANCE`), and `JsonObject.add(key, null)` stores
  `JsonNull.INSTANCE`. So `"favicon": null` reads as no favicon, the same
  as vanilla's absent `favicon`. The same holds for any member of these
  three objects: `"sample": null` reads as the default `List.of()`, and a
  null required field (`"max": null`) reads as missing (an error, which
  `lenientOptionalFieldOf("players")` then turns into an absent
  `players`: that second step *is* lenient error handling).
- Not established (so not canonicalized): the text component codec
  (`description`) and `NameAndId.CODEC` (the sample entries). Both may
  read keys in other ways (the component codec infers its type from the
  keys present), so their unknown keys and nulls stay significant.

## Text components — verified

- `ComponentSerialization.createCodec` is
  `Codec.either(Codec.either(Codec.STRING, nonEmptyList(codec.listOf())), fullCodec)`
  mapped by: a string → `Component.literal`, a list →
  `createFromList` (`first.copy()`, then `append` each of the rest), an
  object → the full codec (contents dispatched on `type`, else inferred
  from the keys; `extra` is `nonEmptyList(codec.listOf())` with default
  `List.of()`; the style fields from `Style.Serializer.MAP_CODEC`).
  Encoding writes a string whenever `Component.tryCollapseToString()`
  gives one.
- So `"x"` and `{"text": "x"}` decode to the same literal component, with
  an empty style and no siblings. `"extra": []` is *not* valid (the list
  must be non-empty). The list form `["a", "b"]` decodes like
  `{"text": "a", "extra": ["b"]}`.
- What the client ends up with (#342), read with `javap -c -p -constants`
  on the 26.3 **client** jar and its DataFixerUpper 10.0.21:
  - A plain string `"x"` is `Component.literal("x")`, the same component
    as `{"text": "x"}` (above). `lambda$createCodec$2` maps the inner
    either with `Component::literal` and `ComponentSerialization::createFromList`.
  - A list `[a, b, ...]` is `createFromList`: `a.copy()`, then
    `MutableComponent.append` of each of `b, ...`. `Component.copy()` is
    `new MutableComponent(getContents(), new ArrayList(getSiblings()),
    getStyle())`, and `append` is `siblings.add`. So the list is the
    component `a`, with `b, ...` added at the end of its `extra`. An
    object is built by the same `MutableComponent(contents, siblings,
    style)` constructor (`lambda$createCodec$0`), so `["a", "b"]` and
    `{"text": "a", "extra": ["b"]}` are the same component, and `["a"]` is
    `"a"`. The list's elements and `extra`'s are decoded by `CODEC`
    itself (`Codec.recursive("Component", createCodec)` in `<clinit>`).
  - An empty list is refused wherever the component codec meets one:
    `ExtraCodecs.nonEmptyList(codec)` is `codec.validate(list ->
    list.isEmpty() ? DataResult.error(...) : DataResult.success(list))`,
    and it wraps both the list form and `extra`
    (`optionalFieldOf("extra", List.of())`, which is not lenient). The
    error reaches the description: `EitherCodec.decode` succeeds only
    when one side succeeds, and `ListCodec$DecoderState` turns one
    element's error into the list's.
  - `ServerStatus.CODEC` reads `description` with
    `lenientOptionalFieldOf("description", CommonComponents.EMPTY)`.
    `OptionalFieldCodec.decode` returns `Optional.empty()` whenever the
    lenient field's value is an error, partial result or not. So a
    description with `"extra": []` or `[]` anywhere in it is shown as
    no description at all: `{"text": "x", "extra": []}` reads as
    `CommonComponents.EMPTY`, not as `"x"`.
- minecraft.wiki *Text component format*, raw wikitext at oldid 3749600
  (2026-08-29), says the same: "A string containing plain text to display
  directly. This is the same as an object that only has a text tag. For
  example, `"A"` and `{text: "A"}` are equivalent", and a list is "Same
  as having all components after the first one appended to the first's
  extra list".
- minecraft.wiki *Java Edition protocol/Server List Ping*, oldid 3789989
  (2026-09-23): `description` is optional and is a text component; the
  favicon is optional; "If [sample is] empty, missing, or the wrong type,
  no tooltip will appear. Notchian servers will omit this field if there
  are no players".

## Text components in NBT (#335) — verified 2026-11-02

Read with `javap -c -p -constants` on the 26.3 **client** jar
(`scripts/research/javap.py client`). In play, every text component is
network NBT (`ComponentSerialization.TRUSTED_STREAM_CODEC` and its
relatives), read with `NbtOps`, then decoded by the same component codec
as the JSON above.

- **The tag.** A root is a type byte and that type's payload, with no
  name. A String is modified UTF-8 (`DataInput.readUTF`, from
  `StringTag$1` and `CompoundTag$1.loadCompound`). A repeated name in a
  compound keeps its last value (`CompoundTag$1.loadCompound` puts each
  entry into a `HashMap`). Lists and compounds nest at most 512 deep
  (`NbtAccounter`).
- **Wrapped list elements.** `ListTag$1.loadList` adds each element with
  `ListTag.addAndUnwrap`, and `tryUnwrap` takes a compound of size 1
  whose tag named `""` is not null as that tag. One level only: the
  tag inside is not unwrapped again, but its own lists are loaded the
  same way. Vanilla writes a list of mixed tag types this way.
- **The contents' `type`.** The contents map codec is
  `ComponentSerialization$StrictEither("type", typed, fuzzy)`. Its
  `decode` takes the typed codec when `type` is present, and otherwise
  `FuzzyCodec.decode`, which tries each contents codec in the order they
  were bootstrapped (text, translatable, keybind, score, selector, nbt,
  object; `ExtraCodecs$LateBoundIdMapper` keeps them in a Guava
  `HashBiMap`, in insertion order) and takes the first that reads the
  object. The text codec is `PlainTextContents.MAP_CODEC`,
  `Codec.STRING.fieldOf("text")`. So `{"type": "text", "text": s}` and
  `{"text": s}` are the same component when `s` is a string.
- **Style flags.** `Style$Serializer.MAP_CODEC` reads `bold`, `italic`,
  `underlined`, `strikethrough` and `obfuscated` with
  `Codec.BOOL.optionalFieldOf` (not lenient) into a nullable `Boolean`.
  `Codec.BOOL` calls `NbtOps.getBooleanValue`, which is
  `getNumberValue(tag).map(n -> n.doubleValue() != 0)`: any numeric tag
  is read, NaN is true (`dcmpl`) and -0.0 false. A String is refused
  (`getNumberValue` takes numeric tags only). A false flag is kept in the
  style, so it is not the same as an absent one.
- **Translation arguments.** `TranslatableContents.MAP_CODEC` reads
  `with` as `ARG_CODEC.listOf().optionalFieldOf("with")`. `ARG_CODEC` is
  `Codec.either(PRIMITIVE_ARG_CODEC, ComponentSerialization.CODEC)`
  mapped by `lambda$static$0`: a primitive as it is, a component as
  `requireNonNullElse(c.tryCollapseToString(), c)`.
  `PRIMITIVE_ARG_CODEC` is `ExtraCodecs.JAVA` (a converter to
  `JavaOps`; `NbtOps.convertTo` makes a numeric tag its boxed number and
  a String a `String`) validated by `filterAllowedArguments` (a
  `Number`, `Boolean` or `String`). `Component.tryCollapseToString`
  gives the text of a plain text component with no siblings and an
  empty style, else null. `getArgument` returns a `Component` as it is,
  null as `TEXT_NULL`, and anything else as
  `FormattedText.of(arg.toString())`. So the argument `"5"`, the byte
  5, the int 5 and `{"text": "5"}` all show as the text `5`. A float's
  `toString` is Java's (`1.0E10`), which the Comparison does not model,
  so float arguments are left as they are. `NbtOps.convertTo` makes a
  float tag a `Float` (`createFloat`, offset 327) and a double tag a
  `Double` (`createDouble`, offset 373), and each has its own
  `toString`: the float 0.1 shows `0.1`, and a double of the same number
  `0.10000000149011612` (Java 25). So a float argument is never the
  same as a double one, even with the same number.
- **Colour.** `color` is `TextColor.CODEC`,
  `Codec.STRING.comapFlatMap(TextColor::parseColor, ...)`.
  `parseColor` reads `#` and then `Integer.parseInt(rest, 16)`, refused
  below 0 or above 0xFFFFFF, or else a name from `NAMED_COLORS`, which
  `TextColor.<clinit>` fills with the sixteen names (`black` 0x000000,
  `dark_blue` 0x0000AA, `dark_green` 0x00AA00, `dark_aqua` 0x00AAAA,
  `dark_red` 0xAA0000, `dark_purple` 0xAA00AA, `gold` 0xFFAA00, `gray`
  0xAAAAAA, `dark_gray` 0x555555, `blue` 0x5555FF, `green` 0x55FF55,
  `aqua` 0x55FFFF, `red` 0xFF5555, `light_purple` 0xFF55FF, `yellow`
  0xFFFF55, `white` 0xFFFFFF). `TextColor.equals` compares the class and
  the `value` field only. So `"red"`, `"#FF5555"` and `"#ff5555"` are the
  same colour.
- **Hover text.** `hover_event` is `HoverEvent.CODEC`, dispatched on
  `action`; `show_text`'s `HoverEvent$ShowText.CODEC` is
  `ComponentSerialization.CODEC.fieldOf("value")`, so its value is a text
  component read like any other.
- **Not modelled.** A key the codecs never read (a record codec ignores
  one), a `type` other than `text`, the `separator` of selector and NBT
  contents, a `show_entity` hover's `name` and `uuid`, `fallback`, float
  translation arguments and colours spelled with non-ASCII digits all
  stay as sent. Each such difference
  is still a gameplay Divergence, never a missed one.

## Python's json module (for the harness) — verified

- `json.loads` read 5000 nested arrays and raised `RecursionError` at
  16000 (CPython 3.13.15, default recursion limit 1000). Recursive Python
  over the result fails far earlier, so the Comparison refuses to parse
  JSON nested deeper than Gson's 255, and compares such a response as a
  raw string.
