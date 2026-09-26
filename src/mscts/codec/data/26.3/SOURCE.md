# Source of the 26.3 packet data

`packets.json` is the vanilla data generator's packet report
(`reports/packets.json`), copied verbatim. Do not edit it by hand.

| | |
| --- | --- |
| Target | 26.3 / protocol 777 (`version.json` in the jar: `protocol_version` 777, `java_version` 25) |
| Server jar | `downloads.server` of 26.3 in the piston-meta version manifest, sha1 `33680f5f2ac32864d6d7cf5e56a705fdb3e05f4c` |
| Generated | 2026-09-25, with Temurin 25 |
| packets.json sha1 | `57d738152562d40d7ba3fc4f106431ec4858de40` |

Generator command (from the `protocol-research` skill):

```sh
java -DbundlerMainClass=net.minecraft.data.Main -jar server.jar --reports --output <dir>
# → <dir>/reports/packets.json
```

The report was generated twice from the same jar, independently, and the two
outputs were byte-identical.

Regenerate and verify this file with `mise run regen:packets` (or
`python -m mscts.codec.regen`); add `--write` to update it after a real
protocol change. It uses the installed jar (`install.require`; install it with
`mscts adapter install vanilla`),
runs the generator with the same Java resolution `VanillaAdapter.prepare`
uses (`resolve_java`), and compares the result byte-for-byte with this
file (`src/mscts/codec/regen.py`).
