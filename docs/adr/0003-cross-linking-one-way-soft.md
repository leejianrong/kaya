# ADR 0003 — Cross-linking is a soft, one-way read: kaya → pandan, and pandan never learns kaya exists

- **Status:** Accepted
- **Date:** 2026-08-01
- **Deciders:** Jian (fork F5, decided from a written options brief)
- **Context source:** [`kaya-vision.md`](../kaya-vision.md) §"Cross-linking, both directions"; pandan
  ADR 0018 §"What is deliberately NOT renamed" (the `KAN-`/`EPIC-` prefixes), pandan M4 work-links.
- **Options brief:** <https://claude.ai/code/artifact/5d18d32d-1277-4f33-8cca-60f9548bbf09>

## Context

The vision doc describes cross-linking in both directions: `[[KAN-123]]` in a note resolving to a card,
and a card's work-links pointing back at a note, plus an eventual embedded live board view. The
question this ADR settles is not *whether* to cross-link but **which way the dependency arrow points**,
because a soft one-way reference and a live bidirectional integration are different products with
different failure modes.

Two designs were compared. A **soft one-way read**, where kaya resolves refs by calling pandan's public
API. And a **self-sufficient** design, where kaya stores the ref as text and renders a hyperlink with no
lookup at all. Both keep pandan ignorant of kaya, and in both the return path is pandan's existing M4
work-link, since a note is just a URL.

The difference: a note that renders `KAN-12 · in_progress · "MCP read tools: add a fields argument"` is
doing the job the suite exists for. A note that renders a bare hyperlink is a markdown file with a URL
in it.

## Decision

**Kaya resolves board refs by reading pandan's public API. Pandan gains nothing and knows nothing.**

### The mechanism

- **On save, parse and record.** A `[[…]]` parser extracts every wikilink and writes a `note_link` edge:
  (source note id, target kind, target ref, resolved target id or `null`). Target kinds are `note`,
  `card` and `epic`. Recording the edge is a **local** operation and never blocks on pandan.
- **Parse `KAN-` and `EPIC-`, not `PAN-`.** The ticket prefixes come from immutable Postgres sequences
  and are deliberately not renamed under the pandan brand (pandan ADR 0018). A parser looking for `PAN-`
  would match nothing that exists.
- **On render, resolve as a read.** Kaya calls pandan's card/epic read API **with the caller's own PAT**,
  so authorization is pandan's business and kaya never holds elevated access. Results are cached.
- **Note → note links resolve by title** at parse time, with the resolved id recorded, so a later rename
  doesn't break the edge (Q19, ADR 0008).
- **Backlinks** are a query over `note_link` in kaya's own database, so "which notes mention `KAN-12`"
  is answerable with pandan down.
- **The return path is pandan's existing work-links.** A note URL is a first-class link target already.
  No pandan schema change, no typed `spec` link, no webhook, no registry.

### The line that must hold

**Nothing in kaya may block on pandan.** A note must save, render, and appear in full-text search with
pandan completely down. An unresolvable or unreachable ref renders as an unresolved wikilink with a quiet
hint, never an error and never an empty page.

This is **R5.1, an acceptance criterion of the linking slice with its own mutation-tested guard**, not a
footnote. It is stated this loudly because it is the exact property that decays first: someone adds one
convenience — a sort by card column, a filter on card status, a validation that rejects a broken ref on
save — and now saving a note requires pandan to be up. Each of those is individually reasonable and
collectively fatal to the design.

### Deferred

**An embedded live board view** (Q37) is out of the MVP. It is the same read API as ref resolution, so
once this resolver exists it is a rendering slice rather than an integration slice, which is the argument
for not building it now.

## Alternatives considered

| Option | Why not |
|--------|---------|
| **Self-sufficient: store the ref, render a hyperlink, never look up** | Genuinely simpler with nothing to cache or invalidate and no failure mode to design, and it still cross-links (the URL works, `note_link` still records the edge). Rejected because the note can't show what the card *is*, which reduces the integration to a hyperlink and gives up the combined value the vision doc argues for. Kept as the fallback: if resolution ever proves troublesome, stop calling and render the stored ref. |
| **Bidirectional live sync** — kaya pushes backlink registrations into pandan, or pandan gains a typed `spec` link | Requires pandan schema and API work, a webhook or polling job, backfill, and a reconciliation story for divergence. It also points the dependency arrow both ways, so neither app can be released in ignorance of the other. Large cost for a convenience the existing work-links already approximate. |
| **Kaya keeps a synchronised copy of card state** | The worst of both: all the sync machinery above, plus a second source of truth for data pandan owns, plus staleness that looks like a bug rather than a cache. |
| Resolve with a kaya-owned service credential instead of the caller's PAT | Kaya would hold access broader than its callers, so a note could leak a card the reader can't see. Forwarding the caller's PAT makes over-disclosure structurally impossible. |

