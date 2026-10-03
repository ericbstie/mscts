# Source of `pumpkin.toml`

`pumpkin.toml` is the file the Pumpkin nightly wrote on its first run in an
empty directory, copied verbatim. Do not edit it by hand. `PumpkinAdapter`
pins every key in it: a changed default can never change a Candidate
Instance silently.

| | |
| --- | --- |
| Binary | `pumpkin-X64-Linux` of the `nightly` release, sha256 `88b1f5f3deb4e6387b7bd192803d83881e445397fe374c0ba58126558ac792c6`, 126,665,832 bytes |
| Version | `0.2.0+26.3-26.51 (Commit: a4d6465)`: Java 26.3, protocol 777 |
| Generated | 2026-09-26, by running the binary once with an empty environment (`PATH` only) in an empty directory inside a new network namespace (`unshare -n`), so its pristine defaults (`0.0.0.0:25565`, telemetry, Bedrock) could reach nothing |
| sha256 | `a7b4a5f467d8008872bc4001782e5bdfea92914b42df9929e86ff94e99a8e28a` |

`seed` is random on every first run; every ServerSpec overrides it.

Between `a4d6465` and the `nightly` tag at `003d3c49` (two commits later),
nothing changed in `pumpkin-config` or in the code that loads it, so this is
also that nightly's default set. After any nightly bump, run the binary once
the same way and diff its output against this file. A new, renamed or
removed key must reach this file, the adapter's tables and the golden test
together.
