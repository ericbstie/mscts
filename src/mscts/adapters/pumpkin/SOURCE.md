# Source of `pumpkin.toml`

`pumpkin.toml` is the file the Pumpkin nightly wrote on its first run in an
empty directory, copied verbatim. Do not edit it by hand. `PumpkinAdapter`
pins every key in it: a changed default can never change a Candidate
Instance silently.

| | |
| --- | --- |
| Binary | `pumpkin-X64-Linux` of the `nightly` release, sha256 `bff2aaede4f8695b688aa7e088f31f9e762ee567c1d6f9f15da64ad63ba66d64`, 138,343,040 bytes |
| Version | `0.2.0+26.3-26.51`, commit `f1c0871f492182a228fa585e9d7c74e683e242f9`: Java 26.3, protocol 777 |
| Generated | 2026-10-07, by running the binary once with an empty environment (`PATH` only) in an empty directory inside a new network namespace (`unshare -n`), so its pristine defaults (`0.0.0.0:25565`, telemetry, Bedrock) could reach nothing |
| sha256 | `30985de8aac68742f5963256c677f5bb68788d86097f13cd057e00e06cea00ba` |

`seed` is random on every first run; every ServerSpec overrides it.

The previous copy came from commit `a4d6465` (2026-09-26). This one differs
from it only in `seed` and in `[networking.management]` (Pumpkin's
WebSocket management server, off by default), which replaced
`[networking.rcon]` and `[networking.rcon.logging]`.

After any nightly bump, run the binary once the same way and diff its
output against this file. A new, renamed or removed key must reach this
file, the adapter's tables and the golden test together.
