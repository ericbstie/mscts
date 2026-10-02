"""Output examples are verbatim lines, with explicit ellipses for omissions (#14)."""

import html
import re
from pathlib import Path

import pytest

from mscts.report import render_text
from tests.docs.replay import report_from_sample

ROOT = Path(__file__).resolve().parents[2]
SAMPLES = Path(__file__).with_name("samples")
PAGES = [ROOT / "docs/getting-started.md", *sorted((ROOT / "docs/guide").glob("*.md"))]


def test_every_stored_output_records_its_capture_command() -> None:
    for sample in SAMPLES.glob("*.txt"):
        command = sample.with_suffix(".command")
        assert command.is_file(), f"Missing provenance: {sample.name}"
        assert command.read_text().startswith("mise exec -- uv run ")


@pytest.mark.parametrize("sample", sorted(SAMPLES.glob("*.json")), ids=lambda path: path.stem)
def test_stored_report_output_matches_the_renderer(sample: Path) -> None:
    verbose = " --verbose" in sample.with_suffix(".command").read_text().splitlines()[0]
    assert (
        render_text(report_from_sample(sample), verbose=verbose)
        == sample.with_suffix(".txt").read_text()
    )


def _matches(excerpt: str, output: str) -> bool:
    pieces = excerpt.strip("\n").split("\n")
    pattern = "".join(
        "(?:[^\\n]*\\n)*" if line.strip() == "..." else re.escape(line) + "\n" for line in pieces
    )
    return re.fullmatch(pattern, output) is not None


def test_every_output_example_matches_a_stored_real_output() -> None:
    outputs = [path.read_text() for path in SAMPLES.glob("*.txt")]
    assert outputs, "Capture command outputs under tests/docs/samples/"
    for page in PAGES:
        blocks = re.findall(
            r"^```([^\n]*)\n(.*?)^```[ \t]*$", page.read_text(), re.MULTILINE | re.DOTALL
        )
        for language, example in blocks:
            if language:
                continue
            assert any(_matches(example, output) for output in outputs), (
                f"{page.relative_to(ROOT)}: output differs from stored samples:\n{example}"
            )


def test_the_home_terminal_matches_the_stored_run_output() -> None:
    page = ROOT / "docs/.vitepress/theme/HomeLanding.vue"
    match = re.search(r"<pre v-pre>(.*?)</pre>", page.read_text(), re.DOTALL)
    assert match is not None
    text = html.unescape(re.sub(r"</?span\b[^>]*>", "", match[1]))
    command, example = text.split("\n", 1)
    assert command == "$ mscts run --candidate pumpkin"
    assert _matches(example, (SAMPLES / "run-pumpkin.txt").read_text())


@pytest.mark.parametrize(
    ("excerpt", "matches"),
    [
        ("a\nb\nc", True),
        ("a\n...\nc", True),
        ("...\nb\n...", True),
        ("a\nc", False),
        ("b", False),
        ("a\nchanged\nc", False),
        ("a\n...\nx", False),
        ("c\n...\na", False),
    ],
    ids=["full", "gap", "ends", "implicit-gap", "implicit-ends", "changed", "missing", "order"],
)
def test_only_explicit_ellipses_can_omit_lines(excerpt: str, *, matches: bool) -> None:
    assert _matches(excerpt, "a\nb\nc\n") is matches
