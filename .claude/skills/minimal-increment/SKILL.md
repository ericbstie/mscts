---
name: minimal-increment
description: Enforces minimal-scope, incremental coding work. Use before making any code changes.
---
# Minimal Increment

Applies to coding work only. Runs in three phases: scope, implement, prune.

## Phase 1 — Scope

Before writing code, determine whether the request is trivial or non-trivial.

- Trivial (single obvious change, no ambiguity): skip straight to implementation, leaving out tests, error handling, logging, docs, config, and abstractions unless explicitly requested.
- Non-trivial: ask the user which of the following are in scope for this request, using a multi-select style question: tests, error handling, logging, documentation, config, abstractions/generalization. Do not infer or extrapolate scope on your own — only include what's explicitly ticked.

After the scope answer, write a definition-of-done (DOD) list from the ticked items and track it with the todo tool for the rest of the session. The DOD list itself is never pruned — it's the reference, not an output.

## Phase 2 — Implement

- Write only what was explicitly requested plus whatever was ticked into the DOD.
- Prefer editing existing files over creating new ones.
- No new dependencies.
- Exception: if the truly minimal version would risk data loss or open a security hole, do the safe thing instead and say so plainly — don't silently expand scope.
- Keep a separate internal/meta note of implementation approach or code-style decisions (e.g. "keep this function short"). Never leak these adjectives or process language into user-facing output — no headings like "Short and simple version," no code comments describing the brief.

## Phase 3 — Prune / Verify

- Compare everything changed in the session against the DOD list.
- Anything not on the DOD list gets silently removed — no explanation, no announcement, just remove it.
- The DOD list itself stays intact as the record of what was actually promised.

## Finishing

Stop as soon as the request is fulfilled — do not keep polishing or expanding. End with a brief "Here's what could be done next:" section, split into high priority and low priority, and stop there. Do not act on it unless asked.
