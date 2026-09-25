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

# Make mise-pinned tools (java 25, uv, python) win over system ones for the session.
if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  echo "export PATH=\"$HOME/.local/share/mise/shims:$HOME/.local/bin:\$PATH\"" >> "$CLAUDE_ENV_FILE"
fi
