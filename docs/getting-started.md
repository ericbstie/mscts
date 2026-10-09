# Getting started

To install the `mscts` command from the latest
[GitHub Release](https://github.com/ericbstie/mscts/releases), run:

```sh
mise use -g uv pypi:ericbstie/mscts
```

Add `@<version>` for one release, such as `pypi:ericbstie/mscts@0.1.0`.
uv installs Python 3.13 for it if you don't have it. With the installed
command, type `mscts` where this page types `uv run mscts`, and install
vanilla with `mscts adapter install vanilla`. Vanilla still requires
Java 25, which `mise use -g java@temurin-25` installs.

## Requirements

- Linux on x86-64. The live tiers have only been tested on Linux, and the
  pinned Pumpkin build is Linux-only. The unit tier has been run on macOS
  (Apple silicon), but does not yet pass because of
  [process checks](https://github.com/ericbstie/mscts/issues/143) and
  [loopback addresses](https://github.com/ericbstie/mscts/issues/144).
- [mise](https://mise.jdx.dev). It installs the pinned Python, uv and Java 25
  for you.
- About 200 MB of disk space for the two servers.

## 1. Set up the checkout

```sh
git clone https://github.com/ericbstie/mscts
cd mscts
mise install        # Python 3.13, uv, Java 25 (Temurin)
mise run sync       # locked Python dependencies into .venv
```

The vanilla server requires Java 25. mscts looks for it in `MSCTS_JAVA` first,
then as `java` on your `PATH`. If `java` on your `PATH` is a different
version or a mise shim, point `MSCTS_JAVA` at the real launcher:

```sh
export MSCTS_JAVA="$(mise where java)/bin/java"
```

## 2. Install vanilla

```sh
mise run install:reference
```

This downloads the vanilla 26.3 server jar from Mojang, checks it against
the sha1 and size Mojang publishes, and stores it in the cache
(`~/.cache/mscts` by default). Running it again does nothing and says so.

## 3. Install a Candidate

```sh
uv run mscts adapter install pumpkin
```

This downloads the latest nightly build of
[Pumpkin](https://github.com/Pumpkin-MC/Pumpkin). mscts checks that it is a
build for Minecraft 26.3 and records the commit it was made from, so every
Report names the exact build it tested. Pumpkin publishes only its latest
nightly. To test another commit, build it yourself and install the file with
`--from`. See [Installing servers](/guide/installing-servers).

Check what you have:

```sh
uv run mscts adapter list
```

```
ADAPTER  VERSION          TARGET  STATE
vanilla  26.3             26.3    installed
pumpkin  nightly 4426d11  26.3    installed
```

## 4. Run the comparison

```sh
uv run mscts run --candidate pumpkin
```

mscts starts both servers, plays every `status/*` Group five times against
each, stops them and prints the Report. One of those Groups,
`status/with-player`, joins a player and waits 6 seconds before it asks for
the status, so it adds about 14 seconds to each repetition. Progress goes to
stderr and the Report to stdout, so `> report.txt` captures only the Report.

```
Running tests against pumpkin nightly 4426d11 (sha256 b8382a8a…)
· status/basic/status_response.description (network traffic only, not scored)
✓ status/basic/status_response.description.text
· status/basic/status_response.enforceSecureChat (network traffic only, not scored)
· status/basic/status_response.favicon (network traffic only, not scored)
...
✗ status/with-player/login_finished.profile.uuid
...
✗ status/with-player/status_response.players.sample[].id
✓ status/with-player/status_response.players.sample[].name
...
25 passed, 10 failed. (71.4%)
Took 89.5 s
```

Each line is one test case of one Group: ✓ if it passed, ✗ if not, and · if
it is not scored. Pumpkin
sends four status values in a different form from vanilla's. The vanilla
client decodes both forms of each to the same thing. Those test cases appear
only because the forms differ, so they are marked "network traffic only, not
scored" and the score leaves them out.

The ten ✗ lines are all from `status/with-player`, which joins a player. Two
are the player's UUID at login and in the server list sample, because
Pumpkin makes the UUID differently from vanilla. The other eight are the
plugin message, registry and tag lines: differences in what Pumpkin sends
while the player joins.
[Reading a Report](/guide/reading-a-report) explains the lines, the totals and the score.

## Next

- [How mscts works](/guide/how-it-works) covers the model behind a Run.
- [Running a comparison](/guide/running) covers `--group` and `--repeat`.
- [Writing an Adapter](/guide/writing-an-adapter) shows how to add your own
  server.
