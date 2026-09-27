# Installing servers

mscts never downloads a server during a Run. You install each server once,
with `mscts adapter install`, and every Run after that verifies the installed
file by its sha256 before it launches it.

## From the Registry

The Registry is a list of server builds, each pinned by a checksum. It lives
in [`src/mscts/data/registry.toml`](https://github.com/ericbstie/mscts/blob/main/src/mscts/data/registry.toml).
The maintainer approves each entry.

```sh
uv run mscts adapter install vanilla
uv run mscts adapter install pumpkin --version nightly-48cba7ee
```

Without `--version`, mscts picks the entry for the current Target. It prints
the URL before it downloads anything, then checks the file against the
entry's hash. If the file is already installed and verified, the command
does nothing and says so.

Current entries:

| Adapter | Version | Source |
| --- | --- | --- |
| `vanilla` | `26.3` | Mojang's server jar, checked by the sha1 and size Mojang publishes |
| `pumpkin` | `nightly-48cba7ee` | One build of Pumpkin's Linux x86-64 nightly, pinned 2026-09-26 by sha256 |

::: warning Pumpkin's nightly moves
Pumpkin publishes every nightly at the same URL. Once a newer build replaces
the pinned one, a Registry install fails with a sha256 mismatch. Install the
new build with `--from` instead, or ask for a new pin.
:::

## From a file you supply

```sh
uv run mscts adapter install pumpkin --from ./pumpkin-X64-Linux
```

mscts asks the Adapter to check that the file is a server it can run for the
Target, hashes it, copies it into the cache and records where it came from.
If the file's hash matches a Registry entry, the Installation records that
entry. Otherwise Reports name the build by its sha256.

## See what is installed

```sh
uv run mscts adapter list
```

```
ADAPTER  VERSION           TARGET  STATE
vanilla  26.3              26.3    installed
pumpkin  nightly-48cba7ee  26.3    not installed
pumpkin  -                 26.3    installed: no Registry entry, from ./pumpkin-X64-Linux (sha256 864f606e...)
```

```sh
uv run mscts adapter status vanilla
```

```
vanilla 26.3: installed at /root/.cache/mscts/vanilla/26.3
  entry:     vanilla 26.3
  sha256:    d052f14d7a173734fba553711e5b570162e2f2a313267ee31a21b975a679be64
  size:      62294556 bytes
  from:      https://piston-data.mojang.com/v1/objects/33680f5f2ac32864d6d7cf5e56a705fdb3e05f4c/server.jar
  installed: 2026-09-27T08:30:59+00:00
```

`status` exits with code 1 when the Adapter has nothing installed, and prints
the command that installs it.

## When a Run needs a missing server

If you start a Run and a server is not installed, mscts asks on a terminal
whether to download the Registry entry or let you supply a file. Without a
terminal, as in CI, it fails at once and prints the exact install command.
It never waits for input that cannot come.

## The cache

Installations live in one cache per user, shared by every checkout:

1. `$MSCTS_CACHE`, if set. It must be an absolute path.
2. Otherwise `$XDG_CACHE_HOME/mscts`.
3. Otherwise `~/.cache/mscts`.

Each Installation is a directory `<adapter>/<minecraft version>/` holding the
server binary and a `SOURCE.json` file that records its sha256, size, the
Registry entry it matches, and the URL or path it came from.
