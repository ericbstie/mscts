from collections.abc import Iterator
from typing import cast

import pytest

from mscts import scenario as scenario_module
from mscts.compare import Mask
from mscts.scenario import (
    SCENARIOS,
    Scenario,
    ScenarioContext,
    ScenarioKind,
    identity,
    resolve,
    scenario,
)
from mscts.spec import ServerSpec


async def _nothing(_: ScenarioContext) -> None:
    pass


@pytest.fixture
def registering() -> Iterator[None]:
    """Let a test register Scenarios; forget them afterwards, so no other test sees them."""
    registered = scenario_module._REGISTERED  # noqa: SLF001 - undo what the test registered
    before = dict(registered)
    yield
    registered.clear()
    registered.update(before)


def test_a_scenario_is_exact_with_no_prerequisites_masks_or_spec_changes_by_default() -> None:
    plain = Scenario(id="test/plain", run=_nothing)
    spec = ServerSpec(host="127.0.0.1", port=25566)

    assert plain.kind is ScenarioKind.EXACT
    assert plain.requires == ()
    assert plain.masks == ()
    assert plain.spec(spec) is spec
    assert identity(spec) is spec


def test_scenario_kinds_are_named_as_adr_0006_names_them() -> None:
    assert [kind.value for kind in ScenarioKind] == ["exact", "tick-exact", "statistical"]


@pytest.mark.usefixtures("registering")
def test_the_decorator_registers_the_scenario_with_its_options() -> None:
    mask = Mask(packet="minecraft:login", path="entity_id", reason="an id with no meaning")

    @scenario(
        "test/decorated",
        requires=("test/first",),
        masks=(mask,),
        kind=ScenarioKind.TICK_EXACT,
    )
    async def decorated(_: ScenarioContext) -> None:
        pass

    assert SCENARIOS["test/decorated"] == Scenario(
        id="test/decorated",
        run=decorated,
        requires=("test/first",),
        masks=(mask,),
        kind=ScenarioKind.TICK_EXACT,
    )


@pytest.mark.usefixtures("registering")
def test_the_decorator_returns_the_function_itself() -> None:
    assert scenario("test/same")(_nothing) is _nothing


@pytest.mark.usefixtures("registering")
def test_a_duplicate_id_is_refused_and_the_first_stays() -> None:
    scenario("test/twice")(_nothing)

    async def other(_: ScenarioContext) -> None:
        pass

    with pytest.raises(ValueError, match="test/twice"):
        scenario("test/twice")(other)

    assert SCENARIOS["test/twice"].run is _nothing


@pytest.mark.usefixtures("registering")
def test_the_registered_scenarios_are_in_registration_order() -> None:
    for name in ("test/b", "test/a", "test/c"):
        scenario(name)(_nothing)

    assert [name for name in SCENARIOS if name.startswith("test/")] == [
        "test/b",
        "test/a",
        "test/c",
    ]


def test_the_registered_scenarios_are_a_read_only_view() -> None:
    with pytest.raises(TypeError):
        cast("dict[str, Scenario]", SCENARIOS)["test/sneaky"] = Scenario(
            id="test/sneaky", run=_nothing
        )


def test_resolve_puts_prerequisites_first_and_each_scenario_once() -> None:
    scenarios = {
        "test/base": Scenario(id="test/base", run=_nothing),
        "test/middle": Scenario(id="test/middle", run=_nothing, requires=("test/base",)),
        "test/top": Scenario(id="test/top", run=_nothing, requires=("test/middle", "test/base")),
    }

    resolved = resolve(["test/top", "test/base"], scenarios)

    assert [each.id for each in resolved] == ["test/base", "test/middle", "test/top"]


def test_resolve_refuses_a_prerequisite_cycle() -> None:
    scenarios = {
        "test/x": Scenario(id="test/x", run=_nothing, requires=("test/y",)),
        "test/y": Scenario(id="test/y", run=_nothing, requires=("test/x",)),
    }

    with pytest.raises(ValueError, match="cycle"):
        resolve(["test/x"], scenarios)


def test_resolve_refuses_an_unknown_id_or_prerequisite_naming_it() -> None:
    scenarios = {"test/x": Scenario(id="test/x", run=_nothing, requires=("test/gone",))}

    with pytest.raises(KeyError, match="test/nowhere"):
        resolve(["test/nowhere"], scenarios)
    with pytest.raises(KeyError, match="test/gone"):
        resolve(["test/x"], scenarios)
