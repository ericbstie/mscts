mise exec -- uv run mscts run --candidate pumpkin --out reports/
Captured 2026-10-03 on issue-254-cap-report-json-divergences (on #240), cloud Linux
container, Java 25. The default Groups include status/with-player (#32).
The run wrote into a scratch folder, which this .txt names reports/. The .json and .md
are the report.json and report.md it wrote, 0.9 MB with each Verdict keeping 20
Divergences of a test case (#254; 88 MB without). They are not trimmed to what the
guide quotes: the .txt and .md are worked out from every Divergence the file holds.
test_cases rewritten 2026-10-09 (#330): the status_response names only network traffic Divergences gave were dropped, as compare no longer lists them; lines, totals and the rendered output follow.
Text re-rendered 2026-10-09 from the same report.json for the · mark of a line not scored (#330).
