"""The glossary follows CONTEXT.md term by term (#14)."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _definitions(context: str) -> dict[str, str]:
    definitions = {}
    for match in re.finditer(
        r"^- \*\*([^*]+)\*\*:?\s*(.*?)(?=^- \*\*|^## |\Z)",
        context,
        re.MULTILINE | re.DOTALL,
    ):
        definition = re.sub(r"_Avoid_:.*", "", match[2], flags=re.DOTALL).strip()
        # The writing skill calls the Codec's wire types "field types" on the site.
        definition = "\n".join(line.removeprefix("  ") for line in definition.splitlines())
        definition = definition[:1].upper() + definition[1:]
        definitions[str(match[1])] = definition.replace("wire types", "field types")
    return definitions


def test_the_glossary_matches_each_context_definition() -> None:
    definitions = _definitions((ROOT / "CONTEXT.md").read_text())
    glossary = (ROOT / "docs/reference/glossary.md").read_text()
    entries = {
        match[1]: match[2].strip()
        for match in re.finditer(
            r"^### ([^\n]+)\n(.*?)(?=^### |^## |\Z)", glossary, re.MULTILINE | re.DOTALL
        )
    }
    assert entries.keys() == definitions.keys()
    for term, definition in definitions.items():
        assert entries[term] == definition, f"Glossary definition differs: {term}"
