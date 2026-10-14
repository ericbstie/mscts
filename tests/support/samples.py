"""Samples that more than one test of statistical Groups judges (#24)."""

import random

from mscts.stats import Categories


def rare_items(seed: int = 6) -> tuple[Categories, Categories]:
    """30 samples a side, each one item of 20, all too rare to pool; the Candidate's of 12."""
    draw = random.Random(seed)
    reference = tuple(f"item{draw.randrange(20)}" for _ in range(30))
    candidate = tuple(f"item{draw.randrange(12)}" for _ in range(30))
    return Categories(reference, (1,) * 30), Categories(candidate, (1,) * 30)


RARE_ITEMS_P = 45 / 10_001
"""The permutation test's p-value of `rare_items`, drawn from `stats.PERMUTATION_SEED`."""
