# Reading a Report

A Report lists every test case mscts compared, each marked ✓ if the
Candidate passed it or ✗ if not. Then it gives the totals and the score. It
does not hide differences the Candidate considers intentional.

A default Run against Pumpkin produced this Report:

```
Running tests against pumpkin nightly 4426d11 (sha256 b8382a8a…)
✓ status/basic/status_response.description (network traffic only)
✓ status/basic/status_response.description.text
✓ status/basic/status_response.enforceSecureChat (network traffic only)
✓ status/basic/status_response.favicon (network traffic only)
...
✗ status/with-player/login_finished.profile.uuid
...
36 passed, 10 failed. (78.2%)
Took 89.5 s
```

The first line names the Candidate's Adapter and the exact build tested:
its version, its commit where the publisher names one, and the start of
the file's sha256.

Each line after that is one test case of one Group, in the order the
Groups were played. It starts with ✓ or ✗, then the Group id and the test
case name joined by `/`. A test case that two Groups compare has a line in
each, but only one per Group, however many repetitions or values
differed.

The last two lines are the totals with the score, and the total Run time
in seconds.

## Score

The score is the share of scored test cases that passed. The goal is that
a Candidate scoring 100% plays like vanilla, and the suite grows toward
it. Today's score covers only the test cases mscts has so far, and only
those of the Groups this Run played. It counts a test case that differs
only in network traffic as passing.

A test case fails if it differs in gameplay in any repetition. Each field
of a packet vanilla sent is a test case, so a Candidate that leaves a
packet out, stops before sending it, or sends it so that it does not
decode, fails each of its fields, as if it had sent them all wrong. The
same holds for a value that holds others,
such as the `players` of a status response: a Candidate that leaves it
out, or sends something else in its place, fails each value inside it,
an empty list or object included. Copies of a packet share its test
cases, so if vanilla sends a packet more often than the Candidate, every
field of that packet fails, even in the copies that matched. The score is
rounded down to one decimal, so only a Run where every scored test case
passes shows 100%. If no test case was scored, the line has no score.

