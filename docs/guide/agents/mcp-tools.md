<!--
title: "MCP tool reference"
description: The six frozen kaya MCP tools, what each does, and how fields, truncation and the count aggregate apply to each.
-->

# MCP tool reference

Six tools, frozen by
[ADR 0006](https://github.com/leejianrong/kaya/blob/main/docs/adr/0006-mcp-surface-born-narrow.md)
before any of them existed: `list_notes`, `get_note`, `create_note`, `edit_note`, `search_notes`,
`get_backlinks`. Each one opens one `KayaClient` session, makes the one call its CLI equivalent
makes, and returns through the same `render()` the CLI calls on its own output. See
[`mcp/README.md`](https://github.com/leejianrong/kaya/blob/main/mcp/README.md) for the CLI verb
behind each tool, the direction that pins them together (`MCP ⊆ CLI`), and the test that proves it
(`mcp/tests/test_cli_parity.py`).

Your client namespaces the tool names by your `mcpServers` key: with the key `kaya`, `list_notes` is
really `mcp__kaya__list_notes`.

## Reading

| Tool | Arguments | What it returns |
| --- | --- | --- |
| `list_notes` | `fields?` | Every note you own, newest-updated first. |
| `get_note` | `ref`, `fields?` | One note, addressed as `NOTE-12`, `note-12`, or a bare `12` — every spelling resolves the same way ([ADR 0008](https://github.com/leejianrong/kaya/blob/main/docs/adr/0008-note-identity.md)). |
| `search_notes` | `q`, `fields?` | Notes matching `q` in title or body, ranked by relevance — the same call `list_notes` makes, with `q` forwarded. There's no separate search endpoint. |
| `get_backlinks` | `ref`, `fields?` | Notes whose body links to `ref` — the same shape a plain list returns, so `fields`, truncation and the count aggregate all apply here with nothing tool-specific written for them. |

## Writing

| Tool | Arguments | What it does |
| --- | --- | --- |
| `create_note` | `title`, `body?`, `path?` | Creates a note. |
| `edit_note` | `ref`, `title?`, `body?`, `path?`, `if_updated_at?` | Changes a note; arguments left unset are untouched. `if_updated_at` is [ADR 0009](https://github.com/leejianrong/kaya/blob/main/docs/adr/0009-optimistic-concurrency-on-note-bodies.md)'s precondition, opt-in — omit it for a plain overwrite, or pass back an earlier read's `updated_at` and get a structured `409` (`attempted`/`stored`, both whole notes) if the note has moved on. |

Neither write tool takes `fields`. There's nothing to project before the write happens, and what
comes back is exactly the note you just wrote, in full.

## `fields`, on every read

`fields` takes a JSON array of column names and narrows the result to those columns — the same
projection `kaya note list --fields ref,title,path` applies, just spelled as a list argument instead
of a comma-joined string:

```json
{ "name": "list_notes", "arguments": { "fields": ["ref", "title", "path"] } }
```

Omit it and you get every column the payload carries. It's accepted on every read tool above and on
neither write tool, matching ADR 0006 §1's literal scope: a write's `fields` would have nothing to
narrow before the request is made.

## Truncation

Long prose — a note's `body` — is cut at `KAYA_MAX_TEXT_CHARS` (500 characters by default) with a
hint saying how much was dropped, resolved the same way a CLI session resolves it: environment, then
the user config file, then the default. There's no per-call `--full` equivalent on any tool; raise
or disable the limit for the whole server process instead, in the `env` block your host launches it
with — see [MCP setup](mcp-setup.md#the-three-settings).

Applied to every tool, reads and writes alike: a note `edit_note` echoes back can hold exactly as
much prose as a `get_note` read.

## The count aggregate

Every read that returns a *list* — `list_notes`, `search_notes`, `get_backlinks` — carries a
`summary: {"count": n}` alongside its `notes` array, computed over the rows actually returned (after
`fields` and truncation, never before). `get_note`, `create_note` and `edit_note` each return one
note and carry no `summary` at all — a single record isn't a set.

## Errors

Every failure comes back as a structured tool-level error rather than a traceback: the same
`{"code", "message", "arg", …}` object the CLI's stdout row and a raw API error body both carry,
raised as the SDK's `ToolError` so a caller can read and recover from it instead of catching an
opaque exception. A stale `if_updated_at` on `edit_note` is the case worth knowing by name: its
`409` carries `attempted` and `stored` as two whole notes inside that error, not a bare message.

## Recap

- Six tools: `list_notes`, `get_note`, `search_notes`, `get_backlinks` (reads, all four take
  `fields`); `create_note`, `edit_note` (writes, neither takes `fields`).
- `fields` narrows a read to named columns as a JSON array; omit it for everything the payload
  carries.
- Truncation and the `KAYA_MAX_TEXT_CHARS` it reads are a server-process setting, not a per-call
  one.
- A list read carries `summary.count`; a single-note read or write carries none.

Next: [agent workflows](workflows.md) — a couple of worked examples using these six.
