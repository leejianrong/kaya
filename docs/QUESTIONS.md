# kaya — Questions

The decision register. Every question, who answered it, and where the answer landed.
This stays accurate after the plan is written, so a later contributor can tell a
**decision** from a **default**.

Statuses: `DECIDED` (Jian answered) · `ASSUMED` (default taken; correct it if wrong) ·
`FORK` (waiting) · `DEFERRED` (not needed this milestone).

Planning mode was **resume**: [`kaya-vision.md`](./kaya-vision.md) and pandan's ADRs
0005/0008/0011/0013/0014/0015/0018/0019 are settled input and were not re-derived. Where a row
says "pandan ADR NNNN" it means an ADR in the `pandan` repo, not this one.

## Open forks

None. Round 1 closed 2026-08-01 with five forks answered; no new forks opened.

| ID | Question | Answered |
|----|----------|----------|
| F1 | Identity contract across two apps | DECIDED → ADR 0002 |
| F2 | Hosting: Fly now or wait for the k8s homelab | DECIDED → ADR 0010 |
| F3 | First vertical slice scope and order | DECIDED → SLICES.md |
| F4 | Reuse pandan's stack verbatim, or deviate | DECIDED → ADR 0001 |
| F5 | Cross-linking direction and depth | DECIDED → ADR 0003 |

The F1/F5 decision brief (three identity options, the async-engine consequence, CodeMirror 6,
soft-vs-self-sufficient linking) is at
<https://claude.ai/code/artifact/5d18d32d-1277-4f33-8cca-60f9548bbf09>.

## Register

### Identity and authorization

