# CLAUDE.md: agent brief for `kaya`

## What this is

A cloud-hosted markdown notes app, API-first and agent-drivable — the docs half of the `kayatoast`
suite, sibling to [pandan](https://github.com/leejianrong/pandan) (the kanban board). Where pandan
tracks *work*, kaya holds the *knowledge*.

Five packages, one dependency arrow (ADR 0001): `kaya-cli` and `mcp/` are thin adapters over
`kaya-client` (all payload shaping — projection, truncation, aggregates, serialization — lives there,
never in an adapter); `frontend/` is a browsable SPA that calls `backend/` directly; nothing depends
on an adapter.

**Status: the MVP is done, and kaya is past it.** All six planned slices shipped (V1 backend, V2a/V2b
CLI, V3 SPA editor, V4 search, V5 cross-linking including wikilink autocomplete, V6 MCP — all six MCP
tools work); `docs/PLAN.md`'s R0–R9 are a closed, frozen record. Work now underway is **post-MVP**,
tracked as R10 onward in `docs/PLAN.md` §Beyond the MVP and shaped in
[`docs/roadmap/BREADBOARD.md`](docs/roadmap/BREADBOARD.md): a graph view, an embedded board view,
export/import, version history, attachments, and an independent Fly.io deploy have all shipped
(EPIC-135's own DNS/TLS finishing touch is the one piece still open, needs-human on a domain the
maintainer chose to defer). An org/team model (R16, ADR 0011) is now under active build, unblocked once
pandan shipped its own Teams milestone. Pandan board 18 ("kaya — Notes") is the day-to-day source of
truth for what's in flight; read it before trusting this paragraph's snapshot.
**The published binary lags `main`** — check `gh release list --repo leejianrong/kaya` and each
package's `pyproject.toml` version before trusting a specific number quoted in any doc, this file
included. Full slice-by-slice history, every measured number, and the KAN-card provenance behind each
rule below live in [`docs/ENGINEERING_NOTES.md`](docs/ENGINEERING_NOTES.md) — read it when you need the
*why* in full, not for day-to-day work.

**Trust the code over the docs.** When this file and the repository disagree, the repository is
right and this file is stale. Fix it in the same PR.

## How the docs relate

[`docs/kaya-vision.md`](docs/kaya-vision.md) (settled intent) → [`docs/PLAN.md`](docs/PLAN.md) +
[`docs/adr/`](docs/adr/) (the *why*, ten ADRs — amend, don't re-litigate) →
[`docs/SLICES.md`](docs/SLICES.md) (the seven **MVP** build slices, matching board 18's original seven
epics) → [`docs/roadmap/BREADBOARD.md`](docs/roadmap/BREADBOARD.md) (everything after — board 18 has
grown four more epics since), with [`docs/QUESTIONS.md`](docs/QUESTIONS.md) as the decision register (a
row marked `ASSUMED` was taken on the maintainer's behalf — correct it if wrong). "pandan ADR NNNN" means
an ADR in the pandan repo; bare "ADR NNNN" means this repo's. Read `PLAN.md` before anything substantial.

## The five decisions you will trip over if you don't know them

1. **Payload shaping lives in `kaya-client`, never in an adapter** ([ADR 0004](docs/adr/0004-shaping-lives-in-the-shared-client.md)).
   `kaya_cli.verbs` opens a session, calls one client method, returns a `Payload`; `__main__.main`
   calls `render()` on exactly one line. Pandan put shaping in its CLI instead, so its MCP adapter
   inherited none of it (44,902 tokens vs 2,689 for the same read).
2. **Kaya has no token format and no prefix logic** ([ADR 0002](docs/adr/0002-identity-pandan-as-provider.md)).
   Auth forwards the bearer to pandan's `GET /api/v1/me`, cached on `sha256(token)`. No `startswith`
   guard — pandan still accepts pre-rebrand `kanban_pat_…` tokens.
3. **`render()`'s signature is frozen** ([ADR 0005](docs/adr/0005-born-agent-conformant.md)). If a
   change needs to alter it, stop — that's the sequencing violated, not a reason to push through.
   Six shipped features found another answer (e.g. `Payload.limited_to()` applied at the call site).
4. **Nothing in kaya may block on pandan** ([ADR 0003](docs/adr/0003-cross-linking-one-way-soft.md)).
   A note saves, renders and appears in search with pandan down. Wikilink resolution degrades to
   unresolved. Authentication is the one exception ADR 0002 accepts knowingly.
5. **A note's identity is its `NOTE-n` ref, never its path or title** ([ADR 0008](docs/adr/0008-note-identity.md)).
   `path` is mutable metadata; moving a note is a `PATCH` to one column, no link rewriting.

## Rules that aren't visible in any one file

These have tests; you'll meet them as a failing build otherwise. Full incident/measurement account
for each is in [`docs/ENGINEERING_NOTES.md`](docs/ENGINEERING_NOTES.md).

- **Every note identifier resolves through `backend/app/api/refs.py`** — a route never parses one
  itself; it depends on `NoteFromRef` and gets a `Note`.
- **A note *list* query is scoped in SQL inside `app/auth/authorization.py`, and nowhere else** —
  `tests/unit/test_no_unscoped_note_query.py` checks this at the AST/statement level, not by
  convention. A *single*-note fetch is deliberately unscoped (so `authorize_note` can distinguish
  404 from 403). `note_link` queries are checked separately (rule 3): that table has no owner
  column, so anything touching it must constrain `source_note_id`.
- **`note.search_vector` is Postgres-generated (`Computed(..., persisted=True)`) and nothing else may
  write it** — assigning it raises `psycopg.errors.GeneratedAlways`. It's `deferred` and absent from
  `NoteRead`; a pinned key-list test fails if it ever reaches the wire. Alembic autogenerate does
  *not* diff a generated column's expression — deleting just the `Computed(...)` wrapper produces a
  silent `pass`, not a caught drop.
- **Search order is `ts_rank DESC, note.id DESC`** — the `id` tie-break is load-bearing; equal ranks
  are common, not exotic, and `updated_at` can't substitute (`now()` is transaction start time).
- **A backlink is found by `resolved_id`, never by title** — keying on the string breaks the moment
  the target is renamed. An edge with `resolved_id IS NULL` is a link to a title, not yet a note.
- **`/links` may call pandan; it may never hold a Postgres connection while doing it** — the route
  releases its connection (`_release_the_connection`, a commit) before resolving, because sync
  handlers share a 40-thread pool with note *saves*.
- **Never log a header, a request object, or anything built from a bearer** — redaction happens at
  serialization (`app/observability/`), so every call site is covered regardless of the author.
- **The SPA fallback (`app/spa.py`) refuses a fixed list of reserved namespaces** rather than
  matching-all-then-excepting — `/api/v1/notes/NOTE-9999` must stay a `404`, not become `200
  text/html`.
- **Svelte owns the editor's `<div>` container and never its children** (`EditorPane.svelte`, PLAN
  §S9) — zero template children, everything inside built imperatively by CM6. The identity guard
  (`needsRemount`) and the echo guard (`needsDispatch`/`syncDocument`) in `lib/editor.ts` are pure
  predicates and are not interchangeable; `view.destroy()` lives in a *second* effect that reads
  nothing, never in the mount effect's cleanup (Svelte cleans up before every re-run).
- **CodeMirror and the markdown-preview parser are both behind a lazy `import()`, and only inside the
  effect that reads nothing** (`lib/codemirror.ts`, `lib/markdown.ts`) — an `await` in the mount
  effect itself risks two views in one host. `tests/module-graph.ts`'s AST scanner is the guard that
  nothing else in `src/` value- or static-imports `@codemirror/*` except that one file.
- **A search is never rendered by the folder tree** (`Sidebar.svelte`) — grouping by `path` destroys
  `ts_rank` order, so a search forces the flat list and hides (not disables) the view toggle while
  active.
- **One module owns "the bearer for a request"** (`lib/auth.ts`) — token lives in `sessionStorage`,
  never `localStorage` or a cookie (it's a live pandan PAT, and the live preview renders arbitrary
  markdown to HTML in the same origin). `credentialState()` returns `set`/`not set` only — never a
  length or a masked fragment.
- **A `PATCH` is guarded only if `if_updated_at` is sent, and only over `body`** (ADR 0009) — a
  title/path-only write is unguarded even with a stale precondition. The CLI's only guard flag is
  `--if-updated-at`; there is no `--force`, and the client never fetches the precondition itself
  (that would narrow the guarantee to a race inside the read window).
- **`kaya note move` delegates to `update_note`, never its own endpoint** (ADR 0008) — pinned
  byte-identical on the wire against `edit --path`.
- **A config write is read-modify-write** (`kaya_client/config.py`) — JSON, not TOML, because a
  naive writer serializing only its own flags would silently drop a hand-set key like
  `max_text_chars`. `config show` prints `set`/`not set`, never a fragment.
- **No verb prompts, and `note delete` has no `--yes`** (ADR 0005 §contract 9) — asserted
  structurally over the CLI's AST; a flag that must always be passed isn't a confirmation.
- **A build states its own provenance or says it can't** (ADR 0007) — `--version` is `kaya X.Y.Z
  (sha)` or `kaya X.Y.Z (source checkout, not a released build)`, never a bare number.
- **Base images are pinned by digest, never by tag** — `scripts/check-image-pins.sh` in the pre-push
  hook and CI.
- **The API error shape is `{"error": {"code","message",…}}` everywhere**, including Starlette's own
  404/405. The client mirrors it (`error_payload`/`render_error`) and owns the *only* CLI-local
  translation: exit codes in `kaya_cli/failures.py` (`0` ok · `1` runtime · `2` usage/400/422 · `3`
  401 · `4` 403 · `5` 404 · `6` 409), add-only, pinned by literal-value tests.
- **`kaya-client`'s read timeout must outlast the backend's auth budget** — a cross-package AST test
  (`test_client_deadline_outlasts_auth.py`) checks this because ADR 0004 forbids either package
  importing the other to check it directly.

## Two inherited traps

- **Keep every `import app.*` inside a test/fixture body in the integration layer, never at module
  top.** A top-level import runs at collection, before the DB fixture sets `DATABASE_URL` — passes
  locally, fails in CI.
- **Alembic autogenerate needs models imported in `env.py`**, or it will cheerfully drop your
  tables. It's also narrower than it looks — see `search_vector` above: it diffs columns/types/
  nullability/indexes, never a generated column's expression.

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
make check             # docs-links + secret-scan + image-pins + lint + test
make audit             # npm audit + pip-audit (network; NOT in `check`)
make measure-auth      # re-measure introspection latency (Docker + a real PAT)
```

**`make up` forwards only two env vars into the app container** — `DATABASE_URL` and
`KAYA_PANDAN_URL`, per `docker-compose.yml`'s `app.environment:` block. Every other `Settings` field
(timeouts, cache TTLs, `log_level`, `spa_dist`) silently takes its default, however you've exported
it in your shell. To exercise a non-default value (e.g. starving card resolution for an R5.1-style
measurement), run the backend directly instead:

```bash
cd backend && KAYA_CARD_RESOLUTION_CONNECT_TIMEOUT_SECONDS=1 KAYA_CARD_RESOLUTION_READ_TIMEOUT_SECONDS=1 \
  uv run uvicorn app.main:app --port 8000
```

The app logs which settings differ from their declared default at boot, so a value that *did* take
effect is visible in `docker compose logs app` — but a value that never reached the process can't be
named that way. `DATABASE_URL` is deliberately excluded from that log (it embeds a plaintext
password).

Fastest frontend loop, against a stack you already have up:

```bash
cd frontend && KAYA_BACKEND_ORIGIN=http://localhost:8010 KAYA_SPA_PORT=5180 npm run dev
```

Set a credential from the browser console into `sessionStorage['kaya.token']` — never from a shell
command that would echo it.

Bundle-size and `toon`-delta re-measurement commands (re-run whenever a CodeMirror/Lezer package or a
serializer changes) are documented in `frontend/README.md` and
[`docs/ENGINEERING_NOTES.md`](docs/ENGINEERING_NOTES.md); quote a `gzip -9` number and say which
chunk/page it's for.

## Conventions

**Branching.** One branch per slice off fresh `main`. PR-only; `main` is protected and requires
branches to be up to date, so `gh pr update-branch` after each merge.

**Worktrees.** [treehouse](https://github.com/kunchenguid/treehouse) (`treehouse.toml`) —
`treehouse get --lease` / `treehouse return <path>`. A fresh tree needs `make install` before
`make lint` works. Only `make dev`/`make db` need a per-tree database
(`COMPOSE_PROJECT_NAME=kaya-x KAYA_DB_PORT=5433 make db`) — the integration layer provisions its own
via testcontainers.

**Tests.** Layered by cost (`docs/PLAN.md` §Testing approach): fast/no-infra, real-Postgres, e2e. A
slow check never gates a local push. Every bug and flake becomes a test, written failing first.

**Orchestrating sub-agents.** Hard limit: **at most 2 concurrent sub-agents** (Agent-tool /
worktree-isolated) driving this repo at once, maintainer's explicit cap. This machine is shared with
unrelated work; each agent's checks (`uv sync` + `npm ci` + pytest + vitest, run in parallel across
several worktrees) contend for the same CPU/network and reliably flake an otherwise-passing pre-push
run past 2 concurrent. Pipeline additional cards — start the next one once a running agent's PR is up,
not by fanning out wider.

**Mutating a guard to prove it fires** (anything marked `[mutate]` in `SLICES.md`): break the
protected thing, confirm the failure names the right thing, restore. **Commit the card's work
before you mutate anything, and restore with `git apply -R` or `git stash` — never `git checkout --`
or `git restore`.** On a dirty tree, `git diff` before the mutation captures uncommitted work too,
and reversing it deletes that work (this has happened — see
[`docs/ENGINEERING_NOTES.md`](docs/ENGINEERING_NOTES.md)). Check `git status --short` is clean
before trusting the result.

**A structural guard does not cover a behavioural claim, even when it reads as though it does.**
Before citing an existing guard as covering new behaviour, mutate the new behaviour and watch that
specific guard — this is the rule above turned around, and it catches the reviewer rather than the
author.

**Versioning.** A behavioural change to a shipped package (`kaya-cli`, `kaya-client`, `mcp`) bumps
its version in the same PR (ADR 0007), enforced by `scripts/check-version-bump.sh`
(`scripts/lib/pyproject_diff.py` classifies a `pyproject.toml` change by *which table* moved, not by
filename — a `uv.lock`-only or `dev`-extra change isn't behavioural; `[project.dependencies]` is).
Diffs against the merge-base with `main`, never the remote tip.

**Cutting a release.** Land the version bump, then `git tag v0.X.0 <merged-sha> && git push origin
v0.X.0` — the tag must equal `v` + `kaya-cli`'s `[project].version` or the workflow fails. Never push
a tag from a branch. `contents: write` lives only on the `publish` job, gated on
`github.event_name == 'push'` so a `workflow_dispatch` can rehearse the build without publishing.
`build` runs inside `quay.io/pypa/manylinux_2_28_x86_64` (glibc floor `2.28`, not `ubuntu-latest`'s
`2.38`) — see `docs/ENGINEERING_NOTES.md` for why `strings | grep GLIBC_` can't catch a regression
here and `scripts/check-release-artifact.sh` can.

**Dependencies.** Lockfiles committed, installs frozen, updates by Dependabot (not renovate). Don't
move `make audit` into the pre-push hook or `make check` — transitive dev advisories nobody can fix
would teach `--no-verify`. No `docker` ecosystem on the bot — base images are digest-pinned and
`check-image-pins.sh` would reject a tag bump. Frontend TypeScript is pinned `^6.0.3`; the ceiling is
upstream (`svelte-check`/`typescript-eslint` refusing newer majors), not this repo's taste — see
`docs/ENGINEERING_NOTES.md` before trying to force it past a red Dependabot PR.

**Docs.** Ban the phrase "full parity". State the direction (`MCP ⊆ CLI`) and cite the test that
proves it — [`mcp/README.md`](mcp/README.md) is the one canonical place for that; link to it rather
than restating it.

**Adding a package directory turns on its CI jobs**, gated on the directory existing. A new package
needs from its first commit: a committed lockfile, lint passing, at least one real test.

**Sprint retros.** Retro notes live in kaya itself, not a pandan card field — the maintainer's
2026-09-04 call, mirrored from the same decision for pandan's own retros, so kaya dogfoods itself for
its own project's retros. Shape: a running index note at `meta/retros` links out to one dated note per
sprint (`retros/sprint-N`, `N` matching the pandan cycle number). Whoever closes out a sprint on board
18 — its cycle's last card done, or its `ends_on` passed — writes that sprint's note before opening the
next sprint's planning; there's no automation for this yet, it's a human/PM-agent habit. This closes
the retro leg of the loop epic 165 (`KAY-E15`, "Adopt real Scrum cadence") asks for, on top of the
2-week/6-sprint-per-PI cadence KAN-1160 recorded (comments 624/625 on that epic). First sprint this
applies to is Sprint 3 (cycle 11, the live one) — Sprints 1–2 were backdated (KAN-1159) and get no
retroactive note.

## Board access

The `pandan` CLI drives board 18 ("kaya — Notes"). **Never print or paste the PAT** — it lives in
`~/.config/pandan/config.toml` and `pandan` finds it on its own; `pandan config show` redacts it.

```bash
pandan warmup                        # the API scales to zero; wake it first
pandan list --board 18 --column todo
pandan next --board 18               # highest-priority unblocked card
pandan get KAN-530
```