## Consequences

- **Positive:** the dependency arrow points one way for both concerns in this suite (identity, ADR 0002;
  linking, here), so pandan stays releasable in complete ignorance of its sibling. Kaya's failure modes
  are contained: with pandan down, notes are fully usable and only the ref *decoration* degrades.
  Authorization is inherited from pandan per-caller, so cross-app over-disclosure is impossible by
  construction.
- **Neutral:** kaya needs a resolution cache and an unresolved rendering state. Both are small, and the
  cache TTL is a separate knob from ADR 0002's auth cache because the tolerances differ — a stale card
  title is cosmetic, a stale identity is not.
- **Negative / deferred:** a stale cache can show a card in the wrong column, which is a real if minor
  wrongness a self-sufficient design wouldn't have. On how resolution scales, see the amendment below —
  this ADR's original answer was wrong.
- **The guard that keeps this honest:** an e2e test that stops the pandan stub and asserts a note still
  saves, renders and is findable by search. Mutation-tested, because a guard for a degradation path is
  exactly the kind that passes for the wrong reason.

## Amendment (2026-08-01): how resolution actually works, and why the fan-out framing was wrong

This ADR originally recorded the cost as *"resolution fans out: a note with forty `[[KAN-n]]` refs is
forty reads unless batched"*, and flagged it as an open risk to settle in V5.
[Spike 0001](../spikes/0001-wikilink-ref-batching.md) settled it, and **the premise was false**.

**There are no reads to fan out.** `GET /api/v1/cards/{card_id}` is typed `card_id: int`
(`backend/app/routers/cards.py:585-587` in the pandan repo), a wikilink carries a `ticket_number`, and
**no pandan route accepts a ticket ref**. The only `ticket_number`-to-row lookup in that entire backend
is internal to the GitHub webhook handler, and pandan's own CLI resolves a ticket by paging the card
list and matching client-side. So kaya cannot make N calls by id, because it does not have the ids, and
obtaining them costs a list sweep — after which the sweep already carries `title` and `column`, the list
item and the single-read response having been verified live as the same 22 keys.

**The mechanism is a bounded sweep, not a fan-out.** One page walk of `GET /api/v1/cards?limit=200` per
resolution batch, with the caller's PAT, one request in flight, caching every card returned rather than
only the referenced ones. Requests scale with **board size, not ref count**: three requests for 540
cards whether the note has one ref or forty. A per-request timeout of ~3s, a total walk deadline of ~8s
and a five-page cap, so a large board degrades to partially resolved rather than to a long sweep.

Two reasons this is right rather than merely available, both of which the original framing would have
walked into:

- **A fan-out would have broken this ADR's own rule from inside kaya.** A sync route holds its Postgres
  session for the whole request (ADR 0001 commits kaya to 100% sync), so blocking on pandan holds a kaya
  database connection for the entire fan-out while doing no database work. Ten concurrent renders
  against a *slow* pandan exhaust the pool and take down note **saving** — the exact coupling this ADR
  forbids, self-inflicted, and as resource exhaustion rather than a timeout it does not degrade
  gracefully. **Slow is worse than down**: a down upstream fails fast on connection refused.
- **A fan-out would have taken pandan down as well.** `fly.toml` sets `hard_limit = 40` on a single
  256 MB instance with `min_machines_running = 0`. One forty-ref note at full concurrency is that
  ceiling; two concurrent renders return 503s to everyone. The board would go down because somebody
  opened a spec note.

**V5 does not wait on [pandan issue 254](https://github.com/leejianrong/pandan/issues/254).** The
resolver's shape is already that issue's shape — one upstream call per batch, a cache, a deadline, an
unresolved fallback — so when `?refs=` lands the sweep becomes one call and nothing else moves.

**The guard this implies**, which belongs in V5's acceptance criteria: assert that requests scale with
**pages, not refs**. A forty-ref note issues at most three upstream requests, and a second render of it
issues none.

**One number cuts the other way, recorded so it isn't rediscovered as an objection.** On cold-cache wall
clock alone, a cap-8 fan-out of twenty refs is 2.4s against a 4.9s sweep, and the two cross at about
forty-five refs on a 540-card board. The sweep still wins, because a per-ref design fills one cache
entry per request while a sweep fills 200 — the amortisation is across the whole workspace, not one
note — and because the wall-clock comparison silently omits the sweep the fan-out would itself need.
