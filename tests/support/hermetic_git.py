"""Git for a test that makes a repository: hermetic, whatever runs the test."""

import os
import subprocess
from pathlib import Path


def hermetic_git(*args: str, cwd: Path) -> None:
    # Hermetic git: drop every GIT_* variable (under `git rebase -x`, GIT_DIR points at
    # the real repository, so a test's `git init/config/commit` would write into it), and
    # pass the identity per command instead of writing any config.
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    subprocess.run(
        ["git", "-c", "user.email=test@example.com", "-c", "user.name=Test", *args],  # noqa: S607
        cwd=cwd,
        env=env,
        check=True,
    )
