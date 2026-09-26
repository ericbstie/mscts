#!/bin/bash
# Provision the mscts toolchain in a fresh Claude Code on the web container:
# mise-pinned Python/uv/Java 25, then the locked dev dependencies.
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "${CLAUDE_PROJECT_DIR:-$(dirname "$0")/../..}"

if ! command -v mise >/dev/null 2>&1; then
  curl -fsSL https://mise.run | sh
  export PATH="$HOME/.local/bin:$PATH"
fi

mise trust --yes --quiet .
mise install --yes
mise run sync

# The Reference: installed explicitly and loudly (ADR-0008), never inside a test run.
# Idempotent: an installed, verified jar is a no-op that says so. A failure is reported
# (with its fix) but does not stop the session from starting.
echo "mscts: installing the Reference (vanilla) for the reference tier ..."
mise run install:reference || echo "mscts: installing vanilla failed; the reference tier will fail until it is installed" >&2

# Make mise-pinned tools (java 25, uv, python) win over system ones for the session.
# MSCTS_JAVA names the real Java 25 launcher: the Reference Adapter refuses shims.
if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  echo "export PATH=\"$HOME/.local/share/mise/shims:$HOME/.local/bin:\$PATH\"" >> "$CLAUDE_ENV_FILE"
  echo "export MSCTS_JAVA=\"$(mise where java)/bin/java\"" >> "$CLAUDE_ENV_FILE"
fi
