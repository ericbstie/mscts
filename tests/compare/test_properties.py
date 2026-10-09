"""Properties of compare() over many seeded random Transcripts (see generate.py)."""

import os
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path

from mscts.codec.packets import Direction, Packet
from mscts.compare import (
    WHOLE_PACKET,
    Divergence,
    DivergenceKind,
    Mask,
    Observability,
    Outcome,
    Verdict,
    compare,
)
from mscts.transcript import Transcript
from tests.compare.build import packet, transcript
from tests.compare.generate import MASKS, random_fields, render, script, seeded

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
            assert (verdict.outcome, verdict.divergences) == (Outcome.MATCH, ()), f"seed {seed}"


def test_a_rerun_that_differs_only_where_it_may_has_only_network_traffic_divergences() -> None:
    # The same Script, with every masked or ignored detail re-rolled, and the status JSON
    # re-spelled: the spelling is network traffic (ADR-0007), everything else is Masked.
    network_traffic = 0
    for seed in SEEDS:
        runs = script(seeded(seed))
        first = render(runs, seeded(2 * seed), server="vanilla")
        second = render(runs, seeded(2 * seed + 1), server="vanilla")
        verdict = compare(first, second, MASKS)
        assert verdict.gameplay == (), f"seed {seed}"
        paths = {str(d.path).split(".", 1)[0] for d in verdict.divergences}
        assert paths <= {"json_response"}, f"seed {seed}"
        network_traffic += bool(verdict.divergences)
    assert network_traffic >= 0.2 * len(SEEDS)  # not vacuous: 35 of 120 when written


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


_ANY_PACKET = ("test:p", "minecraft:set_health", "minecraft:keep_alive")


def test_a_field_no_one_listed_by_hand_still_gets_a_test_case() -> None:
    # Random fields under arbitrary keys. A match must list exactly the test cases that a
    # change to every leaf reports: every compared field, whatever its name or depth.
    named: set[str] = set()
    for seed in SEEDS:
        rng = seeded(seed)
        drawn = [(rng.choice(_ANY_PACKET), random_fields(rng)) for _ in range(rng.randint(1, 4))]
        sent = [packet(name, fields=fields) for name, fields in drawn]
        changed = [
            packet(name, fields={key: _every_leaf_changed(item) for key, item in fields.items()})
            for name, fields in drawn
        ]
        same = compare(_alice(sent), _alice(sent), [])
        different = compare(_alice(sent), _alice(changed), [])
        found = {d.test_case for d in different.divergences}
        assert same.outcome is Outcome.MATCH, f"seed {seed}"
        assert same.test_cases == different.test_cases == tuple(sorted(found)), f"seed {seed}"
        named |= found
    assert len(named) >= 300  # not vacuous: 465 names when written
    assert any("[]" in name for name in named)
    assert any('["' in name for name in named)
    assert any(name.startswith("play:keep_alive.") for name in named)


def test_every_gameplay_divergence_of_a_field_is_in_a_listed_test_case() -> None:
    for seed in SEEDS:
        rng = seeded(seed)
        verdict = compare(render(script(rng), rng), render(script(rng), rng), MASKS)
        assert list(verdict.test_cases) == sorted(set(verdict.test_cases)), f"seed {seed}"
        for divergence in verdict.divergences:
            assert (divergence.test_case == "") == (divergence.kind == "bot"), f"seed {seed}"
        for divergence in verdict.gameplay:
            assert divergence.test_case in {"", *verdict.test_cases}, f"seed {seed}"


def test_two_runs_give_the_same_test_cases_however_the_format_differed() -> None:
    # Re-runs of one Script differ in masked values, ambient packets, interleaving and
    # how the status JSON is spelled. A network traffic difference adds no test case (#330),
    # so the names are the same whether or not the two formats differed.
    varied = 0
    for seed in SEEDS:
        runs = script(seeded(seed))
        first, second = (
            compare(
                render(runs, seeded(4 * seed + n)), render(runs, seeded(4 * seed + n + 1)), MASKS
            )
            for n in (0, 2)
        )
        assert first.test_cases == second.test_cases, f"seed {seed}"
        varied += _network_traffic(first) != _network_traffic(second)
    assert varied >= 0.2 * len(SEEDS)  # not vacuous


def _alice(sent: Sequence[Packet]) -> Transcript:
    return transcript(*(("alice", each) for each in sent))


def _every_leaf_changed(value: object) -> object:
    """`value` with each leaf in a list of its own: a leaf of another type, at its path."""
    if isinstance(value, Mapping):
        return {key: _every_leaf_changed(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_every_leaf_changed(item) for item in value]
    return [value]


def _network_traffic(verdict: Verdict) -> set[str]:
    return {
        d.test_case for d in verdict.divergences if d.observability is Observability.NETWORK_TRAFFIC
    }


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
            replace(
                d,
                index=to_candidate[d.index] if d.kind == "field" else d.index,
                kind=_MIRRORED_KIND[d.kind],
                reference=d.candidate,
                candidate=d.reference,
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
