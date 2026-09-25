# mscts

Minecraft Server Compliancy Test Suite is a test suite that compares and
times custom Minecraft server implementations against a vanilla Minecraft
server. It gives MC server devs an objective measurement of their 1:1
parity compliance and a non-biased, open source performance indicator.

It connects to both servers as an ordinary protocol client, runs the same
Scenario against each, and diffs the packets they send back. The only
server-specific code is a small Adapter that knows how to install,
configure and launch that server.

Status: early. Target is Minecraft 26.3 (protocol 777). See
[`docs/PLAN.md`](docs/PLAN.md) and [`docs/PROGRESS.md`](docs/PROGRESS.md).

## Development

Requires [mise](https://mise.jdx.dev).

```sh
mise install && mise run sync
mise run check
```
