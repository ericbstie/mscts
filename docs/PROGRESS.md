# Progress

Handoff between sessions. Update it at least every few commits and always
before stopping (see the `red-green` skill).

## Now

Milestone **M0 (Harness)** is done. **M1 (Talk to vanilla)** has started:
VarInt encode/decode is green. Work now runs under the tech-lead/worker
model (`docs/PROCESS.md`).

Batch 1 in flight:
- **A** (sonnet): `codec` wire types and framing (Next 1–4).
- **B** (opus): `Target`, `ServerSpec` and `VanillaAdapter` (`prepare` +
  `provision`), from the M1 list.

## Next

Take the first item. Split it if it is more than one failing test.

1. `codec`: `Reader.var_int` raises `WireError` on truncated input and on
   encodings longer than 5 bytes.
2. `codec`: VarLong encode/decode against the wiki sample table (see the
   `protocol-research` skill for `VarInt_and_VarLong?action=raw`).
3. `codec`: String (VarInt byte-length prefix, UTF-8, max length in UTF-16
   units per the Data types page), UShort, Long, Bool, UUID.
4. `codec`: `framing`, meaning frame encode, plus a decoder that yields
   whole frames from partial chunks.
5. `codec`: commit the generated `codec/data/26.3/packets.json` with a
   regen script (the data generator command is in `protocol-research`),
   plus `Codec.packet_id` / `packet_name`.
6. Continue down the **M1** list in `docs/PLAN.md` (schemas for
   handshake/status, `ServerSpec`, `VanillaAdapter.prepare` → `provision`
   → `runner.running` → `Bot.status` against the live Reference).

## Log

### 2026-09-25 — session 1: research and harness

- Researched the domain against live servers in the container. Findings
  are in `docs/research/2026-09-25-domain.md`: the vanilla 26.3 join
  sequence was verified up to chunk batches, along with default-config
  traps, the 26.3 `accept_teleportation` change, and Pumpkin nightly's
  config and divergences.
- Decisions: ADR-0001…0005 (black-box differential testing, Astral + mise
  toolchain, single Target 26.3/777, translator-only Adapters with
  status-ping readiness, in-repo plan with always-green commits on `main`).
- Removed the inherited generic skills. Added the `red-green` and
  `protocol-research` skills, plus a SessionStart hook that provisions
  mise tools and deps.
- Toolchain: `mise run check` = ruff (ALL) + format check + ty (all rules
  error) + bandit + unit tier. It runs in about 1 s.
- Environment notes: `java` on the default PATH is 21. Java 25 comes from
  mise, so run anything that needs it through `mise run …` or with the
  mise shims on PATH (the hook exports them). The `UV_NATIVE_TLS`
  deprecation warning comes from the container env and is harmless.
