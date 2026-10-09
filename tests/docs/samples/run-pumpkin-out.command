mise exec -- uv run mscts run --candidate pumpkin --out reports/
Captured 2026-10-03 on issue-190-run-out rebased onto main 16af262, cloud Linux container, Java 25.
vanilla 26.3 and pumpkin nightly 4426d11 installed by `mscts adapter install`; stdout only.
The .json and .md are the report.json and report.md this run wrote.
Text re-rendered 2026-10-03 from the same report.json for one line per test case (#101).
report.json rewritten 2026-10-03 through report_json.dumps, adding lines and totals (#101).
Played the Groups the default held then, status/basic and status/ping. #32 added
status/with-player to the default; `--group 'status/[bp]*'` plays the same two.
test_cases rewritten 2026-10-09 (#330): the status_response names only network traffic Divergences gave were dropped, as compare no longer lists them; lines, totals and the rendered output follow.
