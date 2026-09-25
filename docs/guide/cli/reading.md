<!--
title: "Reading notes"
description: List and search your notes, read one in detail, and follow the wikilinks between them.
-->

# Reading notes

This page covers what to ask for. [Output formats](output-formats.md) covers how to ask for less
of it.

## Listing your notes

```console
$ kaya note list
NOTE-12  Groceries       home/groceries.md
NOTE-3   A reading list

2 notes

help: kaya note get <ref>
help: kaya note create <title>
```

Newest-updated first, three columns wide by default — `ref`, `title`, `path` — with a summary
line under it and two `help:` suggestions for what to do next. An empty result is still a success:

```console
$ kaya note list
no notes
```

### Full-text search

`--q` searches title and body, ranked by relevance:

```bash
kaya note list --q "cursor pagination"
```

Omit it to list everything. A present-but-blank term is refused with `400` (exit `2`) rather than
treated as "no search" — an empty string and an absent flag mean different things, and only one of
them means "list everything".

## One note in detail

```console
$ kaya note get NOTE-12
ref          NOTE-12
title        Groceries
path         home/groceries.md
created_at   2026-09-05T04:12:03+00:00
updated_at   2026-09-05T04:12:03+00:00

milk
eggs
```

`note get` takes `NOTE-12`, `note-12`, or a bare `12` — whichever spelling you type is passed
straight to the API's one ref resolver
([ADR 0008](https://github.com/leejianrong/kaya/blob/main/docs/adr/0008-note-identity.md)) rather
than being normalised here, so a malformed identifier like `#NOTE-12` is the same `400` byte for
byte wherever you're calling from.

`--fields` narrows a *list*, not one note — it's a usage error here, naming why:

```console
$ kaya note get NOTE-12 --fields title
error	usage	fields selects columns from a list of notes, and one note is already a single record — drop it, or ask a list verb	fields
$ echo $?
2
```

Long prose (`body`) is cut to 500 characters by default; see
[output formats](output-formats.md#truncation) for the hint and `--full`.

## Following links

kaya's notes cross-link with `[[wikilinks]]`, and some of those links point at pandan cards and
epics rather than at other notes. Two verbs read that graph, both answered without you having to
parse a note's body yourself:

```console
$ kaya links NOTE-12
note   A reading list  NOTE-3                   
card   KAN-591                                  

2 links

$ kaya backlinks NOTE-12
NOTE-7   Meal planning   home/meal-planning.md

1 note

help: kaya note get <ref>
help: kaya note create <title>
```

Each row of `links` is `target_kind`, `target_ref`, `resolved_ref`, `title`, `column` — five columns,
in the API's own order, with no header line (nothing in kaya's `human` output has one). A row that
couldn't be resolved — `KAN-591` above, if pandan can't confirm it right now — comes back with the
last three columns blank rather than as an error: `links` lists what a note points *at*, resolved
against pandan with your own token when the link names a card or epic
([ADR 0003](https://github.com/leejianrong/kaya/blob/main/docs/adr/0003-cross-linking-one-way-soft.md):
nothing in kaya blocks on pandan being reachable, so an unresolved link degrades rather than fails).
It gets the summary line every collection does (`2 links`), but no `help:` suggestions — a link
row's `resolved_ref` is a note ref for some rows and not others, so `note get <ref>` would be
advice that only sometimes applies.

`backlinks` lists what points *at* this note — answered entirely from kaya's own database, so it
works with pandan down, and it's keyed on the target note's id rather than its title, so renaming
a note never breaks an existing backlink. Because the API answers `/backlinks` with the same shape
an ordinary list returns, its rows are notes, and it gets the same `help:` suggestions a
`note list` does.

## Exporting what you read

`note export` writes one note to a markdown file — front matter (`kaya_ref`, `title`, `path`, the
two timestamps), a `---` line, then the body exactly as stored:

```bash
kaya note export NOTE-12                       # writes NOTE-12.md
kaya note export NOTE-12 --out groceries.md    # or name the file
```

`export-all` does the same for every note you own, one file per note, into a directory it creates
if needed — useful as a point-in-time backup, or to hand a whole vault to something else that reads
markdown with front matter:

```bash
kaya export-all ./vault
```

Neither rewrites `[[wikilinks]]` on the way out: kaya's link syntax is already the one Obsidian
uses, so an exported note reads the same as it did in kaya.

## Recap

```bash
kaya note list                            # everything, newest first
kaya note list --q "cursor pagination"     # search
kaya note get NOTE-12                     # one note, complete unless truncated
kaya links NOTE-12                        # what it points at
kaya backlinks NOTE-12                    # what points at it
kaya export-all ./vault                   # everything, as files
```

Next: [Writing notes](writing.md) to create, edit and move notes, or
[output formats](output-formats.md) to cut a read down to the fields you actually need.
