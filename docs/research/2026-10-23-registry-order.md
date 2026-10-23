# Does the order of `registry_data` packets matter to the client? — 2026-10-23

Evidence for #451. In configuration a server sends one `registry_data` packet for each
registry it synchronizes. Pumpkin sends the same registries as vanilla in another order. The
question is whether the 26.3 client builds anything different from another order. Facts are
**verified** with `scripts/research/javap.py` on the 26.3 client and server jars, and live as
the last section says.

## Answer

No, for packets of different registries: the client keeps each registry's entries apart, by
registry, and loads the registries at `finish_configuration` in an order of its own. Yes, for
two packets of the same registry: their entries are appended in the order the packets came,
and an entry's place gives its number.

## The client's path (javap)

- `ClientConfigurationPacketListenerImpl.handleRegistryData` calls
  `RegistryDataCollector.appendContents(packet.registry(), packet.entries())` and nothing else.
- `RegistryDataCollector$ContentsCollector.<init>`: `elements = new HashMap()`, keyed by the
  registry's `ResourceKey`. `append` is `elements.computeIfAbsent(key, k -> new ArrayList())`
  then `addAll(entries)`: a second packet of one registry adds to the end of its list.
- `ClientConfigurationPacketListenerImpl.handleConfigurationFinished` (its lambda) calls
  `RegistryDataCollector.collectGameRegistries`, which calls `loadNewElementsAndTags`. That
  copies `elements` into another `HashMap` (`Map.forEach`, `Map.put` by key), then calls
  `RegistryDataLoader.load(map, resources, contexts, RegistryDataLoader.SYNCHRONIZED_REGISTRIES,
  executor)`.
- `RegistryDataLoader.lambda$load$0` makes one load task for each of `SYNCHRONIZED_REGISTRIES`
  in that list's order and runs them in that order.
- `NetworkRegistryLoadTask.load` takes its registry's data with `entries.get(registryKey())`
  (none: nothing to load) and walks `NetworkedRegistryData.elements()` in order.

So until `finish_configuration` the client only collects the packets by registry, and then
loads each registry by key, in the client's own order.

## The server's order (javap)

- `RegistrySynchronization.packRegistries` walks `RegistryDataLoader.SYNCHRONIZED_REGISTRIES`
  (a `List`) with `List.forEach`, and `SynchronizeRegistriesTask` sends one
  `ClientboundRegistryDataPacket` for each registry it is given. So vanilla sends one packet a
  registry, always in the same order, and two vanilla Instances never differ in it.

## Live (verified)

Pumpkin nightly 8ea2b7d against vanilla 26.3, `mscts run --candidate pumpkin` on main
693a4e5 (the default Groups, 5 plays): both send their `registry_data` packets one after
another, the same number of them, but 15 of each play's are in other places than vanilla's.
Pumpkin swaps `minecraft:cow_variant` and `minecraft:cow_sound_variant`, for example. Paired
in the order they came, they made 375 gameplay Divergences, 75 of them at `registry_id`.

## What this means for the Comparison

Packets of different registries can be compared registry by registry, whatever order each
server sent them in, and the order itself is network traffic (ADR-0007). Packets of one
registry keep their order.
