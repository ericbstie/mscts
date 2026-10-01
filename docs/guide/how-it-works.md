# How mscts works

mscts measures a Minecraft server by comparing it with vanilla. It never reads
either server's source or logs. It connects as a client, sends what the
vanilla client would send, and records what comes back.

## The two servers

The **Reference** is the vanilla server for the Target, which is Minecraft
26.3 speaking protocol 777. mscts treats whatever vanilla sends as correct.

The **Candidate** is the server you want to measure, such as Pumpkin. A Run
always has one Reference and one Candidate.

mscts has no expected values of its own. A Group never asserts that a
packet holds some value. It only asserts that the Candidate sends what
vanilla sent.

## A Run, step by step

```
Group ──► Bot(s) ──► vanilla  ──► Transcript R ──┐
                                                 ├──► Comparison ──► Verdict
Group ──► Bot(s) ──► Candidate ──► Transcript C ──┘
                          │
                          └── span Marks ──► Measurements ──► Report
```

1. **Launch.** Each server has an **Adapter**, a small module that turns a
   server-agnostic **ServerSpec** into that server's native config files
   and a launch command. mscts starts both servers at once, each on its own
   address in `127.0.0.0/8`, and waits until a status ping answers with
   protocol 777 from a socket the server's own process holds.
2. **Play.** A **Group** is a short async script with a name like
   `status/ping`. It opens one or more **Bots**. A Bot is a protocol client
   that answers what the vanilla client answers automatically, such as
   keep-alives and teleport confirmations.
3. **Record.** Every packet a Bot sends or receives goes into a
   **Transcript** with a timestamp. A Group can also record named
   **Marks**, such as the start and end of a ping.
4. **Compare.** mscts diffs the two Transcripts packet by packet and field by
   field. The result is a **Verdict**.
5. **Repeat.** The Run plays every Group N times (five by default) against
   the same pair of servers, then stops both.
6. **Report.** mscts prints the differences under their mechanic, followed
   by timings.

## Verdicts

| Verdict | Meaning |
| --- | --- |
| `match` | The Candidate sent what vanilla sent. |
| `mismatch` | At least one difference, called a **Divergence**. |
| `blocked` | A Group this one requires did not match, so mscts did not play it. |
| `error` | mscts itself failed, or vanilla could not run the Group. |

When the Candidate breaks the protocol, sends a frame that does not decode,
closes the connection or stops answering, the Verdict is `mismatch`, led by
a `failed` Divergence that says what happened. It is never `error`.
Compliance scores leave `error` out, so a Candidate must not be able to
score better by crashing.

## Gameplay and network traffic differences

Some differences are visible to a player and some are not. The vanilla client
reads a server description sent as `"mscts"` and one sent as
`{"text": "mscts"}` as the same text. Counting that as a failure would
punish a server for a choice the protocol allows.

So every Divergence is one of two kinds:

- **gameplay**: a vanilla client would read the two values differently, so a
  player could notice it.
- **network traffic**: the bytes differ, but the client decodes both to the
  same thing.

The rules that decide this form the **canonical table**. Each rule rewrites
a value into one canonical form, and each one cites the client code that
proves the two forms are equal. mscts still reports network traffic
differences, in their own section, but compliance scores count only gameplay
ones.

A difference is only network traffic where such a rule says so. Today the
canonical table covers the server list answer. Any other difference counts
as gameplay.

## Masks

Some values differ between two runs of vanilla itself: entity ids,
keep-alive ids, teleport ids. A **Mask** excludes one such field from the
Comparison. A Mask must give a reason, and that reason must show the value
has no gameplay meaning.

A few fields hold a value vanilla picks at random every time, such as the
session id each login gets. Two runs of vanilla never agree on them, so
mscts leaves them out for every Group. Vanilla also sends the tag lists in
an order that changes each time it starts, and the client reads them into
lookup tables, so mscts compares them sorted by name.

Otherwise mscts never masks anything a player could observe, even if it
is random. Random mechanics, such as mob spawning and loot, will be
compared statistically instead, as distributions over many runs.

## Self-checks

Before a Group counts, mscts runs it with vanilla on both sides. This
Self-check must `match` in 20 runs out of 20. A failure means the Group
is flaky or is missing a Mask. It never means vanilla is wrong.

## Timings

A Group marks spans in its script. `status/ping` marks the time from
sending a ping to receiving the pong, and mscts records that as
`status.rtt` in milliseconds. mscts also records `instance.startup`, the
time from launch until the server is ready. The Report shows the median and
p95 of each measurement for both servers.

## What mscts does not cover

- Anything only visible on the server, such as the on-disk world format.
- Online-mode authentication and encryption. Every server runs offline.
- Bedrock Edition.
- More than one Minecraft version at a time.
