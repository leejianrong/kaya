# ADR 0009 — Concurrent note edits are rejected, not silently merged: optimistic concurrency instead of pure last-write-wins

- **Status:** Accepted
- **Date:** 2026-08-01
- **Deciders:** Assumed default (Q21), flagged to Jian as a deliberate deviation and not overruled
- **Context source:** pandan ADR 0007 (cloud-only, last-write-wins, no real-time) and
  [`kaya-vision.md`](../kaya-vision.md) §Ethos, which carries that stance over to kaya explicitly.

## Context

The vision doc commits kaya to pandan's ADR 0007 simplifications, and names last-write-wins as one of them:
*"A note is server-authoritative; concurrent edits are LWW, same as a card."* Consistency between the two
apps is a real value, so deviating needs a reason.

The reason is the payload. LWW is a sound trade for a card, where a write is a handful of short fields and
the loser can see at a glance what changed and redo it. **A note body is long-form prose.** Two writers
editing a 3,000-word runbook under pure LWW means one of them loses an arbitrary amount of work,
**silently** — no error, no notification, no copy of what was overwritten. The loser typically discovers it
days later, if at all.

The failure is likelier than it sounds in this product, because of the actors. A human editing a spec in the
browser and an agent appending to the same note while it works the card is not an edge case, it's the story
the suite is *for*. And an agent's write is exactly the kind that arrives without anyone watching.

Importantly, fixing this does **not** require touching the parts of ADR 0007 that are load-bearing. No
CRDTs, no operational transforms, no realtime transport, no local-first sync. Those are what make
collaborative editing hard, and they all stay out.

## Decision

**Optimistic concurrency on note writes, enforced server-side.**

- A read returns the note's `updated_at`.
- A write (`PATCH /api/v1/notes/{ref}`) carries the `updated_at` it read.
- If the stored `updated_at` differs, the write is **rejected with `409`**, and the response body carries
  both the caller's attempted body and the current stored one so the client can show a real diff.
- If it matches, the write proceeds and stamps a new `updated_at`.
- A write that **omits** the precondition is accepted as a plain LWW overwrite. This keeps `kaya note edit
  --force` and simple scripted appends possible, and keeps the API usable from `curl` without a read-first
  dance. The precondition is a guarantee available to any client that wants it, not a tax on every caller.

Surfaces:

- **The SPA sends it always**, and renders a conflict banner offering "keep mine", "keep theirs", or a
  side-by-side view. This is the affordance that turns a `409` into something a person can act on.
- **The CLI sends it** on `note edit` (read-modify-write in one command) and reports the `409` through ADR
  0005's structured error contract with its own stable code, so a script can branch on it.
- **The MCP `edit_note` tool sends it**, because an agent is the caller most likely to be racing a human.

**What is unchanged from ADR 0007:** cloud-only, server-authoritative, no real-time, no multiplayer cursors,
poll/refresh. Metadata-only writes (title, path) stay plain LWW, because they're card-shaped fields where
the original reasoning holds.

**Clarified while implementing (KAN-537).** "Metadata-only writes stay LWW" left the mixed cases open, and
the implementation had to pick one. The precondition **guards the body**, so:

| The `PATCH` sends | With a stale precondition |
|---|---|
| `body` (with or without `title`/`path`) | `409`, and **nothing** is written — not even the metadata half |
| `title` and/or `path` only | Written, LWW. A rename conflicts with nothing this decision is about |
| Neither (an empty `PATCH`) | A no-op, as always. Nothing changed, so nothing can be lost |

The reading follows this ADR's own reasoning rather than the letter of the sentence: the deviation from
pandan ADR 0007 is about the *payload*, and a re-typed title is not the harm. It also protects the
affordance — the SPA "sends it always", so a `409` on a rename would be a banner its user learns to
dismiss before the one that matters arrives. The mixed write is refused whole because applying half of a
rejected write would be a second silent edit, in the opposite direction.

## Alternatives considered

| Option | Why not |
|--------|---------|
| **Pure LWW, matching pandan exactly** | Consistency is worth something, but not silent loss of prose. The asymmetry is in the payload, not in the philosophy, so matching the *reasoning* (server-authoritative, simple, no realtime) matters more than matching the *mechanism*. |
| **CRDT or operational transform** | The genuinely hard product the vision doc explicitly declines. Weeks of work and a permanent complexity floor to solve a problem `409` solves adequately. |
| **Real-time collaborative editing** | Same objection, plus a transport, plus presence. Explicitly a non-goal. |
| **Auto-merge with a three-way diff** | Sounds helpful and silently produces garbage on prose, which is worse than a rejection because it *looks* successful. A diff shown to a human is fine; a merge applied without one is not. |
| **Row-level locking / pessimistic locks** | Requires lock lifetime management, breaks on a client that closes its tab, and serialises writers who mostly aren't conflicting. |
| **Append-only revision history**, with conflicts resolved by keeping both | The right long-term answer and a bigger feature (storage, a history UI, pruning). `409` is the cheap 90% of it, and this stays the natural evolution. |

## Consequences

- **Positive:** the failure mode that actually loses user work is closed, at the cost of one column
  comparison. The rejected writer sees both versions and decides, which is the only correct resolution for
  prose. And the guarantee is uniform across all three surfaces rather than a browser-only nicety.
- **Neutral:** one extra field on the wire, and a client that wants the guarantee has to round-trip a read
  first. Every client that matters does anyway.
- **Negative / deferred:** kaya and pandan now differ on conflict handling, so "same ethos" needs the
  qualification this ADR provides — which is why the deviation is recorded here rather than left implicit
  against a vision doc that says LWW. There is **no revision history**, so "keep theirs" still discards the
  caller's text; it just does it with the caller's consent and a diff in front of them. And a client that
  omits the precondition gets no protection, which is a deliberate hole and needs saying in the API docs so
  it isn't mistaken for a bug.
- **The guard:** an integration test where two writers read the same note, both write, and the second gets a
  `409` with both bodies present. Mutation-tested, because a concurrency assertion that passes when the
  precondition is ignored entirely is precisely the blind guard pandan kept finding.
