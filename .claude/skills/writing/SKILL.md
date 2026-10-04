---
name: writing
description: The maintainer's voice for mscts prose - the docs site, README, Report text, CLI messages and issue Docs deltas. Use before writing or rewording any user-facing text, and whenever the maintainer removes, rewords or praises a wording (then ask why and record it here).
---

# writing

How mscts talks to its readers, learned from the maintainer's edits.
Every rule here comes from a real edit, with the example that taught it.

## Keeping this skill current

This skill is a living document, and only the maintainer's feedback
changes it. Whenever they ask to remove or reword something, or
say they like a wording:

1. If they have not said why, ask briefly: what put them off (or what
   they liked), and what would read better. One or two questions, not an
   interview.
2. Make the change to the prose.
3. In the same commit, add an entry under **Examples** with the before,
   the after and the why, in their words where possible. If they gave
   no reason, write "why: not given".
4. Only when they have given a reason, suggested a rewording, or
   approved one you proposed: generalise it into a rule under
   **Principles** (new, or a sharpened existing one) that would have
   prevented the mistake.
5. Go back to the work you were doing.

Never invent a reason. Examples without one still count: they are the
raw material for later rules. When two or more examples share a pattern
that no rule covers yet, propose a rule that covers them, and add it
once the maintainer approves it.

Wording changes don't each get their own issue or PR. They collect as
commits on one open PR, the wording batch, which the maintainer merges
when they're done. Run `mise run check` and the docs build before each
push, since the docs site deploys from main. If a proposed wording
describes something the code doesn't do, say so instead of writing it,
and leave the code change to the tech lead.

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
- **Write for Minecraft server developers.** They are the audience.
  Players are not addressed; a developer may show them the results.
- **Write for someone new.** No term or claim the reader cannot
  understand without context they don't have (a Self-check, a Group,
  "vanilla against vanilla").
- **Don't announce what the user will see anyway.** If running the
  command shows it, the page need not say it is shown.
- **Only what is useful to the user.** Internal rules and project
  promises (explicit installs, "every commit passes `mise run check`",
  "the ADRs are the only place decisions live") are not selling points
  and don't help a reader, so leave them out of the docs site.
- **A section holds only what its heading promises.** Under "How it
  works", only how mscts tests compliancy; setup facts such as running
  offline belong elsewhere, if anywhere.
- **State requirements firmly and formally.** "requires", not "needs"
  (reads like a suggestion) or "must have" (too informal).
- **Use the headings readers already know.** A plain, conventional
  title ("Roadmap") over an open-ended phrase ("What works today").
- **End each sentence clearly.** No trailing phrases tacked on with
  commas ("…, checked tick by tick, and …, compared over many runs") that
  leave the reader unsure whether the sentence is over. Split it, or
  drop what the reader doesn't need there.
- **Say each thing once.** Look for redundancy in every text and
  rephrase it so nothing is said twice: not a set-up followed by the
  content ("two servers: vanilla and the custom server"), and not two
  lines that name the same thing ("Running tests against pumpkin" then
  "Candidate: pumpkin …"). Keep the natural flow: this is not about
  cutting filler words or packing the text densely.
