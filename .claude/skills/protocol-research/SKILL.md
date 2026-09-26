---
name: protocol-research
description: How to establish a Minecraft Java protocol or server-behaviour fact for mscts (packet IDs, field layouts, connection sequence, server config defaults) and pin it. Use before writing any codec schema, Scenario, Mask or Adapter config, and whenever vanilla or a Candidate behaves unexpectedly.
---

# protocol-research

The Reference defines correct behaviour. Documentation only describes it,
and it can be stale or wrong. Every fact the code relies on must be pinned
by a test.

## Sources, in order of trust

1. **The vanilla jar for the Target.** Get the URL and sha1 from
   `https://piston-meta.mojang.com/mc/game/version_manifest_v2.json` →
   the version JSON → `downloads.server`. `version.json` inside the jar
   gives the protocol and Java version.
2. **The vanilla data generator**, which produces the packet names and IDs
   plus the registries, blocks and commands:
   ```sh
   # run from a scratch dir OUTSIDE the repo: the bundler unpacks libraries/ and versions/
   # into the cwd, and plain `java`/`mise exec` outside the repo resolve Java 21
   "$(mise where java)/bin/java" -DbundlerMainClass=net.minecraft.data.Main \
       -jar server.jar --reports --output <dir>
   # <dir>/reports/packets.json, registries.json, blocks.json, commands.json
   ```
   The output is deterministic (byte-identical across runs), so a regen
   can be verified by diffing it against the committed copy.
3. **minecraft.wiki as raw wikitext**, for field layouts and semantics:
   `curl -sS 'https://minecraft.wiki/w/Java_Edition_protocol/Packets?action=raw'`.
   Check that the page header names the Target protocol, and record the
   revision id:
   `https://minecraft.wiki/api.php?action=query&prop=revisions&titles=Java_Edition_protocol/Packets&rvprop=ids|timestamp&format=json`.
   Then fetch **that exact revision**, because a plain `action=raw` can race
   with an edit:
   `https://minecraft.wiki/index.php?title=Java_Edition_protocol/Packets&action=raw&oldid=<revid>`.
   Also useful: `Java_Edition_protocol/Data_types`,
   `Java_Edition_protocol/VarInt_and_VarLong`, `Java_Edition_protocol/FAQ`.
4. Candidate source code, only to understand a Candidate. Never use it to
   decide what is correct.

Do **not** rely on a summarizer (WebFetch or similar) for field layouts.
One summary got a 26.3 field order wrong. Grep the raw wikitext table
instead.

## Pinning a fact

- A layout or ID becomes a codec schema plus a `unit` test built from the
  wiki's sample bytes, and a `reference`-tier test that round-trips it
  against a live vanilla Instance.
- A server default or quirk becomes a line in the current
  `docs/research/*.md` note (marked **verified** if you observed it
  yourself), plus a test on the Adapter that overrides it.

## Known traps (26.3)

- The vanilla defaults `white-list=true` and `pause-when-empty-seconds=60`
  must be overridden.
- `accept_teleportation` echoes the pose: `VarInt id, 3×Double, 2×Float`.
- After `login_compression`, every frame is `VarInt data-length ‖ data`,
  where data-length 0 means uncompressed.
- A throwaway raw-socket probe's retry loop must catch
  `(OSError, EOFError)`. An early close raises `EOFError`, which is not an
  `OSError`, and looks exactly like "the server never answers".
- Vanilla accepts TCP before its world exists. Console lines read before
  then are lost to an NPE. Readiness is always a status ping (never a
  TCP connect), and console commands are sent only after it answers.
- Never op a player through the vanilla console. With Mojang services
  unreachable, `op Steve` ops the lower-cased `steve` (a different offline
  UUID). Write `ops.json` directly, with
  `UUID.nameUUIDFromBytes("OfflinePlayer:" + name)`.
- Offline vanilla still calls Mojang services (authlib discovery,
  public keys, name lookups), and log4j resolves the host name through
  the OS resolver. `VanillaAdapter.NO_NETWORK` blocks both with JVM
  properties (`minecraft.api.discovery.host`, `jdk.net.hosts.file`).
  Never set `minecraft.api.env`, because it overrides the discovery URL.
  When checking a launch configuration for network use, run it under
  `strace -f -e trace=connect,sendto,sendmsg,sendmmsg,openat`.
- Pumpkin sends an encryption request in offline mode unless
  `encryption = false`. Its Bedrock listener and telemetry are on by
  default.

Record anything new under `docs/research/` and in this list if it will
bite again.
