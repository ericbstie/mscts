# Getting started

This page takes you from a clean checkout to a Report that compares vanilla
26.3 with [Pumpkin](https://github.com/Pumpkin-MC/Pumpkin). It takes a few
minutes, most of it spent downloading.

mscts is not on PyPI yet. You run it from a checkout.

## Requirements

- Linux on x86-64. The Pumpkin nightly build is Linux-only, and no other
  platform has been tested.
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

The Registry pins one Pumpkin nightly build by its sha256:

```sh
uv run mscts adapter install pumpkin
```

Pumpkin publishes every nightly at the same URL, so the pinned build is
often gone by the time you read this. The install then fails with a sha256
mismatch. Download the current build yourself and install it with `--from`:

```sh
curl -sSfL -o pumpkin-X64-Linux \
  https://github.com/Pumpkin-MC/Pumpkin/releases/download/nightly/pumpkin-X64-Linux
uv run mscts adapter install pumpkin --from pumpkin-X64-Linux
```

A build installed with `--from` matches no Registry entry, so Reports name it
by its sha256. See [Installing servers](/guide/installing-servers).

Check what you have:

```sh
uv run mscts adapter list
```

```
ADAPTER  VERSION           TARGET  STATE
vanilla  26.3              26.3    installed
pumpkin  nightly-48cba7ee  26.3    not installed
pumpkin  -                 26.3    installed: no Registry entry, from pumpkin-X64-Linux (sha256 864f606e...)
```

## 4. Run the comparison

```sh
uv run mscts run --candidate pumpkin
```

mscts starts both servers, plays every `status/*` Group five times against
each, stops them and prints the Report. Progress goes to stderr and the
Report to stdout, so `> report.txt` captures only the Report.

```
mscts Report
  Reference    vanilla (its status says version "26.3")
  Candidate    pumpkin (its status says version "26.3")
  Target       Minecraft 26.3 (protocol 777)
  Repetitions  5 of each group

2 groups: 2 different in network traffic only. No difference a player would notice was found.

Network traffic differences (a vanilla client reads both alike; not counted in scores)
--------------------------------------------------------------------------------------
  Server list ping (status)
    status_response: 4 values are sent differently, e.g.
      - json_response.description: vanilla sends "mscts", pumpkin sends {"text": "mscts"}
      - json_response.enforceSecureChat: vanilla leaves it out, pumpkin sends true
      - json_response.favicon: vanilla leaves it out, pumpkin sends null
      - json_response.players.sample: vanilla leaves it out, pumpkin sends []

Timings (ms)
------------
  measurement       vanilla median    p95  pumpkin median   p95  n
  status.rtt                  1.41   3.18            0.27  0.48  5
  instance.startup           9,987  9,987              39    39  1
```

Pumpkin sends four status values in a different form from vanilla. These are
network traffic differences: the vanilla client decodes each pair to the
same thing, so none of them count against Pumpkin.
[Reading a Report](/guide/reading-a-report) explains each section.

## Next

- [How mscts works](/guide/how-it-works) covers the model behind a Run.
- [Running a comparison](/guide/running) covers `--group` and `--repeat`.
- [Writing an Adapter](/guide/writing-an-adapter) shows how to add your own
  server.
