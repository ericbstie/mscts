"""Plain helpers shared across test tiers.

Not test files themselves, so pytest never collects this package. `pythonpath =
["tests"]` (pyproject.toml) puts `tests/` on `sys.path`, so this imports as a
top-level package (`from support import ...`) from any test, regardless of which
directories pytest has already collected.
"""
