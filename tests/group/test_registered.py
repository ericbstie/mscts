from collections.abc import Iterator
from typing import cast

import pytest

from mscts import group as group_module
from mscts.compare import Mask
from mscts.group import (
    GROUPS,
    Group,
    GroupContext,
    GroupKind,
    group,
    identity,
    resolve,
)
from mscts.spec import ServerSpec


async def _nothing(_: GroupContext) -> None:
    pass


@pytest.fixture
def registering() -> Iterator[None]:
    """Let a test register Groups; forget them afterwards, so no other test sees them."""
    registered = group_module._REGISTERED  # noqa: SLF001 - undo what the test registered
    before = dict(registered)
    yield
    registered.clear()
    registered.update(before)


def test_a_group_is_exact_with_no_prerequisites_masks_or_spec_changes_by_default() -> None:
    plain = Group(id="test/plain", run=_nothing)
    spec = ServerSpec(host="127.0.0.1", port=25566)

    assert plain.kind is GroupKind.EXACT
    assert plain.requires == ()
    assert plain.masks == ()
    assert plain.spec(spec) is spec
    assert identity(spec) is spec


def test_group_kinds_are_named_as_adr_0006_names_them() -> None:
    assert [kind.value for kind in GroupKind] == ["exact", "tick-exact", "statistical"]


@pytest.mark.usefixtures("registering")
def test_the_decorator_registers_the_group_with_its_options() -> None:
    mask = Mask(packet="minecraft:login", path="entity_id", reason="an id with no meaning")

    @group(
        "test/decorated",
        requires=("test/first",),
        masks=(mask,),
        kind=GroupKind.TICK_EXACT,
    )
    async def decorated(_: GroupContext) -> None:
        pass

    assert GROUPS["test/decorated"] == Group(
        id="test/decorated",
        run=decorated,
        requires=("test/first",),
        masks=(mask,),
        kind=GroupKind.TICK_EXACT,
    )


@pytest.mark.usefixtures("registering")
def test_the_decorator_returns_the_function_itself() -> None:
    assert group("test/same")(_nothing) is _nothing


@pytest.mark.usefixtures("registering")
def test_a_duplicate_id_is_refused_and_the_first_stays() -> None:
    group("test/twice")(_nothing)

    async def other(_: GroupContext) -> None:
        pass

    with pytest.raises(ValueError, match="test/twice"):
        group("test/twice")(other)

    assert GROUPS["test/twice"].run is _nothing


@pytest.mark.usefixtures("registering")
def test_the_registered_groups_are_in_registration_order() -> None:
    for name in ("test/b", "test/a", "test/c"):
        group(name)(_nothing)

    assert [name for name in GROUPS if name.startswith("test/")] == [
        "test/b",
        "test/a",
        "test/c",
    ]


def test_the_registered_groups_are_a_read_only_view() -> None:
    with pytest.raises(TypeError):
        cast("dict[str, Group]", GROUPS)["test/sneaky"] = Group(id="test/sneaky", run=_nothing)


def test_resolve_puts_prerequisites_first_and_each_group_once() -> None:
    groups = {
        "test/base": Group(id="test/base", run=_nothing),
        "test/middle": Group(id="test/middle", run=_nothing, requires=("test/base",)),
        "test/top": Group(id="test/top", run=_nothing, requires=("test/middle", "test/base")),
    }

    resolved = resolve(["test/top", "test/base"], groups)

    assert [each.id for each in resolved] == ["test/base", "test/middle", "test/top"]


def test_resolve_refuses_a_prerequisite_cycle() -> None:
    groups = {
        "test/x": Group(id="test/x", run=_nothing, requires=("test/y",)),
        "test/y": Group(id="test/y", run=_nothing, requires=("test/x",)),
    }

    with pytest.raises(ValueError, match="cycle"):
        resolve(["test/x"], groups)


def test_resolve_refuses_an_unknown_id_or_prerequisite_naming_it() -> None:
    groups = {"test/x": Group(id="test/x", run=_nothing, requires=("test/gone",))}

    with pytest.raises(KeyError, match="test/nowhere"):
        resolve(["test/nowhere"], groups)
    with pytest.raises(KeyError, match="test/gone"):
        resolve(["test/x"], groups)
