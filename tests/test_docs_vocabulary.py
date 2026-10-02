"""The docs site says "network traffic" and "gameplay", never "wire" or "observable" (#11).

The two kinds of Divergence are named for a reader who has never met the
protocol. The ADRs, research notes, audits, PLAN, PROGRESS and PROCESS record
history and the codec's own names, so they are not checked.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
THEME = DOCS / ".vitepress" / "theme"
NOT_SITE_PAGES = frozenset({"PLAN.md", "PROGRESS.md", "PROCESS.md", "RISK.md"})

SITE_PAGES = sorted(
    [
        *(page for page in DOCS.glob("*.md") if page.name not in NOT_SITE_PAGES),
        *DOCS.glob("guide/*.md"),
        *DOCS.glob("reference/*.md"),
        *(page for page in THEME.iterdir() if page.is_file()),
        DOCS / ".vitepress" / "config.mts",
        ROOT / "README.md",
    ]
)

LINK_TARGET = re.compile(r"\]\([^)]*\)")
"""A Markdown link's target. ADR-0007's file name keeps its old title, and a reader
never sees the target, so it is not prose."""

BANNED = {
    "wire": 'say "network traffic" (or "field types" for the codec\'s own types)',
    "observable": 'say "gameplay"',
}


def _hits(page: Path, word: str) -> list[str]:
    hits = []
    for number, line in enumerate(page.read_text().splitlines(), start=1):
        if word in LINK_TARGET.sub("]", line).lower():
            hits.append(f"{page.relative_to(ROOT)}:{number}: {line.strip()}")
    return hits


def test_the_site_pages_are_found() -> None:
    names = {page.relative_to(DOCS).as_posix() for page in SITE_PAGES if page.is_relative_to(DOCS)}

    assert {
        "index.md",
        "guide/reading-a-report.md",
        "guide/how-it-works.md",
        "reference/glossary.md",
        ".vitepress/theme/HomeLanding.vue",
    } <= names
    assert not {"PLAN.md", "PROGRESS.md", "PROCESS.md"} & names
    assert not any(name.startswith(("adr/", "research/", "audits/")) for name in names)


@pytest.mark.parametrize("word", BANNED)
def test_the_site_never_says(word: str) -> None:
    hits = [hit for page in SITE_PAGES for hit in _hits(page, word)]

    assert not hits, f"{BANNED[word]}:\n" + "\n".join(hits)
