#!/usr/bin/env python3
"""
PROTOTYPE - THROWAWAY. Do not build on this.

Question this answers:
  "Are vanilla's internal methods usable as-is for golden fixtures, or do they
   need filtering to strip out implementation-detail-dependent ones?"

Approach: run javap over the real (unobfuscated) vanilla server jar and bucket
every member of the parity-relevant classes into a fixture-suitability taxonomy.

The taxonomy is the actual output. The heuristics below are deliberately crude -
the point is to find out HOW MUCH can be decided mechanically and how much needs
human judgement, not to ship a classifier.
"""

import re
import subprocess
import sys
from collections import Counter, defaultdict

# --- the taxonomy -----------------------------------------------------------
# SPEC     observable invariant; a from-scratch impl MUST match this
# EMERGENT the method is vanilla plumbing, but the ORDER/SEQUENCE of its effects
#          is spec-critical. Cannot be fixtured as a return value - must be
#          fixtured as a trace. This bucket is the whole reason tick-by-tick
#          comparison is required rather than end-state comparison.
# INTERNAL vanilla plumbing; impl may differ freely and still be correct
# CLIENT   client/visual only; irrelevant to server-side parity
# SERDE    serialization, codecs, registration; not behaviour
# UNKNOWN  heuristics disagree or say nothing - needs a human
BUCKETS = ["SPEC", "EMERGENT", "INTERNAL", "CLIENT", "SERDE", "UNKNOWN"]

CLIENT_NAMES = re.compile(
    r"^(animateTick|getParticle|spawnDestroyParticles|playSound|getSoundType"
    r"|appendHoverText|getMenuProvider|getDescriptionId)", re.I)

SERDE_NAMES = re.compile(
    r"^(codec|CODEC|createBlockStateDefinition|getStateDefinition|save|load"
    r"|serialize|deserialize|writeTo|readFrom)$")

SERDE_TYPES = re.compile(
    r"(MapCodec|Codec<|StateDefinition\$Builder|CompoundTag|ValueInput|ValueOutput"
    r"|DataComponent|RegistryFriendlyByteBuf|FriendlyByteBuf)")

# Methods whose RESULT is part of observable game behaviour.
SPEC_NAMES = re.compile(
    r"^(getDelay|isLocked|getSignal|getDirectSignal|getInputSignal|getAlternateSignal"
    r"|shouldTurnOn|isSignalSource|getOutputSignal|hasAnalogOutputSignal"
    r"|getAnalogOutputSignal|canSurvive|getStateForPlacement|updateShape|tick"
    r"|neighborChanged|onPlace|affectNeighborsAfterRemoval)$")

# Names that scream "this is how *vanilla* happens to be built".
INTERNAL_NAMES = re.compile(
    r"^(sideInputDiodesOnly|isDiode|shouldPrioritize|checkTickOnNeighbor"
    r"|getControlInputSignal|.*Internal|.*Impl)$")

# Update-propagation machinery. Individually these are vanilla internals, but the
# ORDER in which they fire is exactly what redstone parity hinges on.
EMERGENT_CLASSES = {"CollectingNeighborUpdater"}
EMERGENT_NAMES = re.compile(
    r"^(addAndRun|runUpdates|shapeUpdate|neighborChanged"
    r"|updateNeighborsAtExceptFromFacing|updateNeighborsInFront"
    r"|checkCornerChangeAt|refreshOutputState)$")

# Vanilla's own observability seam - a public per-BlockPos callback fired as
# neighbour updates are drained. This is a candidate trace-capture hook.
OBSERVABILITY_HOOKS = {"setDebugListener"}


