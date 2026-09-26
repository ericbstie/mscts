"""The download cache: one per user, shared by every worktree and session."""

import os
from pathlib import Path

CACHE_ENV = "MSCTS_CACHE"


def cache_dir() -> Path:
    """Where mscts keeps jars, binaries and generated reports, keyed by adapter and Target.

    MSCTS_CACHE if set, else $XDG_CACHE_HOME/mscts, else ~/.cache/mscts. It is never
    inside a checkout, so every worktree and session shares it and downloads only once.
    """
    explicit = os.environ.get(CACHE_ENV)
    if explicit:
        if not Path(explicit).is_absolute():
            # Resolved against each caller's cwd, it would silently split the shared cache.
            msg = f"{CACHE_ENV} must be an absolute path, not {explicit!r}"
            raise ValueError(msg)
        return Path(explicit)
    xdg = os.environ.get("XDG_CACHE_HOME")
    if xdg and Path(xdg).is_absolute():  # the XDG spec: ignore an empty or relative value
        return Path(xdg) / "mscts"
    return Path.home() / ".cache" / "mscts"
