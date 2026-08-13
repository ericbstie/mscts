# PROTOTYPE — fixture surface spike

> **Throwaway.** Do not build on this. It exists to answer one question and to be
> read once. The validated decisions belong in `CONTEXT.md`/ADRs, not here.

Run it:

```bash
./run.sh          # latest release
./run.sh 1.21.11  # pin a version
```

## The question

> Are vanilla's internal methods usable as-is for golden fixtures, or do they need
> filtering to strip out implementation-detail-dependent ones?

Framed originally as "use the Fabric API methods internal to the server JAR".

## Verdict

**Fabric is not needed, and as of the 26.x line neither is any mapping toolchain.**

Three findings, in order of how much they change the plan.

### 1. Vanilla ships unobfuscated as of 26.1 — no Fabric, no Yarn, no remap step

The premise was that Fabric/Yarn is the way to reach readable vanilla internals.
That was true through 1.21.11. It is no longer true.

| | ≤ 1.21.11 | ≥ 26.1 |
|---|---|---|
| Server jar obfuscated | yes | **no** |
| Official `server_mappings` | published | **absent** |
| Fabric Yarn mappings | `1.21.11+build.6` | **empty** |
| Fabric intermediary | real | `0.0.0` stub |
| Java required | 21 | **25** |
| Fixture path | download → remap → call | **download → call** |

Measured by `run.sh`'s obfuscation probe: **26.2 → 636 readable classes** under
`net/minecraft/world/level/block/`; **1.21.11 → 0**.

Mappings did not disappear because access got harder. They disappeared because
there is nothing left to map. Full Mojang-style names survive down to method
parameters:

```java
public boolean isLocked(LevelReader, BlockPos, BlockState);
protected int getDelay(BlockState);
public static final BooleanProperty LOCKED;
public static final IntegerProperty DELAY;
```

The grilling decision to target the latest version only was right — and for a
stronger reason than was known at the time: latest is *substantially* cheaper,
because the entire remapping toolchain drops out of the design.

### 2. The filter is real, and it is not mechanically derivable

Over 107 members of six redstone classes:

| bucket | n | % |
|---|---|---|
| SPEC — observable invariant, impl must match | 38 | 36% |
| EMERGENT — ordering is the invariant | 13 | 12% |
| INTERNAL — vanilla plumbing, impl may differ | 7 | 7% |
| SERDE — codecs/registration | 9 | 8% |
| CLIENT — visual only | 3 | 3% |
| **UNKNOWN — needs human judgement** | **37** | **35%** |

So the worry was justified: only about a third of the surface is directly
fixture-usable, and roughly a third resists mechanical classification entirely.
Crude heuristics (name patterns, return types, codec/NBT types in the signature)
buy ~65% coverage; the rest is a judgement call per method.

`RepeaterBlock` alone shows all the categories:

- `getDelay(BlockState) -> int` — **SPEC**, pure function of block state
- `isLocked(LevelReader, BlockPos, BlockState) -> boolean` — **SPEC**, needs world context
- `sideInputDiodesOnly() -> boolean` — **INTERNAL**, a predicate about how vanilla
  structures diodes; a Rust impl need not have this concept at all
- `animateTick(...)` — **CLIENT**, irrelevant to server parity
- `codec()` / `createBlockStateDefinition(...)` — **SERDE**

Implication: the compliance checklist cannot be auto-generated from the jar. It
needs a curated, reviewed allowlist, and that curation is itself project work.

### 3. `CollectingNeighborUpdater` — why tick-by-tick is mandatory, plus a free trace hook

The class behind the repeater-locking gotcha:

```java
private final ArrayDeque<NeighborUpdates> stack;      // LIFO — the ordering artifact
private final List<NeighborUpdates> addedThisLayer;
private final int maxChainedNeighborUpdates;
public void setDebugListener(Consumer<BlockPos>);      // <-- public trace hook
```

Two things fall out:

**(a) A third category the original two-way split missed.** These methods are
individually implementation details — a from-scratch server needn't have this class
— but the *order* in which their effects fire is exactly the spec. They cannot be
fixtured as return values; they must be fixtured as a **trace**. That is the
`EMERGENT` bucket, and it is the concrete justification for the tick-by-tick
sequence decision made during grilling. End-state comparison would silently miss
every bug in this bucket.

**(b) Vanilla ships its own observability seam.** `setDebugListener` is a *public*
`Consumer<BlockPos>` fired per position as the update queue drains. The
golden-fixture generator can capture exact ordered update sequences by calling a
public setter — no mixins, no bytecode manipulation, no Fabric.

This partly answers the *other* open investigation ("can tick-by-tick ordering be
observed?"): **on the vanilla side, yes, cheaply.** It does not answer the custom-server
side — a Rust implementation still has to expose an equivalent trace, which points
back at the "protocol-observable plus a small mandatory introspection contract"
option. That half remains open.

## What this spike did NOT establish

- **Determinism across runs.** Never executed. JDK 25 is installed and 26.2 targets
  class-file major 69, so it is now runnable here — but no method was actually
  invoked twice and diffed. Golden fixtures are worthless if output is not
  reproducible across JVM runs, and that is unverified.
- **Bootstrap cost.** Whether these classes can be driven headlessly
  (`SharedConstants` + `Bootstrap.bootStrap()` + registries) without booting a full
  dedicated server is unknown.
- **The custom-server side of tracing.** See 3(b).
- **RNG parity.** Untouched.

## Next

Determinism is the cheapest high-value follow-up and is now unblocked: boot the
registries under JDK 25, call one `SPEC` method (`getDelay`) and one `EMERGENT`
trace twice in separate JVMs, and diff.
