# ADR-0008: Explicit installs, a pinned registry, and Adapters as a first-class extension point

Status: accepted (2026-09-26). Amended 2026-10-03 (#156): decision 3 is
replaced, below.

## Context

Getting a server binary can fail for reasons unrelated to the suite,
such as this cloud container's TLS proxy rejecting GitHub downloads. And
a download hidden inside a test run is surprising. The user's priorities:

- an elegant, smooth developer experience;
- simple, idempotent, predictable, honest commands;
- a way for server developers to write their own Adapters easily;
- an official, maintainer-approved list of installable servers, pinned by
  version and checksum rather than by name.

## Decision

1. **Installation is an explicit, idempotent command.**
   `mscts adapter install <adapter> [--version <v>]` downloads a registry
   entry into the cache. It verifies the pinned checksum and does nothing
   if the entry is already installed and verified.
   `mscts adapter install <adapter> --from <path>` provisions a binary
   you supply. It hashes the file, records where it came from, and never
   pretends the file is a registry entry it doesn't match.
   Companion commands: `mscts adapter list` (known Adapters and registry
   entries, with install state) and `mscts adapter status <adapter>`
   (what is installed, which sha256, where it came from).
2. **Honest prompting.** A Run or test that needs a missing Installation
   asks interactively only when stdin is a TTY: "download <entry> (Y) or
   provision it yourself (N)?". N prints the exact `--from` command.
   Without a TTY (CI, agents) it never hangs. It fails at once, naming
   the exact command that would fix it.
3. **The official registry is pinned by checksum.** A committed registry
   lists each installable server as (adapter, version label, URL, sha256
   and/or the publisher's hash) and is approved by the mscts maintainer.
   A name alone is never trusted. A floating "nightly" is not a registry
   entry; a specific nightly build, pinned by its sha256, can be. Reports
   state which entry, or which `--from` sha256, was tested.
4. **Adapters are a documented, first-class extension point.** The
   Adapter contract (PLAN, ADR-0004, ADR-0006) is published as an
   authoring guide with a minimal template. It comes with a runnable
   conformance kit, `mscts adapter check <adapter>`, which verifies the
   contract against a live Instance: complete config, invariants,
   offline login, no outbound network, readiness, graceful stop, and
   refusal of unsupported ServerSpec fields. A third-party developer can
   then prove their Adapter honest before trusting its Reports.
5. **Developer experience is a goal (G6),** not an afterthought:
   - commands are idempotent and say exactly what they did or would do;
   - errors name the fix;
   - nothing downloads, installs or waits without saying so.

## Consequences

- Items 1 and 2 come first, since the Pumpkin Candidate needs them.
  The registry file (3) and the conformance kit and guide (4) follow.
  All are sequenced in PLAN.
- In this container, Pumpkin is provisioned with `--from`, using a binary
  fetched manually with curl, which verifies TLS normally.
- `Adapter.provision` splits into resolving a registry entry and fetching
  it. Fetching is replaceable, which is how `--from` works, and the
  cache records the source of every Installation.

## Amendment (2026-10-03): latest by default, `@` for one build (#156)

Decision 3 (a committed registry, each build pinned by checksum) is
replaced. Pinning a build nobody reviewed adds no safety, and Pumpkin
deletes each nightly once the next one is out, so a pinned nightly soon
cannot be installed at all.

1. **Installing works like npm.** `mscts adapter install <adapter>`
   installs the latest build for the Target, and
   `mscts adapter install <adapter>@<version>` the build that version
   names; `--version` is gone. `--from <file>` stays for any other build.
2. **Each Adapter owns its download information**, in its own module: an
   Adapter's `release` finds its latest build for the Target (vanilla: the
   jar Mojang's version manifest lists; Pumpkin: the nightly, at the
   commit its `nightly` tag names), and its `check` reads which build a
   file is. `src/mscts/data/registry.toml` and `src/mscts/registry.py` are
   gone. `cli.py` keeps a static list of Adapters; there is no dynamic
   discovery.
3. **Only the Target's Minecraft version installs.** `@<version>` and
   `--from` refuse a build for another Minecraft version, and install
   nothing: `vanilla@26.4 is not supported: this mscts tests Minecraft
   26.3.`
4. **A version that can no longer be downloaded fails**, naming `--from`
   (and building from source); mscts never installs a different build
   instead. There is no mirror and no build-from-source step.

   Adapters report these two refusals with the facts only
   (`UnsupportedError`: what was asked for and what it is;
   `UnavailableError`: the latest build instead), and mscts words them
   once, the same for every Adapter (#158).
5. **A checksum the publisher itself publishes is still checked** (Mojang's
   sha1 and size), as an integrity check. What is recorded comes
   from the file, never from the label that found it: Pumpkin's binary
   names its own commit, which may differ from the `nightly` tag's for a
   few minutes a day. Where the release names a commit, a download that
   names none is refused (#158).
6. **Reports name the exact build**: its version, its commit where the
   publisher gives one (a Pumpkin nightly always does), and the sha256 of
   the file tested: `pumpkin nightly 4426d11 (sha256 b8382a8a…)`.

Unchanged: installs are explicit and idempotent (an installed build is
never replaced silently; to get a newer one, delete it and install again),
the honest prompt (decision 2), and Adapters as an extension point
(decision 4). Where to read a Pumpkin nightly's commit is recorded in
`docs/research/2026-10-03-install.md`.
