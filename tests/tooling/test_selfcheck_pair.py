"""Which Groups the Self-check tier's shared pair of Instances can play (#84).

The pair is booted at the default ServerSpec. A Group whose `spec` changes that cannot be
played on an Attached side, so the tier launches Instances of their own for it.
"""

import dataclasses

from support.selfcheck import needs_instances_of_their_own

from mscts.group import Group, GroupContext
from mscts.spec import ServerSpec

SPEC = ServerSpec(host="127.0.0.1", port=25565)


async def _nothing(_: GroupContext) -> None:
    pass


def test_groups_that_leave_the_spec_alone_play_on_the_pair() -> None:
    groups = [Group(id="test/a", run=_nothing), Group(id="test/b", run=_nothing)]

    assert not needs_instances_of_their_own(groups, SPEC)


def test_a_group_that_changes_the_spec_needs_instances_of_its_own() -> None:
    changing = Group(
        id="test/near",
        run=_nothing,
        spec=lambda spec: dataclasses.replace(spec, view_distance=4),
    )

    assert needs_instances_of_their_own([Group(id="test/a", run=_nothing), changing], SPEC)


def test_a_group_that_sets_a_field_to_what_it_is_changes_nothing() -> None:
    same = Group(
        id="test/same",
        run=_nothing,
        spec=lambda spec: dataclasses.replace(spec, view_distance=SPEC.view_distance),
    )

    assert not needs_instances_of_their_own([same], SPEC)


def test_the_endpoint_is_not_part_of_the_spec_a_group_changes() -> None:
    moved = Group(
        id="test/moved",
        run=_nothing,
        spec=lambda spec: dataclasses.replace(spec, host="127.0.0.2", port=1),
    )

    assert not needs_instances_of_their_own([moved], SPEC)
