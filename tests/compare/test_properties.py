"""Properties of compare() over many seeded random Transcripts (see generate.py)."""

import os
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from mscts.codec.packets import Direction
from mscts.compare import (
    WHOLE_PACKET,
    Divergence,
    DivergenceKind,
    Mask,
    Outcome,
    Verdict,
    compare,
)
from mscts.transcript import Transcript
from tests.compare.generate import MASKS, SCENARIO, render, script, seeded

SEEDS = range(120)
ROOT = Path(__file__).resolve().parents[2]


# Each property loops over SEEDS in one test, naming the seed when it fails: one test
# per seed costs more in pytest overhead than the Comparisons themselves (G5).


def test_a_transcript_matches_itself() -> None:
    for seed in SEEDS:
        rng = seeded(seed)
        transcript = render(script(rng), rng)
        for masks in (MASKS, ()):
            verdict = compare(transcript, transcript, masks)
            assert verdict == Verdict(SCENARIO, Outcome.MATCH), f"seed {seed}"


def test_a_rerun_that_differs_only_where_it_may_has_only_wire_only_divergences() -> None:
    # The same Script, with every masked or ignored detail re-rolled, and the status JSON
    # re-spelled: the spelling is wire-only (ADR-0007), everything else is Masked.
    wire_only = 0
    for seed in SEEDS:
        runs = script(seeded(seed))
        first = render(runs, seeded(2 * seed), server="vanilla")
        second = render(runs, seeded(2 * seed + 1), server="vanilla")
        verdict = compare(first, second, MASKS)
        assert verdict.observable == (), f"seed {seed}"
        assert {d.path for d in verdict.divergences} <= {"json_response"}, f"seed {seed}"
        wire_only += bool(verdict.divergences)
    assert wire_only >= 0.2 * len(SEEDS)  # not vacuous: 35 of 120 when written


def test_those_reruns_do_differ_without_the_masks() -> None:
    # Otherwise the property above would hold vacuously.
    differ = 0
    for seed in SEEDS:
        runs = script(seeded(seed))
        first, second = render(runs, seeded(2 * seed)), render(runs, seeded(2 * seed + 1))
        differ += compare(first, second, ()).outcome is Outcome.MISMATCH
    assert differ >= 0.8 * len(SEEDS)


def test_swapping_the_sides_mirrors_the_divergences() -> None:
    for seed in SEEDS:
        rng = seeded(seed)
        reference, candidate = render(script(rng), rng), render(script(rng), rng)
        masks = MASKS if seed % 2 else ()
        forward = compare(reference, candidate, masks)
        backward = compare(candidate, reference, masks)
        assert backward.outcome is forward.outcome, f"seed {seed}"
        mirrored = _mirror(forward.divergences, reference, candidate, masks)
        assert _canonical_order(backward.divergences) == _canonical_order(mirrored), f"seed {seed}"


def test_divergence_order_is_the_same_on_every_call() -> None:
    for seed in SEEDS:
        rng = seeded(seed)
        reference, candidate = render(script(rng), rng), render(script(rng), rng)
        first = compare(reference, candidate, MASKS)
        assert compare(reference, candidate, MASKS).divergences == first.divergences


def test_most_swapped_pairs_have_every_kind_of_divergence() -> None:
    # Otherwise the mirror property above would hold vacuously.
    kinds: set[str] = set()
    mismatches = 0
    for seed in SEEDS:
        rng = seeded(seed)
        verdict = compare(render(script(rng), rng), render(script(rng), rng), MASKS)
        kinds.update(d.kind for d in verdict.divergences)
        mismatches += verdict.outcome is Outcome.MISMATCH
    assert kinds == {"bot", "missing", "unexpected", "field"}
    assert mismatches >= 0.9 * len(SEEDS)


def test_divergence_order_does_not_depend_on_the_hash_seed() -> None:
    # Set and dict orders of str keys change with PYTHONHASHSEED; the Verdict must not.
    child = (
        "from mscts.compare import compare\n"
        "from tests.compare.generate import MASKS, render, script, seeded\n"
        "for seed in range(60):\n"
        "    rng = seeded(seed)\n"
        "    reference, candidate = render(script(rng), rng), render(script(rng), rng)\n"
        "    print(compare(reference, candidate, MASKS if seed % 2 else ()))\n"
    )
    runs = [
        subprocess.Popen(
            [sys.executable, "-c", child],
            cwd=ROOT,
            env={**os.environ, "PYTHONHASHSEED": hash_seed},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for hash_seed in ("1", "2")
    ]
    outputs = [run.communicate(timeout=30) for run in runs]
    assert [run.returncode for run in runs] == [0, 0], outputs
    assert outputs[0][0] == outputs[1][0]
    assert outputs[0][0].count("MISMATCH") >= 50


def _mirror(
    divergences: Sequence[Divergence],
    reference: Transcript,
    candidate: Transcript,
    masks: Sequence[Mask],
) -> list[Divergence]:
    """What compare(candidate, reference) should say, given compare(reference, candidate).

    The matched pairs are the reference and candidate indices no `missing` or
    `unexpected` Divergence names, zipped in order; a `field` Divergence moves to its
    pair's candidate index.
    """
    mirrored = []
    for bot in dict.fromkeys(d.bot for d in divergences):
        own = [d for d in divergences if d.bot == bot]
        missing = {d.index for d in own if d.kind == "missing"}
        unexpected = {d.index for d in own if d.kind == "unexpected"}
        ref_matched = [i for i in range(_length(reference, bot, masks)) if i not in missing]
        cand_matched = [j for j in range(_length(candidate, bot, masks)) if j not in unexpected]
        assert len(ref_matched) == len(cand_matched)
        to_candidate = dict(zip(ref_matched, cand_matched, strict=True))
        mirrored.extend(
            Divergence(
                bot=d.bot,
                index=to_candidate[d.index] if d.kind == "field" else d.index,
                kind=_MIRRORED_KIND[d.kind],
                packet=d.packet,
                path=d.path,
                reference=d.candidate,
                candidate=d.reference,
                observability=d.observability,
            )
            for d in own
        )
    return mirrored


_MIRRORED_KIND: dict[str, DivergenceKind] = {
    "bot": "bot",
    "missing": "unexpected",
    "unexpected": "missing",
    "field": "field",
}


def _length(transcript: Transcript, bot: str, masks: Sequence[Mask]) -> int:
    """The length of `bot`'s normalized stream."""
    dropped = {mask.packet for mask in masks if mask.path == WHOLE_PACKET}
    return sum(
        event.bot == bot
        and event.packet.direction is Direction.CLIENTBOUND
        and event.packet.name not in dropped
        for event in transcript.events
    )


def _canonical_order(divergences: Sequence[Divergence]) -> list[Divergence]:
    """Sort by what makes a Divergence unique, so two lists compare as multisets."""
    return sorted(
        divergences, key=lambda d: (d.bot, d.kind, d.index, d.path or "", d.observability)
    )
