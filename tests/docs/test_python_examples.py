"""Execute the guide's standalone Python examples, with explicit exceptions (#109)."""

import re
from collections.abc import Iterator
from pathlib import Path

import pytest

import mscts.group as groups

ROOT = Path(__file__).resolve().parents[2]
GUIDE = ROOT / "docs" / "guide"
_OPEN = re.compile(r" {0,3}(`{3,}|~{3,})[ \t]*(.*)")
_NOT_RUN = re.compile(r"<!-- not run: (.*?) -->")


def _examples(page: Path) -> Iterator[tuple[int, str, str | None]]:
    lines = page.read_text().splitlines()
    closing = None
    python = False
    start = 0
    body: list[str] = []
    reason = None
    for number, line in enumerate(lines, 1):
        if closing is not None:
            if closing.fullmatch(line):
                if python:
                    yield start, "\n".join(body), reason
                closing = None
            else:
                body.append(line)
        elif opening := _OPEN.fullmatch(line):
            fence, info = opening.groups()
            closing = re.compile(
                r" {0,3}" + re.escape(fence[0]) + "{" + str(len(fence)) + r",}[ \t]*"
            )
            python = info.split(maxsplit=1)[:1] == ["python"]
            start = number
            body = []
            previous = lines[number - 2].strip() if number > 1 else ""
            mark = _NOT_RUN.fullmatch(previous)
            reason = str(mark[1]).strip() if mark else None
    assert closing is None or not python, f"{page}:{start}: unclosed Python fence"


def _execute(page: Path, start: int, code: str) -> None:
    namespace: dict[str, object] = {"__name__": __name__}
    try:
        exec(compile("\n" * start + code, str(page), "exec"), namespace)  # noqa: S102 - #109 executes guide code
    except (Exception, SystemExit) as error:
        line = error.lineno if isinstance(error, SyntaxError) else start + 1
        trace = error.__traceback__
        while trace is not None:
            if trace.tb_frame.f_code.co_filename == str(page):
                line = trace.tb_lineno
            trace = trace.tb_next
        message = f"{page}:{line}: {type(error).__name__}: {error}"
        raise AssertionError(message) from error


@pytest.fixture(autouse=True)
def isolated_group_registration(monkeypatch: pytest.MonkeyPatch) -> None:
    """An example may register a shipped Group without changing the suite's registry."""
    monkeypatch.setattr(groups, "_REGISTERED", {})


_EXAMPLES = [
    (page, start, code, reason)
    for page in sorted(GUIDE.glob("*.md"))
    for start, code, reason in _examples(page)
]


@pytest.mark.parametrize(
    ("page", "start", "code", "reason"),
    _EXAMPLES,
    ids=[f"{page.relative_to(ROOT)}:{start}" for page, start, _code, _reason in _EXAMPLES],
)
def test_each_guide_python_example_runs_on_its_own(
    page: Path, start: int, code: str, reason: str | None
) -> None:
    if reason is not None:
        assert reason, f"{page}:{start}: not-run marks need a reason"
        pytest.skip(f"{page.relative_to(ROOT)}:{start}: {reason}")
    _execute(page, start, code)


def test_a_raising_example_reports_its_page_and_source_line(tmp_path: Path) -> None:
    page = tmp_path / "broken.md"
    page.write_text('# Example\n\n```python\nx = 1\nraise RuntimeError("broken example")\n```\n')
    ((start, code, reason),) = list(_examples(page))
    assert reason is None
    expected = re.escape(str(page)) + r":5: RuntimeError: broken example"
    with pytest.raises(AssertionError, match=expected):
        _execute(page, start, code)


def test_examples_do_not_share_a_namespace(tmp_path: Path) -> None:
    page = tmp_path / "independent.md"
    _execute(page, 1, "value_from_another_example = 42")
    _execute(page, 1, "assert 'value_from_another_example' not in globals()")


def test_fences_keep_their_language_and_only_an_adjacent_mark_skips_python(tmp_path: Path) -> None:
    page = tmp_path / "fences.md"
    page.write_text(
        "```text\n```python\nnot Python\n```\n"
        "<!-- not run: fragment -->\n~~~~python\nx = 1\n~~~~~\n"
        "<!-- not run: distant -->\n\n```python\nx = 2\n```\n"
    )
    examples = list(_examples(page))
    assert [(start, code, reason) for start, code, reason in examples] == [
        (6, "x = 1", "fragment"),
        (11, "x = 2", None),
    ]