def classify(name, ret, params, flags, cls=""):
    """Return (bucket, reason). Crude on purpose."""
    sig = f"{ret} {params}"

    if name in OBSERVABILITY_HOOKS:
        return "EMERGENT", "*** vanilla's own trace-capture hook ***"
    if cls in EMERGENT_CLASSES or EMERGENT_NAMES.match(name):
        return "EMERGENT", "update propagation - ORDER is the invariant, not the value"
    if SERDE_NAMES.match(name) or SERDE_TYPES.search(sig):
        return "SERDE", "codec/registration/NBT in signature"
    if CLIENT_NAMES.match(name):
        return "CLIENT", "client-visual method name"
    if "RandomSource" in params and name == "animateTick":
        return "CLIENT", "animateTick is client-only"
    if INTERNAL_NAMES.match(name):
        return "INTERNAL", "vanilla-structural predicate"
    if SPEC_NAMES.match(name):
        return "SPEC", "observable behavioural output"
    if "static" in flags and ret == "void":
        return "INTERNAL", "static void - side-effecting plumbing"
    if ret == "void" and "Builder" in params:
        return "SERDE", "builder registration"
    return "UNKNOWN", "no rule matched - needs human judgement"


JAVAP_MEMBER = re.compile(
    r"^\s+(?P<flags>(?:public |protected |private |static |final |abstract |synchronized |native )*)"
    r"(?P<ret>[\w\.\$<>\[\],\? ]+?)\s+"
    r"(?P<name>[\w\$]+)\((?P<params>.*)\);\s*$")


def short(t):
    """net.minecraft.core.BlockPos -> BlockPos"""
    return re.sub(r"(?:[a-z_][\w]*\.)+(?=[A-Z])", "", t)


def parse(classname, cp):
    out = subprocess.run(
        ["javap", "-p", "-cp", cp, classname],
        capture_output=True, text=True)
    if out.returncode != 0:
        print(f"  !! javap failed for {classname}", file=sys.stderr)
        return []
    members = []
    for line in out.stdout.splitlines():
        m = JAVAP_MEMBER.match(line)
        if not m:
            continue
        name = m.group("name")
        if name in ("static", classname.split(".")[-1]):
            continue
        # synthetic compiler output - never part of any spec surface
        if name.startswith("lambda$") or name.startswith("access$"):
            continue
        members.append({
            "cls": classname.split(".")[-1],
            "name": name,
            "ret": short(m.group("ret").strip()),
            "params": short(m.group("params")),
            "flags": m.group("flags").strip(),
        })
    return members


def main():
    cp = sys.argv[1]
    classes = sys.argv[2:]

    all_members = []
    for c in classes:
        all_members.extend(parse(c, cp))

    for mem in all_members:
        mem["bucket"], mem["reason"] = classify(
            mem["name"], mem["ret"], mem["params"], mem["flags"], mem["cls"])

    by_bucket = defaultdict(list)
    for mem in all_members:
        by_bucket[mem["bucket"]].append(mem)

    print("=" * 78)
    print("FIXTURE-SUITABILITY CLASSIFICATION  (PROTOTYPE)")
    print("=" * 78)

    counts = Counter(m["bucket"] for m in all_members)
    total = len(all_members)
    print(f"\n{total} members across {len(classes)} classes\n")
    for b in BUCKETS:
        n = counts.get(b, 0)
        pct = (100.0 * n / total) if total else 0
        bar = "#" * int(pct / 2)
        print(f"  {b:9} {n:4}  {pct:5.1f}%  {bar}")

    for b in BUCKETS:
        if not by_bucket[b]:
            continue
        print(f"\n{'-' * 78}\n{b}\n{'-' * 78}")
        for m in sorted(by_bucket[b], key=lambda x: (x["cls"], x["name"])):
            params = m["params"]
            if len(params) > 46:
                params = params[:43] + "..."
            print(f"  {m['cls']:22} {m['name']:28} ({params})")
            print(f"  {'':22} -> {m['ret']:24} [{m['reason']}]")

    mech = total - counts.get("UNKNOWN", 0)
    print(f"\n{'=' * 78}")
    print(f"VERDICT: {mech}/{total} ({100.0*mech/total:.0f}%) bucketed mechanically; "
          f"{counts.get('UNKNOWN',0)} need a human.")
    print(f"Fixture-usable surface (SPEC) = {counts.get('SPEC',0)}/{total} "
          f"({100.0*counts.get('SPEC',0)/total:.0f}%)")
    print("=" * 78)


if __name__ == "__main__":
    main()
