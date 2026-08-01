# kaya MCP server

A thin adapter over `kaya-client`, so `fields` and truncation exist on day one by construction
rather than by being retrofitted ([ADR 0004](../docs/adr/0004-shaping-lives-in-the-shared-client.md),
[ADR 0006](../docs/adr/0006-mcp-surface-born-narrow.md)).

Skeleton only. KAN-531 creates the package; V6 stands the server up with a frozen tool set —
`list_notes`, `get_note`, `create_note`, `edit_note`, `search_notes`, `get_backlinks` — and the
tests that pin the tool names, the tool count, and the direction `MCP ⊆ CLI`.

```bash
uv sync --all-extras
uv run pytest -q
uv run ruff check .
```

`TOOL_NAMES` in `src/kaya_mcp/__init__.py` is the frozen set, declared now so V6 fills tools in
against a list that already exists. Adding a name is an ADR 0006 decision, not an implementation
detail, and `tests/test_frozen_tool_set.py` makes that cost visible.

The direction is `MCP ⊆ CLI`: every tool has a CLI verb behind it. Do not write "full parity" in
this repo — state the direction and cite the test.
