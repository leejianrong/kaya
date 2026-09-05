<!--
title: "Using the CLI"
description: What the kaya CLI is, how its verbs are organised, and where to go for each task.
-->

# Using the CLI

`kaya` is a thin client over kaya's REST API. Every verb opens a session, makes one API call, and
prints what comes back — the API stays the single source of truth, and the CLI holds no shaping
logic of its own beyond turning argv into that one call.

It uses only `argparse` from the standard library, so the binary starts fast and there is nothing
to configure beyond the two settings from [get started](../get-started/index.md).

## How the verbs are organised

Notes are the thing you touch most, and they're nested under `note` rather than top level, because
`note` is the one word that says what every positional under it means:

```bash
kaya note list                       # query your notes
kaya note get NOTE-12
kaya note create "A new note"
kaya note edit NOTE-12 --title "A clearer title"
kaya note move NOTE-12 archive/2026/groceries.md
kaya note delete NOTE-12
kaya note export NOTE-12 --out groceries.md
kaya note import groceries.md
```

Two verbs about links sit at the top level, because `backlinks`' positional is not always a note
ref and the ref resolver ([ADR 0008](https://github.com/leejianrong/kaya/blob/main/docs/adr/0008-note-identity.md))
should never have to guess which kind of identifier it was handed:

```bash
kaya links NOTE-12                   # what NOTE-12 points at
kaya backlinks NOTE-12                # what points at NOTE-12
```

So do the two corpus verbs, for the same reason a directory positional isn't a note:

```bash
kaya export-all ./vault              # every note you own, one file per note
kaya import-all ./vault               # every markdown file under a directory
```

`config` is its own group, because it never opens a session — reading and writing local
configuration has to work even when there's no token yet:

```bash
kaya config show
kaya config set --api-url https://kaya-jian.fly.dev
kaya config path
```

Run `kaya --help` for the full list, or `kaya <group> --help` for one group's own help.

## The full command map

| Group | Verbs | Covered in |
| --- | --- | --- |
| Notes | `note list/get/create/edit/move/delete/export/import` | [Reading](reading.md), [Writing](writing.md) |
| Links | `links`, `backlinks` | [Reading](reading.md) |
| Corpus | `export-all`, `import-all` | [Writing](writing.md) |
| Configuration | `config set/show/path` | [Configuration](configure.md) |

## Flags every verb shares

Every verb — `note`, `config`, `links`, `backlinks`, the corpus pair — accepts the same output
flags, from one parent parser, so a verb can never be added later without them:

- **`--format {human,json,toon}`**, with `--json` as a documented alias for `--format json`.
  `--format` wins if both are given.
- **`--fields a,b,c`** projects a list read down to named columns. It's a usage error, never a
  silent no-op, on a verb that returns one record rather than a list (`note get`, `note create`, …).
- **`--full`** prints prose in full instead of cutting it at `KAYA_MAX_TEXT_CHARS` (500 by default).

All three are covered in [output formats](output-formats.md).

## What makes it agent-friendly

**Errors print on stdout, machine-readable.** One tab-separated row under `human`, or an
`{"error": {…}}` object under `json`/`toon`. Nothing important goes to stderr, so a script never
merges two streams to find out what happened.

**Exit codes distinguish causes.** `3` unauthorized, `4` forbidden, `5` not found, `6` conflict —
see [errors and exit codes](errors-and-exit-codes.md).

**Every list ends with a summary.** `2 notes` under `human`, a `summary` object under the
structured formats — precomputed over the rows actually returned, so counting them never costs a
second request.

**Results suggest what comes next.** `help: kaya note get <ref>` lines under `human` point at a
plausible follow-up command, with placeholders left for you to fill in — never a value copied from
the row above them.

**Nothing ever prompts.** There is no `input()` and no tty branch anywhere in this package
([ADR 0005](https://github.com/leejianrong/kaya/blob/main/docs/adr/0005-born-agent-conformant.md)
§contract 9), so a note body reaches the CLI as `--body`, a file (`--body-file`), or not at all —
never a question waiting on a terminal that isn't there.

## What it is not

kaya also ships an MCP server for agents that would rather call a tool than shell out. The
direction there is `MCP ⊆ CLI` — the MCP surface is a narrow, deliberately incomplete subset of
what this CLI can do, not the other way around. See
[`mcp/README.md`](https://github.com/leejianrong/kaya/blob/main/mcp/README.md) for exactly what
that subset is and the test that proves it.

## Next

<div class="grid cards" markdown>

-   **[Configuration](configure.md)**

    Where settings come from, `config set`, and the token safety rules.

-   **[Reading notes](reading.md)**

    `note list`, `note get`, full-text search, and the two link verbs.

-   **[Writing notes](writing.md)**

    Create, edit, move, delete, export/import, and optimistic concurrency.

-   **[Output formats](output-formats.md)**

    `human`, `json`, `toon`, plus `--fields` and truncation.

-   **[Errors and exit codes](errors-and-exit-codes.md)**

    The full exit-code table and how to branch on it in a script.

</div>
