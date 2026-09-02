---
shaping: true
---

# kaya: post-V6 direction — Shaping

See `FRAME.md` for Source/Problem/Outcome. This is the working document — requirements first, shapes
once the requirements settle enough to design against.

## Requirements (R)

| ID | Requirement | Status | Owner |
|----|-------------|--------|-------|
| R0 | Browser reaches CRUD parity with CLI/MCP for notes | 🟡 Core goal — **sequenced first, decoupled from R2/R3** | kaya-only |
| R0.1 | Create a note from the SPA | Core goal | kaya-only |
| R0.2 | Delete a note from the SPA | Core goal | kaya-only |
| R0.3 | Move/rename a note's `path` from the SPA | Core goal | kaya-only |
| R0.4 | Edit a note's title from the SPA | Core goal | kaya-only |
| R1 | kaya has an independently reachable hosted deployment, not gated on pandan's own homelab timeline (supersedes part of ADR 0010) | 🟡 Core goal — **interim target decided: Fly.io first, generalize later** | kaya-only (infra) |
| R2 | An organization/team model: a company's multiple internal teams operate isolated boards + notes under one shared account structure | 🟡 Must-have — **scope decided: self-hosted single-company multi-team, not cross-company multi-tenant SaaS** | **needs pandan coordination** — tracked as [pandan#322](https://github.com/leejianrong/pandan/issues/322) |
| R3 | Self-hosting readiness: a third party can stand up their own pandan+kaya instance without inheriting operator-specific assumptions (hardcoded Fly/Neon/homelab specifics, single hardcoded origin, etc.) | Must-have | **needs pandan coordination** — tracked as [pandan#323](https://github.com/leejianrong/pandan/issues/323) |
| R4 | Today's single-owner, single-board usage does not regress while R2/R3 are designed | Must-have (guardrail) | both |
| R5 | New standalone capabilities | 🟡 Graph view and embedded board view shipped (KAN-1049/1050, PRs #115/#116 open for review). The remaining three — export/import, version history, attachments — shaped 2026-09-01, see R5.1–R5.3 below and Detail R5.1/R5.2/R5.3 in `BREADBOARD.md`. Tags/templates dropped (not requested). | kaya-only |
| R5.1 | Export/import (KAN-1051) — single-note + corpus markdown export/import, Obsidian-vault-compatible layout, `NOTE-n` ref preserved when free else minted fresh | 🟡 Shaped 2026-09-01 — see Detail R5.1 | kaya-only |
| R5.2 | Version history (KAN-1052) — append-only `note_version`, full-body snapshot on every save, restore implemented as an ordinary save, no pruning in v1 | 🟡 Shaped 2026-09-01 — see Detail R5.2 | kaya-only |
| R5.3 | Attachments (KAN-1053) — Cloudflare R2, kaya-proxied reference (never a direct provider URL), drag/drop upload in the editor | 🟡 Shaped 2026-09-01 — **sequenced after R1 lands** (needs a real origin to configure CORS/callback host against) — see Detail R5.3 | kaya-only |
| R6 | A durable, visible way to mark which roadmap items are kaya-only vs pandan-coordinated, since one person operates both repos and the line blurs easily | 🟡 Satisfied by this doc's Owner column + the filed pandan issues | kaya-only artifact, describes both |
| R7 | A licensing/openness stance for self-hosters exists before self-hosting docs promise anything (open-source terms, any paid-tier boundary) | 🟡 Base case resolved — pandan is already Apache 2.0, same as kaya, so self-hosting isn't licence-blocked. A paid hosted-tier boundary remains a parked business question, not an engineering one. | n/a for now |

## Decisions made (2026-09-01)

- **R0 ships first, as its own epic**, independent of the enterprise-direction work below. It has no
  open design questions — see Detail R0 below.
- **R1's interim hosting target is Fly.io**, matching pandan's current setup, generalizing to a
  portable target later rather than now. This means ADR 0010 gets amended (not replaced) to record
  "independent Fly.io deploy, not gated on the homelab" as the new position.
- **R2's scope is self-hosted, single-company, multi-team** — not a hosted multi-tenant SaaS serving
  many separate companies. This is the smaller of the two readings and is what pandan#322 asks for.
- R2 and R3 are **not sliced into board-18 stories yet** — they need the ADR-level design work in
  pandan#322/#323 to land first. What's tracked on board 18 for them now is a single placeholder epic
  plus one kaya-side spike (see Detail R2/R3 below), not implementation stories.
- **R5's five accepted capabilities are not fully shaped yet either** — unlike R0, none of them has
  been through a fit check or breadboard. They vary a lot in how settled their mechanism already is:
  graph view and embedded board view are near-free (both reuse `note_link`/ADR 0003's resolver, which
  already exist); export/import and version history need a real data-model decision before a story can
  be written; attachments needs an object-storage decision (Cloudflare R2 was named in `PLAN.md` §Scope
  as the eventual mechanism, never committed to). Board 18's Epic 137 cards for these are intentionally
  written as "design + build" rather than fully broken-down stories — expect the first work on each to
  be a short shaping pass, not straight-to-code.

## What research turned up (context for the table above)

**Confirmed SPA gaps behind R0** (each traced to one root cause — `EditorPane.svelte`'s save path
only ever sends `{ body, if_updated_at? }`):

- **R0.1 create** — `frontend/src/lib/router.ts` has exactly two routes (`home`, existing `note`);
  `createNote()` exists in `lib/notes.ts:53` but is called from nowhere in `src/`; the empty sidebar
  state is plain text with no call-to-action.
- **R0.2 delete** — `deleteNote()` (`lib/notes.ts:132`) is likewise defined and never called.
- **R0.3 move/rename** — `moveNote()` (`lib/notes.ts:77`) is never called; no folder-drag or rename
  field exists anywhere in the SPA.
- **R0.4 title edit** — `EditorPane.svelte:656` renders the title as a static `<h2>`, not an input.

Already fine, not gaps: full-text search (`Sidebar.svelte`), conflict resolution
(`ConflictBanner.svelte`), manual save with a visible button + `Mod-s` (a deliberate consequence of
ADR 0009's precondition model, not a discoverability bug). Config/settings has no SPA equivalent by
design — ADR 0004 makes the SPA a direct consumer of complete records, so CLI/MCP-only shaping
concerns (`--fields`, truncation) have no SPA analog to build.

**On R1 (independent hosted deployment) vs. pandan's KAN-439:** pandan's own board (board 5) carries
KAN-439 — migrate pandan itself off Fly+Neon onto a self-hosted k8s homelab, 13 points, human-flagged,
not started. Its card body is pandan-only (new OAuth app, DNS/TLS, Postgres relocation, a rate-limiter
assumption that breaks past one replica) and mentions kaya nowhere. There is no coordination artifact
linking the two efforts today — they'd likely land on the same physical hardware eventually (same
operator), but as two independent migrations. Given the interview answer (pursue an independent host
sooner rather than wait), **ADR 0010 needs a formal amendment or successor ADR**, not just a README
update — it currently states the no-hosted-deploy position as a considered decision, and this reverses
part of it.

**On R2/R3 (org/teams, self-hosting) — pandan's current shape:** pandan is mature (6 milestones
shipped, 19 accepted ADRs, board sharing by role — viewer/editor/owner — already exists) but has
**no organization tier above a user**, and no formal API stability/versioning policy (ADR 0005 states
an intent that endpoints "should stay stable-feeling," not a contract). In practice pandan's
maintainer has already shipped endpoints on kaya's behalf before (`GET /api/v1/me`, a batch card read
— both closed issues that look purpose-built for kaya's identity and wikilink-resolution needs), which
is a good sign for cross-repo cooperation, but it means **R2 cannot be designed inside kaya alone** —
the org/team concept, if it lives at the identity layer, is a pandan-repo decision kaya would then
consume.

**On R5 (new capabilities):** already-deferred-on-the-record candidates, none built: version history
(not explicitly deferred anywhere — a gap in the record, not just in the code), attachments/images
(Q35 — deferred to object storage "when genuinely needed"), export/import (Q18 — deferred, but
`NOTE-n` refs are deliberately designed to survive it), a graph view (Q36 — deferred, "cheap once
`note_link` exists," which it now does), an embedded live board view inside a note (Q37, ADR 0003
§Deferred — same read API as wikilink resolution, so also cheap now). None of these were requested by
name in this conversation — they're carried over from the existing decision register as candidates,
not commitments.

## Discussion points (need your read before this becomes shapes/epics)

1. **"Multi-team" — one shape or two?** Your source quote covers two things that could be the same
   feature or two different ones: (a) *"teams or companies with multiple teams to use"* — an org/team
   data model, however it's hosted — and (b) *"self host their own instance"* — a deployment/packaging
   concern. A company could self-host a single-tenant instance that internally has multiple teams
   (org/team model, single deployment, no true multi-tenancy needed) — which reads as the simpler,
   more likely target — **or** you could be picturing a hosted SaaS where *we* run one instance serving
   many separate companies (true multi-tenancy, much larger scope: tenant isolation, billing-adjacent
   concerns, noisy-neighbor limits). Which one is the actual target?
2. **Sequencing.** R0 (SPA parity) is small and shovel-ready — a few days of work with no open design
   questions. R2/R3 (org/teams, self-host readiness) is a multi-month initiative that needs its own
   ADR-level design work in *both* repos before a single story can be written. Recommendation: ship R0
   as its own near-term epic now, and open a **separate**, slower-moving shaping thread for the
   enterprise direction (R2/R3/R7) that starts with an ADR draft rather than board cards. Agree, or do
   you want them sequenced differently?
3. **R1's interim hosting target.** ADR 0010 already named Fly.io as the fallback escape hatch if the
   homelab slipped. Given self-hosting is now a stated goal, is a Fly-specific deploy still the right
   interim answer, or does it make more sense to skip straight to a **portable** target (plain Docker
   Compose / the existing k8s manifests, runnable on any VPS or the eventual homelab alike) so the
   "independent host sooner" work and the "self-hosting readiness" work produce the same artifact
   instead of two?
4. **R7 (licensing) — in scope for this pass at all?** It's a business decision, not an engineering
   one, and nothing forces it to be resolved before writing engineering epics for R0/R1. Fine to leave
   it as a named-but-parked item, or do you want to settle it now because it changes how R3 gets
   written (e.g. a paid self-host tier changes what "self-hosting readiness" needs to include, like
   license-key gating)?

---

## R5.1/R5.2/R5.3 shaping session (2026-09-01)

Board check at session start: KAN-1051/1052/1053 all still `todo`, descriptions unchanged from what's
summarized above. KAN-1049/1050 (graph view, embedded board view) show `done` on the board but their
PRs (#115, #116) are still open for review — not yet merged.

**A correction that changed the shape of R5.1:** the original card text and ADR 0008 both talk about
"rewriting `NOTE-n` refs in body text" as an import-time concern. That concern doesn't exist — kaya's
`[[...]]` wikilink mechanism (`backend/app/wikilinks.py`) already resolves plain **titles**, not refs;
`NOTE-n` is only ever a URL/API identifier (`refs.py`), never a link target in a note body. This means
kaya's own note bodies are already Obsidian-native (`[[Title]]` is Obsidian's own syntax) — export
needs no link rewriting at all, and title-collision handling on import is already covered by the
existing "newest note with a shared title wins" resolver rule (`note_links.py:49-53`), not new
mechanism. Net effect: R5.1 is smaller than the card description implied.

**Key decisions from the interview, by card:**

- **R5.1 (export/import):** driver is portability + bulk onboarding, not backup/DR. Single-note first,
  corpus archive second, both CLI-only. Ref handling: preserve `NOTE-n` if globally free (the `ref`
  column is a Postgres-sequence default, not app-settable, so preserving one means an explicit INSERT
  bypassing the sequence plus a `setval()` bump — see Detail R5.1), else mint fresh. Arbitrary
  non-kaya markdown folders (genuine Obsidian vaults, no kaya frontmatter) are first-class for bulk
  import.
- **R5.2 (version history):** cut a version on every save, full-body snapshots (no diffing), no
  retention/pruning in v1. Stays a separate concern from any future R2/R3 audit trail — no speculative
  actor/team fields. SPA-only surface (no CLI/MCP verbs this card). Restore is implemented as an
  ordinary save (no special-cased write path), so it never bypasses ADR 0009 or note_link
  reconciliation. `note_version` rows CASCADE-delete with their note — this is version history for
  content recovery, not an undelete-a-note feature (not requested).
- **R5.3 (attachments):** kaya-proxied reference in markdown (never a direct provider URL). Storage
  provider reopened and re-fit-checked rather than carried forward as an assumption — **Cloudflare R2
  confirmed**, this time on a real fit check rather than PLAN.md's original unexamined lean (see Detail
  R5.3's component fit check). Sequenced strictly after R1 (KAN-1044–1047, all still `todo`) lands, since
  object storage needs a real origin to configure CORS/callback host against. Upload UX is drag/drop
  or paste directly into the CodeMirror editor. **One real technical wrinkle surfaced during
  breadboarding:** the SPA's bearer lives in `sessionStorage` and is attached only to `fetch()` calls,
  never sent by the browser on a plain `<img src>` request — so the preview renderer must fetch
  attachment bytes via an authenticated call and swap in a `blob:` URL, not link `<img>` straight at
  the kaya-proxied endpoint. See Detail R5.3, part G6.

Full requirements, shapes, fit checks, and breadboards for all three are in `DETAIL.md`'s
Detail R5.1/R5.2/R5.3 sections (not the top-level `docs/roadmap/BREADBOARD.md`, which is a separate,
later reconstruction covering the same shipped work under different R-numbers — see `DETAIL.md`'s own
provenance note).
