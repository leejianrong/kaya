# CLAUDE.md: agent brief for `kaya`

## What this is

A cloud-hosted markdown notes app, API-first and agent-drivable: the docs half of the `kayatoast`
suite, sibling to [pandan](https://github.com/leejianrong/pandan) (the kanban board). Where pandan
tracks *work*, kaya holds the *knowledge*.

Five packages, one dependency arrow (ADR 0001): `kaya-cli` and `mcp/` are thin adapters over
`kaya-client` (all payload shaping, meaning projection, truncation, aggregates and serialization,
lives there, never in an adapter); `frontend/` is a SPA that calls `backend/` directly; nothing
depends on an adapter, **with one narrow, deliberate exception since KAN-1744**:
`backend/app/identity/mcp_host.py` imports `kaya_mcp.server.server` to host the Streamable HTTP
transport on the same origin (ADR 0014 argues why).

**Status: past the MVP.** `docs/PLAN.md`'s R0-R9 are a closed, frozen record. Post-MVP work (R10
onward, `docs/PLAN.md` §Beyond the MVP, shaped in
[`docs/roadmap/BREADBOARD.md`](docs/roadmap/BREADBOARD.md)) has shipped a graph view, board embeds,
export/import, version history, attachments, a Fly.io deploy, a Settings page with format-on-save,
standalone identity (EPIC-283), device-flow login and a hosted remote MCP endpoint (EPIC-284, docs
pass pending), and a mobile-first shell with a Read/Edit/Split mode switch (EPIC-305). Open: the
org/team model (R16, ADR 0011), brand and landing page (EPIC-306), and Fly DNS/TLS (needs-human).
Pandan board 18 ("kaya - Notes") is the source of truth for what is in flight; read it before
trusting this paragraph.
**The published binary lags `main`**: check `gh release list --repo leejianrong/kaya` and each
package's `pyproject.toml` before trusting a version number quoted in any doc, this file included.
The full history, every measured number and the KAN-card provenance behind each rule below live in
[`docs/ENGINEERING_NOTES.md`](docs/ENGINEERING_NOTES.md); read it for the *why*, not for day-to-day work.

**Trust the code over the docs.** When this file and the repository disagree, the repository is
right and this file is stale. Fix it in the same PR.

## How the docs relate

