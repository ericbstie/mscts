# Installing servers

mscts never downloads a server during a Run. You install each server once,
with `mscts adapter install`, and every Run after that verifies the installed
file by its sha256 before it launches it.

## The latest build

```sh
uv run mscts adapter install vanilla
uv run mscts adapter install pumpkin
```

Each command installs the latest build of that server for Minecraft 26.3,
the version this mscts tests. It prints every URL before it downloads it:

```
downloading https://github.com/Pumpkin-MC/Pumpkin.git/info/refs?service=git-upload-pack ...
downloading https://github.com/Pumpkin-MC/Pumpkin/releases/download/nightly/pumpkin-X64-Linux ...
installed pumpkin nightly 4426d11 from https://github.com/Pumpkin-MC/Pumpkin/releases/download/nightly/pumpkin-X64-Linux into /home/user/.cache/mscts/pumpkin/26.3
```

| Server | Where the latest build comes from |
| --- | --- |
| `vanilla` | The 26.3 server jar in Mojang's version list, checked by the sha1 and size Mojang publishes. |
| `pumpkin` | Pumpkin's nightly build for Linux x86-64. Its commit comes from Pumpkin's `nightly` tag, and the file must name the same commit. |

If a build is already installed, the command does nothing and says so:

```
pumpkin nightly 4426d11 is already installed at /home/user/.cache/mscts/pumpkin/26.3 (sha256 b8382a8af2afd0a2cab48133ed335a436a771f813823a39b8b2b9c68a2dd360e): nothing to do. To check for a newer build, delete /home/user/.cache/mscts/pumpkin/26.3 and install again.
```

## A specific build

Name the version after `@`:

```sh
uv run mscts adapter install vanilla@26.3
uv run mscts adapter install pumpkin@4426d11
```

For vanilla, the version is the Minecraft version. For Pumpkin, it is the
commit a nightly build was made from, at least its first 7 characters.

Pumpkin publishes only its latest nightly, so an older commit cannot be
downloaded. mscts then installs nothing, and says how to get it:

```
downloading https://github.com/Pumpkin-MC/Pumpkin.git/info/refs?service=git-upload-pack ...
mscts: pumpkin@8f3c2a1 is not available: Pumpkin only publishes its latest nightly (now 4426d11).
Build it yourself and install it with:
  uv run mscts adapter install pumpkin --from <file>
```

## Only Minecraft 26.3

A build for another Minecraft version is refused, whether you name it with
`@` or supply it with `--from`, and nothing is installed:

```
mscts: vanilla@26.4 is not supported: this mscts tests Minecraft 26.3.
```

## From a file you supply

```sh
uv run mscts adapter install pumpkin --from ./pumpkin-X64-Linux
```

mscts asks the Adapter to check that the file is a server it can run for
26.3 and which build it is, hashes the file, copies it into the cache and
records where it came from. A Pumpkin binary names its own version and
commit, so a build you made yourself shows both too.

## See what is installed

```sh
uv run mscts adapter list
```

```
ADAPTER  VERSION          TARGET  STATE
vanilla  26.3             26.3    installed
pumpkin  nightly 4426d11  26.3    installed
```

```sh
uv run mscts adapter status pumpkin
```

```
pumpkin 26.3: installed at /home/user/.cache/mscts/pumpkin/26.3
  version:   nightly
  commit:    4426d1113a211e6018a2db416e33b6b8a7802614
  sha256:    b8382a8af2afd0a2cab48133ed335a436a771f813823a39b8b2b9c68a2dd360e
  size:      126447960 bytes
  from:      https://github.com/Pumpkin-MC/Pumpkin/releases/download/nightly/pumpkin-X64-Linux
  installed: 2026-10-03T01:18:09+00:00
```

`status` exits with code 1 when the Adapter has nothing installed, and prints
the command that installs it. Every Report names the same build: its
version, its commit, and the start of its sha256.

## When a Run needs a missing server

If you start a Run and a server is not installed, mscts asks on a terminal
whether to download its latest build or let you supply a file. Without a
terminal, as in CI, it fails at once and prints the exact install commands.
It never waits for input that cannot come.

## The cache

Installations live in one cache per user, shared by every checkout:

1. `$MSCTS_CACHE`, if set. It must be an absolute path.
2. Otherwise `$XDG_CACHE_HOME/mscts`.
3. Otherwise `~/.cache/mscts`.

Each Installation is a directory `<adapter>/<minecraft version>/` holding the
server binary and a `SOURCE.json` file that records its version and commit,
its sha256 and size, and the URL or path it came from.
