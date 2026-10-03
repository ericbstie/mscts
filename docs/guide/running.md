# Running a comparison

```sh
uv run mscts run --candidate pumpkin
```

`mscts run` compares vanilla with one Candidate. It starts both servers,
plays the chosen Groups against each, stops both, and prints a Report.

## Choose Groups

`--group` takes a glob over Group ids. The default is `status/*`, which includes
`status/with-player`: it joins a player and waits 6 seconds before it asks for the
status. Each repetition of it takes about 14 seconds.

```sh
uv run mscts run --candidate pumpkin --group 'status/ping'
```

mscts adds each chosen Group's prerequisites and plays them first. If a
prerequisite does not `match`, mscts skips the Group that needs it and
reports it as `blocked`. A glob that matches nothing fails and lists the
Groups that exist. The [Group reference](/reference/groups) lists
them too.

## Choose how many repetitions

`--repeat N` plays each Group N times against the same two servers. The
default is 5.

```sh
uv run mscts run --candidate pumpkin --repeat 20
```

More repetitions give steadier timings. They also expose differences that
appear only some of the time. The Report says when a difference appeared in
fewer than all runs, for example `(in 3 of 20 runs)`.

## Output

Progress lines go to stderr. The Report goes to stdout. To save only the
Report:

```sh
uv run mscts run --candidate pumpkin > report.txt
```

The Report is plain text. To keep it as files, add `--out DIR`:

```sh
uv run mscts run --candidate pumpkin --out reports/
```

mscts creates `reports/` if needed and writes `report.json` and
`report.md` into it, replacing the files of an earlier Run. To keep two
Runs side by side, give each its own folder.
[Report files](/guide/reading-a-report#report-files) says what each
file holds.

## Exit codes

| Code | Meaning |
| --- | --- |
| `0` | The Run finished and printed a Report, whatever it found, and wrote any `--out` files. |
| `1` | mscts could not run, or could not write an `--out` file after printing the Report. The message on stderr says why. |
| `2` | The command line was invalid. |

A Run that finds differences still exits 0. An option to exit non-zero on
gameplay differences is planned.

## When a server fails to start

If a server does not become ready within 120 seconds, or exits during
startup, `mscts run` stops and keeps that server's working directory. The
error message gives the path to its console log.

## What each server gets

Both servers run from the same ServerSpec. mscts writes each Adapter's config
into a fresh temporary directory and deletes it when the Run ends. The
defaults are a flat world, seed 0, peaceful difficulty, view distance 2,
and a server description of `mscts`. See [ServerSpec](/reference/server-spec).
