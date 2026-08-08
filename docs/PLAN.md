# kaya: Plan

Status: **agreed** (forks closed 2026-08-01) · Milestone: **MVP**

This is the live planning document. It absorbs what pandan splits across FRAME / PRD / CONTEXT /
SHAPING / BREADBOARD, so nothing can drift out of sync between them. The chain that matters here is:

[`kaya-vision.md`](./kaya-vision.md) (settled intent) → **PLAN.md** (this file) + [`adr/`](./adr/) →
[`SLICES.md`](./SLICES.md) · with [`QUESTIONS.md`](./QUESTIONS.md) as the decision register.

Cross-repo references: **"pandan ADR NNNN"** always means an ADR in the `pandan` repo. Bare
"ADR NNNN" means this repo's [`docs/adr/`](./adr/).

## Problem

Pandan tracks work well and holds knowledge badly, on purpose. It declined file attachments and rich
documents twice (the M5 competitive delta, the M6 shaping) because storage infrastructure sits off
the "simple" line. So a card can say *what* to do and never say *how*, and the spec, the runbook and
the meeting note that explain it live somewhere else — a local Obsidian vault an agent can't read, or
a card description that outgrew its field.

The gap bites hardest for the agent story, which is the thing pandan spent Milestone 7 sharpening. An
agent holding a PAT can claim a card, move it, and comment on it. It cannot maintain that card's spec
document as it works, because there is nowhere to put one that the same credential can reach.

## Solution

A cloud-hosted markdown notes app that feels like Obsidian and answers to an API. You write markdown
in a real editor, organise notes in folders, search the full text, and link notes to each other with
`[[wikilinks]]`. A wikilink can also point at board work: typing `[[KAN-12]]` renders the card's
title and column inline, and a backlinks panel answers "which notes mention this card".

The same PAT that drives the board drives the notes, from the same `.mcp.json`, with no second login
and no second token. An agent working `KAN-12` reads its spec note, edits it, and moves the card,
using one credential and one identity throughout. That combination is the product; either app alone
is a smaller thing.

## Users and actors

**Primary: an agent holding a PAT.** Not because humans matter less, but because the agent is the
actor whose ergonomics are measurable and whose failure modes are silent. If a read costs 45k tokens
or an error goes to stderr as prose, a human shrugs and an agent burns a context window or
misbranches. Design for the agent and the human inherits a tool with narrow reads, real exit codes,
and honest errors.

**A human author in a browser.** Writes and reads prose, wants live preview, folder organisation, and
search that finds a phrase from three weeks ago.

**A human operator at a terminal.** Drives `kaya` for scripting, CI, and the times a browser is the
slow path.

**When they conflict, the API wins and the agent's contract wins.** The UI may never do anything the
API cannot (pandan ADR 0005). And where a nicer human display would break a machine contract, the
machine contract holds: the fix is a `--format` flag, not a special case. One place this bites
concretely is truncation — a human wants the whole note, a narrow read wants 500 characters, so the
default is truncated with a true total and `--full` opts out.

## Scope

**In this milestone.**

- Create, read, edit, move and delete a note through `/api/v1`, owner-scoped.
- Folder paths as mutable metadata; a note's identity is a stable `NOTE-n` ref (ADR 0008).
- Identity shared with pandan: one account, one set of PATs, no second login (ADR 0002).
- A `kaya` CLI and a `kaya` MCP server, both thin adapters over one `kaya-client` (ADR 0004).
- The full agent-ergonomics surface from the first CLI slice, not retrofitted (ADR 0005).
- Full-text search over title and body (Postgres FTS).
- `[[wikilink]]` parsing, a `note_link` edge table, a backlinks panel, and `[[KAN-n]]` / `[[EPIC-n]]`
  resolution against pandan as a soft one-way read (ADR 0003).
- A CodeMirror 6 editor in a Svelte 5 SPA served from the same origin as the API.
- Optimistic concurrency so concurrent edits cannot silently lose prose (ADR 0009).
- Release provenance from the first release, plus a version-bump guard (ADR 0007).
- One OCI artifact and k8s manifests, exercised locally; no hosted deploy (ADR 0010).

**Out, and why.**

- **A hosted deployment.** Deferred to the homelab so kaya isn't the second app to migrate off Fly
  (ADR 0010). This is the one scope cut that makes "cloud-hosted" aspirational for the MVP, and it is
  deliberate.
- **Browser single sign-on.** Needs a shared apex domain, which arrives with the homelab (Q7). PAT
  auth carries the MVP, which is the path the primary actor uses anyway.
