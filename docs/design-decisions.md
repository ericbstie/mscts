# Design decisions

mscts records each significant decision as an Architecture Decision Record
in [`docs/adr/`](https://github.com/ericbstie/mscts/tree/main/docs/adr).
This page summarizes them. The ADR is the source when the two disagree.

| ADR | Decision |
| --- | --- |
| [0001](https://github.com/ericbstie/mscts/blob/main/docs/adr/0001-black-box-differential-testing.md) | mscts observes servers only as a protocol client, and vanilla is the oracle. Groups never hard-code expected values. |
| [0002](https://github.com/ericbstie/mscts/blob/main/docs/adr/0002-python-astral-toolchain.md) | Python 3.13 with uv, ruff (every rule), ty and bandit. mise pins the tools and defines the tasks. |
| [0003](https://github.com/ericbstie/mscts/blob/main/docs/adr/0003-single-pinned-target.md) | One Target at a time: Minecraft 26.3, protocol 777. Packet ids come from vanilla's data generator. |
| [0004](https://github.com/ericbstie/mscts/blob/main/docs/adr/0004-adapters-are-translators.md) | An Adapter only translates a ServerSpec into config. One runner launches every server, and readiness is a status ping, never a log line. |
| [0005](https://github.com/ericbstie/mscts/blob/main/docs/adr/0005-in-repo-plan-and-green-commits.md) | Every commit passes `mise run check`. The plan lives in the repository; the queue moved to issues (0009). |
| [0006](https://github.com/ericbstie/mscts/blob/main/docs/adr/0006-compliance-is-a-catalogue-of-differences.md) | The Report lists every differing test case (0012 replaces the mechanic sections), with no accepted deviations. Masks cover only ids with no gameplay meaning. Random mechanics are tested statistically. |
| [0007](https://github.com/ericbstie/mscts/blob/main/docs/adr/0007-network-traffic-divergences.md) | Network traffic differences, where the vanilla client ends up with the same result, are left out of scores. ADR-0012 replaces the separate section. |
| [0008](https://github.com/ericbstie/mscts/blob/main/docs/adr/0008-explicit-installs-pinned-registry-adapter-dx.md) | Installs are explicit and idempotent, the Registry pins every build by checksum, and Adapters get an authoring guide and a conformance check. |
| [0009](https://github.com/ericbstie/mscts/blob/main/docs/adr/0009-docs-are-the-spec-issues-and-prs.md) | This site is the spec for what users see and always matches the code. Changes are GitHub issues, each landing as one PR. |
| [0012](https://github.com/ericbstie/mscts/blob/main/docs/adr/0012-short-default-report.md) | The default Report lists differing test cases, skipped or failed Groups, and total Run time. Gameplay and network traffic share the list. |

## Why a black box

Candidates are written in different languages, with different config
formats and admin APIs. The one interface they all share is the Java
Edition protocol at one version. Testing only through that protocol keeps
mscts from depending on any server's internals, and it tests exactly what a
player's client sees.

## Why no accepted deviations

A list of accepted deviations would let a Candidate decide which of its
differences count. mscts reports every difference and leaves the judgement
to the reader. A Candidate that fixes a vanilla bug shows up as a
Divergence, like any other change in behaviour.

## Why network traffic differences are listed

Some differences change the bytes but not what the client decodes, such as
a text component sent as `"x"` or as `{"text": "x"}`. mscts calls these
network traffic differences. Counting those as
failures would penalize choices the protocol allows. Hiding them would
remove information a server developer may want. mscts lists them alongside
gameplay differences and keeps them out of scores.
