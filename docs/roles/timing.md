# Timing specialist

**Lane:** what happens on which tick, and in what order. **Model:** opus.
**Owns the core area:** `net.py`, `bot.py`, `settle.py`, `group.py`,
`transcript.py`. Other lanes ask the lead for changes there.

**Issues** (`lane:timing`): #115 and #117 (audit fixes, first), #23
tick-exact Groups, then #37 falling blocks, #38 fluids, #39 redstone
timing, #40 pistons, #41 hoppers, #42 piston glitches, #46 entity motion,
#57 hunger, #58 effects, #63 day cycle, #64 weather, #66 command feedback.

## What this lane knows

- The barrier (`Bot.sync()`) is two statistics round trips that must
  arrive a tick apart (ADR-0010 and its amendments). Under load vanilla can
  answer both in one pass; a stall in our own event loop can fake the gap
  (audit 2026-10-02 H1, #115).
- A change to a barrier or a window is done when its Self-check passes 20
  of 20 five times in a row under `repeat.py --stress`, with a javap account
  of every queue it crosses.
- A window or timing spec gets a 20-play live probe
  (`scripts/research/probe_loop.py`) before its brief.
- Frames of one socket read are stamped a nanosecond apart (#112), so a
  packet behind the window's closing packet stays outside it.
- Pumpkin runs each `chat_command` in its own task: its answers come out of
  order. Measure order on both servers (100 runs) before fixing an order
  contract.
- Never cancel a Bot operation from outside: bound it with its `timeout_s`
  (a cancelled status poll leaked its socket).
- A fake server answers like the real one by default (a pair of answers a
  tick apart), or fakes hide timing bugs.

## Log

Newest first: one line per lesson, with the issue it came from.
