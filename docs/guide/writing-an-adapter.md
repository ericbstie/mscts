# Writing an Adapter

An Adapter is the only code in mscts that knows about a particular server.
To test a new server, you write one Adapter. You never change a Group.

An Adapter does not download, start or stop anything. It does two things:

- `check` confirms that a file is a server build it can run.
- `prepare` writes that server's complete native config for a ServerSpec
  and returns a `LaunchPlan`, the command that starts it.

mscts owns everything else: installing the binary, launching the process,
waiting for readiness, and stopping it.

::: info Work in progress
This page describes the contract in
[`src/mscts/adapters/base.py`](https://github.com/ericbstie/mscts/blob/main/src/mscts/adapters/base.py)
as it is today. A conformance command, `mscts adapter check`, will test an
Adapter against a live server. Until it exists, the unit tests of the
vanilla and Pumpkin Adapters are the best examples.
:::

## The contract

```python
class Adapter(Protocol):
    name: str    # the name on the command line: "pumpkin"
    binary: str  # the one file an Installation holds: "server.jar"

    def check(self, binary: Path, target: Target) -> None:
        """Raise ProvisionError unless `binary` is a server this Adapter can run."""

    def prepare(self, installation: Installation, spec: ServerSpec, workdir: Path) -> LaunchPlan:
        """Write the complete native config for `spec` into `workdir`."""
```

```python
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
executable and reads `config.toml` from its working directory.

```python
from pathlib import Path
from types import MappingProxyType

from mscts.adapters.base import Installation, LaunchPlan, PrepareError, ProvisionError
from mscts.net import Endpoint
from mscts.spec import ServerSpec, WorldPreset
from mscts.target import Target

BINARY = "myserver"


class MyServerAdapter:
    name = "myserver"
    binary = BINARY

    def check(self, binary: Path, target: Target) -> None:
        if binary.read_bytes()[:4] != b"\x7fELF":
            msg = f"{binary} is not an ELF executable"
            raise ProvisionError(msg)

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

## Rules

**Write the complete config.** Do not leave any setting to the server's
first-run defaults, because those can change between builds. The Pumpkin
Adapter even writes the empty ban and whitelist files Pumpkin would
otherwise create.

**Enforce the invariants.** Every server in a Run must run in offline mode,
without encryption, whitelist, telemetry or a server icon, with spawn
protection 0, and without pausing when empty. None of these are ServerSpec
fields. Your Adapter sets them every time.

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

1. Put the module in `src/mscts/adapters/<name>.py`.
2. Add it to `ADAPTERS` in `src/mscts/cli.py`.
3. Write unit tests for `check` and `prepare` that assert on the files
   `prepare` writes and on each invariant.
4. To let `mscts adapter install <name>` download a build, propose a
   Registry entry in `src/mscts/data/registry.toml` with a pinned sha256.
   Without one, people install your server with `--from`.

Then run it:

```sh
uv run mscts adapter install myserver --from ./myserver
uv run mscts run --candidate myserver
```
