# mscts

Minecraft Server Compliancy Test Suite is a test suite that compares and
times custom Minecraft server implementations against a vanilla Minecraft
server. It gives MC server devs an objective measurement of their 1:1
parity compliance and a non-biased, open source performance indicator.

It connects to both servers as an ordinary protocol client, runs the same
Groups against each, and diffs the packets they send back. The only
server-specific code is a small Adapter that knows how to install,
configure and launch that server.

Documentation is a VitePress site in [`docs/`](docs/getting-started.md):
`mise run docs:dev` serves it locally.

Status: early. Target is Minecraft 26.3 (protocol 777). See
[`docs/PLAN.md`](docs/PLAN.md) and [`docs/PROGRESS.md`](docs/PROGRESS.md).

## Development

Requires [mise](https://mise.jdx.dev).

```sh
mise install && mise run sync
mise run check
```

## Repository layout

- `src/mscts/groups/`: the compliance tests mscts runs against a server,
  one file per area, such as `status.py` and `blocks.py`. Each test
  script is called a Group.
- `src/mscts/`: the rest of mscts itself.
- `tests/`: mscts's own tests, which check that mscts works.
- `docs/`: the documentation site.

[`CONTEXT.md`](CONTEXT.md) explains the words the project uses, and
[`docs/contributing.md`](docs/contributing.md) explains how to contribute.
