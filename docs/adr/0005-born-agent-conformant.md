# ADR 0005 — The machine-facing contract is designed in from the first CLI slice, and the output layer's signature lands before behaviour goes inside it

- **Status:** Accepted
- **Date:** 2026-08-01
- **Deciders:** Jian (inherited conclusions, made binding)
- **Context source:** pandan Milestone 7 slices V42–V48 and V50, and the corrections recorded in each.

## Context

Pandan spent Milestone 7 retrofitting agent ergonomics onto a CLI that already existed. Seven slices:
`--fields` projection (V42), structured errors with a documented exit-code scheme (V43), pre-computed
aggregates on every list verb (V44), content truncation with true totals and `--full` (V45),
content-first bare invocation plus `help[]` next-step templates (V46), `--format {human,json,toon}` over
one serializer (V47), and ambient session context (V48).

Retrofitting is what made them expensive, and the slice records say so. V44 had to update ~40 pre-existing
assertions. V45 needed only 2, and the record notes that as *"the slice's first promise working"* — the
promise being that under-limit output stays byte-identical. Kaya can have V45's cheapness on every slice by
starting from the finished shape.

Two lessons from those records matter more than the feature list:

**The sequencing lesson.** V47 changed the output layer's *signature* — it introduced
`_structured_payload` / `_render_structured` as the one shaping-and-serializing seam. V44 and V45 then
landed "on V47's seams unmoved", which is why they were cheap. Had they landed first, each would have
been rewritten by V47. **The slice that changes the output layer's signature must come before the slices
that add behaviour inside it.**

**Errors are part of the contract.** V43's record notes it "defines the error shape the rest of Wave 2
emits, so it lands before V44–V47". An error is an output, and an output layer that only shapes successes
is half a contract.

## Decision

**Kaya's CLI is born with the finished contract, and the slice order enforces the sequencing lesson.**

### The contract

| # | Guarantee | Note |
|---|---|---|
| 1 | `--format {human,json,toon}` over **one** serializer in `kaya-client` (ADR 0004), so formats cannot drift | `--json` is a documented alias for `--format json`; `--format` wins if both are given |
| 2 | `--fields a,b,c` widens the human row on every list verb; vocabulary derived from the payload's own keys; an unknown name is a clean error naming it | Does not affect structured output, which is already complete. A usage error on single-entity verbs, never a silent no-op |
| 3 | Errors **structured on stdout**: `error<TAB><code><TAB><message><TAB><arg>`, or an `{"error": {...}}` object under a structured format, with all keys always present | Human `usage:` text still goes to stderr |
| 4 | Exit codes: `0` ok · `1` runtime · `2` usage (argparse rejected argv) · `3` 401 · `4` 403 · `5` 404 | **Pandan's scheme, adopted verbatim.** Branch on the stable `code` string, never on message text |
| 5 | A pre-computed `summary` on every list verb, describing **the returned set** — under a filter or `--limit`, the returned set, not the whole corpus | A trailing line for humans, a `summary` object for structured consumers, both from the same dict |
| 6 | Text truncated by default with a **true** total and `--full` to opt out; an allow-list of prose fields, never "any long string" | A truncated value stays a string: no key added, removed or retyped |
| 7 | Bare `kaya` prints live state and exits `0`; `--help` still prints usage | No token → a structured auth error, not a stack trace |
| 8 | Results carry `help[]` next-step **templates** with placeholders left unfilled | Every hint must parse as a real command, pinned by a test |
| 9 | No verb prompts when stdin isn't a tty | A structured failure instead of a hang |

Three of pandan's specific corrections are adopted as rules rather than rediscovered:

- **The truncation allow-list is named prose fields**, not a length heuristic. A blanket rule eventually
  cuts a `next_cursor` and silently breaks pagination, or mangles a URL.
- **`summary` is attached after truncation**, so its counts are structurally out of the truncator's reach.
- **Every `help[]` template must parse.** Pandan's spec shipped `pandan comment add <id> "…"`, which is
  not a valid command (the body needs `--body`), and the wrong form propagated into a card. The guard is a
  test that parses every emitted hint.

### The sequencing rule, made structural

Kaya's CLI arrives in **two slices, in this order**:

- **V2a — the signature.** The `render` seam in `kaya-client`, `--format`, the error shape, the exit-code
  table, and build-stamped `--version` (ADR 0007). A deliberately minimal verb set (`note list`,
  `note get`) so the slice is about the *layer*, not the breadth.
- **V2b — the behaviour inside it.** `--fields`, aggregates, truncation, content-first, `help[]`, and the
  full verb set — all landing on V2a's seam unmoved.

That split is the sequencing lesson expressed as slice boundaries rather than as advice. V2a's own
acceptance criteria include a byte-identity pin on the default human row, so V2b can prove it changed
nothing it didn't mean to.

**Exit codes are a published contract from V2a.** Do not renumber them later.

## Alternatives considered

| Option | Why not |
|--------|---------|
| Ship a simple CLI first, add ergonomics when needed | The experiment has been run. It cost pandan seven slices, ~40 rewritten assertions in one of them, and left the MCP adapter permanently behind. |
| One big "AXI-conformant CLI" slice | Violates small-and-reversible, and collapses the very sequencing distinction that makes the parts cheap. |
| Invent a cleaner exit-code scheme for a greenfield CLI | The scheme is fine and *sameness across the suite* is worth more than marginal elegance. An operator scripting both tools should never have to remember which is which. |
| Skip `toon`, since pandan measured it as a win only on uniform rows | Correct that it doesn't always pay (`get` was +2% vs compact JSON), but the flag is nearly free once one serializer exists, and note *lists* are exactly the uniform-row case where it wins. Measure and record per payload, as V47 did. |

## Consequences

- **Positive:** every later slice emits through a finished layer, so adding a verb is adding a verb.
  Under-limit output stays byte-identical by construction, which is what kept V45's test churn to two
  assertions. Suite-wide consistency: an operator or agent fluent in `pandan`'s output is fluent in
  `kaya`'s.
- **Neutral:** V2a and V2b together are more up-front work than a naive CLI, spent before there is much to
  list. That is the point, and it is cheaper here than the same work later.
- **Negative / deferred:** the contract is frozen early, so a genuine improvement to the exit-code scheme
  or the error shape is a breaking change from V2a onward. Accepted: a stable machine contract is worth
  more than the improvement, which is exactly why pandan's V43 says "do not renumber them".
- **Ambient session context** (pandan V48) is **not** in the MVP. It's real value, but it depends on
  having enough notes for ambient state to be worth injecting. Post-MVP.