- **Attachments and images.** Text-only markdown in Postgres. Object storage when genuinely needed
  (Q35).
- **Per-note sharing and ACLs.** Owner-only, mirroring pandan's pre-M5 stance (Q8).
- **Real-time collaboration and local-first sync.** Poll/refresh, per pandan ADR 0007. Local-first is
  a different and much harder product (Q22).
- **A graph view** (Q36) and **an embedded live board view** (Q37). Both become cheap once
  `note_link` and ADR 0003's resolver exist, which is the argument for not building them now.
- **A plugin ecosystem.** Never (Q38).
- **Export and import.** Not built, but the `NOTE-n` ref is designed to survive it, because
  retrofitting identity is the expensive kind of change (Q18).

## Requirements

| ID | Requirement | Status |
|----|-------------|--------|
| **R0** | A note can be created, read, edited, searched and linked to board work through one API that the UI, CLI and MCP all use, under the same identity as pandan | Core goal |
| **R1** | One account and one PAT span both apps; kaya implements no token format and mints no tokens | Must-have |
| R1.1 | An unreachable pandan never produces a wrong answer about identity | Must-have |
| **R2** | Every UI action is a plain `/api/v1` call; the SPA has no privileged path | Must-have |
| **R3** | The machine-facing surface is agent-ergonomic from its first slice, not retrofitted | Must-have |
| R3.1 | `--fields` projection on every list verb, with a vocabulary derived from the payload's own keys | Must-have |
| R3.2 | Errors structured on **stdout** with a documented exit-code scheme; branch on a stable code, never on message text | Must-have |
| R3.3 | A pre-computed aggregate on every list verb, describing the returned set | Must-have |
| R3.4 | Content truncated by default with a **true** total, and `--full` to opt out | Must-have |
| R3.5 | Bare invocation prints live state and exits `0`; `--help` still prints usage | Must-have |
| R3.6 | Results carry `help[]` next-step templates with placeholders left unfilled | Must-have |
| R3.7 | `--format {human,json,toon}` over **one** shared serializer, so the formats cannot drift | Must-have |
| **R4** | Full-text search over title and body, reachable from API, CLI and MCP | Must-have |
| **R5** | `[[wikilinks]]` resolve to notes and to `KAN-`/`EPIC-` tickets; backlinks are queryable | Must-have |
| R5.1 | A note saves, renders and appears in search with pandan completely down | Must-have |
| **R6** | An MCP server that ships `fields` and truncation from day one, with the CLI relationship documented **and pinned by a test** | Must-have |
| **R7** | `--version` identifies the **build**; a release refuses to ship an artifact that can't identify itself | Must-have |
| R7.1 | A behavioural change to a shipped package bumps its version in the same PR, enforced against the **base ref** | Must-have |
| **R8** | A markdown editor with live preview and wikilink autocomplete | Must-have |
| **R9** | Concurrent edits to one note cannot silently lose prose | Must-have |

## Shape

The mechanisms. Each part is something built, not an intention. Data sits with the feature that needs
it, so there is no horizontal "data model" part.

| Part | Mechanism | ADR |
|------|-----------|-----|
| **S1** | **Principal resolver.** A sync FastAPI dependency: take the bearer, look up `sha256(token)` in a TTL cache, on a miss call pandan's `GET /api/v1/me` with the bearer forwarded verbatim, mirror the returned UUID into a local `user` row if absent, return that row. No prefix inspection anywhere. | ADR 0002 |
| **S2** | **Note store.** `note` (id, `NOTE-n` ref from a sequence, owner_id → user mirror, title, body TEXT, path, created_at, updated_at) with a `updated_at` precondition on every write returning `409` on mismatch. | ADR 0008, 0009 |
| **S3** | **`kaya-client`** — the shared core, and the only place that shapes a payload. One `render(payload, fields, limit, format)` seam carrying projection, truncation, aggregate attachment and human/json/toon serialization. Both adapters call it; neither reimplements it. | ADR 0004, 0005 |
| **S4** | **`/api/v1` + single-artifact serving.** REST/JSON under `/api/v1`, OpenAPI at `/docs`, FastAPI serving the built SPA from the same origin. One sync engine, one pool, no async anywhere. | ADR 0001 |
| **S5** | **`kaya` CLI** — argv → `kaya-client` → `render` → stdout. Errors are structured rows on stdout; exit codes come from a named-code table so a raise site picks a meaning, never a number. | ADR 0005 |
| **S6** | **`kaya` MCP server** — a thin adapter over the same client, so `fields` and truncation exist on day one by construction. A frozen tool-name set and count, asserted in a test. | ADR 0006 |
| **S7** | **Search.** A generated `tsvector` column over title + body with a GIN index, exposed as `--q` on the list verb, exactly as pandan V15 does it. | — |
| **S8** | **Wikilink resolution.** A parser extracting `[[…]]` on save, a `note_link` edge table recording (source note, target kind, target ref, resolved id or null), and a resolver that batches `KAN-`/`EPIC-` refs to pandan with the caller's PAT, caches, and degrades to unresolved. | ADR 0003 |
| **S9** | **Editor SPA.** CodeMirror 6 mounted once against an element ref, markdown language + decorations for wikilink pills + an autocomplete source; a folder tree; a backlinks panel. Svelte never renders inside CM6's subtree. | ADR 0001 |
| **S10** | **Release and guards.** Build-stamped `--version`, a release job that fails on an unidentifiable artifact, and a version-bump guard diffing against the merge-base with `main`. | ADR 0007 |

