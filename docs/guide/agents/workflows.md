<!--
title: "Agent workflows"
description: A few worked examples -- search then read, following a wikilink to a card, and checking backlinks -- with the MCP call and its CLI equivalent side by side.
-->

# Agent workflows

A few small patterns, each shown as an MCP tool call with the CLI invocation that does the same
thing underneath it. Every tool and verb below is real — see
[`mcp/README.md`](https://github.com/leejianrong/kaya/blob/main/mcp/README.md) for the complete
tool-to-verb mapping and the test that pins it.

## Search, then read the note in full

Search narrows to candidates; a full read is one more call, on the note you actually want:

```
search_notes(q="cursor pagination", fields=["ref", "title"])
```

```bash
kaya note list --q "cursor pagination" --fields ref,title
```

Both make the same API call — there's no separate search endpoint. `search_notes` and `list_notes`
share one client method, with `q` forwarded. Once you have the ref:

```
get_note(ref="NOTE-12")
```

```bash
kaya note get NOTE-12
```

`get_note` takes no `q` — it's one full record, not a narrowed list. `fields` still applies, but a
search term wouldn't mean anything on a single ref.

## Follow a wikilink to a pandan card

A note's body can hold a `[[KAN-591]]`-style wikilink into pandan. Reading the raw note tells you
the link is there:

```
get_note(ref="NOTE-12")
```

Resolving it — turning that bracketed text into a confirmed pandan card, with its title and
column — is the CLI's `links` verb, and **it has no MCP tool**. Only the reverse direction,
backlinks, made ADR 0006's frozen six; forward-link resolution didn't. If your host can shell out
alongside its MCP tools, that's the one gap this covers:

```bash
kaya links NOTE-12
```

That's a stated limit of the frozen tool set, not an oversight — `MCP ⊆ CLI`, and this is one of the
verbs the CLI side still has that the six tools don't. See
[`mcp/README.md`](https://github.com/leejianrong/kaya/blob/main/mcp/README.md) if you're deciding
whether a gap like this one matters for what you're building.

## Check what links back

The reverse direction — what points *at* this note — is a tool, because it's answered entirely from
kaya's own database and needs no round trip to pandan:

```
get_backlinks(ref="NOTE-12", fields=["ref", "title"])
```

```bash
kaya backlinks NOTE-12 --fields ref,title
```

`get_backlinks` returns the same shape a plain list does — a `notes` array and a `summary.count` —
because `/backlinks` answers with the same collection a `list_notes` call would, just filtered to
notes that reference this one by id rather than by title. Renaming the target note never breaks an
existing backlink, for exactly that reason.

## Write a note, then confirm it landed

```
create_note(title="Groceries", body="milk\neggs", path="home/groceries.md")
```

```bash
kaya note create "Groceries" --body $'milk\neggs' --path home/groceries.md
```

The tool echoes back the whole note it just wrote. There's no `fields` argument to narrow it,
because there's nothing to project before the write happens — what comes back is exactly what you
asked for.

## Recap

| Task | MCP tool | CLI verb |
| --- | --- | --- |
| Search | `search_notes` | `kaya note list --q` |
| Read one note | `get_note` | `kaya note get` |
| Follow a wikilink to a card | *(no tool)* | `kaya links` |
| Check what links back | `get_backlinks` | `kaya backlinks` |
| Write a note | `create_note` | `kaya note create` |

Next: back to the [tool reference](mcp-tools.md), or
[`mcp/README.md`](https://github.com/leejianrong/kaya/blob/main/mcp/README.md) for the full picture
of what MCP does and doesn't cover.
