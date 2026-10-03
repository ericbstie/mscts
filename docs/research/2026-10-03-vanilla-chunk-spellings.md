# Two chunk spellings vanilla varies between its own runs — 2026-10-03

Evidence behind #172. Across 40 vanilla-against-vanilla join plays (#30's
measurement, `player_movement_check false`, `respawn_radius 0`), gameplay
matched every time, but 39 plays had network traffic Divergences in
`level_chunk_with_light` that come from two spellings vanilla itself varies.
The client keeps the same chunk under either spelling
(`2026-10-02-chunks-light.md`), so the Comparison writes each in one spelling
before it diffs the raw fields.

Facts are **verified** with `scripts/research/javap.py` on the 26.3 server jar
unless a line says *inferred*.

## Palette order

What was recorded: in the first play on fresh Instances, the lowest section of
some chunks came as `palette [0, 88, 10, 9]` from one Instance and
`[88, 10, 9, 0]` from the other (air, then the flat world's three layers), with
the data repacked so that each entry resolves to the same block state.

Why the order varies:

- A new container holds one value: `PalettedContainer(T, Strategy)` makes its
  data for 0 bits, then calls `palette.idFor(initial)`. For a section that value
  is air. When a second value is set, the palette grows (`onResize`) and keeps
  the values it has, so a container built in memory lists its values in the
  order they were first set: air first, then the blocks world generation put
  there.
- A container written to disk goes through `PalettedContainerFactory`'s
  `blockStatesContainerCodec` or `biomeContainerCodec` (`SerializableChunkData`),
  whose codec (`PalettedContainer.codec`) packs it first (`pack`): a new
  `HashMapPalette` at the storage's bits, filled by `reencodeContents`, which
  walks the entries from index 0 and calls `idFor` for each value it has not
  met. So a container read back from disk (`unpack`, with that palette as is)
  lists its values in entry order: the bottom layer's block first, and air,
  which is above it, last.
- The packet writes the container as it is in memory
  (`PalettedContainer.write`: the palette, then the storage's raw longs).

So the same section is sent in insertion order by an Instance that generated
the chunk and still holds it, and in entry order by one that saved it and read
it back. Which of two fresh Instances has reloaded a given chunk by the first
join is *inferred* to depend on timing: it differed only in the first play,
and the plays after it (Instances reused, chunks saved) all agreed.

The biome containers are the same class and are packed the same way, so their
palette order varies for the same reason. Neither recorded run had a biome
palette of more than one value.

`pack` also drops values no entry uses, and picks the bits for the palette's
size (`getConfigurationForPaletteSize`). Neither showed in the measurement: the
recorded containers had the same values and the same bits, so only the order is
treated as one spelling.

## Sky light below the world

What was recorded: in 1 to 3 chunks a play, one Instance sent light section 0
(the one below the world) in the empty sky mask, and the other sent it in the
sky mask with 2048 zero bytes.

- The server sends an array for a stored layer that has one, and the empty bit
  for one that `isEmpty()` (`ClientboundLightUpdatePacketData.prepareSectionData`,
  `2026-10-02-chunks-light.md`). The same code writes the light of a
  `light_update`.
- Whether the server's sky layer for light section 0 has an array when the chunk
  is sent depends on the light engine's work on the chunk and its neighbours,
  which runs on worker threads: *inferred* from the measurement, where the
  chunks that differed changed from play to play.
- The client stores the same light either way: it never fills light section 0
  with sky light, and nothing else it does tells `new DataLayer()` from an array
  of zeros there (`2026-10-02-chunks-light.md`, "An empty section against an
  array of zeros"). The canonical form already equates them (#22); only the raw
  fields still differed.

## One spelling

The Comparison writes each copy of a chunk's fields, and of a light update's,
this way before it diffs them:

- A list or hash palette whose entries all index into it, and that has no more
  values than its bits have slots for, is put in ascending order of id. (A
  hash palette can be longer: the client's `HashMapPalette.read` reads a count
  and that many ids with no bound, but sorted, an entry's index might then not
  fit its slot. Vanilla does not send one: its palette gets more bits when it fills,
  `onResize`, *inferred*.)
  Each entry's index is changed to match. The bits, unused bits and any packing left after the last
  entry stay as sent.
- A sky light section 0 sent as an array of 2048 zero bytes is written as an
  empty section: bit 0 leaves the sky mask (written as `BitSet.toByteArray()`
  writes it, no trailing zero byte), the array goes, and bit 0 is set in the
  empty sky mask.

Every other spelling stays network traffic: a palette with values no entry uses
or with another number of bits, block light sent empty against zeros, and an
empty section against zeros anywhere but sky light section 0.
