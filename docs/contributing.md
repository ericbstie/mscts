# Development guide

mscts uses Python 3.13, managed with [mise](https://mise.jdx.dev) and
[uv](https://docs.astral.sh/uv/).

## Set up

```sh
mise install && mise run sync
mise run check
```

`check` runs ruff (every rule enabled), the ruff format check, ty with every
diagnostic as an error, bandit over `src/`, the public-name check against
`docs/PLAN.md`, and the unit tests in parallel.
It takes a few seconds.

## Test tiers

The development tests are split into tiers by the infrastructure they need.

| Tier | Needs | Command |
| --- | --- | --- |
| `unit` | Nothing outside the machine. Localhost sockets and short helper processes are allowed. | `mise run check` |
| `reference` | A live vanilla 26.3 server and Java 25. | `mise run test:reference` |
| `selfcheck` | Two live vanilla 26.3 servers and Java 25. | `mise run test:selfcheck` |
| `candidate` | A live Candidate server. | `mise run test:candidate` |
| `statistical` | Many repeated runs. Opt-in and slow. | `mise run test:statistical` |

Install vanilla before the `reference` and `selfcheck` tiers with
`mise run install:reference`.
Tests never install anything themselves.

When a test in one of the server tiers fails, look at the end of its failure
output: for every server it used, an `Instance console` section shows the
last lines of that server's console.

Run one test with:

```sh
uv run pytest tests/path/test_file.py::test_name
```

### The `selfcheck` tier

`mise run test:selfcheck` plays every registered Group against two vanilla
servers and expects `match` every time. That is a Self-check. The tier has
one test for each Group, named by the Group's id, so a Group is covered as
soon as it is registered, with no test file to write for it. A Group
that changes the server's settings with `spec` gets two servers of its own,
which adds two boots.

Each Group is played 3 times. `MSCTS_SELFCHECK_REPEAT` changes that, and `-k`
picks Groups by id:

```sh
MSCTS_SELFCHECK_REPEAT=20 uv run pytest -m selfcheck -k 'status/'
```

A pull request that adds Groups shows 20 runs out of 20 for them this way.
That is a command you run once, not part of `mise run check`. The pull
request also shows what the Candidate does, with
`uv run mscts run --candidate pumpkin --group '<mechanic>/*'`. No test pins
what a Candidate does.

When a play does not match, in this tier or in the `reference` tier's
20-out-of-20 Self-checks, the failure message also names a file under the
test's temporary directory. The file lists the packets each Bot
sent and received on both servers, in time order, in milliseconds since the
play started. For each packet received, it says whether an Observation
window compared it. For each `award_stats`, it says how long after the
Bot's previous one it arrived. This shows where a play that fails only
sometimes went differently.

## How changes are made

- **One failing test first.** Write one test that fails, write the least
  code that passes it, run `mise run check`, and commit. Then repeat.
- **Research before encoding a protocol fact.** Packet layouts, defaults
  and client behaviour are verified against the vanilla jar and recorded in
  [`docs/research/`](https://github.com/ericbstie/mscts/tree/main/docs/research)
  before code depends on them.
- **Use the vocabulary.** Terms in
  [`CONTEXT.md`](https://github.com/ericbstie/mscts/blob/main/CONTEXT.md)
  have one meaning each. Add a term there in the same commit that
  introduces it.
- **Name public definitions in PLAN.** `mise run plan` checks classes,
  functions, constants and type aliases defined directly at module level
  under `src/mscts/`. Names starting with `_`, imports, class members and
  definitions inside functions are excluded. Add each public name to its
  module's interface section in `docs/PLAN.md` in the same PR.
- **One issue, one PR.** Changes start as a spec issue that quotes the
  target wording of this site. The PR changes the code and the page
  together, so the site always matches the code.
- **Flag conflicts with an ADR.** A change that reverses a decision needs a
  new ADR. See [Design decisions](/design-decisions).

## Releasing

A release is a GitHub Release, made from a tag. mscts is not published to
PyPI.

1. Set `version` in `pyproject.toml`, run `uv lock`, and merge that into
   `main`.
2. Tag the merge and push the tag:

   ```sh
   git tag v0.1.0
   git push origin v0.1.0
   ```

The `release` workflow checks that the tag matches `version`, runs
`mise run check`, and creates the Release with the wheel and source
archive attached. If the tag doesn't match, it fails and creates nothing.

To withdraw a release, delete both the Release and its tag on GitHub.
`mise use -g uv pypi:ericbstie/mscts` then installs the newest remaining
release.

## Inspecting the Target's libraries

The research tool can disassemble a class from a library the Target uses:

```sh
mise exec -- uv run python scripts/research/javap.py --lib datafixerupper server com.mojang.serialization.codecs.OptionalFieldCodec
```

Repeat `--lib` to add another library, such as `--lib gson`. Each value is
a substring that must match exactly one artifact name in Mojang's version
metadata. If it matches more than one, the tool lists the matches. Selected jars are cached under
`research/26.3/libraries/` in the mscts cache, and their published sha1 and
size are checked on every use. With no `--lib`, only the Target jar is on
the classpath.

## Proposing a test

Each mechanic, such as lighting, mob spawning or redstone timing, is
checked by a Group that plays it against vanilla and the Candidate. Propose
a new one as a GitHub issue from the **Test proposal** template, so that
anyone can pick it up and build it.

A proposal:

- **Says what a player would notice** when a server gets the mechanic
  wrong, in plain words.
- **Cites its evidence.** Say what vanilla does and where servers are known
  to differ: another server's config option or documentation, a Mojang bug
  id, or something you observed and recorded in `docs/research/`.
- **Leaves the expected values to vanilla.** Say what to do and what to
  compare, never what the result should be.
- **Sets up the world with commands only**, such as `/setblock`, `/fill`,
  `/summon`, `/gamerule` and `/tick`, so that it works on any server that
  has those commands.
- **Removes every source of variation it can.** Freeze the world with
  `/tick freeze` and step it one tick at a time. Turn off what the mechanic
  does not need (`advance_time`, `advance_weather`, `random_tick_speed 0`,
  `spawn_mobs false`). Pin the join position with `respawn_radius 0` and
  `/setworldspawn`. Give entities explicit positions and motion. Whatever
  is still random needs a statistical Group, which runs many times on
  each server. It is never hidden with a Mask.
- **Compares what the vanilla client receives**, and names the packets. A
  Mask may only hide an identifier that means nothing in the game, such as
  an entity id.
- **Names the issues it needs.** When a test needs something mscts cannot
  do yet, such as sending commands, stepping ticks, or decoding chunks and
  entities, that is a separate issue. Every test that needs it links to
  it.

A test issue is labelled `test`, and `needs-triage` until the tech lead
has sized it and checked its spec. If it needs other issues first, the
lead names them in a **Blocked by** line at the top of its description,
and it is ready once they are closed. Game rules and commands use their
vanilla 26.3 names: `advance_time`, not `doDaylightCycle`.

## Repository layout

| Path | Contents |
| --- | --- |
| `src/mscts/codec/` | Field types, framing, packet schemas and the generated `packets.json` and `registry_names.json` |
| `src/mscts/net.py`, `bot.py` | Connections and Bots |
| `src/mscts/adapters/` | One module per server, plus the Adapter contract |
| `src/mscts/runner.py` | Launching, readiness and stopping of Instances |
| `src/mscts/group.py`, `groups/` | The Group API and the shipped Groups |
| `src/mscts/compare.py` | Masks, the canonical table, and the diff into Verdicts |
| `src/mscts/run.py`, `measure.py`, `report.py`, `cli.py` | Runs, Measurements, Reports and the `mscts` command |
| `docs/` | This site, plus the working notes: `PLAN.md`, `PROGRESS.md`, `PROCESS.md`, `adr/`, `research/`, `audits/` |

## Working on this site

The site is [VitePress](https://vitepress.dev). Its pages are the Markdown
files in `docs/` outside the working notes, and its config is in
`docs/.vitepress/`.

```sh
mise run docs:dev     # http://localhost:5173 with live reload
mise run docs:build   # static site in docs/.vitepress/dist
```

Both tasks install Node and the site's dependencies on first use. Keep
examples real: when a page shows command output, copy it from an actual
run.
