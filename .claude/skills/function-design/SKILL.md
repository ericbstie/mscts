---
name: function-design
description: Rules for designing and reviewing functions — honesty about dependencies, one level of abstraction per body, and caller-empathetic signatures. Must always apply to any code change. Use whenever writing new functions, refactoring existing ones, reviewing code, or deciding how to structure logic in any language. Also use when code touches global state, RNGs, clocks, IO, or framework callbacks, or when a function has grown multiple responsibilities.
---

# Function Design

Functions exist so a name and signature can carry enough meaning that a limited mind, human or agent, can trust it without reading the body.

## 1. Honest by default

A function is **honest** when it only touches the world through its signature: it never reads or writes anything not reachable via its parameters (including `this`/`self`). Honest functions are deterministic given their arguments, reasoned about in isolation, and testable. A function is **dishonest** when its signature misrepresents its real inputs or outputs — reading globals, singletons, clocks, RNGs, environment, filesystem, network.

Mutation does not make a function dishonest. In-place sort and `vector.clear()` are honest: they mutate only what the caller handed them, deterministically. Returning information about a mutation (à la `remove_if`) is also fine — two output channels, both declared.

**Dishonesty spreads through call chains**: if function A calls dishonest function B, A is dishonest too — A's behavior now depends on whatever B reads or writes outside its parameters, without that being communicated through its signature. One dishonest function anywhere in a call chain makes every function above it in that chain untestable in isolation. Therefore:

- Build core logic entirely from honest functions.
- Inject dishonesty at the topmost level only: `main`, the request handler, the frame loop. That layer reads the clock, seeds entropy, does IO, and passes the results down as arguments.
- Pass dependencies as parameters. Need randomness? Take a generator parameter; seed it from time/OS entropy at the top (or a fixed seed for tests and reproducibility). Need "now"? Take a timestamp or clock parameter. The caller can still choose to pass the global instance as the argument — that's fine. What matters is that reading the global directly inside the function body makes two things impossible: nothing outside the function can tell it depends on that global (it's not in the signature), and nothing outside the function can ever substitute a different value (e.g. a fake clock in a test). Taking it as a parameter keeps both options open, even if the real caller always passes the same global.
- Treat IO and side effects at the boundary as legitimate and necessary — just quarantined. Prefer the honest core to return a data structure describing the full result, which a thin dishonest layer then acts on. If materializing the result is too expensive, provide a callback-taking (`for_each_x`) or iterator/generator function at the bottom and build the collecting version on top.

## 2. One level of abstraction per body

Golden rule: every line of a function body sits at the same level of abstraction. Never zoom into a sub-problem's mechanics and back out within one function. This subsumes single-responsibility, "separate producing data from acting on it," and "no raw loops."

Same level of abstraction means this: describe the function's job as a short list of natural-language steps, then write the body so each line matches one step. Any step that itself needs its own multi-step description becomes its own function instead.

For example, a function that processes an order reads as:

```
processOrder(order):
    validate(order)
    charge(order.customer, order.total)
    ship(order.items, order.address)
    notify(order.customer)
```

Four steps, four function calls, one-to-one. One level down, `charge` expands the same way:

```
charge(customer, amount):
    method = lookupPaymentMethod(customer)
    authorize(method, amount)
    recordTransaction(customer, amount)
```

Its own three-step description matches its body line for line. `charge` never contains `authorize`'s raw HTTP calls, retry-loop mechanics, or response parsing inline — those live inside `authorize`, one level further down.

Lines at the current level may still do real work: call an algorithm, branch on its result. What they must not do is contain a lower-level function's internal steps directly. You can verify a function is correct just by reading its own few lines, without re-checking what each function it calls does internally — as long as you trust that each of those called functions actually does what its name and signature claim.

Prefer the language/library algorithm over hand-rolling — inline reimplementations are exactly where bugs hide, and they can't be tested or optimized once.

When two sibling functions must mirror each other's conventions (e.g., a lookup that lowercases + binary-searches, and an insert that must do the same), you are hand-maintaining an ad hoc data structure. Encapsulate it as a real type (e.g., a case-insensitive map) and let the thin wrappers dissolve.

## 3. Signatures are for the caller

Design the signature for the human or agent reading the call site.

- Several positional parameters, especially bare booleans, are unreadable and error-prone. Use a parameters struct / named or keyword arguments, or strong types.
- The inverse is also an anti-pattern: don't demand an entire existing object when you need two fields from it — that's a cashier demanding your whole wallet for one card.
- Ask for the weakest type that suffices. If you only iterate, accept any iterable/sequence view, not one blessed container type. Don't dictate how callers store their data.
- But when you genuinely need a guarantee, demand it in the type system rather than documenting it:
  - Precondition on a value → a wrapper type whose construction establishes the invariant (`NormalizedVec3` instead of `Vec3` + "must be unit length"). Invalid input becomes impossible instead of ignored, asserted, or optional-checked. Make conversion back to the plain type free. Bonus: operations can specialize on the invariant (normalizing an already-normalized vector is a no-op).
  - Ordering constraint ("must call A before B", "lock must be held") → A returns a token/receipt type that B requires as a parameter.
  - Counterweight: when a change requires extra work that serves the type system rather than the actual task, e.g. re-normalizing a value you already know is normalized just to satisfy the type, or writing separate overloads for `Vec3` and `NormalizedVec3` to handle both, the wrapper type is causing friction. Weigh that friction against the bug it prevents: the more expensive the bug would be if the invariant broke silently, the more friction is worth tolerating.
- Fail through the signature: return a bool/optional/result that distinguishes failure modes. Never abort the process from deep inside a lookup.

## 4. Working habits

- Extract at n=1. Pull code into a function when you first write it — for local reasoning and testability — not after the third copy-paste. Reuse is a side effect, not the trigger.
- Verify that names communicate the functions' effects truthfully: give a reviewer (human or a fresh agent with no access to the implementation) only a function's name, signature, and call site, and ask them to predict what it does and doesn't do. Where their prediction and the real behavior diverge, the name or signature is lying — rename or restructure it until an outsider's prediction matches reality.
- Write the functions you wish existed. Mid-implementation, when you hit a sub-problem you can't solve on the spot, invent the ideal call (`bounce_vector(vel, surface_normal)`), keep going, implement it after. A function call abstracts details in time, not just space.
- Keep framework hooks thin. `main`, `update()`, event handlers, and other inversion-of-control callbacks exist only to glue the framework to your code. Delegate to your own honest functions in the first line or two.

## Smells — flag these on sight

- Core logic reading a global RNG, clock, config, or singleton instead of taking a parameter.
- An accessor-named function whose result depends on hidden global state or bakes in one caller's assumption.
- Section comments labeling phases of a function body (`/* convert name */ ... /* search */ ...`) — each phase wants to be a function.
- Raw loops or hand-rolled algorithms (searching, parsing, char-fiddling) inline among high-level steps.
- A comment or doc saying "must call X first" or "lock must be held" — encode it as a token parameter instead.
- Long positional argument lists with anonymous booleans at the call site.
- Parameters demanding a concrete container or a whole object when a view or two fields would do.
- Precondition checks (or missing ones) that a wrapper type could make unrepresentable.
- `exit()`/`abort()`/panic in ordinary lookup or business logic.
- Sibling functions mirroring each other's encoding/sorting/hashing conventions — an unencapsulated data structure.
- Copy-pasted code awaiting a "third repetition" before extraction.
