<!--
title: "Output formats"
description: Choose between human, json and toon output, narrow a read with --fields, and control text truncation.
-->

# Output formats

Three formats, one serializer in `kaya-client` that all of them go through, and two flags that
change how much comes back. If an agent is doing the reading, this page is the one that matters —
an unshaped read is where the tokens go.

## human, the default

Tab-and-space-aligned rows, with no header and no keys — the cheapest output the CLI produces, and
readable by a person and `cut`-able by a script:

```console
$ kaya note list
NOTE-12  Groceries       home/groceries.md
NOTE-3   A reading list

2 notes

help: kaya note get <ref>
help: kaya note create <title>
```

A collection ends with a summary line — `2 notes`, counting the rows actually returned rather than
your whole corpus — and, unique to `human`, up to two `help:` lines suggesting a plausible next
command with its placeholders left unfilled. Neither line is data about the payload the way the
rows above it are, so neither survives under `json` or `toon`.

An empty result is a definitive zero state rather than an empty string, which would be
indistinguishable from a crashed pipe:

```console
$ kaya note list --q "no such term"
no notes
```

## json

```console
$ kaya note get NOTE-12 --format json
{"ref":"NOTE-12","id":12,"title":"Groceries","body":"milk\neggs","path":"home/groceries.md","created_at":"2026-09-05T04:12:03+00:00","updated_at":"2026-09-05T04:12:03+00:00","team_id":null}
```

Compact — no `indent=2` — because `json` is the format a script or an agent reads, and pretty-
printing measured as 16% of a payload's token cost for whitespace nobody looks at in that path.
`--json` is a permanent alias for `--format json`; if you pass both, `--format` wins.

A list is an envelope, not a bare array — and every record here is complete, the same eight keys
`note get` returns, whether or not `--fields` narrowed what `human` shows you:

```console
$ kaya note list --format json
{"notes":[{"ref":"NOTE-12","id":12,"title":"Groceries","body":"milk\neggs","path":"home/groceries.md","created_at":"2026-09-05T04:12:03+00:00","updated_at":"2026-09-05T04:12:03+00:00","team_id":null},{"ref":"NOTE-3","id":3,"title":"A reading list","body":"","path":"","created_at":"2026-09-05T03:58:11+00:00","updated_at":"2026-09-05T03:58:11+00:00","team_id":null}],"summary":{"count":2}}
```

```bash
kaya note list --format json | jq -r '.notes[].ref'
```

not `jq '.[]'` — the rows live under `notes`, alongside `summary`.

## toon

TOON prints a uniform array's field names once, in a header, instead of repeating them on every
row — cheaper than JSON on a list, without giving up structure:

```console
$ kaya note list --format toon
notes[2]{ref,id,title,body,path,created_at,updated_at,team_id}:
  NOTE-12,12,Groceries,"milk\neggs",home/groceries.md,2026-09-05T04:12:03+00:00,2026-09-05T04:12:03+00:00,null
  NOTE-3,3,A reading list,"","",2026-09-05T03:58:11+00:00,2026-09-05T03:58:11+00:00,null
summary:
  count: 2
```

Measured against compact JSON with `o200k_base` over 40 notes
(`kaya-client/scripts/measure_toon_delta.py`): `note list` **−11.3%**, `note get` **+1.4%**. Reach
for it on a list; a single-entity read is not worse under plain `json`.

## `--fields`

Print only the columns you need — the single biggest saving on a list read, and the one flag that
behaves differently depending on what it's applied to:

```console
$ kaya note list --fields ref,title
NOTE-12  Groceries
NOTE-3   A reading list

2 notes
```

Under `human` it *widens* the visible row past the default three columns (`ref`/`title`/`path`);
under `json`/`toon` it *narrows* the payload down to exactly the named keys — a plain
`note list --format json` carries every field the API returned (eight of them, `body` included),
and `--fields ref` cuts that down to one. Same parameter, one meaning either way: a complete record
you can feed back to the API when you don't ask, and exactly what you named when you do.

```console
$ kaya note list --fields ref,title --format json
{"notes":[{"ref":"NOTE-12","title":"Groceries"},{"ref":"NOTE-3","title":"A reading list"}],"summary":{"count":2}}
```

A name the payload doesn't have is a usage error naming what's available:

```console
$ kaya note list --fields ref,nope
error	usage	unknown field 'nope' — a note has ref, id, title, body, path, created_at, updated_at, team_id	nope
$ echo $?
2
```

And it's a usage error, not a silent no-op, on a verb that answers with one record rather than a
list — see [reading notes](reading.md#one-note-in-detail) for the exact refusal on `note get`.

## Truncation

Long prose — a note's `body` — is cut to **500 characters** by default, with a hint carrying the
**true** total, in-band inside the string itself:

```
<first 500 characters of body, byte-for-byte the original — no ellipsis inserted>

(truncated, 2847 chars total — use --full to see complete body)
```

The hint travels in every format, `json` and `toon` included — an agent reading `--format json`
otherwise can't tell a 500-character note from a truncated 3,000-character one, and "a true total"
would be a promise kept only to the reader who could have counted. Only fields named as prose are
ever cut (just `body`, on a note) — never `title` or `path`, which are already schema-bounded and
short.

Turn it off for one command:

```bash
kaya note get NOTE-12 --full
```

Or change the default everywhere:

```bash
export KAYA_MAX_TEXT_CHARS=2000    # a higher cap
export KAYA_MAX_TEXT_CHARS=0       # unlimited — the same state --full resolves to
```

Cuts land on a code-point boundary, never mid-byte, but not necessarily on a grapheme-cluster
boundary — a cut can still fall between a base character and a combining accent. Fixing that fully
needs a Unicode segmentation table, which is a dependency `kaya-client` doesn't carry.

## The summary line

Every collection carries `{"count": n}` under the structured formats and a trailing `2 notes`
under `human` — both read from the same dict, so they can't drift from each other. It's the count
of the rows **actually returned**, not of your whole corpus: under `--q`, that's the count of
matches.

An entity (`note get`, `note create`, …) gets no summary at all — `count: 1` on a single record
would be the same fact on every call ever made, tokens spent to say nothing.

## Recap

```bash
kaya note list --fields ref,title           # cheapest useful read
kaya note get NOTE-12 --format toon         # structured, no key repetition
kaya note list --format json | jq -r '.notes[].ref'
kaya note get NOTE-12 --full                # complete body
```

Next: [errors and exit codes](errors-and-exit-codes.md), where the same three formats cover a
failure too.
