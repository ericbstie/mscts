# ServerSpec

A ServerSpec describes how a server must be configured, without naming any
server. Each Adapter translates it into its server's own config files. A
Group can change it through its `spec` option.

## Fields

| Field | Type | Default | Notes |
| --- | --- | --- | --- |
| `host` | `str` | set by mscts | A loopback address in `127.0.0.0/8`, as a dotted quad. Each server gets its own. |
| `port` | `int` | set by mscts | The port the server binds. |
| `motd` | `str` | `"mscts"` | The description shown in the server list. |
| `max_players` | `int` | `20` | |
| `view_distance` | `int` | `2` | In chunks, at most 12. A server sends each player the chunks within its own view distance or the player's, whichever is smaller, and every Bot asks for 12, as a new vanilla client does. |
| `simulation_distance` | `int` | `2` | In chunks. |
| `world` | `WorldPreset` | `FLAT` | Flat is the only preset so far. Void comes once it is verified on vanilla. |
| `seed` | `int` | `0` | |
| `game_mode` | `GameMode` | `SURVIVAL` | `SURVIVAL`, `CREATIVE`, `ADVENTURE` or `SPECTATOR`. |
| `difficulty` | `Difficulty` | `PEACEFUL` | `PEACEFUL`, `EASY`, `NORMAL` or `HARD`. |
| `operators` | `tuple[str, ...]` | `()` | Player names with operator status, besides `control`, which always has it. |
| `compression_threshold` | `int` | `256` | Packets at least this many bytes long are compressed. |

A ServerSpec whose host is not a loopback host address raises `ValueError`,
and one whose view distance is over 12 raises `SpecError`.

## Invariants

Every Adapter applies these on every launch. They are not fields, so no
Group can turn them off.

- Offline mode, with no encryption.
- No whitelist.
- No pause when the server is empty.
- No telemetry.
- No server icon.
- Spawn protection 0.
- No outbound network connections beyond loopback.
- A player called `control` is an operator.

Offline mode lets anyone who can reach the port log in under any name,
including an operator's. That is why every server listens on loopback only.
