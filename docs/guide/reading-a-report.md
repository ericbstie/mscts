# Reading a Report

A Report is a list of every difference mscts found between vanilla and the
Candidate. It does not grade the Candidate or hide differences the Candidate
considers intentional. It shows what differed, where, and how often.

The Report has up to eight sections. Empty sections are left out.

## Header

```
mscts Report
  Reference    vanilla (its status says version "26.3")
  Candidate    pumpkin (its status says version "26.3")
  Target       Minecraft 26.3 (protocol 777)
  Repetitions  5 of each group
```

Each server's line quotes the version name its own status response gave.
**Repetitions** is the `--repeat` value.

## Summary

The first line counts the Groups by outcome, and the second counts the
test cases the same way. When no difference is one a player would notice, a
third line says so:

```
2 groups: 2 different in network traffic only.
10 test cases: 6 identical, 4 different in network traffic only.
No difference a player would notice was found.
```

If nothing differed at all, the summary is one sentence:
`No differences from vanilla were found in the 10 test cases of the 2 groups run.`

## Test cases

Every value mscts compares is a test case, named after its packet and
where the value is in it. `status_response.players.max` is the `max` value
inside `players` in the status response. Every difference in the Report
starts with the name of its test case.

- `[]` stands for any element of a list, so all the elements share one test
  case: `status_response.players.sample[].name`. The entry says which
  element differed.
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

A value that a Mask excludes, such as an entity id, is not a test case.

Each test case is identical, different, or different in network traffic
only. One that is different in any Group or any run counts as different.
A network traffic difference belongs to the test case of the value as it
was sent. When Pumpkin sends the description `{"text": "mscts"}` for
vanilla's `"mscts"`, `status_response.description` is different in
network traffic only, and `status_response.description.text`, the text a
player reads, is identical.

## Differences a player would notice

This section lists gameplay Divergences under their mechanic, then under
their Group. The mechanic is the first part of the Group id, so `status/ping`
falls under "Server list ping (status)". An illustrative entry:

```
Differences a player would notice
---------------------------------
  Server list ping (status)
    status/basic
      - status_response.players.max: vanilla sends 20, pumpkin sends 100
```

Each entry names its test case, then both values. Values longer than 80
characters are cut and show their full length. When the field is in a list,
the entry also says which element differed:
`status_response.players.sample[].name (at json_response.players.sample[2].name)`.
A packet compared byte for byte ends in `(the whole packet)`. Other entry
shapes:

- `the Candidate failed: ...` when the Candidate broke the protocol, sent a
  frame that did not decode, closed the connection, or did not answer in
  time.
- `<packet>: vanilla sends this packet, pumpkin does not`, and the reverse.
  The packet name is the test case.
- `bot 'status' exchanged 4 packets with vanilla, 3 with pumpkin` when the
  two conversations have different lengths.

An entry that appeared in only some runs ends with `(in 2 of 5 runs)`.

## Network traffic differences

```
Network traffic differences (a vanilla client reads both alike; not counted in scores)
--------------------------------------------------------------------------------------
  Server list ping (status)
    status_response: 4 values are sent differently, e.g.
      - status_response.description: vanilla sends "mscts", pumpkin sends {"text": "mscts"}
      - status_response.enforceSecureChat: vanilla leaves it out, pumpkin sends true
      - status_response.favicon: vanilla leaves it out, pumpkin sends null
      - status_response.players.sample: vanilla leaves it out, pumpkin sends []
```

These values differ in bytes but decode to the same thing in the vanilla
client. mscts collects them per packet and shows up to five examples for
each packet, then `and N more`. They do not count against the Candidate. They
are listed because a server developer may still want to match vanilla
byte for byte.

`vanilla leaves it out` means vanilla omitted a key that the Candidate sent.
Vanilla's own key is `enforcesSecureChat`, with an `s`. The client never
reads a key spelled `enforceSecureChat`, so Pumpkin's value decodes as if the
key were absent, exactly like vanilla's.

### What counts as network traffic

mscts calls a difference network traffic only where a hand-written rule says
the two formats mean the same. Each rule comes from reading vanilla's own
decoding code. Today there are rules only for the server list answer and the
tag lists sent while joining. Every other difference counts as gameplay, even
one that only changes how the same thing is sent, such as a compressed
payload. A difference in the gameplay section can therefore turn out to be
network traffic once a rule for it exists.

## Not judged, or not the same every run

```
Not judged, or not the same every run
-------------------------------------
  join/basic was not played (blocked): prerequisite status/basic was mismatch
  status/ping was different in 2 of 5 runs
```

This section lists Groups that mscts skipped (`blocked`), because a
prerequisite did not match or because the Candidate does not have a command
the Group sets up the world with (`needs /tick`, for example). It also lists
Groups it could not judge because mscts or vanilla failed (`error`), and
Groups that had a gameplay difference in some runs but not in others. A Group that differs only some of the time often points
to a race or a timing-dependent path in the Candidate.

## Timings

```
Timings (ms)
------------
  measurement       vanilla median    p95  pumpkin median   p95  n
  status.rtt                  1.41   3.18            0.27  0.48  5
  instance.startup           9,987  9,987              39    39  1
```

Each row is one Measurement, in milliseconds, with the median and p95 for
each server. `n` is the number of samples, or `reference/candidate` if the
two differ. `instance.startup` is measured once per server, from launch
until the server answers a status ping.

mscts measures on the client side, so the numbers include loopback latency
and the Bot's own decoding. Both servers pay the same cost. Compare the two
columns with each other, not with numbers from another machine.

A Group that was not played measures nothing. The table says which ones
those were.

## Notes and legend

**Notes** lists what this Report leaves out, such as file output that is not
built yet. **How to read this** defines gameplay and network traffic in the
Candidate's name, and says what a test case is:

```
How to read this
----------------
  gameplay: a vanilla client would read pumpkin's value differently from vanilla's, so a player could notice it.
  network traffic: the bytes differ, but a vanilla client decodes both to the same thing, so no player could notice it.
  test case: one value mscts compares, named after its packet and where it is in it (status_response.description); [] stands for any element of a list.
```
