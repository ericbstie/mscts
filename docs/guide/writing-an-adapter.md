# Writing an Adapter

An Adapter is the only code in mscts that knows about a particular server.
To compare a new server with vanilla, you write one Adapter. You never change a Group.

An Adapter does not install, start or stop anything. It does three things:

- `release` says where to download the server's latest build for the
  Minecraft version mscts tests, or the build a version names.
- `check` reads which build a file is, and refuses one it cannot run.
- `prepare` writes that server's complete native config for a ServerSpec
  and returns a `LaunchPlan`, the command that starts it.

mscts owns everything else: downloading and verifying the binary,
installing it, launching the process, waiting for readiness, and stopping
it. Everything you write lives in your Adapter's own folder.

::: info Work in progress
This page describes the contract in
[`src/mscts/adapters/base.py`](https://github.com/ericbstie/mscts/blob/main/src/mscts/adapters/base.py)
as it is today. A conformance command, `mscts adapter check`, will check an
Adapter against a live server. Until it exists, the unit tests of the
vanilla and Pumpkin Adapters are the best examples.
:::

## The contract

```python
from pathlib import Path
from typing import Protocol

from mscts.adapters.base import Build, Fetch, Installation, LaunchPlan, Release
from mscts.spec import ServerSpec
from mscts.target import Target


class Adapter(Protocol):
    name: str    # the name on the command line: "pumpkin"
    binary: str  # the one file an Installation holds: "server.jar"
    latest_aliases: frozenset[str]  # versions that mean the latest build: {"nightly"}

    def release(self, target: Target, version: str | None, fetch: Fetch) -> Release:
        """The latest build for `target`, or the one `<name>@<version>` names."""

    def check(self, binary: Path, target: Target) -> Build:
        """The build `binary` is; ProvisionError unless this Adapter can run it."""

    def prepare(self, installation: Installation, spec: ServerSpec, workdir: Path) -> LaunchPlan:
        """Write the complete native config for `spec` into `workdir`."""
```

```python
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from mscts.net import Endpoint


@dataclass(frozen=True, slots=True)
class Build:
    version: str               # "26.3", "nightly", "1.4.0"
    commit: str | None = None  # the full commit, where the publisher names one


@dataclass(frozen=True, slots=True)
class Release:
    build: Build
    url: str                   # HTTPS
    sha1: str | None = None    # the publisher's own hash, where it publishes one
    size: int | None = None    # bytes, where the publisher states it


@dataclass(frozen=True, slots=True)
class LaunchPlan:
    argv: tuple[str, ...]
    cwd: Path
    env: Mapping[str, str]
    endpoint: Endpoint         # the host and port the server binds
    stop_stdin: bytes | None   # b"stop\n" for a console stop; None means SIGTERM
```

## A minimal Adapter

This sketch is for an imaginary server, `myserver`, that ships as one
executable and reads `config.toml` from its working directory. Its
publisher describes the latest build in a small JSON file, and the
executable holds the text `myserver <version> for Minecraft <version>`.

```python
import json
import re
from pathlib import Path
from types import MappingProxyType

from mscts.adapters.base import (
    Build,
    Fetch,
    Installation,
    LaunchPlan,
    PrepareError,
    ProvisionError,
    Release,
    UnavailableError,
    UnsupportedError,
)
from mscts.net import Endpoint
from mscts.spec import ServerSpec, WorldPreset
from mscts.target import Target

BINARY = "myserver"
# {"version": "1.4.0", "minecraft": "26.3", "url": "https://..."}
LATEST = "https://myserver.example/releases/latest.json"
NAMES = re.compile(rb"myserver ([\w.]+) for Minecraft ([\w.]+)")


class MyServerAdapter:
    name = "myserver"
    binary = BINARY
    latest_aliases = frozenset({"latest"})  # `myserver@latest` is plain `myserver`

    def release(self, target: Target, version: str | None, fetch: Fetch) -> Release:
        latest = json.loads(fetch(LATEST).body)
        if latest["minecraft"] != target.minecraft_version:
            msg = f"myserver has no build for Minecraft {target.minecraft_version} yet"
            raise ProvisionError(msg)
        build = Build(version=latest["version"])
        if version is not None and version != build.version:
            raise UnavailableError(self.name, version, latest=build)
        return Release(build=build, url=latest["url"])

    def check(self, binary: Path, target: Target) -> Build:
        body = binary.read_bytes()
        names = NAMES.search(body)
        if body[:4] != b"\x7fELF" or names is None:
            msg = f"{binary} is not a myserver build"
            raise ProvisionError(msg)
        version, minecraft = names[1].decode(), names[2].decode()
        if minecraft != target.minecraft_version:
            actual = f"myserver {version}, for Minecraft {minecraft}"
            raise UnsupportedError(str(binary), target=target, actual=actual)
        return Build(version=version)

    def prepare(self, installation: Installation, spec: ServerSpec, workdir: Path) -> LaunchPlan:
        if spec.world is not WorldPreset.FLAT:
            msg = f"myserver cannot generate a {spec.world} world"
            raise PrepareError(msg)
        workdir.mkdir(parents=True, exist_ok=True)
        (workdir / "config.toml").write_text(
            f'address = "{spec.host}:{spec.port}"\n'
            f'motd = "{spec.motd}"\n'
            f"max_players = {spec.max_players}\n"
            f"view_distance = {spec.view_distance}\n"
            "online_mode = false\n"
            "encryption = false\n"
        )
        return LaunchPlan(
            argv=(str(installation.root.absolute() / BINARY),),
            cwd=workdir,
            env=MappingProxyType({}),
            endpoint=Endpoint(host=spec.host, port=spec.port),
            stop_stdin=b"stop\n",
        )
```

A real Adapter writes every setting the server reads, not only the ones
shown here. See the rules below.

## Rules for `release` and `check`

**Read only through `fetch`.** `release` gets every URL it reads through the
`fetch` it is given, never by itself. mscts announces each download, and
your tests pass a fake `fetch` so they never touch the network.

**Name the build exactly.** Give the version your publisher uses, and the
full commit when the publisher names one. Reports show both. The commit a
release names only finds the file: mscts records the commit `check` reads
from the file itself. Where the release names a commit, it refuses a
download that names none. A `--from` file that names none installs
without one.

**Pass on the publisher's own checksum.** If the publisher lists a sha1 and
size for the file, as Mojang does, put them in the `Release`. mscts checks
the download against them.

**Only the Minecraft version mscts tests.** Refuse a build for any other
version with `UnsupportedError`, in `release` when you can tell from the
version, and always in `check`. Give it what was asked for (`myserver@1.2`
or the file) and, when you know it, what the build is. mscts words the
message, the same for every Adapter.

**Raise `ProvisionError` for anything else you expect,** such as a page
that is not what you asked for. Say only what is wrong, never what to
type: mscts adds how to install a build from a file. If anything else goes
wrong in `release`, such as a page that does not parse, mscts says the
build could not be found, gives the error and names `--from`, so a user
never sees a traceback.

**Never substitute a build.** If the version asked for cannot be
downloaded, raise `UnavailableError` with the latest build that can. mscts
says so and how to install the build from a file with `--from`. Never
return a different build instead.

## Rules for `prepare`

**Write the complete config.** Do not leave any setting to the server's
first-run defaults, because those can change between builds. The Pumpkin
Adapter even writes the empty ban and whitelist files Pumpkin would
otherwise create.

**Enforce the invariants.** Every server in a Run must run in offline mode,
without encryption, whitelist, telemetry or a server icon, with spawn
protection 0, and without pausing when empty. None of these are ServerSpec
fields. Your Adapter sets them every time.

**Turn mob spawning off.** Every server must start with the
`spawn_mobs` game rule off, so that no mob spawns naturally from the first
tick. Vanilla and Pumpkin read it from
`world/data/minecraft/game_rules.dat`, not from their config.
`mscts.adapters.fixture_world.game_rules()` builds that file. Write it
gzipped to `fixture_world.GAME_RULES_DAT`, and name
`fixture_world.WORLD_FOLDER` as the world folder in the server's config. A
unit test checks the file for every Adapter in `ADAPTERS`. A server that
cannot read the file starts with spawning on and gives no error, so also
ask a running server for `gamerule spawn_mobs` in a live test.

**Bind exactly the Endpoint.** The ServerSpec's host is always a loopback
address, and each server gets its own. The server must listen on that host
and port, and the LaunchPlan's `endpoint` must name them.

**Refuse what the server cannot do.** If the server cannot honour a
ServerSpec field, raise `PrepareError` before writing any file. A Run then
fails with your message instead of comparing a misconfigured server.

**Pass a fixed environment.** Put only what the server needs in `env`. The
vanilla Adapter passes `PATH=/usr/bin:/bin` and nothing else. The Pumpkin
Adapter passes an empty environment, so `RUST_LOG` and proxy variables from
your shell never reach it.

**Keep `prepare` pure.** It writes files and returns a plan. It does not
start a process or open a socket. Tests can then call it with a ServerSpec
and check the files it wrote.

**Refuse a used workdir.** A server keeps its world and player data in its
working directory, so a reused directory would carry state from one run into
the next. Raise `PrepareError` if `workdir` is not empty.

## Readiness and stopping

mscts considers a server ready once it answers a status ping with protocol
777 from a socket its own process group holds. It never parses logs, so you
do not need to tell mscts what a "done" line looks like.

To stop a server, mscts writes `stop_stdin` to its console if you set it,
then sends SIGTERM, then SIGKILL, waiting up to 30 seconds at each step.

## Register it

1. Put everything you write in one folder, `src/mscts/adapters/<name>/`.
   Its `__init__.py` holds the Adapter, or imports it from other modules
   in the folder. Any data files the Adapter reads, such as a pinned
   default config, go in the folder too.
2. In `src/mscts/cli.py`, import your Adapter and add it to `ADAPTERS`,
   which maps each Adapter name the command knows to its class. Those
   two lines are the only change outside your folder.
3. Write unit tests in `tests/adapters/<name>/`: `release` with a fake
   `fetch`, `check` on small stand-in files, and `prepare` on the files
   it writes and on each invariant.

```text
src/mscts/adapters/myserver/__init__.py   # the Adapter
src/mscts/cli.py                          # an import, and an entry in ADAPTERS
tests/adapters/myserver/test_myserver.py  # its tests
```

The unit tests check this layout for every Adapter in `ADAPTERS`. The
vanilla and Pumpkin Adapters, in `src/mscts/adapters/vanilla/` and
`src/mscts/adapters/pumpkin/`, follow it.

Then run it:

```sh
uv run mscts adapter install myserver
uv run mscts adapter install myserver --from ./myserver
uv run mscts run --candidate myserver
```
