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

## Python's json module (for the harness) — verified

- `json.loads` read 5000 nested arrays and raised `RecursionError` at
  16000 (CPython 3.13.15, default recursion limit 1000). Recursive Python
  over the result fails far earlier, so the Comparison refuses to parse
  JSON nested deeper than Gson's 255, and compares such a response as a
  raw string.