- **Every sentence is complete and meaningful.** No fragments ("Almost
  all of it is one session"): if the fact matters, write it as a full
  sentence; if a sentence carries no meaning, drop it.
- **No label for what is already shown.** No heading or lead-in that
  only names what follows: "What came out." over the results, "Graph"
  over a graph, "Summary" over a summary.
- **Keep it minimal, and let it flow.** Remove every redundant sentence;
  blank space is fine. Don't condense the phrasing to get there. Vary
  sentence length, some long and some short, and don't stress or
  dramatise anything.
- **Never say what you're about to say; just say it.** No sentence
  that announces what a page or section will do ("This page takes you
  from …", "This page lists them."). Start with the content itself.
- **No detail that means nothing to the reader.** Drop numbers and
  identifiers the reader cannot use where they appear (a protocol number
  in a hero). Put them where they matter.

## Examples

### Token spend infographic (outside the docs site)

- Before: a section headed "What came out."; a lead-in "Every session
  …, added up from …."; and "Almost all of it is one session."
- After: the heading and the lead-in removed; the last kept, as a
  complete sentence.
- Why: "What came out." is "redundant and sounds like AI slop". The
  lead-in gives "the vibe of a passive phrasing and/or a sentence
  fragment" and "doesn't really convey any meaning". "Almost all of it
  is one session" is meaningful but "an incomplete sentence". "Make sure
  every sentence is complete and meaningful." Earlier in that thread:
  remove all redundant text, "it's totally fine if parts of the page is
  blank"; don't label what is shown; "do not condense the prose
  phrasing"; "vary sentence lengths, some long some short"; "avoid
  stressing or overdramatising anything. Keep it to the point and flow
  naturally."

### Getting started, the opening

- Before: "This page takes you from a clean checkout to a Report that
  compares vanilla 26.3 with Pumpkin. It takes a few minutes, most of it
  spent downloading. This page runs mscts from a checkout. To install the
  `mscts` command from the latest GitHub Release instead, run:"
- After: "To install the `mscts` command from the latest GitHub
  Release, run:". The same sweep dropped "This page lists …" from the
  status and design decisions pages.
- Why: redundant and unnecessary prose. "Never say what you're about to
  say — just say it." The download time comment is "totally
  unnecessary".

### Status, design decisions and development guide openings

- Before: "mscts is at an early stage. The working log is
  docs/PROGRESS.md, and the milestones are in docs/PLAN.md."; "The ADRs
  are the only place decisions live."; "Every commit on `main` passes
  `mise run check`."
- After: "mscts is in its early development stage. Future milestones are
  documented in docs/PLAN.md." (the maintainer's wording); the other two
  sentences removed.
- Why: "No need to show / tell about the working log." The other two
  are internal project rules that don't help a reader; the maintainer
  confirmed that reason.

### Development guide, the language

- Before: "mscts is Python 3.13, managed with mise and uv."
- After: "mscts uses Python 3.13, managed with mise and uv." The
  maintainer gave the correction.
- Why: a grammatical error; mscts is not Python, it uses it.

### Report output, the first line and the totals

- Before: "Running tests against pumpkin", then "Candidate: pumpkin
  nightly 4426d11 (sha256 b8382a8a…)"; at the end "19 passed, 0 failed"
  then "Score: 100% (19 of 19 test cases pass)".
- After: "Running tests against pumpkin nightly 4426d11 (sha256
  b8382a8a…)"; at the end "19 passed, 0 failed. (100%)". The maintainer
  chose both wordings.
- Why: each pair says the same thing twice. "Always look for redundancy
  and try to rephrase for conciseness. I don't want to lose the natural
  flow in text, so this isn't about removing filler words and making it
  as dense as possible, just not saying the same thing twice."

### Report output, a title after each test case

- Before: "✓ status/basic/status_response.players.max Player limit".
- After: "✓ status/basic/status_response.players.max".
- Why: the maintainer doesn't want a message after each one; "I liked
  that it only shows the pathname of the test."

### Home page, "What is tested?", what comes next

- Before: "Joining a world is next. Later come redstone, checked tick by
  tick, and random mechanics such as mob spawning, compared over many
  runs (see everything checked today)."
- After: "The next planned changes are related to world joining.
  Redstone and random mechanics are planned after that." The
  maintainer suggested the rewording.
- Why: "very open-ended and it's a little bit hard to understand when
  the sentence is finished or not. Depending on the intonation, that
  sentence could be continued." "Tick by tick" and "compared over many
  runs" aren't necessary there.

### Home page hero title

- Before: "Measure how close your server is to vanilla."
- After: "Minecraft Server Compliancy Test Suite — mscts", with the
  description under it unchanged. The maintainer chose the wording.
- Why: not given.

### Home page, "What works today"

- Before: the heading "What works today".
- After: "Roadmap".
- Why: "a bit open-ended and unclear, especially for being a title", and
  it "gives me this AI vibe"; the maintainer is used to just "Roadmap".

### Home page, "Gameplay and network traffic test cases"

- Before: a section explaining gameplay and network traffic differences,
  with two cards.
- After: removed.
- Why: not given.

### Home page, "Why use this tool?"

- Before: "mscts is for people who want a custom server that keeps
  vanilla's behavior. It gives an objective measure of that playability:
  it lists every difference a player on the vanilla client could notice.
  As a player, you can decide … As a developer, you can focus …"
- After: the maintainer's draft. Vanilla has features and quirks a
  modified server most likely wants to uphold; mscts gives developers a
  simpler way to check which are kept; use the results as a benchmark,
  like Test262 for JavaScript engines.
- Why: the colon says the same thing twice in two different ways (see
  "How it works", opening). And the page is not for players at all:
  "This is targeted only for Minecraft server developers. It's up to the
  Minecraft server developers to use this tool as marketing."

### Home page, "How it works", opening

- Before: "mscts starts two servers on your machine: vanilla Minecraft and
  the custom server you want to compare with it."
- After: "mscts starts a vanilla Minecraft server alongside the custom
  server you're testing." The maintainer suggested the rewording.
- Why: "the custom server you want to compare with it is a bit weirdly
  sentenced". And say it straight away: "AI has a tendency to say the
  same thing two times". The colon first announces two servers, then
  names them. (Rule not yet generalised: the maintainer was "not sure
  exactly what makes it correct".)

### Home page, "How it works", the Adapter

- Before (the maintainer's draft): "The custom server must have an mscts
  Adapter for it that can set up the baseline world state before the
  test suite is run."
- Before (the writer's version): "The custom server needs an mscts
  Adapter, a small module that writes its configuration so it starts
  with the same settings and the same world as vanilla."
- After: "The custom server requires an mscts Adapter, a small module
  that writes its configuration …"
- Why: "needs" sounds more like a suggestion; "must have" is firmer but
  "a bit too informal"; "requires is the correct word here". "A small
  module that writes its configuration …" was praised as "great", why
  not given.

### Home page, "How it works", running offline

- Before: "Both run offline on your machine, and neither can reach the
  internet."
- After: removed.
- Why: "How it works" should only say how mscts is able to test
  compliancy. Running on localhost isn't necessary for that.

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