[`docs/kaya-vision.md`](docs/kaya-vision.md) (intent) → [`docs/PLAN.md`](docs/PLAN.md) +
[`docs/adr/`](docs/adr/) (the *why*; amend, don't re-litigate) →
[`docs/SLICES.md`](docs/SLICES.md) (the seven MVP slices) →
[`docs/roadmap/BREADBOARD.md`](docs/roadmap/BREADBOARD.md) (everything after), with
[`docs/QUESTIONS.md`](docs/QUESTIONS.md) as the decision register (a row marked `ASSUMED` was taken
on the maintainer's behalf; correct it if wrong). "pandan ADR NNNN" is an ADR in the pandan repo;
bare "ADR NNNN" is this repo's. `docs/guide/` is the published user site (Zensical) and is separate
from the planning docs. Read `PLAN.md` before anything substantial.

## The decisions you will trip over

1. **Payload shaping lives in `kaya-client`, never in an adapter** ([ADR 0004](docs/adr/0004-shaping-lives-in-the-shared-client.md)).
   `kaya_cli.verbs` opens a session, calls one client method, returns a `Payload`; `__main__.main`
   calls `render()` on exactly one line.
2. **Kaya mints and verifies its own credentials** ([ADR 0012](docs/adr/0012-standalone-identity.md),
   supersedes ADR 0002). `get_principal` resolves a cookie session or a `kaya_pat_…` bearer against
   kaya's own tables (`app/identity/`, `app/auth/kaya_principal.py`), a local lookup that never calls
   pandan. Sign-in is GitHub OAuth; the CLI uses device flow (`kaya auth login/logout/check`, ADR 0013;
   the verb is `check`, not `status`, because `context` already owns that word); the hosted MCP endpoint
   is Streamable HTTP at `/mcp` (ADR 0014, authorization_code+PKCE, long-lived `kaya_pat_…`, no refresh
   rotation). Existing notes' `owner_id` still points at the retired pandan-mirror `user` table and is
   unreachable under a new `KayaAccount` id: an accepted cutover cost (BREADBOARD R19), not a bug. The
   board-embed preview uses its own explicitly linked pandan credential (`/api/v1/pandan-link`,
   `app/api/embeds.py`), never the caller's kaya bearer. Card-by-card detail is in ENGINEERING_NOTES.
3. **`render()`'s signature is frozen** ([ADR 0005](docs/adr/0005-born-agent-conformant.md)). If a
   change needs to alter it, stop: that is the sequencing violated. Six shipped features found
   another answer (e.g. `Payload.limited_to()` applied at the call site).
4. **Nothing in kaya may block on pandan** ([ADR 0003](docs/adr/0003-cross-linking-one-way-soft.md)).
   A note saves, renders and appears in search with pandan down; wikilink resolution degrades to
   unresolved; team-default access (ADR 0011) soft-fails the same way. Kaya never calls pandan to
   authenticate anyone.
5. **A note's identity is its `NOTE-n` ref, never its path or title** ([ADR 0008](docs/adr/0008-note-identity.md)).
   `path` is mutable metadata; moving a note is a `PATCH` to one column, no link rewriting.

## The frontend shell (KAN-1818/1819)

New UI work starts at `frontend/src/lib/windowClass.ts`: the window class (`compact` < 600 <=
`medium` < 840 <= `expanded`) is the one structural signal for what renders. Three pure modules, each
unit-tested without a browser, decide everything; components only consume them.

- **`lib/windowClass.ts`** owns the 600/840 breakpoints. CSS cannot import them, so stylesheets
  mirror the numbers, and `tests/window-class.test.ts` fails if a shell stylesheet uses any other
  width (the one allowance is the 60rem split stack). Do not invent a third breakpoint.
- **`lib/shell.ts`** (`shellRegions`) says which regions render: compact is a bottom nav with the
  list and the note as separate screens; `supportingSurface` says backlinks/history are a modal
  bottom sheet on compact (opened by the top bar's Links button) and an on-demand pane on medium
  (below the note) and expanded (beside it), closed by default, open state remembered per class.
- **`lib/noteMode.ts`** owns Read | Edit | Split (`ModeSwitch.svelte`). It replaced the Preview
  toggle, which is gone. Split exists only at `expanded` and is *hidden*, never disabled, below 840;
  expanded opens in Edit, narrower opens a saved note in Read and a just-created one in Edit. The mode
  changes the layout around `EditorPane`, never its mount.
- Tokens, the pandan link and format-on-save live under **Settings** now (routes `/tokens`,
  `/pandan` unchanged); `tokens` and `device` render in `main` alone and are reachable with no
  credential.

## Rules that aren't visible in any one file

These have tests; you will meet them as a failing build otherwise. Full accounts are in
[`docs/ENGINEERING_NOTES.md`](docs/ENGINEERING_NOTES.md).

- **Every note identifier resolves through `backend/app/api/refs.py`**: a route never parses one
  itself; it depends on `NoteFromRef` and gets a `Note`.
- **A note *list* query is scoped in SQL inside `app/auth/authorization.py`, and nowhere else**;
  `tests/unit/test_no_unscoped_note_query.py` checks it at the AST/statement level. A *single*-note
  fetch is deliberately unscoped (so `authorize_note` can tell 404 from 403). `note_link` has no
  owner column, so any query touching it must constrain `source_note_id`.
- **`note.search_vector` is Postgres-generated (`Computed(..., persisted=True)`) and nothing else may
  write it.** It is `deferred` and absent from `NoteRead` (a pinned key-list test). Alembic
  autogenerate does *not* diff a generated column's expression: deleting just the `Computed(...)`
  wrapper is a silent `pass`.
- **The formatter protects every `[[…]]` span and declines rather than change a note's link edges**
  (`app/markdown_format.py`): bare `mdformat` turns `[[KAN-12]]` into `\[[KAN-12]\]` and one save
  would delete a graph edge. `format: true` is a body write, so `if_updated_at` guards it.
- **Search order is `ts_rank DESC, note.id DESC`**; the `id` tie-break is load-bearing (equal ranks
  are common, and `updated_at` can't substitute: `now()` is transaction start).
- **A backlink is found by `resolved_id`, never by title.** An edge with `resolved_id IS NULL` is a
  link to a title, not yet a note.
- **`/links` may call pandan; it may never hold a Postgres connection while doing it**
  (`_release_the_connection`): sync handlers share a 40-thread pool with note saves.
- **Never log a header, a request object, or anything built from a bearer.** Redaction happens at
  serialization (`app/observability/`).
- **The SPA fallback (`app/spa.py`) refuses a fixed list of reserved namespaces**, so
  `/api/v1/notes/NOTE-9999` stays a `404`, not `200 text/html`.
- **Svelte owns the editor's `<div>` container and never its children** (`EditorPane.svelte`): CM6
  builds everything inside. The identity guard (`needsRemount`) and echo guard
  (`needsDispatch`/`syncDocument`) in `lib/editor.ts` are pure predicates and not interchangeable;
  `view.destroy()` lives in a *second* effect that reads nothing.
- **CodeMirror and the markdown parser sit behind a lazy `import()`, only inside the effect that
  reads nothing** (`lib/codemirror.ts`, `lib/markdown.ts`). `tests/module-graph.ts` guards that
  nothing else in `src/` imports `@codemirror/*`.
- **A search is never rendered by the folder tree** (`Sidebar.svelte`): grouping by `path` destroys
  `ts_rank` order, so a search forces the flat list and hides the view toggle.
- **One module owns "the bearer for a request"** (`lib/auth.ts`): the token lives in
  `sessionStorage`, never `localStorage` or a cookie, and `credentialState()` returns `set`/`not set`
  only. It is separate from `lib/identity.ts`'s cookie-session seam on purpose.
- **A linked pandan PAT is encrypted at rest, never hashed** (`app/identity/pandan_link.py`, Fernet
  keyed from `KAYA_AUTH_SECRET`): it must be handed back to pandan raw. Known, tracked gap:
  `app/integrations/card_resolution.py` (wikilink resolution) still forwards the caller's kaya bearer,
  which is no longer a pandan credential, so it degrades to "unresolved" (ADR 0003).
- **A `PATCH` is guarded only if `if_updated_at` is sent, and only over `body`** (ADR 0009). The CLI's
  only guard flag is `--if-updated-at`; there is no `--force`, and the client never fetches the
  precondition itself.
- **`kaya note move` delegates to `update_note`, never its own endpoint** (ADR 0008), pinned
  byte-identical on the wire against `edit --path`.
- **A config write is read-modify-write** (`kaya_client/config.py`): JSON, so a hand-set key like
  `max_text_chars` survives. `config show` prints `set`/`not set`, never a fragment.
- **No verb prompts, and `note delete` has no `--yes`** (ADR 0005 §contract 9), asserted over the
  CLI's AST.
- **A build states its own provenance or says it can't** (ADR 0007): `--version` is `kaya X.Y.Z (sha)`
  or `kaya X.Y.Z (source checkout, not a released build)`.
- **Base images are pinned by digest, never by tag** (`scripts/check-image-pins.sh`).
- **The API error shape is `{"error": {"code","message",…}}` everywhere**, Starlette's own 404/405
  included. The client mirrors it and owns the only CLI-local translation: exit codes in
  `kaya_cli/failures.py` (`0` ok · `1` runtime · `2` usage/400/422 · `3` 401 · `4` 403 · `5` 404 ·
  `6` 409), add-only, pinned by literal-value tests.

## Two inherited traps

- **Keep every `import app.*` inside a test/fixture body in the integration layer, never at module
  top.** A top-level import runs at collection, before the DB fixture sets `DATABASE_URL`.
- **Alembic autogenerate needs models imported in `env.py`**, or it will drop your tables, and it
  never diffs a generated column's expression (see `search_vector`).

## Commands

`make help` is the source of truth. Python via **`uv`** (3.12), the SPA via **`npm`** (Node 24.15+).

```bash
make hooks             # install the pre-push gate; once per clone
make install           # uv sync every Python package + npm ci
make dev               # db, then backend :8000 and SPA :5173 together
make up                # db + migrate + the app image, one origin on :8000
make k3d               # deploy/k8s to a local cluster, then prove the pod serves
make test              # the fast, no-infra layer (what pre-push runs)
make test-integration  # real Postgres via testcontainers (needs Docker)
make check             # docs-links + secret-scan + image-pins + version-bump + lint + test
make audit             # npm audit + pip-audit (network; NOT in `check`)
```

**`make up` forwards only `DATABASE_URL` and `KAYA_PANDAN_URL`** into the app container
(`docker-compose.yml`'s `app.environment:`); every other `Settings` field silently takes its default.
To use a non-default value, or to sign in (GitHub OAuth variables), run the backend directly:

```bash
cd backend && KAYA_CARD_RESOLUTION_CONNECT_TIMEOUT_SECONDS=1 uv run uvicorn app.main:app --port 8000
```

Fastest frontend loop, against a stack you already have up:

```bash
cd frontend && KAYA_BACKEND_ORIGIN=http://localhost:8010 KAYA_SPA_PORT=5180 npm run dev
```

The dev proxy covers `/api` only. Set a credential from the browser console into
`sessionStorage['kaya.token']`, never from a shell command that would echo it. Re-measure bundle size
and the `toon` delta (commands in `frontend/README.md`) whenever a CodeMirror/Lezer package or a
serializer changes; quote a `gzip -9` number and say which chunk it is for.

## Conventions

**Branching.** One branch per slice off fresh `main`. PR-only; `main` is protected and requires
branches to be up to date, so `gh pr update-branch` after each merge.

**Worktrees.** [treehouse](https://github.com/kunchenguid/treehouse) (`treehouse.toml`):
`treehouse get --lease` / `treehouse return <path>`. A fresh tree needs `make install` before
`make lint` works. Only `make dev`/`make db` need a per-tree database
(`COMPOSE_PROJECT_NAME=kaya-x KAYA_DB_PORT=5433 make db`).

**Tests.** Layered by cost (`docs/PLAN.md` §Testing approach): fast/no-infra, real-Postgres, e2e. A
slow check never gates a local push. Every bug and flake becomes a test, written failing first.

**Orchestrating sub-agents.** Hard limit: **at most 2 concurrent sub-agents** (Agent-tool /
worktree-isolated) driving this repo at once, the maintainer's explicit cap. The machine is shared,
and parallel `uv sync` + `npm ci` + pytest + vitest runs flake an otherwise-passing pre-push past 2.
Start the next card once a running agent's PR is up, not by fanning out wider.

**Mutating a guard to prove it fires** (anything marked `[mutate]` in `SLICES.md`): break the
protected thing, confirm the failure names the right thing, restore. **Commit the card's work before
you mutate anything, and restore with `git apply -R` or `git stash`, never `git checkout --` or
`git restore`** (reversing a diff on a dirty tree deletes uncommitted work; this has happened).
Check `git status --short` is clean before trusting the result. And a structural guard does not
cover a behavioural claim: before citing a guard as covering new behaviour, mutate that behaviour and
watch that guard fail.

**Versioning.** A behavioural change to a shipped package (`kaya-cli`, `kaya-client`, `mcp`) bumps
its version in the same PR (ADR 0007), enforced by `scripts/check-version-bump.sh` (it classifies a
`pyproject.toml` change by *which table* moved; `uv.lock`-only and `dev`-extra changes don't count,
`[project.dependencies]` does). Docs-only and image-only PRs need no bump.

**Cutting a release.** Land the version bump, then `git tag v0.X.0 <merged-sha> && git push origin
v0.X.0`. The tag must equal `v` + `kaya-cli`'s `[project].version`. Never push a tag from a branch.
`build` runs in `quay.io/pypa/manylinux_2_28_x86_64` (glibc floor 2.28);
`scripts/check-release-artifact.sh` is the guard, and ENGINEERING_NOTES explains why.

**Dependencies.** Lockfiles committed, installs frozen, updates by Dependabot. Don't move `make
audit` into the pre-push hook or `make check` (unfixable transitive advisories teach `--no-verify`).
No `docker` ecosystem on the bot (digest pins). Frontend TypeScript is pinned `^6.0.3`; see
ENGINEERING_NOTES before forcing it past a red Dependabot PR.

**Docs.** Ban the phrase "full parity". State the direction (`MCP ⊆ CLI`) and link
[`mcp/README.md`](mcp/README.md), the one canonical place for it, rather than restating it. A README
or screenshot changes in the same PR as the UI it shows; screenshots live in `docs/images/`.

**Adding a package directory turns on its CI jobs.** A new package needs, from its first commit, a
committed lockfile, lint passing and at least one real test.

**Sprint retros** live in kaya itself: a running index note `meta/retros` links to one note per
sprint, `retros/sprint-N` (N is the pandan cycle number), written by whoever closes the sprint on
board 18 before the next sprint's planning. Convention history is in ENGINEERING_NOTES.

## Board access

The `pandan` CLI drives board 18 ("kaya - Notes"). **Never print or paste the PAT**: it lives in
`~/.config/pandan/config.toml` and `pandan` finds it on its own; `pandan config show` redacts it.

```bash
pandan warmup                        # the API scales to zero; wake it first
pandan list --board 18 --column todo
pandan next --board 18               # highest-priority unblocked card
pandan get KAN-530
```
