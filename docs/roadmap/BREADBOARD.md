# kaya: Beyond the MVP — breadboard

All six MVP slices (`docs/SLICES.md`, R0–R9) shipped. This doc shapes the seven epics that came after
board 18 grew EPIC-134 through EPIC-137: two now shipped (the graph view, the board embed), three under
active build (export/import, version history, attachments), one investigation (an org/team model), and
one deferred by the maintainer's own choice (an independent Fly.io deploy, EPIC-135 — see KAN-1044,
still `todo`, when that's picked back up).

**Provenance note.** A shaping pass ran 2026-08-01–09-01 and closed KAN-1051/1052/1053 as
design-complete, each with a comment pointing at "`docs/roadmap/BREADBOARD.md` — Detail R5.x/\<letter\>N".
That file was never committed — the design lived only in an agent's working tree, which is exactly the
"looks done, isn't" failure `scripts/not-yet.sh` warns about, just one layer up from a Makefile target.
This is that file, reconstructed from the surviving card descriptions and comments (`pandan get
KAN-1051..1053 --full`, `pandan comment list`) rather than recovered verbatim. Two things follow: the
**R-numbers below start at R10**, not R5 — `docs/PLAN.md` already defines `R5`/`R5.1` for V5's wikilink
work, and reusing `R5.x` for an unrelated feature would silently collide with a requirement that's
already shipped and tested. And the exact per-item letter/number citations on already-`done` cards
(`A1`, `B1–B3`, `G1–G3+G5`) are historical color from the lost draft, not something this file reproduces
letter-for-letter — the shape below is authored fresh, grounded in the current codebase.

## R10: Graph view — shipped (KAN-1050)

`GET /api/v1/graph` (`backend/app/api/graph.py`) returns every note the caller owns and every resolved
note-to-note wikilink among them, node-and-edge shaped. `GraphView.svelte` + `lib/layout.ts` render it as
a new SPA view alongside the tree and search (`lib/router.ts`), with a hand-rolled force layout — no new
runtime dependency, so ADR 0001 §2's bundle-cost obligation stayed a non-question rather than something
to justify.

## R11: Embedded board view — shipped (KAN-1049)

`GET /embeds/board` (`backend/app/api/embeds.py`, `backend/app/integrations/board_embed.py`) reuses ADR
0003's resolver shape unchanged: the caller's own PAT, no session held while calling out, unresolved-on-
failure. An embed block in a note's markdown renders read-only in `PreviewPane.svelte` via
`lib/markdown.ts`'s existing AST walk — never raw HTML, per the no-html-injection guard
(`frontend/tests/no-html-injection.test.ts`).

## R12: Export and import (Q18)

**Requirement.** A note's `NOTE-n` ref survives a round trip through a file. ADR 0008 already designed
for this — identity is the ref, not the path or title — so this epic spends nothing retrofitting
identity and everything on the file format and the reconciliation on the way back in.

**Key finding that shrank the scope.** kaya's `[[Title]]` wikilink syntax (ADR 0003, V5) is already
Obsidian-native. Export needs **no link rewriting** — the body goes out verbatim. That's most of why
this epic is 1–2 points per card instead of the 5 the original spike card carried.

**Shape**

