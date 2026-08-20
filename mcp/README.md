# kaya MCP server

A thin adapter over `kaya-client`, so `fields` and truncation exist on day one by construction
rather than by being retrofitted ([ADR 0004](../docs/adr/0004-shaping-lives-in-the-shared-client.md)).
KAN-569 stood the server up: `src/kaya_mcp/server.py` holds one `MCPServer` instance and six
`@server.tool()` registrations, and `src/kaya_mcp/tools.py` holds the one-client-call-each bodies.
This is a running server, not a skeleton.

There used to be a third module, `src/kaya_mcp/errors.py`, holding the one failure this package
invented for itself — the refusal `get_backlinks` raised while `/links`/`/backlinks` had landed at no
layer. KAN-964 deleted it: KAN-566 landed all three layers, so the refusal was no longer an honest
sequencing gap. **This package now invents no failure of its own**, which is what ADR 0004's arrow
predicts of a thin adapter — every failure a tool can raise is a `kaya_client` one.

## The direction: `MCP ⊆ CLI`

**This is the one place that states it.** Every other document in this repo links here rather than
restating it — that duplication is exactly what let pandan's packaged skill claim complete tool-for-
tool coverage in bold while a `curl` workaround for a missing CLI verb sat forty lines below it, and
the false claim nearly justified deleting a working MCP surface from a roadmap card. See
[ADR 0006](../docs/adr/0006-mcp-surface-born-narrow.md) for the full reasoning and the numbers
behind it — pandan's own unnarrowed `list_cards` read costs 44,902 resident tokens, falling to 7,204
once projected to five fields (ADR 0004), which is the ~84% saving kaya's tools inherit from
`render()` by construction rather than as a follow-up.

Every MCP tool has a CLI verb behind it — deliberately the inverse of pandan's `MCP ⊇ CLI`, which is
how pandan ended up with four MCP capabilities no CLI command could reach and a surface that became
impossible to retire. In kaya, the MCP server is always removable, and a single exec-`kaya` tool
stays available as a future simplification rather than being blocked on closing gaps.

Two tests hold today's half of that: `tests/test_frozen_tool_set.py` pins `kaya_mcp.TOOL_NAMES`
against the six names ADR 0006 froze, and `tests/test_server.py` pins the *running server's*
registrations against that same tuple, so a stray seventh tool or a missing decorator fails before
anything else notices. What isn't built yet is the other half of the direction: a test asserting
that every one of those six names has a corresponding CLI verb. That's KAN-570
(`FROZEN_TOOLS`/`FROZEN_TOOL_COUNT` plus the parity test itself), still `todo` on the board. Until it
lands, `MCP ⊆ CLI` is true by inspection — all six tools call the same `KayaClient` methods
`kaya-cli` calls, and the table below is that inspection written out so the claim can be checked
rather than trusted.

| MCP tool | `KayaClient` method | CLI verb |
|---|---|---|
| `list_notes` | `list_notes()` | `kaya note list` |
| `get_note` | `get_note(ref)` | `kaya note get <ref>` |
| `create_note` | `create_note(...)` | `kaya note create <title>` |
| `edit_note` | `update_note(...)` | `kaya note edit <ref>` |
| `search_notes` | `list_notes(q)` | `kaya note list --q <term>`¹ |
| `get_backlinks` | `backlinks(ref)` | `kaya backlinks <ref>` |

¹ The only row where the tool name and the CLI word differ, and the only one where two tools share a
client method: there is no separate search call, because `GET /api/v1/notes?q=` answers with the same
`NoteList` a plain list does (KAN-558/559). Worth writing down before KAN-570, since a parity test
keyed on tool *names* would look for a `kaya search_notes` that will never exist.

**KAN-964 is why every row above names something real.** Until it landed, `get_backlinks` refused
every call, which would have let KAN-570's parity test go green over a tool that did not work — a
correct-looking pin across a set where one member was broken. Landing this first means KAN-570 pins
a set where every member functions.

## The six tools, honestly

ADR 0006 froze `list_notes`, `get_note`, `create_note`, `edit_note`, `search_notes`, `get_backlinks`
before any of them existed, so they'd be written against a list rather than the list being
reverse-engineered from whatever got built. All six are real today:

- `list_notes`, `get_note`, `create_note`, `edit_note`, `search_notes` each open a `KayaClient`
  session, make the one call `kaya-cli`'s equivalent verb makes, and return through `render()` — so
  `fields` and truncation are inherited rather than reimplemented, and a stale `if_updated_at` on
  `edit_note` surfaces ADR 0009's `409` (`attempted`/`stored`, both whole notes) as a structured
  tool-level failure rather than a swallowed error.
- `get_backlinks` does the same, as of KAN-964: `KayaClient.backlinks(ref)`, then `render()`. It is
  worth its own bullet only because of where it came from. KAN-569 had to register it — ADR 0006
  froze it as one of the six — while `/links`/`/backlinks` existed at no layer, so every call raised
  a refusal naming KAN-566 rather than a stub returning `{"notes": []}`, an empty list being
  indistinguishable from "this note genuinely has no backlinks". KAN-566 then landed the route
  (`backend/app/api/links.py`), the client method and two CLI verbs — and the refusal did **not**
  resolve itself, which is what this README claimed it would. KAN-964 is the card that noticed, and
  the lesson is the one ADR 0006 §4 is already about: a claim in the canonical place has to be
  re-read when the thing it describes changes, because nothing else re-reads it.

  Two things worth knowing about how it landed. **The signature did not move**, which KAN-569
  predicted in `server.py`'s docstring — the whole change is one function body in `tools.py`. And
  `fields`, truncation and the `{"count": n}` aggregate arrived with **no line written for them**,
  because `KayaClient.backlinks` returns the note noun, the note columns and the note prose fields:
  `/backlinks` answers with the very same `NoteList` a plain list does, so the tool is `list_notes`
  at a different URL (ADR 0004, and `kaya-client/src/kaya_client/client.py`'s `backlinks` docstring
  for the full argument).

## Watch for: a new tool needs a restart; a new field doesn't

Because the tools pass JSON straight through `render()`, a new **field** the API starts returning
shows up in a tool's response immediately, with no change on this side. A new **tool**, by contrast,
is a registration this process makes once at import time — it isn't callable by an MCP host until
the host restarts the server subprocess. If a "the tool doesn't exist" report ever shows up right
after a tool was added, check whether the host picked up the new process before chasing anything
else (ADR 0006 §Consequences).

## Commands

```bash
uv sync --all-extras
uv run pytest -q
uv run ruff check .
```

Verified against this package as of this README: 30 tests pass, ruff is clean.
