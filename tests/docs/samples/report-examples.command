mise exec -- uv run python -c "from pathlib import Path; from mscts import report_json; from mscts.report import render_text; print(render_text(report_json.loads(Path('tests/docs/samples/report-examples.json').read_text())), end='')"
Rendered 2026-10-02 from illustrative Report inputs; not a live Candidate run.
Inputs rewritten as report.json 2026-10-03 (#190); the rendered text is unchanged.
Text re-rendered 2026-10-03 from the same report.json for one line per test case (#101).
report.json rewritten 2026-10-03 through report_json.dumps, adding lines and totals (#101).
join/basic's blocked repetitions list two test cases of vanilla's play 2026-10-04 (#285); re-rendered.
join/basic fails as a Candidate failure of its prerequisite 2026-10-04 (#285 review B); re-rendered.
