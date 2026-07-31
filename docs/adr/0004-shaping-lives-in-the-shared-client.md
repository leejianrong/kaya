# ADR 0004 — Payload shaping lives in `kaya-client`, not in the adapters

- **Status:** Accepted
- **Date:** 2026-08-01
- **Deciders:** Jian (fork F4, deviation 3)
- **Context source:** pandan ADR 0005 (API-first: the CLI and MCP server are thin adapters over one
  shared client) and pandan ADR 0019 §"Per-task cost", which measured what happens when they aren't.

## Context

Pandan is API-first and its packaging reflects it: `pandan-client` is the shared core, with
`pandan-cli` and `pandan-mcp` as adapters. The intent was right. The **placement of one seam** was not,
and it cost an order of magnitude.

Pandan's payload shaping — `--fields` projection (V42), truncation (V45), content-first rendering (V46),
and the `json`/`toon` serializer (V47) — all landed in `pandan_cli/cli.py`, in `_structured_payload` /
`_render_structured`. The MCP server calls the same `PandanClient`, but the client returns a raw dict, so
the MCP adapter inherited **none** of it and FastMCP renders that dict at `indent=2`.

The measured result, from pandan ADR 0019:

| Read against the live 121-card board | MCP | CLI | ratio |
|---|---:|---:|---:|
| `list --column todo` | 7,014 | 324 | 21.6× |
| `list` (all cards) | 44,605 | 2,689 | 16.6× |
| `epic list` | 4,796 | 476 | 10.1× |
| **total, five reads** | **61,368** | **5,405** | **11.4×** |

And the decomposition that identifies the cause: of that 44,902-token `list_cards` payload,
pretty-printing is only 16%. **Field breadth is the cost** — 1,111 null or empty values serialized across
one page. Narrowing to five useful fields takes it to 7,204.

The conclusion pandan drew, which is the one kaya inherits: *"the gap is not intrinsic to MCP. It exists
because the MCP adapter never received V42, V45, V46 or V47."* A `fields` argument on the read tools would
recover ~84%, and that is roughly ten times the saving available from any amount of resident-schema
trimming.

## Decision

**`kaya-client` owns every decision about what a payload looks like. An adapter owns only how it gets its
arguments.**

Concretely, one seam in the client:

```
render(payload, *, fields=None, text_limit=500, fmt="human") -> str | dict
```

carrying, in this order:

1. **projection** — `fields` selection, vocabulary derived from the payload's own keys so it cannot drift
   from the API,
2. **truncation** — an allow-list of prose fields, with a **true** total in the hint,
3. **aggregate attachment** — the `summary` object, attached *after* truncation so its counts are
   structurally out of the truncator's reach,
4. **serialization** — `human`, `json` and `toon` from the same shaped dict.

Every consumer goes through it:

- **The CLI** parses argv, calls a client method, calls `render`, prints.
- **The MCP server** takes the same arguments as tool parameters, calls the same client method, calls the
  same `render`, returns the string. So `fields` and truncation exist on the MCP surface **on the day it
  is written**, by construction rather than by discipline.
- **The API** does not use `render` — it returns full records, because HTTP has content negotiation and a
  browser client that wants everything. Narrowing is the *adapter's* job, and the API stays the complete
  surface both adapters project from.

**No adapter may reimplement a shaping concern.** A projection or truncation rule appearing in
`kaya-cli/` or `mcp/` is a bug, not a local optimisation, and the review question is always "why isn't
this in the client?"

## Alternatives considered

| Option | Why not |
|--------|---------|
| Shaping in the CLI, as pandan does | This is the thing being fixed. It made the MCP surface 11.4× more expensive per task and left the fix as *advice* ("prefer the CLI") rather than a mechanism. |
| Shaping in the API, so every client gets it | Conflates two audiences. The browser SPA wants the whole record; a `?fields=` API parameter is a second contract to version and test, and it pushes agent ergonomics into a surface that also serves a UI. Keep the API complete and let adapters narrow. |
| Shaping duplicated in both adapters | Two implementations of one contract drift, and the drift is silent — you find out when an agent's payload is unexpectedly large. Pandan's own experience is that a *single* shared seam is what keeps `json` and `toon` from diverging. |
| A shaping middleware between client and adapter | An extra layer for one function. The client is already the shared place. |

## Consequences

- **Positive:** the MCP surface is born with the ~84% saving pandan had to file as a follow-up (`KAN-501`,
  still in progress at the time of writing). One implementation means one set of tests covering both
  adapters, and it makes the CLI↔MCP parity claim in ADR 0006 structurally easier to keep true. A future
  third adapter gets it free.
- **Neutral:** `kaya-client` is a fatter package than `pandan-client` — it is no longer a thin HTTP
  wrapper but a wrapper plus a presentation layer. That is the trade being made deliberately, and it
  argues for the client having its own substantial unit-test suite rather than being tested through the
  adapters.
- **Negative / watch this:** `render` is a single function accumulating four concerns, which is how a
  god function starts. It is flagged as an open risk in PLAN, and V2b — when the fourth concern lands in
  it — is the slice where the seam gets examined. The mitigation is that each concern is a separate
  composable step with its own tests, not four branches in one body.
- **Now has to be true:** the API returns complete records, since it is what both adapters project from.
  An API that pre-narrows would leave the client unable to satisfy `--full`.
