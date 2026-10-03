# CLI reference

Run every command from a checkout with `uv run mscts ...`. Every command
prints what it did. Every error goes to stderr, starts with `mscts:` and
names the fix. Exit code 1 means a failure with such a message. Exit code 2
means the command line itself was invalid.

Every command accepts `-h` / `--help` to show its arguments and options.

## `mscts`

Choose `adapter` to install or inspect servers, or `run` to compare them.

## `mscts adapter`

Choose `install`, `list` or `status` to manage server Installations.

## `mscts adapter install`

```
mscts adapter install <adapter>[@<version>] [--from PATH]
```

Installs a server build into the cache. With no version, it installs the
latest build for the Minecraft version mscts tests (26.3). Running it again
when a build is already installed does nothing and says so. To get a newer
build, delete the installed one first; the message names its folder.

| Argument | Description |
| --- | --- |
| `<adapter>` | `vanilla` or `pumpkin`. |
| `@<version>` | The build to install. For vanilla, a Minecraft version (only `26.3` works). For Pumpkin, the commit of its nightly build, at least 7 characters. |
| `--from PATH` | Install a file you supply instead of downloading. mscts checks that it is a build for 26.3, hashes it and records its path. |

A version and `--from` cannot be combined. A build for another Minecraft
version is refused, and so is a Pumpkin commit that is not its latest
nightly: Pumpkin publishes only that one. Build an older commit yourself
and install the file with `--from`.

```sh
uv run mscts adapter install vanilla
uv run mscts adapter install vanilla@26.3
uv run mscts adapter install pumpkin
uv run mscts adapter install pumpkin@4426d11
uv run mscts adapter install pumpkin --from ./pumpkin-X64-Linux
```

## `mscts adapter list`

```
mscts adapter list
```

Lists every Adapter, the build installed for it and whether it is installed.
A broken Installation shows as `unusable` and points to `mscts adapter status`.

## `mscts adapter status`

```
mscts adapter status <adapter>
```

Shows where the Adapter's Installation lives, its version, its commit (when
the build names one), its sha256 and size, where it came from, and when it
was installed. Exits with code 1 if nothing is installed, and prints the
install command.

## `mscts run`

```
mscts run --candidate <adapter> [--group GLOB] [--repeat N] [-v | --verbose]
```

Starts vanilla and the Candidate, plays the chosen Groups against both,
stops both and prints the Report to stdout. Progress goes to stderr.

The Report starts with `Running tests against <adapter name>`, lists each
differing test case once, then gives the total Run time in seconds. Known
test cases have a [title](/reference/test-cases); others keep just their
name. Gameplay and network traffic differences share the list. Skipped or
failed Groups follow it with their reasons. If nothing differed and no
Group was skipped or failed, the Report says `No differences.`.

| Option | Default | Description |
| --- | --- | --- |
| `--candidate <adapter>` | required | The Candidate's Adapter. |
| `--group GLOB` | `status/*` | Group ids to play, matched as a shell glob. mscts adds their prerequisites. |
| `--repeat N` | `5` | How many times to play each Group. Must be at least 1. |
| `-v`, `--verbose` | off | Add installed versions, Target, repetitions, both values for each difference, and time per Group. |

Verbose values appear directly under their test case. Distinct values from
different repetitions are kept; identical differences are shown once.
Group time is the sum of playing both sides and comparing them across
all repetitions. It excludes Instance startup and shutdown, which remain
in the final total. Skipped Groups say `not played`. The installed version
is the installed build: its version, its commit where the build names one,
and the start of its sha256. It does not trust the version claimed in a
status response.

`--candidate vanilla` plays vanilla against a second vanilla server. That is
a quick way to see a Self-check.

If a server is not installed, `mscts run` asks on a terminal whether to
install it. Without a terminal it fails and prints the install command.

If a server fails to start, `mscts run` exits with code 1 and keeps that
server's working directory, and the message gives the path to its console
log.

## mise tasks

The repository defines these tasks in `mise.toml`:

| Task | What it runs |
| --- | --- |
| `mise run sync` | `uv sync --locked` |
| `mise run install:reference` | `mscts adapter install vanilla` |
| `mise run check` | Lint, format check, type check, bandit and the unit tests. Every commit must pass it. |
| `mise run fix` | `ruff format` and autofixable lint. |
| `mise run test:reference` | Tests against a live vanilla server. |
| `mise run test:selfcheck` | Every registered Group against two live vanilla servers. |
| `mise run test:candidate` | Tests against a live Candidate server. |
| `mise run test:statistical` | Opt-in statistical tests. |
| `mise run docs:dev` | This site, served locally with live reload. |
| `mise run docs:build` | This site, built into `docs/.vitepress/dist`. |
