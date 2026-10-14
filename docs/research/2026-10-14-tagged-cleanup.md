# How long a killed mob stays, and what `@e` still finds — 2026-10-14

Evidence for #368 (the clean-up a Group runs on the entities it tagged). Facts are **verified**
with `scripts/research/javap.py` on the 26.3 server jar.

## A killed mob's body

- `LivingEntity.tickDeath` adds 1 to `deathTime` each tick of the body. Once it reaches 20, on
  the server and if the body is not removed yet, it broadcasts entity event 60 and removes the
  body (`remove(KILLED)`). So the body stays for 20 of its own ticks, and the players that track
  it are told it is gone (`remove_entities`) only then.
- `LivingEntity.isAlive` is `!isRemoved() && getHealth() > 0`. A killed mob has no health, so it
  is not alive while its body stays.

## What `@e` matches

- `EntitySelectorParser.parseSelector` adds `Entity::isAlive` to the predicates of `@e` and
  `@n`, and not to those of `@p`, `@a`, `@r` or `@s`.
- So `@e[tag=...]` never matches a body that is dying, and `execute if entity @e[tag=...]`
  fails as soon as `kill` has run. A clean-up that waits for that answer returns while every
  body is still there; only the players that track the bodies can tell when they are gone.
