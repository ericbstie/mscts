# Getting started

This page takes you from a clean checkout to a Report that compares vanilla
26.3 with [Pumpkin](https://github.com/Pumpkin-MC/Pumpkin). It takes a few
minutes, most of it spent downloading.

mscts is not on PyPI yet. You run it from a checkout.

## Requirements

- Linux on x86-64. The live tiers have only been tested on Linux, and the
  pinned Pumpkin build is Linux-only. The unit tier has been run on macOS
  (Apple silicon), but does not yet pass because of
  [process checks](https://github.com/ericbstie/mscts/issues/143) and
  [loopback addresses](https://github.com/ericbstie/mscts/issues/144).
- [mise](https://mise.jdx.dev). It installs the pinned Python, uv and Java 25
  for you.
- About 200 MB of disk for the two servers.

## 1. Set up the checkout

```sh
git clone https://github.com/ericbstie/mscts
cd mscts
mise install        # Python 3.13, uv, Java 25 (Temurin)
mise run sync       # locked Python dependencies into .venv
```

The vanilla server needs Java 25. mscts looks for it in `MSCTS_JAVA` first,
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

This downloads Pumpkin's latest nightly build. mscts checks that it is a
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
the status. It adds about 14 seconds to each repetition. Progress goes to stderr and
the Report to stdout, so `> report.txt` captures only the Report.

```
Running tests against pumpkin
Candidate: pumpkin nightly 4426d11 (sha256 b8382a8a…)
✓ status/basic/status_response.description Server list description (network traffic only)
✓ status/basic/status_response.description.text Server list description text
✓ status/basic/status_response.enforceSecureChat Unused secure chat flag (network traffic only)
✓ status/basic/status_response.favicon Server list icon (network traffic only)
...
✗ status/with-player/login_finished.profile.uuid Player UUID at login
...
✗ status/with-player/status_response.players.sample[].id Server list player UUID
✓ status/with-player/status_response.players.sample[].name
...
36 passed, 10 failed
Score: 78.2% (36 of 46 test cases pass)
Took 89.5 s
```

Each line is one test case of one Group: ✓ if it passed, ✗ if not. Pumpkin
sends four status values in a different form from vanilla. The vanilla
client decodes each pair to the same thing, so these test cases pass, marked
"network traffic only".

The ten ✗ lines are all from `status/with-player`, which joins a player. Two
are the player's UUID, which Pumpkin makes differently from vanilla: at
login, and in the server list sample. The other eight, the plugin message,
registry and tag lines, are differences in what Pumpkin sends while the
player joins.
[Reading a Report](/guide/reading-a-report) explains the lines, the totals and the score.

## Next

- [How mscts works](/guide/how-it-works) covers the model behind a Run.
- [Running a comparison](/guide/running) covers `--group` and `--repeat`.
- [Writing an Adapter](/guide/writing-an-adapter) shows how to add your own
  server.
