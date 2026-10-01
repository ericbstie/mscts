"""The give table (tests/support/gives.py) has a row for every component a command can give.

The reference tier plays the table against vanilla; this unit test keeps it whole when the
Target's data component list changes.
"""

from support.gives import GIVES, NOT_GIVEABLE

from mscts.codec.components import TABLE
from mscts.codec.registry_names import registry_names
from mscts.target import TARGET

COMPONENTS = {name.removeprefix("minecraft:") for name in TABLE.names}


def test_every_data_component_a_command_can_give_has_a_row_in_the_give_table() -> None:
    rows = {name for give in GIVES for name in give.added}
    assert COMPONENTS - NOT_GIVEABLE - rows == set(), "components with no row"
    assert rows - COMPONENTS == set(), "rows for names that are not components"


def test_the_components_no_command_can_give_are_components_of_the_target() -> None:
    names = registry_names(TARGET.minecraft_version, "minecraft:data_component_type")
    assert {f"minecraft:{name}" for name in NOT_GIVEABLE} <= set(names)


def test_no_row_is_for_a_component_no_command_can_give() -> None:
    assert {name for give in GIVES for name in give.added} & NOT_GIVEABLE == set()


def test_no_two_rows_share_a_label_or_an_argument() -> None:
    labels = [give.label for give in GIVES]
    arguments = [give.argument for give in GIVES]
    assert len(set(labels)) == len(labels)
    assert len(set(arguments)) == len(arguments)
