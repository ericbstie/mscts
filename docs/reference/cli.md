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
| `@<version>` | The build to install. For vanilla, a Minecraft version (only `26.3` works). For Pumpkin, the commit of its nightly build, at least 7 characters long, or `nightly` for the latest. |
| `--from PATH` | Install a file you supply instead of downloading. mscts checks that it is a build for 26.3, hashes it and records its path. |

A version and `--from` cannot be combined. A build for another Minecraft
version is refused, and so is a Pumpkin commit other than the latest
nightly, because Pumpkin publishes only the latest one. To test an older
commit, build it yourself and install the file with `--from`.

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

Lists every Adapter and the build installed for it, if any.
A broken Installation shows as `unusable` and points to `mscts adapter status`.

## `mscts adapter status`

```
mscts adapter status <adapter>
```

Shows where the Adapter's Installation lives, its version, its commit (when
the build names one), its sha256 and size, where it came from, and when it
was installed. If nothing is installed, it prints the
install command and exits with code 1.

## `mscts run`

```
mscts run --candidate <adapter> [--group GLOB] [--repeat N] [-v | --verbose] [--out DIR]
```

Starts vanilla and the Candidate, plays the chosen Groups against both,
stops both and prints the Report to stdout. Progress goes to stderr.

The Report starts with `Running tests against <adapter name> <build>`,
the exact build of the Candidate it tested. Then it lists each test case
of each Group on a line of its own, marked ✓ if it passed or ✗ if not. A
test case that differs only in network traffic passes, marked
`(network traffic only)`. One that only network traffic shows, such as a
value the vanilla client never reads, is listed only when the two servers
differ in it, marked `(network traffic only, not scored)`, and is not
scored. A Group with no test cases to list has one line
with its reasons. The Report ends with the totals and the score on one
line, then the total Run time in seconds. [Reading a Report](/guide/reading-a-report) explains
each line.

On a terminal, ✓ is green, ✗ red and `!` yellow. Set `NO_COLOR` to any
value to turn the colours off. Output sent to a file or another program has
no colours, and neither do `report.md` and `report.json`.

| Option | Default | Description |
| --- | --- | --- |
| `--candidate <adapter>` | required | The Candidate's Adapter. |
| `--group GLOB` | `status/*` | Group ids to play, matched as a shell glob. mscts adds their prerequisites. The default includes `status/with-player`, which joins a player and waits 6 seconds, so it takes about 14 seconds for each repetition. |
| `--repeat N` | `5` | How many times to play each Group. Must be at least 1. |
| `-v`, `--verbose` | off | Also show the Reference's installed version, Target, repetitions, both values under each test case that differs, and time per Group. |
| `--out DIR` | none | Also write the Report to `DIR/report.json` and `DIR/report.md`. |

Verbose values appear directly under their test case. Distinct values from
different repetitions are kept; identical differences are shown once.
A Group's time is the sum, over all repetitions, of playing the sides each
repetition played and comparing them. A repetition that played vanilla
only counts that play. It excludes Instance startup and shutdown, which remain
in the final total. Skipped Groups say `not played`. An installed version
names the installed build: its version, its commit where the build names
one, and the start of its sha256. mscts does not trust the version claimed
in a status response.

`--out DIR` creates `DIR` if needed and writes two files into it:
`report.json`, the whole Report with both values of each difference, up to 20
differences for each test case in each Verdict (`omitted` counts the rest), and
`report.md`, the printed Report as Markdown. The names are fixed, so a `report.json` and
`report.md` already in `DIR` are replaced. To keep two Runs side by side,
give each its own folder. The Report is still printed, followed by one
line:

```
Report written to reports/report.json and reports/report.md
```

If `DIR` cannot be created, `mscts run` exits with code 1 before it
starts any server. If a file cannot be written, it prints the Report,
then exits with code 1 and names the file. Both files are written in full
before either replaces an earlier one. See [Reading a Report](/guide/reading-a-report#report-files)
for what the files hold.

`--candidate vanilla` plays vanilla against a second vanilla server. That is
a quick way to see a Self-check.

If a server is not installed, `mscts run` asks on a terminal whether to
install it. Without a terminal it fails and prints the install command.

If a server fails to start, `mscts run` exits with code 1 and keeps that
server's working directory. The message gives the path to its console
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

Every task that runs pytest gives the run its own temp directory and removes it afterwards, so runs
at the same time, such as several agents on one machine, cannot delete each other's files. The live
tiers and `test:statistical` keep that directory when the run fails and print where it is.
Pass `--basetemp <dir>` after `--` to put the files in a folder of your own instead.