| ID | Question | Status | Answer or default | Landed |
|----|----------|--------|-------------------|--------|
| Q1 | How does kaya know who a caller is? | DECIDED (F1) | Forward the bearer to a new `GET /api/v1/me` on pandan; cache the resolved user briefly. Kaya implements no token format. | ADR 0002 |
| Q2 | Where do kaya's users live? | DECIDED (F1) | A local mirror row keyed on pandan's user UUID, created just-in-time on first sight. Notes hang off the mirror. | ADR 0002 |
| Q3 | Does kaya mint its own PATs? | DECIDED (F1) | No. One mint point (pandan's Tokens tab) is what "one set of PATs" means. | ADR 0002 |
| Q4 | Shared database with pandan? | DECIDED (F1) | No. Separate database per app; the only coupling is one HTTP endpoint. | ADR 0002 |
| Q5 | Does kaya gate on the token prefix for load-shedding? | ASSUMED | No prefix logic at all. pandan still accepts `kanban_pat_…`; a `startswith` on one prefix is the exact bug pandan ADR 0018 had to correct. Kaya sheds load with a negative cache instead. | ADR 0002 |
| Q6 | What is the introspection cache keyed on? | ASSUMED | A SHA-256 of the raw token, never the raw value. TTL 60s, negative results cached 10s. | ADR 0002 |
| Q7 | Browser single sign-on in the MVP? | DEFERRED | Needs both apps under one owned apex domain; `fly.dev` is on the Public Suffix List so `*.fly.dev` origins cannot share a cookie. Arrives with the homelab. PAT auth carries the MVP. | ADR 0002, ADR 0010 |
| Q8 | Per-note sharing or ACLs? | DEFERRED | Owner-only for the MVP, mirroring pandan's pre-M5 stance. pandan's board membership model is the template when it's needed. | PLAN §Scope |
| Q9 | What does kaya do when pandan is unreachable and the token isn't cached? | ASSUMED | `503` with a structured error naming the upstream. It is never a `401` — a wrong answer about identity is worse than no answer. | ADR 0002 |
| Q40 | Does the `403` on someone else's note leak that it exists? | ASSUMED | Yes, and deliberately. A `403` tells the caller the note is real; a blanket `404` would hide that but would also leave someone who mistyped a ref hunting a note sitting right there. The bit is cheap to give up — refs come from one global sequence and already leak a rough note count (ADR 0008 §Consequences). Per-note sharing (Q8) is the trigger to revisit; "hardening" it to `404` unilaterally is a contract change and fails `test_someone_elses_note_is_a_403_and_deliberately_not_a_404`. | ADR 0002, PLAN §Authorization, SLICES §V1 |
| Q42 | Can a caller's bearer reach a log line? | DECIDED | **No, and it is enforced twice.** Structurally: the access line carries a fixed allowlist (`ACCESS_FIELDS`) with no header of any name and no query string in it. As a backstop: every record is scrubbed at serialization, so a header mapping, a `repr()` or an exception message logged by any call site — kaya's, httpx's, SQLAlchemy's — is cleaned without that call site knowing the rule exists. Guarded by `test_log_redaction.py`, which asserts against every contiguous **fragment** of a realistically-shaped fake token rather than the whole string, because a partial leak is a leak. Mutation-proven per Q32. | ADR 0002, `app/observability/redaction.py` |

### Stack and architecture

| ID | Question | Status | Answer or default | Landed |
|----|----------|--------|-------------------|--------|
| Q10 | Same stack as pandan? | DECIDED (F4) | Yes, verbatim: FastAPI, sync SQLAlchemy, psycopg v3, Postgres, Alembic, Svelte 5 runes, uv + npm, same CI shape. | ADR 0001 |
| Q11 | Does kaya carry a second async engine? | DECIDED (F4) | No. No `fastapi-users`, no OAuth client, no session table, so kaya is 100% sync — one engine, one pool. A consequence of Q1, not an independent choice. | ADR 0001 |
| Q12 | Markdown editor: build or adopt? | DECIDED (F4) | CodeMirror 6 (MIT), what Obsidian uses. Do not hand-roll. Measure the bundle in V3 and record the number. | ADR 0001 |
| Q13 | Where does output shaping live? | DECIDED (F4) | In `kaya-client`, the shared core, not in the CLI. pandan put it in `pandan_cli/cli.py`, which is exactly why its MCP adapter never inherited `--fields`/truncation and one `list_cards` costs ~45k tokens. | ADR 0004 |
| Q14 | Single deployable artifact? | ASSUMED | Yes. FastAPI serves the built SPA from one origin, per pandan ADR 0003. No new CORS surface. | PLAN §Shape S4 |
| Q15 | Monorepo or split repos? | ASSUMED | One repo, four packages: `backend/`, `frontend/`, `kaya-client/`, `kaya-cli/`, `mcp/`. Mirrors pandan, and the client is consumed by two adapters in-tree. | ADR 0001 |
| Q43 | Which TypeScript major does the SPA build on? | DECIDED | **6.0, and 7.x is blocked upstream rather than declined.** TypeScript 7.0 is the Go-native compiler and it ships *no programmatic API*: its `package.json` `exports` map resolves `"."` to `lib/version.cjs`, so `require('typescript')` yields `{version, versionMajorMinor}` and nothing else. Every tool that type-checks *through* the compiler therefore refuses it by name — `svelte-check` throws from its own `bin/ts-version-check.js`, and `typescript-eslint` throws citing [issue 10940](https://github.com/typescript-eslint/typescript-eslint/issues/10940). Microsoft says the same thing directly: "projects using Vue, MDX, Astro, Svelte, and others will need to continue using TypeScript 6.0 for now", with an API expected in 7.1. 6.0 is not a compromise but the right place to sit — it is the release that *removes* the deprecated options 7.0 hard-errors on, so V3's editor gets written on a config already cleared for the native port. **Unblock condition:** TS 7.1 ships the API, `svelte-check` and `typescript-eslint` widen their `typescript` peer ranges past 7, and `npm run check` plus `eslint .` pass unforced. Dependabot PR #20 stays open until then. **A nearer wall sits at 6.1:** every `@typescript-eslint/*` package at 8.66.0 declares `>=4.8.4 <6.1.0`, tighter than `svelte-check`'s range, so the `^6.0.3` caret is held to 6.0.3 by the lockfile and a future `typescript 6.1.x` bot PR is expected to go red on that peer range until typescript-eslint releases — the same "held, not declined" situation one minor earlier, not a new question. | KAN-704, `frontend/package.json` |

### Data model and identity of a note

| ID | Question | Status | Answer or default | Landed |
|----|----------|--------|-------------------|--------|
| Q16 | How is a note addressed? | ASSUMED | Stable integer id plus a `NOTE-n` human ref from a Postgres `SEQUENCE` (pandan ADR 0006/0009 precedent: atomic at INSERT, immutable, never reused). Every id-taking verb accepts either form. | ADR 0008 |
| Q17 | Is the folder path part of a note's identity? | ASSUMED | No. `path` is mutable metadata. Path-as-identity is what breaks Obsidian links on a move; a ref that survives rename and move is the whole point. | ADR 0008 |
| Q18 | Does a note ref survive export and re-import? | ASSUMED | Yes. Export writes the `NOTE-n` ref into front matter; import re-uses it when free and records a remap when not. Export/import itself is out of the MVP, but the ref is designed for it now because retrofitting identity is the expensive kind of change. | ADR 0008 |
| Q19 | How do `[[wikilinks]]` resolve to a target? | ASSUMED | By title at parse time, with the resolved id recorded in `note_link`. So a later rename doesn't break the recorded edge, and an unresolvable link is stored unresolved rather than dropped. | ADR 0003, ADR 0008 |
| Q20 | Where does note body text live? | ASSUMED | A Postgres `TEXT` column. Markdown is just text; no object storage in the core. | PLAN §Shape S2 |

### Concurrency, failure, and contracts

| ID | Question | Status | Answer or default | Landed |
|----|----------|--------|-------------------|--------|
| Q21 | Last-write-wins on a note body? | ASSUMED — **a deliberate deviation from pandan ADR 0007** | No. Optimistic concurrency: a write carries the `updated_at` it read, and a mismatch returns `409` with both versions. Silent LWW on 3,000 words of prose loses paragraphs and the loser never finds out. No CRDTs, no realtime — the no-realtime stance is untouched. | ADR 0009 |
| Q22 | Real-time collaboration? | DEFERRED | No. Poll/refresh, per pandan ADR 0007. Local-first sync is a different, much harder product. | PLAN §Scope |
| Q23 | What is the CLI's machine contract? | ASSUMED | Adopt pandan's verbatim rather than inventing one: errors structured on **stdout**, exit `0` ok / `1` runtime / `2` usage / `3` 401 / `4` 403 / `5` 404, and branch on a stable `code` string never on message text. | ADR 0005 |
| Q24 | CLI ↔ MCP relationship? | ASSUMED | **MCP ⊇ CLI**, stated in one place and **pinned by a test**. Nobody may write "full parity" without a verified check — pandan's skill asserted it while contradicting itself 40 lines later, and the false claim reached a roadmap card that nearly justified deleting the MCP surface. | ADR 0006 |
| Q25 | Is the MCP tool surface frozen from the start? | ASSUMED | Yes. A pinned name set and count, plus `fields` and truncation on every read tool from day one. pandan measured field breadth, not tool count, as the real cost (one `list_cards` = 44,902 tokens vs 8,775 for the whole 49-tool schema). | ADR 0006 |
| Q26 | What happens when a `[[KAN-12]]` target can't be reached? | ASSUMED | The link renders unresolved with a quiet hint. A note must save, render and appear in search with pandan completely down — an acceptance criterion, not a footnote. | ADR 0003 |
| Q27 | Does the API version go to `/api/v2` for a breaking change? | DEFERRED | No. Stay on `/api/v1` and move every client together, per pandan ADR 0013's reasoning: we own all three clients. | PLAN §Implementation decisions |

### Deployment, release, and quality

| ID | Question | Status | Answer or default | Landed |
|----|----------|--------|-------------------|--------|
| Q28 | Where does kaya run in the MVP? | DECIDED (F2) | Nowhere hosted. One OCI artifact plus k8s manifests from V1, exercised against a local k3d cluster. The homelab (pandan `KAN-439`) is kaya's first real deploy. Fly stays an explicitly open option later, not a closed door. | ADR 0010 |
| Q29 | Does `--version` identify the build? | ASSUMED | Yes, from the first release: version plus the commit it was built from, and an explicit "source checkout, not a released build" for a checkout. The release **fails** if the artifact can't identify itself. pandan retrofitted this after a stale binary caused two false bug reports. | ADR 0007 |
| Q30 | What does the version-bump guard diff against? | ASSUMED | The **base ref** (merge-base with `main`), not the previous push or the remote tip. pandan's diffs against the remote tip and false-positives on merge commits (open bug `KAN-484`). | ADR 0007 |
| Q31 | Test layering? | ASSUMED | Per `/dev-playbook`: a no-infra unit layer, an integration layer on throwaway Postgres via testcontainers, e2e that boots the stack. Pre-push mirrors the cheap CI jobs; deploy gates on green CI and ships the validated SHA. | PLAN §Testing approach |
| Q32 | How is a "this can't regress" guard proven? | ASSUMED | Mutation-test it: break the protected thing, confirm the failure names the right thing, restore **non-destructively** (`git apply -R`, not `git checkout --`). pandan found six blind guards this way in five slices. | PLAN §Testing approach |
| Q33 | Secrets in the repo? | ASSUMED | None. `.mcp.json` and `.env` ignored and scanned. Kaya holds no long-lived credential of its own — it forwards the caller's token and stores only hashes in the cache. The introspection URL is config, not a secret. | PLAN §Implementation decisions |
| Q34 | Docs site? | ASSUMED | Docs-as-code with a PR build check, mirroring pandan. Not in the MVP slices; the ADR chain in this repo is the MVP's documentation. | DEFERRED to post-MVP |
| Q41 | How is a running kaya observed? | ASSUMED | **In:** one JSON line per request on stdout, an `X-Request-Id` echoed to the caller and carried on every log line of that request (including tracebacks), and unhandled exceptions logged with that id. Stdlib `logging` with a ~130-line JSON formatter — no new dependency. **Out, deliberately:** no metrics endpoint (nothing scrapes it under ADR 0010, and an unread `/metrics` is a surface to secure for no reader), no error-tracking SaaS (a DSN is configuration for an environment that doesn't exist), no sampling (at this traffic it only loses the one request somebody is asking about), no request/response bodies. `/health` logs at DEBUG so the liveness probe doesn't drown the log. Revisit at the first homelab deploy, which is the first time anything reads these logs. | `app/observability/`, KAN-700 |

### Scope

| ID | Question | Status | Answer or default | Landed |
|----|----------|--------|-------------------|--------|
| Q35 | Attachments and images? | DEFERRED | Out. Text-only markdown in Postgres. Object storage (R2) when genuinely needed, not before. | PLAN §Scope |
| Q36 | A graph view? | DEFERRED | Out. `note_link` makes it possible later; building it now is decoration before the core works. | PLAN §Scope |
| Q37 | Embedding a live board view in a note? | DEFERRED | Out of the MVP. It's the same read API as wikilink resolution, so it's cheap to add once ADR 0003's resolver exists. | PLAN §Scope |
| Q38 | Plugin ecosystem? | DEFERRED | Never. Obsidian's plugins are its moat and its complexity. | PLAN §Scope |
| Q39 | A short CLI alias (`ky`)? | ASSUMED | No. One console script, `kaya`. pandan's `pdn` alias was withdrawn (`KAN-442`) because `[project.scripts]` entries don't exist on a PyInstaller `--onefile` release. Document the one-line symlink instead. | ADR 0007 |

## Coverage

One row per checklist category, so a skipped category is visible rather than absent.

| Category | Covered by |
|----------|-----------|
| Primary user and actors | Q1, Q3, Q23, Q24 · PLAN §Users |
| Scope boundary | Q8, Q22, Q35–Q38 · PLAN §Scope |
| Core data model and identity | Q16–Q20 · ADR 0008 |
| State and storage | Q4, Q20, Q28 |
| Concurrency and conflict | Q21, Q22 · ADR 0009 |
| Interfaces and contracts | Q13, Q14, Q23, Q24, Q25, Q27 · ADR 0004–0006 |
| Failure behaviour | Q9, Q26 · ADR 0002 §Consequences, ADR 0003 |
| External dependencies | Q10, Q12 (CodeMirror 6, MIT), Q1 (pandan as a runtime dependency of the resolver only) |
| Runtime and deployment | Q14, Q28, Q29, Q41 · ADR 0010 |
| Measurable success | PLAN §Requirements (each R carries a checkable acceptance line in SLICES.md) |
| Security and secrets | Q5, Q6, Q9, Q33, Q40, Q42 · ADR 0002 |
| Versioning and migration | Q18, Q27, Q29, Q30 · ADR 0007, ADR 0008 |
| Agent ergonomics *(domain category, added)* | Q13, Q23, Q24, Q25 · ADR 0004, 0005, 0006 |
