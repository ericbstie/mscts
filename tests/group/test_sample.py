"""`GroupContext.sample`: what a statistical Group records (#24)."""

from typing import cast

import pytest

from mscts.group import GroupContext
from mscts.net import Endpoint
from mscts.stats import Sample
from mscts.transcript import Transcript

_UNUSED = Endpoint(host="127.0.0.1", port=1)


def _context(samples: dict[str, list[Sample]] | None = None) -> GroupContext:
    transcript = Transcript(group_id="test/sample", server="fake")
    return GroupContext(_UNUSED, transcript, timeout_s=1.0, samples=samples)


def _untyped(value: object) -> object:
    return value


def test_samples_are_recorded_by_name_in_order() -> None:
    samples: dict[str, list[Sample]] = {}
    context = _context(samples)

    context.sample("spawn.distance", 3.2)
    context.sample("spawn.mob", "minecraft:zombie")
    context.sample("spawn.distance", 4)

    assert samples == {"spawn.distance": [3.2, 4], "spawn.mob": ["minecraft:zombie"]}


def test_samples_add_to_those_of_earlier_plays() -> None:
    samples: dict[str, list[Sample]] = {"spawn.distance": [1.0]}

    _context(samples).sample("spawn.distance", 2.0)

    assert samples == {"spawn.distance": [1.0, 2.0]}


def test_a_context_without_a_record_keeps_its_samples_to_itself() -> None:
    context = _context()

    context.sample("x", 1.0)

    assert context.samples == {"x": [1.0]}


def test_a_category_after_numbers_of_one_name_is_refused() -> None:
    context = _context({"spawn.distance": [1.0]})

    with pytest.raises(ValueError, match=r"'spawn\.distance' holds numbers, so 'far'"):
        context.sample("spawn.distance", "far")


def test_a_number_after_categories_of_one_name_is_refused() -> None:
    context = _context()
    context.sample("spawn.mob", "minecraft:zombie")

    with pytest.raises(ValueError, match=r"'spawn\.mob' holds categories, so 2"):
        context.sample("spawn.mob", 2)


@pytest.mark.parametrize("value", [True, None, b"x", [1.0]], ids=["bool", "None", "bytes", "list"])
def test_a_sample_is_a_number_or_a_category(value: object) -> None:
    with pytest.raises(TypeError, match="a sample is a number or a category"):
        _context().sample("x", cast("Sample", _untyped(value)))


@pytest.mark.parametrize("value", [float("nan"), float("inf")], ids=["nan", "inf"])
def test_a_number_sample_is_finite(value: float) -> None:
    with pytest.raises(ValueError, match="finite"):
        _context().sample("x", value)


def test_a_sample_has_a_name() -> None:
    with pytest.raises(ValueError, match="a sample needs a name"):
        _context().sample("", 1.0)