The totals line counts the lines that passed and failed, and how many of
the failed were not tested, then gives the score, such as `0 passed, 3
failed (1 not tested). (0%)`. Errors are not scored, so they get a line
of their own after it, such as `1 error (not scored)`. [Skipped or failed
Groups](#skipped-or-failed-groups) says which lines count how.

## Test cases

Every value mscts compares is a test case, named after its packet and
where the value is in it. `status_response.players.max` is the `max` value
inside `players` in the status response. Every line in the Report
shows the name of its test case. [Test cases](/reference/test-cases)
describes each one.

- `[]` stands for any element of a list, so all the elements share one test
  case: `status_response.players.sample[].name`. The Report lists the test case once per Group.
- Repeats of a packet share one test case too, so a name is the same in
  every run.
- A key that is not a plain word is written as a quoted string in
  brackets, such as `["a.b"]`.
- A packet compared as a whole is the test case of its name, such as
  `hurt_animation`. That is a packet only one server sent, or one mscts
  has no schema for, so it compares the bytes.
- A packet name that vanilla uses in more than one protocol state starts
  with the state: `configuration:keep_alive`, `play:keep_alive.id`.
- The status response is one piece of JSON text, so its test cases are
  named from inside the JSON: `status_response.description`.

A value that a Mask hides, such as a sound's random seed, is not a test
case, unless one server leaves it out.

In each Group, a test case is identical, different in network traffic
only, or different. A network traffic difference belongs to the test case
of the value as it was sent. When Pumpkin sends the description
`{"text": "mscts"}` for vanilla's `"mscts"`, `status_response.description`
is different in network traffic only, and
`status_response.description.text`, the text a player reads, is
identical.

## Network traffic differences

The test cases marked `(network traffic only)` in the Pumpkin example
pass: their bytes differ, but the vanilla client decodes both to the same
thing. The Report marks them because a server developer may want to match
vanilla byte for byte. `--verbose` shows their values.

In a chunk, mscts shows a section's palette with its ids in ascending
order, and its packed data to match, rather than as the server sent
them. Vanilla itself sends the same section with its palette in
different orders, so that order is not compared.

Vanilla omits `enforceSecureChat`, `favicon` and `players.sample` in this
response. Pumpkin sends `true`, `null` and `[]`, respectively. Vanilla's
own key is `enforcesSecureChat`, with an `s`. The client never reads a key
spelled `enforceSecureChat`, so Pumpkin's value decodes as if that key
were absent.

mscts calls a difference network traffic only where a hand-written rule
says the formats mean the same. Each rule comes from reading vanilla's
own decoding code. Today these rules cover the server list answer. Every
other difference counts as gameplay until a rule proves otherwise.

## Skipped or failed Groups

A Group with no test cases to list has one line of its own: its id and
its reasons. This example is rendered from illustrative Report inputs:

```
Running tests against pumpkin
✗ status/basic/status_response.players.max
✗ status/ping/status:pong_response.timestamp
✗ join/basic Not tested: prerequisite status/basic was mismatch
0 passed, 3 failed (1 not tested). (0%)
Took 41 s
```

`Not tested` means a prerequisite did not pass, or the Candidate lacks a
command the Group needs, such as `/tick`. A prerequisite passes when each
of its test cases passes and it has no line of its own. So a prerequisite
that differs only in network traffic passes. No shipped Group has a
prerequisite yet. `Error` means mscts or vanilla
failed. `Candidate failed` means the Candidate broke the protocol, sent a
frame that did not decode, sent a value mscts could not compare with
vanilla's, closed the connection, did not answer in time, or still had
players online from the Group before. If this happens while
mscts waits for the players of the Group before to leave, it does not
play the Group. If the Candidate's world stays frozen after a Group,
mscts plays no later Group, and each of them fails as `Candidate failed`.
Different packet counts for a Bot also give the Group a
line.

The line names each distinct reason from the Group's repetitions once. It
counts as one test case: a failing one, unless every reason is an `Error`.
Then the line is marked `!` instead of ✗ and is not scored, because the
fault lies with mscts or vanilla, not the Candidate. A Group the Candidate
failed also fails each test case that vanilla's play of it has in any
repetition. So a Candidate that crashes, or sends something mscts cannot
compare, never scores better than one that sends every value wrong. If
the Group was never played, because the Candidate still had players
online from the Group before in every repetition, its line is all that
fails.

## Total time

The clock starts after both Installations have been resolved, before the
working directories are created. It stops after both servers have stopped
and those directories have been removed. Install prompts and downloads
are excluded. Seconds are rounded to tenths, with whole seconds shown
without a decimal point.

Groups still record Measurements such as `status.rtt`, and the Run records
`instance.startup`. The default Report keeps the final total and leaves
those Measurements in the Run result.

## Verbose values and Group times

Add `-v` or `--verbose` to see both values below each test case that
differs, and the Reference, Target and repetitions at the top:

```sh
uv run mscts run --candidate pumpkin --group 'status/[bp]*' --verbose
```

```
Running tests against pumpkin nightly 4426d11 (sha256 b8382a8a…)
  Reference    vanilla 26.3 (sha256 d052f14d…)
  Target       Minecraft 26.3 (protocol 777)
  Repetitions  5 of each group
✓ status/basic/status_response.description (network traffic only)
  vanilla sends "mscts", pumpkin sends {"text": "mscts"}
✓ status/basic/status_response.description.text
✓ status/basic/status_response.enforceSecureChat (network traffic only)
  vanilla leaves it out, pumpkin sends true
...
Group times
  status/basic 0 s
  status/ping 0 s
19 passed, 0 failed. (100%)
Took 16.7 s
```

The installed version names the exact build tested: its version, its
commit where the build names one, and the start of the sha256 of the
verified file. A server's own status version can claim something else, so
it never supplies this header. Without installation provenance, the header
says `installed version unknown`.

Identical differences from repetitions appear once; distinct values stay
under the same line. A value that failed because the Candidate left out
or replaced the packet or value holding it has no values of its own:
they are under the line of the packet or value that holds it. List values also name their element's path.
Missing values say `leaves it out`; `null` remains a value. Binary values
use hexadecimal, and UUIDs use their usual string form. Inside a composite
value, binary data is written as `{"bytes": "<hex>"}`. A packet mscts
could not read is compared byte by byte and shown in hexadecimal: 256 of
its bytes, with how many come after them, such as `(257 more bytes)`. These
are its first 256 bytes, unless both servers sent more than 256 bytes. Then
both start just before the first byte that differs, after a count such as
`(576 bytes before)`. An entity spawned before the compared part is written by its type and where the client
first saw it, such as `"pig@(1.5, -60.0, 7.5)"`; a masked position reads
`<masked>`, as in `"pig@(<masked>, -60.0, 7.5)"`, and -0.0 is written 0.0.
A player spawned then is written `"player <uuid>"`. If such an entity has
another type or position on the two servers, the difference shows as
`<packet>.entity_id` on each packet about that entity. Any other entity id
is written `"#<n>"`: the n-th entity in what mscts compared for that Bot.
An entity removed before the Bot heard of it is written `"#?"`.
The UUID of an entity that is not a player is written the same way,
counted on its own.

Each Group's time adds all repetitions, playing both servers and comparing
their Transcripts. It excludes starting and stopping Instances, which the
final total includes. A skipped Group says `not played`. Older Report
inputs without durations say `not recorded`.

## Report files

`mscts run --out DIR` also writes the Report into two files in `DIR`.

`report.md` is the printed Report as Markdown. Its first line is a
heading, and test case names and values are code. Like the printed
Report, it has the header, values and Group times only with `--verbose`.
A Run of `status/basic` and `status/ping` against Pumpkin wrote:

```md
# Running tests against pumpkin nightly 4426d11 (sha256 b8382a8a…)

- ✓ `status/basic/status_response.description` (network traffic only)
- ✓ `status/basic/status_response.description.text`
...

19 passed, 0 failed. (100%)\
Took 13.3 s
```

`report.json` is the whole Report, with or without `--verbose`, but for the
differences a Verdict leaves out (see `results` below). Its keys
are `target`, `reference`, `candidate`, `lines`, `totals`,
`results`, `notes` and `elapsed_s`. `lines` has one entry for each test
case of each Group and one for each Group's own line. `totals` counts
them, with the score as a fraction of 1, or `null` if no test case was
scored:

```json
...
  "lines": [
    {
      "group_id": "status/basic",
      "test_case": "status_response.description",
      "result": "pass",
      "network_traffic_only": true
    },
...
  "totals": {
    "passed": 19,
    "failed": 0,
    "not_tested": 0,
    "errors": 0,
    "scored": 19,
    "score": 1.0
  },
...
```

A `result` is `pass`, `fail`, `not tested` or `error`. A Group's own line
has its `reasons` instead of a `test_case`.

`results` has one entry per Group, with each repetition's
Verdict, its differences with both values, and each server's
Measurements. A Verdict keeps at most 20 differences of one test case, and
its `omitted` counts the ones it left out. Without that limit, a default
Run against Pumpkin wrote an 88 MB file, almost all of it the elements of
one tag list. A difference past the 20 stays if it is the first of its test
case with its kind, observability and kind of value, so the lines and the
score read the same. A difference of a Group itself is never left out. The
printed Report and `report.md` are not cut short, but the values a verbose
Report reads from a `report.json` are the stored ones. A Run of the first
two Groups wrote this, among its other differences:

```json
...
  "results": [
    {
      "group_id": "status/basic",
      "verdicts": [
        {
          "group_id": "status/basic",
          "outcome": "mismatch",
          "divergences": [
...
            {
              "bot": "status",
              "index": 0,
              "kind": "field",
              "packet": "minecraft:status_response",
              "path": "json_response.enforceSecureChat",
              "reference": {
                "absent": true
              },
              "candidate": true,
              "test_case": "status_response.enforceSecureChat",
              "observability": "network traffic"
            },
...
```

The default Run also played `status/with-player`. Its first Verdict stored
141 differences, the first the player's UUID, and left out 35,282:

```json
...
      "group_id": "status/with-player",
      "verdicts": [
        {
          "group_id": "status/with-player",
          "outcome": "mismatch",
          "divergences": [
            {
              "bot": "player",
              "index": 1,
              "kind": "field",
              "packet": "minecraft:login_finished",
              "path": "profile.uuid",
              "reference": {
                "uuid": "b1033201-7292-3cac-9bf0-2059ac139adc"
              },
              "candidate": {
                "uuid": "cdb59355-f3ba-2939-77fc-0945fb85f118"
              },
              "test_case": "login_finished.profile.uuid",
              "observability": "gameplay"
            },
...
          ],
          "omitted": 35282,
          "detail": "",
...
```

Values are JSON where JSON can hold them. Any other value is an object
with one key:

- `{"absent": true}`: the server left the value out.
- `{"bytes": "<hex>"}`: binary data.
- `{"uuid": "<uuid>"}`: a UUID.
- `{"float": "nan"}`, `{"float": "inf"}` or `{"float": "-inf"}`: a number
  JSON cannot write.

An object a server sent whose only key is one of these, or `dict`, is
written inside `{"dict": ...}`, so it never reads as one of them.

In Python, `mscts.report_json.loads` reads a `report.json` back into the
Report mscts wrote, with up to 20 differences of a test case in each Verdict
and the rest counted in `omitted`. It ignores `lines` and `totals`, which
follow from `results`, and reads a file with no `omitted`, written before the
limit, as one that left nothing out.
