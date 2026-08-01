# kaya-client

The shared core. Two in-tree adapters consume it — [`kaya-cli`](../kaya-cli/) and
[`mcp`](../mcp/) — and **neither of them is allowed to shape a payload**
([ADR 0004](../docs/adr/0004-shaping-lives-in-the-shared-client.md)).

Empty of logic today. KAN-531 creates the package; V2a fills it with `KayaClient` over httpx and
the `render(payload, *, fields, text_limit, fmt)` seam that carries projection, truncation,
aggregate attachment and human/json/toon serialization.

```bash
uv sync --all-extras
uv run pytest -q
uv run ruff check .
```

## Why this package exists at all

Pandan put shaping in its CLI, so its MCP adapter inherited none of it: one `list_cards` call costs
44,902 tokens there against 2,689 for the equivalent CLI read. Kaya puts the shaping one layer down
so both adapters get it by construction. A projection or truncation rule appearing in `kaya-cli/`
or `mcp/` is a bug, not a local optimisation.

`render()`'s signature lands complete in V2a and behaviour fills in during V2b
([ADR 0005](../docs/adr/0005-born-agent-conformant.md)). If a V2b-or-later change needs to alter
the signature, that is a sequencing failure, not a reason to push through.
