"""Every known test case has a matching title and reference entry (#12)."""

import re
from pathlib import Path

from mscts.case_titles import TITLES

ROOT = Path(__file__).resolve().parents[2]


def test_the_reference_entries_match_the_title_table() -> None:
    page = ROOT / "docs/reference/test-cases.md"
    assert page.is_file(), "Add the test case reference"
    entries = re.findall(
        r"^## `([^`]+)`\n\n\*\*([^\n]+)\*\*\n\n([^#]+)", page.read_text(), re.MULTILINE
    )
    assert len(entries) == len({name for name, _, _ in entries}), "Duplicate test case entries"
    assert {name: title for name, title, _ in entries} == TITLES
    assert all(prose.strip() for _, _, prose in entries)


def test_a_swing_animation_has_a_title_for_itself_and_each_of_its_fields() -> None:
    swing = {name for name in TITLES if name.startswith("swing_animation")}
    assert swing == {
        "swing_animation",
        "swing_animation.entity_id",
        "swing_animation.hand",
        "swing_animation.animation.type",
        "swing_animation.animation.duration",
    }
