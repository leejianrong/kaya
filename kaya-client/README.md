# kaya-client

The shared core. Two in-tree adapters consume it — [`kaya-cli`](../kaya-cli/) and
[`mcp`](../mcp/) — and **neither of them is allowed to shape a payload**
([ADR 0004](../docs/adr/0004-shaping-lives-in-the-shared-client.md)).

Two things live here:

- **`KayaClient`** over httpx — the only thing in the suite that speaks to `/api/v1`. Its methods
  return a `Payload`, never a response body.
- **`render(payload, *, fields=None, text_limit=500, fmt="human") -> str | dict`** — the one seam.
  Four composable steps in ADR 0004's fixed order, one module each:

  ```
  projection  →  truncation  →  aggregate attachment  →  serialization
  projection.py  truncation.py  aggregates.py           serialization.py
  ```

```bash
uv sync --all-extras
uv run pytest -q
uv run ruff check .
```

## What is and is not implemented

**KAN-540 (V2a) implements the `fmt` dimension only**, per ADR 0005's sequencing rule: the
signature lands before the behaviour goes inside it.

| | Today |
|---|---|
| `fmt` | `human`, `json`, `data`. `toon` is KAN-541's and is simply not registered yet |
| `fields` | Accepted, shape-validated, **no-op**. Vocabulary checking is V2b |
| `text_limit` | Accepted, shape-validated, **no-op**. `0` will mean `--full` |
| `summary` | Never attached. `Shaped` already carries the slot |
| Verbs | `list_notes()`, `get_note(ref)`. The writes arrive with V2b's full verb set |

`fmt="data"` is what makes the `str | dict` return type precise: it returns the shaped dict itself
and every other format returns a string. It exists so V6's MCP adapter can hand a host
`structuredContent` without `json.loads(render(..., fmt="json"))` — a shaping decision leaking out
of this package one careless line at a time.

If a V2b-or-later change needs to alter `render`'s signature, that is a sequencing failure, not a
reason to push through — `src/kaya_client/render.py`'s docstring argues requirement by requirement
why each of V2b's build-plan items lands on it unmoved.

## Why this package exists at all

Pandan put shaping in its CLI, so its MCP adapter inherited none of it: one `list_cards` call costs
44,902 tokens there against 2,689 for the equivalent CLI read. Kaya puts the shaping one layer down
so both adapters get it by construction. A projection or truncation rule appearing in `kaya-cli/`
or `mcp/` is a bug, not a local optimisation.

The rule has a mechanical edge here rather than a cultural one: `render` raises `TypeError` on a
raw `dict`, and `KayaClient` has no method that returns one. An adapter that wanted to shape a
payload locally would first have to unpack a `Payload` to get at the records, which is a visible
thing to do in review — unlike calling `.json()` on a response, which is not.

See also [ADR 0005](../docs/adr/0005-born-agent-conformant.md) for why the signature lands a slice
before the behaviour.
