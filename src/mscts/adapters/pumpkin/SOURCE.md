# Source of `pumpkin.toml`

`pumpkin.toml` is the file the Pumpkin nightly wrote on its first run in an
empty directory, copied verbatim. Do not edit it by hand. `PumpkinAdapter`
pins every key in it: a changed default can never change a Candidate
Instance silently.

| | |
| --- | --- |
| Binary | `pumpkin-X64-Linux` of the `nightly` release, sha256 `da7ce80d05a254fe8ee66848bfefdc3ed64beaa24029da13ae847e5fad8c27b8`, 120,469,824 bytes |
| Version | `0.2.1+26.3-26.51`, commit `5e9101f350245f6faa656a6b0676a99b4a40f2e1`: Java 26.3, protocol 777 |
| Generated | 2026-10-26, by running the binary once with an empty environment (`PATH` only) in an empty directory inside a new network namespace (`unshare -rn`), so its pristine defaults (`0.0.0.0:25565`, telemetry, Bedrock) could reach nothing. It stopped on its own at the Bedrock UDP socket, which the namespace has no address family for; `pumpkin.toml` was written before that |
| sha256 | `44bd52d80a0c359ec9fc576e57953638eeae5c0a10f43cab6f92bd111eac7cbd` |

`seed` is random on every first run; every ServerSpec overrides it.

The previous copy came from commit `9c04f71` (2026-10-24). This one differs
from it only in `seed`: the nightly of 2026-10-26 added no key, and renamed
and removed none.

The copy before that came from commit `f1c0871` (2026-10-07). Against it,
both later copies differ in `seed` and in `[world]`:

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

After any nightly bump, run
`uv run scripts/research/pumpkin_pristine.py <binary>`: it runs the binary once
the way the Generated row describes and prints a diff of what it wrote against
this file, ignoring `seed` (exit 0: no difference, 1: a diff). A new, renamed or removed key must reach this
file, the adapter's tables and the golden test together. Then run
`tests/adapters/pumpkin/test_pumpkin_running.py` against the Candidate tier:
it fails if Pumpkin rewrites the file the Adapter wrote.
