# Reading a Report

A Report lists every difference mscts found between vanilla and the
Candidate. It does not grade the Candidate or hide differences the
Candidate considers intentional.

A default Run against Pumpkin produced this Report:

```
Running tests against pumpkin
- Server list description  status_response.description
- Unused secure chat flag  status_response.enforceSecureChat
- Server list icon  status_response.favicon
- Server list player sample  status_response.players.sample
Took 22.7 s
```

The first line names the Candidate's Adapter. Each following difference
line has a [test case title](/reference/test-cases), then its name. A test
case without a title keeps just its name. Each name appears once across
all Groups and repetitions, even if several values differed.

Gameplay and network traffic differences share the list. If nothing
differed and no Group was skipped or failed, it says `No differences.`.
The final line is the total Run time in seconds.

## Test cases

Every value mscts compares is a test case, named after its packet and
where the value is in it. `status_response.players.max` is the `max` value
inside `players` in the status response. Every line in the Report
keeps the name of its test case, after its title when one is known.

- `[]` stands for any element of a list, so all the elements share one test
  case: `status_response.players.sample[].name`. The default Report lists the test case once.
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

Each test case is identical, different, or different in network traffic
only. One that is different in any Group or any run counts as different.
A network traffic difference belongs to the test case of the value as it
was sent. When Pumpkin sends the description `{"text": "mscts"}` for
vanilla's `"mscts"`, `status_response.description` is different in
network traffic only, and `status_response.description.text`, the text a
player reads, is identical.

## Network traffic differences

The four differences in the Pumpkin example are network traffic:
their bytes differ, but the vanilla client decodes both to the same thing.
They stay in the list because a server developer may want to match
vanilla byte for byte. Compliance scores exclude them.

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

After the test cases, the Report names any Group it could not compare,
with its reason. This example is rendered from illustrative Report inputs:

```
Running tests against pumpkin
- Player limit  status_response.players.max
- Server list ping response  status:pong_response.timestamp
- Not tested: prerequisite status/basic was mismatch  join/basic
Took 41 s
```

`Not tested` means a prerequisite did not match, or the Candidate lacks a
command the Group needs, such as `/tick`. `Error` means mscts or vanilla
failed. `Candidate failed` means the Candidate broke the protocol, sent a
frame that did not decode, closed the connection, did not answer in time,
or still had players online from the Group before. If this happens while
mscts waits for the players of the Group before to leave, it does not
play the Group. Different packet counts for a Bot also name the Group.

A Group appears once, with each distinct reason from its repetitions.
Skipped or failed Groups never produce a misleading `No differences.`.

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

Add `-v` or `--verbose` to see both values below each difference and the
installed versions at the top:

```sh
uv run mscts run --candidate pumpkin --verbose
```

```
Running tests against pumpkin
  Reference    vanilla 26.3
  Candidate    pumpkin sha256 b8382a8af2afd0a2cab48133ed335a436a771f813823a39b8b2b9c68a2dd360e
  Target       Minecraft 26.3 (protocol 777)
  Repetitions  5 of each group
- Server list description  status_response.description
  vanilla sends "mscts", pumpkin sends {"text": "mscts"}
- Unused secure chat flag  status_response.enforceSecureChat
  vanilla leaves it out, pumpkin sends true
- Server list icon  status_response.favicon
  vanilla leaves it out, pumpkin sends null
- Server list player sample  status_response.players.sample
  vanilla leaves it out, pumpkin sends []
Group times
  status/basic 0.1 s
  status/ping 0.2 s
Took 50.5 s
```

The installed version is the Registry version or the verified binary's
sha256. A server's own status version can claim something else, so it
never supplies this header. Without installation provenance, the header
says `installed version unknown`.

Identical differences from repetitions appear once; distinct values stay
under the same test case. List values also name their element's path.
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

`report.json` is the whole Report, with or without `--verbose`. Its keys
are `target`, `reference`, `candidate`, `results`, `notes` and
`elapsed_s`. `results` has one entry per Group, with each repetition's
Verdict, every difference with both values, and each server's
Measurements. Values are JSON where JSON can hold them. Any other value
is an object with one key:

- `{"absent": true}`: the server left the value out.
- `{"bytes": "<hex>"}`: binary data.
- `{"uuid": "<uuid>"}`: a UUID.
- `{"float": "nan"}`, `{"float": "inf"}` or `{"float": "-inf"}`: a number
  JSON cannot write.

An object a server sent whose only key is one of these, or `dict`, is
written inside `{"dict": ...}`, so it never reads as one of them.

In Python, `mscts.report_json.loads` reads a `report.json` back into the
Report mscts wrote.
