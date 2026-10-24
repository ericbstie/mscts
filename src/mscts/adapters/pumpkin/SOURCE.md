# Source of `pumpkin.toml`

`pumpkin.toml` is the file the Pumpkin nightly wrote on its first run in an
empty directory, copied verbatim. Do not edit it by hand. `PumpkinAdapter`
pins every key in it: a changed default can never change a Candidate
Instance silently.

| | |
| --- | --- |
| Binary | `pumpkin-X64-Linux` of the `nightly` release, sha256 `2f2369d8e7dc7843163d55dab4b3cff50e97b67cb73f8bf2dceefe6cdde2ca9c`, 117,583,512 bytes |
| Version | `0.2.0+26.3-26.51`, commit `9c04f714bb7eb26579c652f9744895d465ee902b`: Java 26.3, protocol 777 |
| Generated | 2026-10-24, by running the binary once with an empty environment (`PATH` only) in an empty directory inside a new network namespace (`unshare -rn`), so its pristine defaults (`0.0.0.0:25565`, telemetry, Bedrock) could reach nothing. It stopped on its own at the Bedrock UDP socket, which the namespace has no address family for; `pumpkin.toml` was written before that |
| sha256 | `419ecc145fe888b3bf3d35d99de6bb8037609284903d91c64f2aceec3d9f0acc` |

`seed` is random on every first run; every ServerSpec overrides it.

The previous copy came from commit `f1c0871` (2026-10-07). This one differs
from it only in `seed` and in `[world]`:

- `[world.chunk]` has `type = "pump"` (Pumpkin's own format), where the
  previous copy had `"anvil"`. `"pump"` has no options, so
  `[world.chunk.compression]` is gone from the file.
- `write_in_place` is gone from `[world.chunk]`. Pumpkin rewrites a file
  that still has it.
- `[world.entity_islands]` is new: `unaudited_reach = 16.0` and
  `knockback_reach = 4.0`, the safety margins for ticking entities in
  parallel.

The Adapter stores chunks in Anvil, as vanilla does: `_anvil_defaults`
sets `type = "anvil"` and adds the `[world.chunk.compression]` table
Pumpkin writes for it (`LZ4`, level 6). The file here stays what Pumpkin
wrote.

After any nightly bump, run the binary once the same way and diff its
output against this file. A new, renamed or removed key must reach this
file, the adapter's tables and the golden test together. Then run
`tests/adapters/pumpkin/test_pumpkin_running.py` against the Candidate tier:
it fails if Pumpkin rewrites the file the Adapter wrote.
