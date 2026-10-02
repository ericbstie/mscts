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

A build installed with `--from` matches no Registry entry, so the Adapter
listing and verbose Report name it by its sha256. See [Installing servers](/guide/installing-servers).

Check what you have:

```sh
uv run mscts adapter list
```

```
ADAPTER  VERSION           TARGET  STATE
vanilla  26.3              26.3    installed
pumpkin  nightly-b8382a8a  26.3    installed
```

## 4. Run the comparison

```sh
uv run mscts run --candidate pumpkin
```

mscts starts both servers, plays every `status/*` Group five times against
each, stops them and prints the Report. Progress goes to stderr and the
Report to stdout, so `> report.txt` captures only the Report.

```
Running tests against pumpkin
- Server list description  status_response.description
- Unused secure chat flag  status_response.enforceSecureChat
- Server list icon  status_response.favicon
- Server list player sample  status_response.players.sample
Took 22.7 s
```

Pumpkin sends four status values in a different form from vanilla. These are
network traffic differences: the vanilla client decodes each pair to the
same thing, so none of them count against Pumpkin.
[Reading a Report](/guide/reading-a-report) explains the list and the test case names.

## Next

- [How mscts works](/guide/how-it-works) covers the model behind a Run.
- [Running a comparison](/guide/running) covers `--group` and `--repeat`.
- [Writing an Adapter](/guide/writing-an-adapter) shows how to add your own
  server.