## Affordances

**UI.** Places a person sees and acts on.

| Affordance | Place | Wires to |
|------------|-------|----------|
| Folder tree, note list | Sidebar | `GET /api/v1/notes` |
| Markdown editor with live preview | Main pane | `GET`/`PATCH /api/v1/notes/{ref}` |
| Wikilink autocomplete on `[[` | Editor popup | `GET /api/v1/notes?q=` |
| Wikilink pill showing card title + column | Editor + preview | `GET /api/v1/notes/{ref}/links` (resolved server-side) |
| Backlinks panel | Right rail | `GET /api/v1/notes/{ref}/backlinks` |
| Search box | Top bar | `GET /api/v1/notes?q=` |
| Conflict notice with both versions | Editor banner | the `409` body from `PATCH` |
| Sign-in prompt pointing at pandan | Landing | pandan's origin, from `KAYA_PANDAN_URL` |

**Non-UI.**

| Affordance | Kind | Wires to |
|------------|------|----------|
| `get_principal` | FastAPI dependency | pandan `GET /api/v1/me`, TTL cache, user mirror |
| `authorize_note` | FastAPI dependency | note.owner_id vs principal |
| `KayaClient` | shared library | `/api/v1` over httpx |
| `render()` | shared library seam | projection, truncation, aggregates, human/json/toon |
| `kaya note {list,get,create,edit,move,delete}` | CLI verbs | `KayaClient` |
| `kaya note list --q` | CLI flag | `GET /api/v1/notes?q=` |
| `kaya links`, `kaya backlinks` | CLI verbs | link + backlink reads |
| MCP `list_notes`, `get_note`, `create_note`, `edit_note`, `search_notes`, `get_backlinks` | MCP tools | `KayaClient`, each with `fields` |
| Link resolver | background-on-save handler | wikilink parser → `note_link` |
| Version-bump guard | pre-push hook + CI job | merge-base diff |

## Implementation decisions

**Modules and boundaries.** Five packages in one repo: `backend/` (FastAPI + Alembic),
`frontend/` (Svelte 5 SPA), `kaya-client/` (the shared core), `kaya-cli/`, `mcp/`. The dependency
arrows point one way: adapters depend on the client, the client depends on the HTTP contract, and
nothing depends on an adapter. `kaya-client` owns every decision about what a payload looks like
(ADR 0004); an adapter owns only how it gets its arguments.

**The `/api/v1` contract.** REST/JSON, OpenAPI-described, auth-required on every route. Notes are
addressed by `NOTE-n` **or** bare integer id, and both forms must produce identical results including
identical error codes for a missing note — pandan shipped a version where the code depended on the
identifier form and had to fix it in the resolver rather than at each call site. A breaking change
moves every client together on `/api/v1` rather than minting `/api/v2` (Q27): we own all three
clients, which is the same reasoning pandan ADR 0013 used.

**List envelopes are the contract, not an accident.** A list verb returns
`{"notes": [...], "summary": {...}}` and carries `next_cursor` when the page is full; a single read
returns a bare object. Pandan's shape differs per verb because the envelope grew organically, and its
skill needed a whole table to document which verb returns what. Kaya fixes the envelope shape once,
up front, and pins it.

