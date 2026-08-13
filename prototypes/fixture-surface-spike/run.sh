#!/usr/bin/env bash
# PROTOTYPE - THROWAWAY. Do not build on this.
#
# One command. Downloads the vanilla server jar, unpacks it, and classifies the
# parity-relevant API surface into fixture-suitability buckets.
#
#   ./run.sh            # latest release
#   ./run.sh 1.21.11    # pin a version
#
# The jar is downloaded to .work/ (gitignored) and never redistributed.
set -euo pipefail
cd "$(dirname "$0")"

WORK=".work"
mkdir -p "$WORK"

MANIFEST="https://launchermeta.mojang.com/mc/game/version_manifest_v2.json"
VERSION="${1:-}"

echo "==> resolving version"
[ -f "$WORK/manifest.json" ] || curl -sS --max-time 60 "$MANIFEST" -o "$WORK/manifest.json"

read -r VERSION SERVER_URL HAS_MAPPINGS <<<"$(python3 - "$WORK/manifest.json" "$VERSION" <<'PY'
import json,sys,urllib.request
mf,want = sys.argv[1], sys.argv[2]
m = json.load(open(mf))
want = want or m["latest"]["release"]
hit = [v for v in m["versions"] if v["id"] == want]
if not hit:
    sys.exit(f"unknown version {want}")
d = json.load(urllib.request.urlopen(hit[0]["url"], timeout=60))
print(want, d["downloads"]["server"]["url"], "server_mappings" in d["downloads"])
PY
)"

echo "    version=$VERSION  official_mappings=$HAS_MAPPINGS"

JAR="$WORK/server-$VERSION.jar"
[ -f "$JAR" ] || { echo "==> downloading server jar"; curl -sS --max-time 600 -o "$JAR" "$SERVER_URL"; }

# Modern server jars are bundlers: real classes live in META-INF/versions/<v>/
INNER_DIR="$WORK/inner-$VERSION"
INNER=$(unzip -l "$JAR" | awk '/META-INF\/versions\/.*\.jar$/{print $4; exit}')
if [ -n "$INNER" ]; then
  echo "==> unpacking bundled inner jar: $INNER"
  rm -rf "$INNER_DIR"; mkdir -p "$INNER_DIR"
  unzip -o -q "$JAR" "$INNER" -d "$INNER_DIR"
  CLASSJAR="$INNER_DIR/$INNER"
else
  CLASSJAR="$JAR"
fi

# Is it obfuscated? Readable package names are the tell.
READABLE=$(unzip -l "$CLASSJAR" | awk '{print $4}' | grep -c '^net/minecraft/world/level/block/' || true)
echo "==> obfuscation probe: $READABLE readable classes under net/minecraft/world/level/block/"
if [ "$READABLE" -eq 0 ]; then
  echo "    !! jar appears OBFUSCATED - this spike needs a remap step for $VERSION"
  exit 1
fi
echo "    jar is UNOBFUSCATED - callable directly, no mappings needed"

# Redstone/repeater surface: the pilot's target.
CLASSES=(
  net.minecraft.world.level.block.RepeaterBlock
  net.minecraft.world.level.block.DiodeBlock
  net.minecraft.world.level.block.ComparatorBlock
  net.minecraft.world.level.block.RedStoneWireBlock
  net.minecraft.world.level.block.RedstoneTorchBlock
  net.minecraft.world.level.redstone.CollectingNeighborUpdater
)

EXTRACT="$WORK/classes-$VERSION"
rm -rf "$EXTRACT"; mkdir -p "$EXTRACT"
for c in "${CLASSES[@]}"; do
  unzip -o -q "$CLASSJAR" "${c//.//}.class" -d "$EXTRACT" 2>/dev/null || echo "    (missing $c)"
done

echo "==> classifying"
python3 classify.py "$EXTRACT" "${CLASSES[@]}"
