# ADR 0006 — The MCP surface is born narrow and frozen, and the CLI↔MCP relationship is pinned by a test

- **Status:** Accepted
- **Date:** 2026-08-01
- **Deciders:** Jian (inherited conclusions, made binding)
- **Context source:** pandan ADR 0019 in full, and the parity correction in pandan's packaged skill.

## Context

Pandan measured its MCP surface and two of the answers were the opposite of what the plan assumed. Both
carry directly into kaya, and both are the sort of thing a project re-litigates from intuition unless the
numbers are written down.

**Finding 1: tool count is not where the tokens are.** All 49 tool schemas cost **8,775** tokens resident.
One `list_cards` call against the live board returns **44,902** — 5.1× the entire schema surface, in one
result. Trimming the resident surface optimises a ~4%-of-window line item while a 22% one sits beside it
untouched. And the cost inside that payload is **field breadth**, not pretty-printing: compacting the JSON
saves 16%, narrowing to five useful fields saves 84%.

**Finding 2: a parity claim nobody checked was false, and the false claim did damage.** Pandan's packaged
skill asserted "full parity as of v0.3.0" in bold while the *same file*, forty lines below, documented a
`curl` workaround for a missing CLI verb. Verification found the relationship is one-directional —
`update_board` and `delete_board` have no CLI verb, `create_cards` (batch) has none, and `next --claim`
claims whatever is next rather than a chosen card, so it isn't an atomic substitute for `claim_card`. The
false claim was inherited into a roadmap card where it *nearly justified deleting the MCP surface*, which
under pandan ADR 0005 would have been a silent parity regression.

## Decision

### 1. Narrow reads on day one

Every MCP read tool takes a **`fields`** argument and applies truncation, from the moment it is written.
This is free under ADR 0004: the tools call `kaya-client`'s `render`, which already projects and truncates,
so the MCP adapter inherits both by construction. Pandan had to file this as a follow-up (`KAN-501`, still
in progress); kaya cannot ship the tool without it.

### 2. The surface is frozen from its first commit

A pinned **tool-name set** and a pinned **count**, asserted in a test whose failure message explains why the
pin exists and warns that a removal needs a CLI-parity check first. Adding a tool means amending this ADR,
not appending a decorator. **The CLI is where new capability lands by default**, and the MCP server follows
deliberately.

The MVP surface is six tools: `list_notes`, `get_note`, `create_note`, `edit_note`, `search_notes`,
`get_backlinks`.

### 3. Take the free schema hygiene

Strip generated `title` keys and collapse `anyOf: [{T}, {null}]` → `type: [T, null]` — a 16% resident
saving with no rename, no removal and no consumer migration. Two traps from pandan's implementation are
adopted as named guards rather than rediscovered:

- **A nullable enum must not be collapsed.** `anyOf: [{enum: [...]}, {type: null}]` accepts a member *or*
  `null`; the collapsed `{enum: [...], type: [string, null]}` **rejects null**, because `enum` constrains
  the whole value. The collapse is allow-listed to sibling keys provably inert for `null` and blocks on
  anything unreasoned-about.
- **`title` is both a JSON Schema annotation and a real argument name.** Pandan's first implementation
  recursed blindly and *deleted the `title` argument from two tools* — a behaviour change wearing a
  cosmetic disguise. The traversal is driven by JSON Schema keywords, and this case gets its own test.

The general lesson, worth keeping: *cosmetic* is a claim requiring proof, not a category exempt from it.

### 4. Parity discipline — the direction is stated once, and pinned

**The intended relationship is `MCP ⊆ CLI`.** Deliberately the *inverse* of pandan's `MCP ⊇ CLI`, and the
inversion is the point: pandan's MCP surface grew ahead of its CLI, which is what created four unreachable
capabilities and made the surface impossible to retire. In kaya, every MCP tool has a CLI verb by
construction, so the MCP server is always removable and option (b) from pandan ADR 0019 — a single
exec-`kaya` tool — stays permanently available as a future simplification rather than being blocked on
closing gaps.

Three rules enforce it:

1. **The relationship is stated in exactly one place**, `mcp/README.md`, and every other document links to
   it rather than restating it. Pandan's contradiction was possible because the claim was duplicated.
2. **A test asserts it.** For every frozen tool name, a corresponding CLI verb must exist. A new MCP tool
   without a CLI verb fails CI.
3. **Nobody writes "full parity".** The phrase is banned from this repo's docs, skill and card text. Write
   the direction and cite the test.

## Alternatives considered

| Option | Why not |
|--------|---------|
| One tool per entity with an `action` argument (~-51% resident) | Pandan authored and measured it, then rejected it: it does nothing about the payload cost, which is the actual problem, and it dissolves precise schemas into unions where nearly every argument must be optional — so the schema can no longer *tell* the model which arguments a given action needs. Cheaper context, more invalid calls, tokens spent on retries. |
| A single exec-`kaya` tool (−96% resident) | The best numbers, and blocked in pandan by parity gaps and by an image with no CLI in it. Kaya's `MCP ⊆ CLI` rule keeps this permanently open as a future option, which is why it isn't foreclosed here — just not first. |
| Skip the MCP server; tell agents to use the CLI | The MCP surface is the only entry point for a consumer without a checkout, and a typed surface gives in-schema discovery a `--help` round trip can't. Ship it narrow instead of not at all. |
| Don't freeze; let the surface grow with the API | Growth-by-default is the drift pandan's freeze was really about. Freezing at six with an explicit amendment path costs nothing and prevents the 49-tool position from being reached by accident. |

## Consequences

- **Positive:** the ~84% per-read saving that pandan measured and deferred is present from day one, and it
  arrives *free* because ADR 0004 put shaping in the client. The parity direction is unambiguous, checked
  by CI, and stated once, so it cannot rot into a contradiction. The exec-tool simplification stays
  available.
- **Neutral:** six tools is a narrow surface, and some capability will be CLI-only for a while. That is the
  correct default direction under this ADR, not a gap.
- **Negative / deferred:** the freeze adds friction to genuinely wanting a seventh tool — an ADR amendment
  for a one-line decorator. Accepted; the friction is the mechanism.
- **Watch for:** a newly added MCP *tool* isn't callable until the client restarts, whereas a new API
  *field* appears immediately since the tools pass JSON through. Worth stating in the README so a "the tool
  doesn't exist" report gets diagnosed in seconds.