**Authorization.** One resolver, one check, mirroring pandan ADR 0013's structure: `get_principal`
→ a local `user` row, then `authorize_note(principal, note)` allowing only the owner. A `404` for a
note that doesn't exist, a `403` for one that isn't yours, and list endpoints scoped to the caller
rather than silently empty.

**Secrets.** Kaya holds no long-lived credential of its own. It forwards the caller's token upstream
and stores only `sha256` digests in the cache, so a heap dump or a log line cannot leak a live PAT
(Q33). `KAYA_PANDAN_URL` is configuration, not a secret. `.env` and `.mcp.json` are ignored and
scanned.

**Dependencies.** Lockfiles committed and installs frozen, which kaya had from the first commit;
automated updates and a vulnerability report, which it did not until KAN-699. Updates come from
**Dependabot** — one weekly window across the four uv packages, the SPA and `github-actions` — chosen
over renovate because `kaya-cli` and `mcp` declare `[tool.uv.sources]` path dependencies on
`../kaya-client`, and renovate's open bug on that layout updates the shared package's lockfile while
leaving the consumer's stale. Vulnerabilities are a **report, not a gate**: `make audit` runs
`npm audit` and `pip-audit` over the committed lockfiles, and a weekly workflow writes what it finds
into a single issue. The gate stays out because an advisory arrives on a third party's timetable — a
transitive dev advisory nobody can fix would otherwise redden every open PR, which is how a gate gets
bypassed rather than satisfied, and the same argument that keeps the history secret scan on demand.
Dependabot raises a PR for everything fixable; the issue names the residue.

**Config.** Per-app prefix, each key resolved independently from the first source that supplies it:
environment → user config file → nearest `.mcp.json`. `KAYA_API_URL`, `KAYA_TOKEN`,
`KAYA_PANDAN_URL`, `KAYA_MAX_TEXT_CHARS`. No legacy fallback tier, because kaya has no legacy.

**Naming.** The PyPI distribution name is `kaya-notes`; bare `kaya` is an abandoned stub (pandan ADR
0018 §Package-name reality). This constrains the **distribution** name only. The console script is
`kaya`, and there is exactly one of them (Q39).

## Testing approach

Per `/dev-playbook`, layered by cost and gated by layer, with the rule that keeps it honest: a slow
check never gates a local push.

**The seams worth testing, fewest and highest.** Four, and they carry nearly everything:

1. **`render()` in `kaya-client`.** Every projection, truncation and format guarantee is one function
   away from its assertion, and because both adapters go through it, a test here covers the CLI and
   the MCP server at once. The formats prove themselves by **round-trip equality** against the same
   payload, not by golden strings.
2. **The principal resolver, with pandan faked at the HTTP boundary.** Inject the upstream client so
   unit tests need no network: valid token, revoked token, cache hit, cache miss, upstream down,
   upstream slow. This is where R1.1 lives.
3. **`/api/v1` against a throwaway Postgres** via testcontainers, covering authorization, the `409`
   precondition, search, and identifier round-trips.
4. **The e2e stack booting itself**, with self-cleaning prefixed data, for the editor and the
   conflict banner.

**What makes a good test here.** External behaviour: the bytes on stdout, the exit code, the HTTP
status, what a person sees. Not internals. Keep every `import app.*` inside a test or fixture body in
the integration layer, never at module top — a top-level import binds the engine before the fixture
sets `DATABASE_URL`, which passes locally against a dev database and fails in CI. That's pandan's
PR #17 trap and it costs an afternoon to diagnose.

**Every "this can't regress" guard is mutation-tested** (Q32). Break the protected thing, confirm the
failure names the right thing, restore with `git apply -R` rather than `git checkout --`, which would
silently discard uncommitted work. Pandan found six blind guards this way across five slices, and
every one was an assertion that passed for the wrong reason: an `x in out` check that's vacuously
true for an empty string, an arithmetic identity that holds when both sides are zero. The guards in
this plan that get this treatment: the frozen MCP tool set, the parity check, the version-bump guard,
the default human row's byte-identity, and R5.1's pandan-down behaviour.

**Gates.** Pre-push runs lint, type-check and the no-infra layer. CI runs one job per concern in
parallel with lockfile-frozen installs and caching. There is no deploy gate to arm yet (ADR 0010), so
the release job is the last gate in the MVP, and it fails on an artifact that can't identify itself.

## Assumed defaults

Decisions taken without asking. Each one is a default, not a conclusion — the register row has the
reasoning.

