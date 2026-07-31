# ADR 0008 — A note is identified by an immutable `NOTE-n` ref; its path is mutable metadata

- **Status:** Accepted
- **Date:** 2026-08-01
- **Deciders:** Assumed default (Q16–Q19), settled by pandan's precedent
- **Context source:** pandan ADR 0006 / 0009 (per-table Postgres sequences, immutable and never reused),
  pandan ADR 0018 §"What is deliberately NOT renamed", and the failure mode Obsidian has.

## Context

Identity is the decision that becomes expensive fastest, because every wikilink, every `note_link` edge,
every CLI invocation and every export embeds it. It has to be settled before the first migration.

The tempting choice is the folder path, since that's how Obsidian and every filesystem vault works, and it's
free — no extra column, human-readable, and the tree is right there. It is also the source of Obsidian's
most-complained-about behaviour: **moving or renaming a note breaks the links pointing at it**, and the
workarounds (rewrite every referencing file on move) are why that operation is slow and occasionally lossy.

Kaya is server-authoritative and holds notes in Postgres, so it has an option a filesystem vault doesn't: a
real identifier that nothing user-facing can change.

Pandan already solved this shape of problem twice, and the mechanism is proven in production: ticket numbers
come from a per-table Postgres `SEQUENCE` via a column `server_default`, so they're allocated atomically at
INSERT, are immutable, and are never reused. Pandan ADR 0018 records the consequence that matters — the
prefixes could not be renamed during a full rebrand, precisely *because* the identifiers are immutable and
there is no correct way to renumber history. That's the property to want.

## Decision

**A note has three names, and only one of them is its identity.**

| Name | Mutable? | Purpose |
|---|---|---|
| `id` (integer PK) | no | internal joins, `note_link` edges |
| **`NOTE-n` ref**, from a Postgres `SEQUENCE` via `server_default` | **no** | the user- and agent-facing identifier |
| `path` (folder + filename) | **yes** | organisation and display only |
| `title` | yes | display, and the wikilink resolution key |

- **Every id-taking verb accepts either the `NOTE-n` ref or a bare integer id**, case-insensitively, and
  both forms must produce **identical results including identical error codes**. Pandan shipped a version
  where `get 999999` exited `1` and `get KAN-999999` exited `5`, so the error code depended on the identifier
  form; it was fixed in the *resolver* rather than at each call site, which is the right place because it
  then covers every ref-taking verb at once. Kaya resolves centrally from V2a.
- **Anything the tool prints must be accepted back.** That's the contract, and it gets a round-trip test per
  id-taking verb: list, take the printed identifier verbatim, feed it back, assert success. Leniency beyond
  that is not a goal — a leading `#` is a usage error, pinned by a test, because leniency in an identifier
  parser buys a future ambiguity for no measured need. (Pandan's V42 record makes exactly this call.)
- **`path` is metadata.** Moving a note between folders is a `PATCH` to one column. No link rewriting, no
  cascade, nothing to break.
- **Wikilinks resolve by `title` at parse time, and the resolved id is recorded** in `note_link` (Q19). So a
  later rename doesn't break the recorded edge, and the backlinks panel stays correct across renames. An
  unresolvable link is stored *unresolved* rather than dropped, so it resolves later if a matching note
  appears.
- **Export carries the ref.** Export and import are out of the MVP (Q18), but the ref goes into front matter
  when they arrive, and an import re-uses it when free and records a remap when not. Designing for this now
  costs a column comment; retrofitting identity costs a migration plus a link rewrite.

**Add a comment at the sequence definition** recording that the `NOTE-` prefix and the sequence are
deliberately immutable, so nobody "finishes" a future rename and damages data. Pandan did this at its own
sequences after ADR 0018, and it's the cheapest possible insurance.

## Alternatives considered

| Option | Why not |
|--------|---------|
| **Path as identity** (Obsidian's model) | Renaming or moving a note breaks every link to it. It's the single most-felt wart in the product kaya is modelled on, and a server-side database makes it unnecessary. |
| **Title as identity** | Same problem plus a uniqueness constraint on a field users expect to edit freely, and two notes genuinely can want the same title in different folders. |
| **A slug derived from the title** | Either it changes on rename (path's problem) or it doesn't (and is then a meaningless string worse than `NOTE-n`, since it's stale-looking rather than obviously opaque). |
| **UUIDs as the user-facing ref** | Correct and unusable. `[[NOTE-12]]` is typeable and readable in a diff; `[[550e8400-e29b-…]]` is neither, and prose is the thing being edited. |
| Sequence per user rather than global | Gives contiguous per-user numbering nobody asked for, at the cost of a composite key in every edge and every ref parse. |

## Consequences

- **Positive:** move and rename are free and non-destructive, which is the operation Obsidian users flinch
  at. Refs are short, typeable, greppable, diffable, and stable across every mutation. The mechanism is
  proven in the sibling.
- **Neutral:** `NOTE-n` is opaque, so a ref alone doesn't tell you what a note is — the resolver renders the
  title beside it wherever it's displayed, exactly as pandan does for `KAN-n`.
- **Negative / deferred:** the sequence is global, so refs leak a rough count of notes across all users.
  Irrelevant for a single-maintainer suite, worth revisiting only if kaya ever becomes multi-tenant with
  untrusting users. And as pandan learnt, **the prefix can never be changed** — `NOTE-` is permanent, which
  is a reason to be sure of it now rather than a cost later.
- **Now has to be true:** the ref resolver is central and lands in **V1** (API) and **V2a** (CLI), before any
  verb that takes an identifier. A per-call-site resolver is the shape that produced pandan's inconsistency.
