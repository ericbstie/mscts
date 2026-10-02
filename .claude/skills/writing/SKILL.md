---
name: writing
description: The maintainer's voice for mscts prose - the docs site, README, Report text, CLI messages and issue Docs deltas. Use before writing or rewording any user-facing text, and whenever the maintainer removes, rewords or praises a wording (then ask why and record it here).
---

# writing

How mscts talks to its readers, learned from the maintainer's edits.
Every rule here comes from a real edit, with the example that taught it.

## Keeping this skill current

This skill is a living document, and only the maintainer's explicit
feedback changes it. Whenever they ask to remove or reword something, or
say they like a wording:

1. If they have not said why, ask briefly: what put them off (or what
   they liked), and what would read better. One or two questions, not an
   interview.
2. Make the change to the prose.
3. Update this skill only when they have given a reason, suggested a
   rewording, or approved one you proposed. Then, in the same commit:
   generalise it into a rule under **Principles** (new, or a sharpened
   existing one) that would have prevented the mistake, and add an entry
   under **Examples** with the before, the after and the why, in their
   words where possible.
4. Go back to the work you were doing.

Never invent a reason. If they give no reason and no rewording, change
the prose and leave this skill as it is.

The maintainer may run a dedicated writer session for wording tweaks.
Any session that writes user-facing text follows this skill all the same.

## Principles

- **Be humble and honest.** Claim only what is true for every reader.
  No sweeping judgements about what is good, fun or worthwhile. mscts is a
  tool for people who *want* vanilla behaviour, not a verdict on servers
  that don't.
- **Give insight; let the reader decide.** mscts shows the differences.
  The reader decides whether a server is close enough to vanilla for
  them.
- **Use normal names.** Don't coin a new name where an ordinary one
  exists.
- **Say "network traffic", never "wire".** "Wire" is vague jargon.
- **Keep the terms for the terms.** "Group" and "test case" name things
  in mscts, so don't use "group" or "test" as ordinary words next to them
  ("the Report groups results by …", "tests are grouped by …"). Say
  "sorts", "lists" or "splits" instead.
- **Write for someone new.** No term or claim the reader cannot
  understand without context they don't have (a Self-check, a Group,
  "vanilla against vanilla").
- **Don't announce what the user will see anyway.** If running the
  command shows it, the page need not say it is shown.
- **Only what is useful to the user.** Internal rules and project
  promises (explicit installs) are not selling points.
- **No detail that means nothing to the reader.** Drop numbers and
  identifiers the reader cannot use where they appear (a protocol number
  in a hero). Put them where they matter.

## Examples

### Home page, "Rules mscts follows"

- Before: a section of six rules ("Vanilla is always right", "Every
  Scenario passes a Self-check", "Timings are repeated", "Installs are
  explicit", "One Adapter per server", "Servers stay local").
- After: removed. The Adapter and the servers staying local are told
  in passing in "How it works".
- Why: "Vanilla is always right" makes no sense for a tool that tests
  compliance. The Self-check point assumes the reader knows what a
  Self-check, a Scenario and "vanilla against vanilla" are, and makes a
  claim without that context. "Rules it follows" is not useful to the
  user. Timings are visible when you run the command, so saying so is
  useless. Explicit installs were an instruction to the agent, not a
  selling feature.

### Home page, "What a player can see, and what only the wire can"

- Before: that title; "files it in one of two groups", "observable",
  "wire-only", "Only observable differences count toward compliance."
- After: "Gameplay and network traffic test cases", with a plain account
  of how mscts decides two formats mean the same.
- Why: it assumes the reader knows what "wire" is; say network traffic.
  "Checks each difference against how the client reads it" is too
  abstract: it doesn't say how. (Also, no compliance score exists yet.)

### Command output header

- Before: a four-line block (Reference, Candidate, Target, Repetitions).
- After: `Running tests against <server name>`.
- Why: "It's not easily scannable."

### "Scenario"

- Before: "Scenario" for a set of checks, with no name for each check.
- After: "Group" (for now) for the set, "test case" for each check.
- Why: "an unnecessary new name. Stick to normal names."

### Home page terminal sample (the default Report)

- Before: "2 scenarios: 2 different on the wire only. No difference a
  player would notice was found." followed by long sections per packet.
- After: a simple bullet list of what is different (spec in progress).
- Why: too verbose; "genuinely just show them as bullet lists, not as a
  long-winded response".

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