| ID | Assumed | Cost if wrong |
|----|---------|---------------|
| Q6 | 60s cache TTL, so a revoked PAT works in kaya for up to a minute | Lower the TTL, or have pandan push revocations. Hours. |
| Q9 | Unreachable pandan on a cache miss is `503`, never `401` | None; the alternative is the bug. |
| Q16 | Note identity is a `NOTE-n` sequence ref, not a path or a slug | A migration plus a link rewrite. Days, and the reason this is decided now. |
| Q19 | Wikilinks resolve by **title** at parse time, with the id recorded | Change the parser and re-resolve every edge. A day. |
| Q21 | Optimistic concurrency instead of pure LWW — **a deliberate deviation from pandan ADR 0007** | Drop the precondition and the `409` handling. Half a day, and it's additive so the risk is unnecessary work, not lost work. |
| Q23 | Pandan's exit-code scheme adopted verbatim | Renumbering a published contract. Avoided precisely by adopting rather than inventing. |
| Q25 | The MCP surface is frozen from slice one | Amend the ADR and unpin the count. Minutes, by design. |
| Q30 | The version-bump guard diffs against the merge-base | It false-positives on merge commits, which is pandan's open `KAN-484`. Cheap to fix, and known before it's written. |
| Q39 | One console script, no short alias | Nothing; the symlink is documented. |

## Open risks

| Risk | Earliest slice that reveals it |
|------|-------------------------------|
| ~~**Introspection latency is worse than tolerable — and on a cold upstream it is.**~~ **MEASURED 2026-08-08 by KAN-539, MITIGATED the same day by KAN-666.** KAN-539, real PAT against `simple-kanban-jian.fly.dev` and real Postgres: cache hit **1.6 µs** [n=2000], warm miss **387 ms** [n=15] of which 383 ms is the round trip and 4.7 ms the mirror write, cold miss **21.8 s** [n=3: 11.4, 21.8, 23.2] — every cold sample outside the then-single 10 s deadline, so a cold pandan returned `503` on a valid PAT rather than making the caller wait. KAN-666 asked the question KAN-539 had not: *where* in the round trip does the cold time sit? `--split-only` times one call at the socket and separates connect (DNS + TCP + TLS) from read (the wait for the first response byte). **Connect is 67–103 ms [n=5] and flat while read varies 392–650 ms**, and the `*.fly.dev` certificate is presented by fly's shared edge two `fly.io` hops in front of pandan, so the app machine is not in the handshake path at all. The deadline is therefore split — `KAYA_PANDAN_CONNECT_TIMEOUT_SECONDS` 5 s, `KAYA_PANDAN_READ_TIMEOUT_SECONDS` 30 s — and concurrent misses on one token are coalesced into one upstream call (`app/auth/single_flight.py`), without which a 30 s budget would hold one of Starlette's 40 threadpool workers per concurrent request and stall note saving, which is the coupling ADR 0003 forbids. **The residual, stated plainly:** all five KAN-666 samples came back warm — pandan would not stay idle long enough during the session — so the cold *connect* number is inferred from the edge-termination mechanism rather than measured. The split is safe regardless, because it cannot be worse than the single deadline it replaces, but a genuinely cold `--split-only` sample would still be worth taking. | Measured in **V1** as planned, on both a cold and a warm upstream. KAN-539 opened it; KAN-666 closed it. |
| **CodeMirror 6 and Svelte 5 runes fight over the DOM.** A naive rune binding to the document creates an update loop. The pattern is known, not researched, but it's the only frontend unknown with teeth. | **V3**, and it can't invalidate the data model or the API, which is why it isn't slice one. |
| **`render()` becomes a god function.** Putting every shaping concern in one seam is what makes the adapters thin; it's also how that seam grows into something nobody wants to touch. | **V2b**, when the fourth concern lands in it. Watch for it there. |
| ~~**Wikilink resolution costs a fan-out.**~~ **SETTLED 2026-08-01 by [spike 0001](./spikes/0001-wikilink-ref-batching.md), and the premise was wrong.** There is no fan-out available: a wikilink carries a ticket ref and no pandan route accepts one, so there are no reads to make. The mechanism is a bounded, cached list sweep that scales with **board size, not ref count**. V5 does not wait on pandan. | Revealed early, in the spike, rather than mid-slice. See ADR 0003 §Amendment. |
| **The MVP has no hosted deployment**, so nothing is proven under a real origin, real TLS, or a real cookie until the homelab lands. | Reveals at the homelab, not in a slice. Accepted knowingly (ADR 0010); the manifests and the local cluster are the hedge. |