| Part | Mechanism |
|------|-----------|
| Single-note export | `kaya note export <ref>` (new `kaya-cli` verb → `kaya-client`) writes one `.md` file: YAML front matter (`kaya_ref`, `title`, `path`, `created_at`, `updated_at`) + a `---` separator + the body verbatim. No new API route — reads through the existing `GET /api/v1/notes/{ref}`, same as everything else in `refs.py`. |
| Single-note import | `kaya note import <file>` parses the front matter. If `kaya_ref` is present **and free** (no note holds it), the new note is created carrying that ref forward; if taken or absent, a fresh ref is minted and the old one is recorded (front matter `kaya_ref` on the new note's export, next time). `note_link` reconciles exactly the way an edit does today (KAN-563) — importing runs the same on-save wikilink parse, nothing bespoke. |
| Corpus export | `kaya export --all` walks every owned note and writes an Obsidian-vault-compatible directory: one file per note at its `path`, same front-matter shape as the single-note case. A vault opened in Obsidian should just work, wikilinks included. |
| Corpus import | `kaya import --dir <path>` walks a directory of markdown files. A file with kaya's front matter shape imports as in the single-note case; a file with **no** `kaya_ref` (arbitrary external markdown, e.g. an existing Obsidian vault) imports as a fresh note, ref minted, `[[Title]]` links resolved against the batch the same way `note_link` resolution always works — some may land `resolved_id IS NULL` until the rest of the batch (or a later note) fills them in, which is the existing, already-correct behaviour for a link to a title that doesn't exist yet. |

**Affordances**

| Affordance | Place | Wires to |
|------------|-------|----------|
| `kaya note export <ref>` / `kaya note import <file>` | CLI | `GET`/`POST /api/v1/notes` (no new routes) |
| `kaya export --all` / `kaya import --dir` | CLI | same, looped |
| Export/Import entries | SPA note menu (stretch — CLI is the MVP surface for this epic; SPA affordance can follow once the CLI round-trip is proven) | same |

**Fit-check.** No new backend route, no new table — this stays entirely in `kaya-client` + `kaya-cli`
(ADR 0004: shaping lives in the client). A `409` never applies here; import is always a create.

**Cards:** KAN-1060 (single export), KAN-1061 (single import), KAN-1062 (corpus export), KAN-1063
(corpus import).

## R13: Version history

**Requirement.** A concurrent-edit conflict (R9, ADR 0009) already stops a save from silently losing
prose. Version history is the complementary guarantee: a save that **wasn't** concurrent — just wrong —
is still recoverable.

**Shape**

| Part | Mechanism |
|------|-----------|
| Storage | `note_version` (id, `note_id` FK `CASCADE`, `body`, `created_at`). **No `owner_id`** — same pattern as `note_link` (see CLAUDE.md's owner-scoping rule): a version is reached only by joining through its parent note, never queried standalone, so `authorize_note`'s existing scoping covers it without a second scoped-query surface to maintain. |
| Cut point | `create_note` and `update_note` (`backend/app/api/notes.py`) insert a version on every body write — no debounce, no "only if changed by N chars" heuristic. Simpler, and cheap: a note body is small text, and pruning is a separate, later concern (not this epic — full history first, retention policy only if the table's size ever asks for it). |
| List | `GET /api/v1/notes/{ref}/versions`, a fourth route module or folded into `notes.py` (call at build time whether it needs a bearer-and-upstream shape like `links.py`/`embeds.py` — it doesn't; it's a plain scoped read, so it belongs on `notes.py`'s router). |
| Preview | Reads one version's `body` — no new route; the list response can carry enough (`id`, `created_at`, and either the full body or a snippet) that a preview is a client-side selection, not a second network round trip, unless a version body is large enough that this needs its own `GET .../versions/{id}`. Decide at implementation time by measuring, not guessing (house style, ADR 0001 §2). |
| Restore | A restore is a `PATCH /api/v1/notes/{ref}` with `body` set to the chosen version's body — **not a new endpoint**. Same shape as `kaya note move` delegating to `update_note` rather than growing its own route (ADR 0008). Goes through the same `409` precondition as any other edit, `if_updated_at` included, so restoring over someone else's concurrent edit is caught the same way any other write conflict is. |
| SPA | A **History** tab beside **Backlinks** in the right rail (the same rail KAN-568 built) — list, click to preview, a Restore button that fires the `PATCH` above. |

**Affordances**

| Affordance | Place | Wires to |
|------------|-------|----------|
| History tab | Right rail, beside Backlinks | `GET /api/v1/notes/{ref}/versions` |
| Version preview | History tab | client-side, or `GET .../versions/{id}` if measurement says the list payload is too heavy |
| Restore | History tab | `PATCH /api/v1/notes/{ref}` (existing route, existing `409` contract) |

**Fit-check.** No new precondition semantics — restore reuses ADR 0009 exactly. No new owner-scoping
surface — `note_version` is reached only through its parent note, same shape as `note_link`.

**Cards:** KAN-1064 (cut on save + list), KAN-1065 (preview), KAN-1066 (restore).

## R14: Attachments (Q35)

**Requirement.** A note can carry a non-text asset (an image, most often) without kaya becoming a
general file host. Deferred in the MVP specifically until "genuinely needed" (Q35) — this epic is that
decision landing.

**Shape**

| Part | Mechanism |
|------|-----------|
| Storage | Cloudflare R2 (named as the eventual mechanism at MVP time, now committed to). One bucket, credentials via `Settings` (mirrors how `KAYA_PANDAN_URL` and the DB URL already arrive — env-configured, logged as non-default at boot per the existing convention, never the value itself). |
| Data model | `attachment` (id, `note_id` FK `CASCADE`, `r2_key`, `content_type`, `size_bytes`). **No `owner_id`** — same reasoning as `note_version`: reached only by joining through the owning note. |
| Upload | `POST /api/v1/notes/{ref}/attachments`, multipart body, streams to R2 under a key namespaced by note id (`{note_id}/{uuid}.{ext}`, never the caller-supplied filename verbatim — avoids a path-traversal-shaped key). Returns the markdown reference to insert. |
| Editor integration | A drop/paste handler in `lib/codemirror.ts` — the one file allowed to touch CodeMirror directly (CLAUDE.md's import-guard rule) — uploads on drop/paste and inserts the returned markdown reference at the cursor. |
| Render | **Never a direct R2 URL** — auth on fetch must not leak another owner's file, so a note's rendered attachment reference resolves through kaya (`GET /api/v1/notes/{ref}/attachments/{id}`, authorized exactly like the note itself), fetched by the SPA and swapped into a `blob:` URL for the `<img>` src. Same reasoning as the bearer-in-`sessionStorage` rule: nothing that identifies a private resource sits in a URL bar or a cached HTML response. |
| Auth guardrail | A note's attachment is unreachable to anyone who isn't its owner, proven the way every other owner-scoping claim here is: `[mutate]` — break `authorize_note`'s check on this route specifically, confirm the failure names the right thing, restore. |

**Affordances**

| Affordance | Place | Wires to |
|------------|-------|----------|
| Drop / paste a file | Editor | `POST /api/v1/notes/{ref}/attachments` |
| Rendered image | Preview pane | `GET /api/v1/notes/{ref}/attachments/{id}` → `blob:` URL swap |

**Fit-check.** Whether this epic waits on or pairs with the independent Fly.io deploy (EPIC-135) was an
open question at shaping time — it doesn't have to: R2 is reachable from wherever kaya runs today (the
homelab), so this ships independently of that deferred decision. Nothing here blocks on it or is blocked
by it.

**Cards:** KAN-1067 (upload path), KAN-1068 (authenticated render), KAN-1069 (auth guardrail proof,
`[mutate]`).

## R15: Org/team model — investigation only (KAN-1048)

No shape yet — this is a spike, not a build. The questions on the table: which tables gain a team/org
scope column: does `authorize_note`'s owner check become a team-membership check; how the SPA's
credential model (one PAT, one `sessionStorage` token) changes if a PAT can act on behalf of a team; and
what pandan#322's eventual answer needs to hand kaya for any of this to be buildable. This section gets
filled in once the spike reports back — the card is the source of truth until then (`pandan get
KAN-1048 --full`).
