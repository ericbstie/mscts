mise exec -- uv run mscts run --candidate pumpkin
Captured 2026-10-03 on issue-254-cap-report-json-divergences (on #240), cloud Linux
container, Java 25. The default Groups include status/with-player (#32).
The run also had --out, to keep the files: the .json and .md are the report.json and
report.md it wrote, 0.9 MB with each Verdict keeping 20 Divergences of a test case (#254;
88 MB without). The .txt is the stdout, without its `Report written to` line.
