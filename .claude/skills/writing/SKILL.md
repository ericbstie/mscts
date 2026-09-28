---
name: writing
description: The maintainer's voice for mscts prose - the docs site, README, Report text, CLI messages and issue Docs deltas. Use before writing or rewording any user-facing text, and whenever the maintainer removes, rewords or praises a wording (then ask why and record it here).
---

# writing

How mscts talks to its readers, learned from the maintainer's edits.
Every rule here comes from a real edit, with the example that taught it.

## Keeping this skill current

Whenever the maintainer asks to remove or reword something, or says they
like a wording:

1. If they have not said why, ask why and how they perceived it: what it
   made them think or feel, and who they pictured reading it.
2. Make the change.
3. Add their reason to this skill in the same commit: a rule under
   **Principles** (new, or sharpened), and an entry under **Examples**
   with the before, the after and the why, in their words where possible.

Never invent a reason. If the maintainer gave none and declines to say,
record the example with "why: not given".

## Principles

- **Be humble and honest.** Claim only what is true for every reader.
  No sweeping judgements about what is good, fun or worthwhile. mscts is a
  tool for people who *want* vanilla behaviour, not a verdict on servers
  that don't.
- **Give insight; let the reader decide.** mscts shows the differences.
  The reader decides whether a server is close enough to vanilla for
  them.
- **No detail that means nothing to the reader.** Drop numbers and
  identifiers the reader cannot use where they appear (a protocol number
  in a hero). Put them where they matter.

## Examples

### Home page hero label

- Before: `Minecraft 26.3 · protocol 777`
- After: removed. The Target is stated on a later page.
- Why: "It doesn't mean anything" at the top of the page.

### Home page, "Why use this tool?"

- Before: "A custom server is only worth playing on if it behaves like
  vanilla. mscts gives you an objective measure of that playability …"
- After: "mscts is for people who want a custom server that keeps
  vanilla's behavior. It gives an objective measure of that playability
  …"
- Why: a bold statement that is not true at all. A heavily modded,
  non-vanilla game can be really fun too, so it reads as obnoxiously
  ignorant. mscts ensures vanilla compliance for those who want a server
  that keeps vanilla features, and gives the player the insight to decide
  whether a server is close enough to vanilla for their liking.
