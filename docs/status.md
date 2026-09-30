# Project status

mscts is early. This page lists what works today and what comes next. The
working log is
[`docs/PROGRESS.md`](https://github.com/ericbstie/mscts/blob/main/docs/PROGRESS.md),
and the milestones are in
[`docs/PLAN.md`](https://github.com/ericbstie/mscts/blob/main/docs/PLAN.md).

## Works today

| Area | State |
| --- | --- |
| Target | Minecraft 26.3, protocol 777. One Target at a time. |
| Candidates | Pumpkin. Its Adapter writes Pumpkin's config and a flat world save with the spec's seed and difficulty. |
| Installs | `mscts adapter install`, `list` and `status`, a Registry pinned by checksum, and `--from` for builds you supply. |
| Protocol | Handshake, status, login, configuration, and enough of play to join a world. A Bot joins vanilla in about 1.25 seconds. |
| Groups | `status/basic` and `status/ping`. The status Self-check matches in 20 runs out of 20, with no Mask. |
| Comparison | Observable and wire-only Divergences. Each rule in the canonical table cites the vanilla client code behind it. |
| Report | Plain text on stdout, with Divergences by mechanic, median and p95 timings, and startup time. |

The first comparison of Pumpkin found no observable difference in the
server list ping, and four wire-only ones.

## Next

1. The `join/basic` Group in the Report.
2. JSON and Markdown Report output with `--out DIR`, and an option to exit
   non-zero on observable differences.
3. Alternating the order in which the two servers run, for fairer timings.
4. `mscts selfcheck` as a command.
5. An operator Bot for Fixtures, then world and block Groups.
6. `tick-exact` Groups for redstone and known vanilla glitches.
7. `statistical` Groups for spawning and loot, in an opt-in tier.
8. `mscts adapter check`, to prove a third-party Adapter against a live
   server.

## Not planned

- Bedrock Edition.
- Online-mode authentication and encryption.
- Several Minecraft versions at once.
- Anything only the server can see, such as its on-disk format.
