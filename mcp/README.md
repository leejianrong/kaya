# kaya MCP server

A thin adapter over `kaya-client`, so `fields` and truncation exist on day one by construction
rather than by being retrofitted ([ADR 0004](../docs/adr/0004-shaping-lives-in-the-shared-client.md)).
KAN-569 stood the server up: `src/kaya_mcp/server.py` holds one `MCPServer` instance and six
`@server.tool()` registrations, `src/kaya_mcp/tools.py` holds the one-client-call-each bodies, and
`src/kaya_mcp/errors.py` holds the one failure this package invents for itself. This is a running
server, not a skeleton.

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
lands, `MCP ⊆ CLI` is true by inspection — five of the six tools call the same `KayaClient` methods
`kaya-cli` calls, and the sixth is a deliberate refusal (below) rather than a capability with nowhere
to check it against.

## The six tools, honestly

ADR 0006 froze `list_notes`, `get_note`, `create_note`, `edit_note`, `search_notes`, `get_backlinks`
before any of them existed, so they'd be written against a list rather than the list being
reverse-engineered from whatever got built. Five of the six are real today:

- `list_notes`, `get_note`, `create_note`, `edit_note`, `search_notes` each open a `KayaClient`
  session, make the one call `kaya-cli`'s equivalent verb makes, and return through `render()` — so
  `fields` and truncation are inherited rather than reimplemented, and a stale `if_updated_at` on
  `edit_note` surfaces ADR 0009's `409` (`attempted`/`stored`, both whole notes) as a structured
  tool-level failure rather than a swallowed error.
- `get_backlinks` is registered — it has to be, ADR 0006 froze it as one of the six — but **every
  call refuses**. There is no `/links`/`/backlinks` route in `backend/`, no method on `KayaClient`,
  and no CLI verb for it yet; that capability is KAN-566 (V5), blocked on KAN-562, and it hasn't
  landed at any layer. `src/kaya_mcp/errors.py`'s `BacklinksNotAvailable` is why this is a refusal
  naming KAN-566 rather than a stub returning `{"notes": []}` — an empty list would be
  indistinguishable from "this note genuinely has no backlinks," which is a fabricated answer ADR
  0006 §2's "the CLI is where new capability lands by default" rules out. This is not a bug to fix
  here; it resolves itself the moment KAN-566 gives the tool something real to call.

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

Verified against this package as of this README: 27 tests pass, ruff is clean.
