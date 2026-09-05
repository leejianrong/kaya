<!--
title: "Writing notes"
description: Create, edit, move and delete notes, export and import them, and the optimistic-concurrency guard on note bodies.
-->

# Writing notes

Every write goes through the same API the web UI and the MCP server use, so nothing here is
second-class. The server is authoritative: a write returns the stored note, and that's what you
should trust rather than what you sent.

## Create

The title is positional and required. A body and a path are optional flags:

```bash
kaya note create "Groceries"
kaya note create "Groceries" --body "milk, eggs" --path home/groceries.md
kaya note create "Groceries" --body-file ./groceries.md
```

`--body` and `--body-file` are mutually exclusive — pick one. There's no way to read the body from
standard input as a bare `-`: kaya's CLI never reads stdin at all, on any verb, so a script that
wants to pipe text in names a file (`--body-file /dev/stdin` costs nothing and works today).

```console
$ kaya note create "Groceries" --body $'milk\neggs' --path home/groceries.md
ref          NOTE-12
title        Groceries
path         home/groceries.md
created_at   2026-09-05T04:12:03+00:00
updated_at   2026-09-05T04:12:03+00:00

milk
eggs

help: kaya note edit <ref> --body-file <path>
```

The ref, the numeric id and both timestamps are the database's — nothing you pass in influences
any of them.

### Sharing with a team

```bash
kaya note create "Sprint retro" --team 4
```

`--team` is a plain numeric id — a team has no ref of its own — and it exists only on `create`;
there's no way to move a note into or out of a team afterwards. `pandan team list` is where you
find the id. A team you don't belong to is a `403`.

## Edit

```bash
kaya note edit NOTE-12 --title "A clearer title"
kaya note edit NOTE-12 --body-file ./updated-groceries.md
kaya note edit NOTE-12 --path archive/2026/groceries.md
```

Fields you don't name are left alone — `edit` is a partial update, not a replace. `--body ""`
clears the body deliberately; omitting `--body` entirely leaves it untouched, and those are
different requests.

!!! note "`note move` is `note edit --path`"

    ```bash
    kaya note move NOTE-12 archive/2026/groceries.md
    ```

    `move` earns its own word because "move this note" is the sentence a person says, but it is
    sugar over the identical `PATCH` request `edit --path` makes — one column changed, no link
    rewriting, no separate endpoint
    ([ADR 0008](https://github.com/leejianrong/kaya/blob/main/docs/adr/0008-note-identity.md): a
    note's identity is its ref, never its path).

### Optimistic concurrency: `--if-updated-at`

A note body is long-form prose, and two writers editing the same one under plain
last-write-wins means one of them silently loses work — no error, no notification, discovered days
later if at all. So a body write can carry a precondition:

```bash
kaya note get NOTE-12 --format json | jq -r .updated_at
# 2026-09-05T04:12:03.881903+00:00

kaya note edit NOTE-12 --body "new text" --if-updated-at 2026-09-05T04:12:03.881903+00:00
```

If the note hasn't changed since that timestamp, the write proceeds. If it has, the write is
refused whole — **nothing is written, not even a title or path change bundled into the same
call** — with a `409` carrying both the note you attempted and the note as it's actually stored,
so you can see exactly what changed and retry:

```console
$ kaya note edit NOTE-12 --body "new text" --if-updated-at 2026-09-05T04:12:03.881903+00:00
error	note_conflict	NOTE-12 has changed since you read it: stored 2026-09-05T04:19:47.220110+00:00, precondition 2026-09-05T04:12:03.881903+00:00. Nothing was written.	
$ echo $?
6
```

`arg` is blank here — the refusal's two extra details, `attempted` and `stored`, are each a whole
note object rather than a scalar, so there's nothing that fits ADR 0005's single-value `arg` slot.
Both travel in full under `--format json`, which is where a script that wants to merge
programmatically reads them from:

```console
$ kaya note edit NOTE-12 --body "new text" --if-updated-at 2026-09-05T04:12:03.881903+00:00 --format json
{"error":{"code":"note_conflict","message":"NOTE-12 has changed since you read it: stored 2026-09-05T04:19:47.220110+00:00, precondition 2026-09-05T04:12:03.881903+00:00. Nothing was written.","arg":"","attempted":{"ref":"NOTE-12","id":12,"title":"Groceries","body":"new text","path":"home/groceries.md","created_at":"2026-09-05T04:12:03+00:00","updated_at":"2026-09-05T04:12:03.881903+00:00","team_id":null},"stored":{"ref":"NOTE-12","id":12,"title":"Groceries","body":"milk\neggs\nbutter","path":"home/groceries.md","created_at":"2026-09-05T04:12:03+00:00","updated_at":"2026-09-05T04:19:47.220110+00:00","team_id":null}}}
```

`attempted` is what you were trying to write — every field you sent, plus whatever you didn't
change carried over from the stored note, and `updated_at` set to the precondition you sent (the
version you thought you were editing). `stored` is the note exactly as it is right now. Diffing
the two `body` fields is the whole of "keep mine, keep theirs, or merge by hand".

Omit `--if-updated-at` for a plain overwrite. **There is no `--force`.** The precondition is a
guarantee available to any write that wants it, not a tax on every one — the same reasoning
[ADR 0009](https://github.com/leejianrong/kaya/blob/main/docs/adr/0009-optimistic-concurrency-on-note-bodies.md)
gives for making it opt-in at the API itself.

!!! note "The guard is on `body`, not on the note"

    A title- or path-only edit is never guarded, even if you send `--if-updated-at`: a rename
    conflicts with nothing this precondition is about. Only a write that touches `body` can produce
    a `409`.

## Delete

```console
$ kaya note delete NOTE-12
ref      NOTE-12
deleted  true

help: kaya note edit <ref> --body-file <path>
```

The ref is never reused, so a later `note get NOTE-12` is a `404` forever. **There is no `--yes`
and nothing here ever prompts** — every verb in this CLI answers structurally rather than asking a
question, which is what lets a script run `note delete` in a pipeline with no confirmation to
suppress.

## Export and import

`note export` writes one note to a markdown file with front matter, and `note import` reverses it:

```bash
kaya note export NOTE-12 --out groceries.md
kaya note import groceries.md
```

A fresh ref is always minted on import — kaya's ref allocator is a Postgres sequence, not
application code, so it can't accept a caller-chosen one — but the file's own `kaya_ref` (if it has
one) comes back as `imported_from_ref`, so you can see what it used to be called. `title`/`path`/
`body` come from the front matter when present; failing that, a title comes from an H1 heading or
the filename, and the note is unfiled.

For a whole vault at once:

```bash
kaya export-all ./vault      # every note you own, one file per note
kaya import-all ./vault      # every *.md file under the directory, recursively
```

`import-all` walks files in any order — `[[Title]]` links are resolved against the whole batch as
it's created, so a link named before its target has been walked is simply unresolved until the
target arrives, the same reconciliation an ordinary edit already gets.

## Recap

```bash
kaya note create "Groceries" --body "milk, eggs" --path home/groceries.md
kaya note edit NOTE-12 --title "Weekly groceries"
kaya note move NOTE-12 archive/2026/groceries.md
kaya note edit NOTE-12 --body "new text" --if-updated-at <the updated_at you read>
kaya note delete NOTE-12
```

Next: [Output formats](output-formats.md) for how much of this comes back and in what shape, or
[errors and exit codes](errors-and-exit-codes.md) for handling a `409` or anything else in a
script.
