# ADR 0011 — Team-scoped notes: a second, softer rung under `authorize_note`

- **Status:** Accepted
- **Date:** 2026-09-03
- **Deciders:** Jian (forks F1–F3, kaya-teams-decision artifact)
- **Context source:** `KAN-1048` (kaya-side spike, done 2026-09-01), pandan
  [ADR 0021](https://github.com/leejianrong/pandan/blob/main/docs/adr/0021-organization-team-tier.md)
  (accepted 2026-09-01, `team` tier over `board`), pandan Milestone 9 "Teams" (`V65`–`V70`, `EPIC-138`,
  shipped), `docs/roadmap/FRAME.md` / `SHAPING.md` (2026-09-01 planning pass, R2/R3).

## Context

`KAN-1048`'s acceptance criterion was to map every kaya-side touchpoint an org/team model would need,
without designing a solution — it was explicitly blocked on two things: pandan's own ADR-level answer
(`pandan#322`) and pandan actually *building* it (Milestone 9). Both have now happened. `GET
/api/v1/teams` exists, `board.team_id` exists, and pandan's own `_effective_access` check gained a
team-default rung without touching its owner or explicit-share checks. Kaya's own note model
(`Note.owner_id`, ADR 0002/0008) is single-owner, with every list query scoped in
`app/auth/authorization.py` and pinned there by an AST-level test
(`tests/unit/test_no_unscoped_note_query.py`) that already anticipates widening to a team-membership
subquery.

Three questions had no confident default and were put to the maintainer as forks (published as an
artifact, "Kaya Teams", 2026-09-03): whether to build this now or park it further; what shape the
team-scoping takes; and what a team-shared note does when pandan can't be reached. All three were
accepted as recommended.

## Decision

**Add one nullable rung to `authorize_note`, sourced from a live call to pandan, and let it fail soft.**

### Fork 1 — sequencing: now

The blocker (pandan's design and build) is gone, `KAN-1048` already has file:line touchpoints mapped,
and the direction was already stated in the 2026-09-01 interview (`FRAME.md`). The cost of opening the
epic and later deciding it was premature is small — an epic sitting mid-build. The cost of parking it
and returning later is re-deriving `KAN-1048`'s seven touchpoints from a cold start, which is exactly
the rework the spike already paid down. Tracked as `EPIC-136`, cards `KAN-1082`–`KAN-1088` (see
`docs/roadmap/BREADBOARD.md` R16).

### Fork 2 — shape: mirror pandan's, minus the rung kaya doesn't have

- **`team` (new table): `id` only** — pandan's id for the team, verbatim, no other column. This is
  the exact reasoning `app/models/user.py`'s docstring already gives for the user mirror: any column
  beyond an id goes stale, and the first caller to trust a stale copy is right to be annoyed. JIT-
  inserted the same way a user mirror row is, `ON DELETE RESTRICT` for the same reason too — a locally
  mirrored row is not the authority on whether a note should keep existing, so a future cleanup job
  fails loudly rather than silently orphaning a note's team association. **Unlike `user.id`, this is
  a `BigInteger`, not a `Uuid`** — pandan's own `Team.id` is a plain integer (verified against
  pandan's `backend/app/models.py`), so the mirror matches the wire type rather than assuming every
  pandan identity is UUID-shaped the way a `User` happens to be.
- **`note.team_id`** — nullable `FK → team.id`, additive, mirrors `board.team_id`'s shape in pandan ADR
  0021 exactly. Every existing note gets `team_id = NULL`, i.e. today's behavior, byte-for-byte — the
  same consequence ADR 0021 recorded for `board`.
- **`authorize_note` gains one rung, not a rewrite**, and it is a **two**-step check, not pandan's four:

  | Step | Source | Result |
  |---|---|---|
  | 1. `note.owner_id == principal.id` | unchanged | full access |
  | 2. `note.team_id` is set and the principal is a member (`TeamAccessResolver`) | **new** | access via team default |
  | 3. neither | unchanged | `403` |

  Kaya has no per-note explicit share to slot in between (Q8: owner-only, by design, since the MVP) —
  that is the one place this shape is *simpler* than pandan's, not a partial port of it.
- **A new `TeamAccessResolver`** (`app/auth/`), shaped like `PrincipalResolver`: given a bearer, calls
  pandan's `GET /api/v1/teams` (the caller's own memberships — `GET /api/v1/me` deliberately stays
  `{id, email}` per ADR 0021, so team data has nowhere else to come from), cached on `sha256(token)`
  with the same positive/negative TTL split as `PrincipalCache` (ADR 0002 Q6).
- **`POST /api/v1/notes` gains an optional `team_id`**, validated the same way pandan validates
  `POST /api/v1/boards`' `team_id` — the creating principal must be a member, `403` otherwise.
- **Wikilink resolution needs no change.** `note_link`'s resolver already scopes by whatever
  `authorize_note`/the visible-notes query returns; a link only ever resolves within notes the
  resolving path can already see. `KAN-1048` flagged this as an open question; it is now a verified
  "no" rather than an assumption.
- **The AST guard widens**, per its own docstring's anticipation, to accept the new team-membership
  subquery alongside the existing owner check.

Rejected shapes: a separate "team notebook" namespace (a second query surface to maintain for no
capability this shape doesn't already give) and a UI-only surfacing with no authorization change
(ships no team value — see the fit-check matrix in the kaya-teams-decision artifact).

### Fork 3 — failure behavior: soft, like cross-linking, not hard, like identity

ADR 0002's hard dependency on pandan is scoped narrowly to *who you are* — a wrong answer about
identity is worse than no answer, and that is the one exception ADR 0003 grants. Team membership is
*what you can see*, which is ADR 0003's territory: nothing in kaya may block on pandan. Concretely:

| | pandan reachable | pandan unreachable |
|---|---|---|
| your own note | visible | **visible** |
| a teammate's team-shared note | visible (if a member) | **hidden** (membership unconfirmed → treated as absent) |

`TeamAccessResolver` returns "no team memberships known" rather than raising, on any pandan failure.
A note's owner never loses access to their own work because pandan had a bad minute; a teammate's
access to a shared note degrades to not-found, the same shape as any other unresolved cross-link.

## Alternatives considered

See the kaya-teams-decision artifact for the full fit-check matrix and 2×2 failure-mode grids; not
repeated here beyond the one-line reasons above, per this repo's "cite, don't restate" convention.

## Consequences

- **Purely additive migration** — two new columns/tables, every existing note's meaning unchanged
  (`team_id IS NULL`), same shape ADR 0021 already proved once.
- **`app/auth/authorization.py` and its AST guard both grow by one rung**, not a rewrite; every
  existing 403/200 test keeps passing because the new clause is a no-op wherever `team_id IS NULL`.
- **A second live pandan dependency exists now**, alongside identity — but explicitly a *soft* one.
  `TeamAccessResolver` must never hold a Postgres connection while calling out, same discipline as
  `/links` (CLAUDE.md).
- **No MCP tool count change assumed.** `ADR 0006`'s freeze still governs; `R16.6` (`KAN-1087`) checks
  whether `team_id` fits the existing field vocabulary before proposing a new tool.
- **Kaya still mirrors nothing beyond an id.** If pandan later exposes team names, roles, or anything
  else through `/api/v1/teams`, kaya fetches it live through `TeamAccessResolver` rather than growing
  the `team` mirror table — the same discipline `app/models/user.py` already states as a rule, not a
  one-off choice for this feature.

## Open

- **Team-scoped SPA affordances beyond a read-only badge** (creating or moving a note into a team from
  the browser) are `R16.7`'s stretch goal, not committed here.
- **Per-note explicit sharing** (Q8's other half) is untouched by this ADR — it remains a separate,
  undecided question, and nothing here forecloses adding a third rung between owner and team-default
  later if it's ever needed.
