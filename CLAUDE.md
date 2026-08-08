# CLAUDE.md — agent brief for `kaya`

## Build status, stated honestly

**The skeleton is up; there is no product yet.** All five packages exist and all five are green in
CI, but they hold almost nothing (KAN-531):

| Package | What's actually in it |
|---|---|
| `backend/` | FastAPI app, `GET /health`, one sync engine, migration `0001` (the `user` mirror, `note`, the `NOTE-` sequence), `app/auth/` (principal resolver, `get_principal`, `authorize_note`, `notes_owned_by`), `app/api/`: **`/api/v1/notes` CRUD** over the central ref resolver with ADR 0009's `409` precondition on `PATCH`, `app/spa.py` serving the built SPA from the same origin, and `app/observability/` (one JSON log line per request on stdout, a request id, credential redaction) |
| `kaya-client/` | An importable package and a version. No `KayaClient`, no `render()` — those are V2a |
| `kaya-cli/` | The `kaya` console script, one entry point, **no verbs** |
| `mcp/` | A package and ADR 0006's frozen tool-name tuple. No server, no tools |
| `frontend/` | Svelte 5 + Vite + TS toolchain, a shell page, and the dev proxy for `/api` |
| *root* | `Dockerfile` (one artifact, bases pinned by digest), `docker-compose.yml` (db + migrate + app), `deploy/k8s/` (base for the homelab, overlay for k3d) |

Not built yet: `?q=` search (KAN-558/559), `/links` and `/backlinks` (KAN-566), the SPA's actual UI
(V3, KAN-552 onward).

**V1 is complete.** `make up` runs the whole stack on `:8000` from the image; `make k3d` applies
`deploy/k8s/` to a throwaway local cluster and then *makes requests against it* — an `apply` that
succeeds only means the API server liked the YAML (ADR 0010, KAN-538).

**The SPA fallback must never answer for `/api`.** A single-page app needs history fallback so
`/notes/NOTE-12` loads the app, and the two obvious ways to build it (`StaticFiles(html=True)` at
`/`, or an exception handler on `404`) both swallow the API — `/api/v1/notes/NOTE-9999` comes back
`200 text/html` and KAN-536's byte-identical `404` is gone. `app/spa.py` refuses a fixed list of
reserved namespaces instead, and `tests/unit/test_spa_single_origin.py` proves it by running every
reserved path against two apps, one with the SPA mounted and one without, and requiring
byte-identical answers. **Every other API test in the repo passes with the fallback mounted wrong**,
because they stand the app up with no build directory and therefore no fallback at all.

**Base images are pinned by digest, never by tag** (`Dockerfile`, `docker-compose.yml`,
`deploy/k8s/base/`). A tag is a mutable pointer, so an image on one has provenance labels that
describe kaya's source and nothing else — pandan's KAN-475. `scripts/check-image-pins.sh` runs in
the pre-push hook and in CI; `scripts/image-build.sh` is the only build path that produces true
labels, and it suffixes the revision `-dirty` when the tree it built from was.

**A `PATCH` is guarded only if it asks to be, and only over the body** (ADR 0009, KAN-537,
`backend/app/api/concurrency.py`). Send `if_updated_at` and a stale value is a `409` carrying
`attempted` and `stored` — two whole notes, so a client can diff them. Omit it and the write is a
plain overwrite, *by specification*: the precondition is a guarantee for clients that want it, not a
tax on every caller, and making it mandatory would be a different decision from the accepted one. A
write touching only `title`/`path` is unguarded even when it carries a stale precondition, because
ADR 0009 keeps card-shaped fields on last-write-wins; one touching `body` **and** `title` is guarded
and refused whole. The comparison is exact to the microsecond — a `timestamptz` token that loses
precision anywhere in the round trip refuses *every* correct write, which is why the tests pin
`.123456` rather than a round number.

**Every identifier goes through `backend/app/api/refs.py`.** `NOTE-12`, `note-12` and `12` resolve
in *one* place, so a missing note is the same `404` byte for byte whichever spelling asked for it,
and `#NOTE-12` is a `400` usage error (ADR 0008). A route never sees a string — it depends on
`NoteFromRef` and is handed a `Note`, which is what makes V5's `/links` and `/backlinks` inherit the
guarantee without writing any ref handling. If you add a ref-taking verb, take the dependency; if
you find yourself parsing an identifier in a route, that is the bug ADR 0008 exists to prevent.

**Never log a header, a request object, or anything built from a bearer** (Q41/Q42, KAN-700,
`backend/app/observability/`). One JSON line per request goes to stdout, carrying `ACCESS_FIELDS`
and nothing else — no header of any name, and no query string. The redaction rule sits at
*serialization*, so a record any call site emits is scrubbed whether or not its author knew the rule
existed; that is why the fix for "I need to see the headers" is never to log them here. ADR 0002
buys one property with everything it costs — kaya holds no replayable credential — and a log line is
the cheapest way to give it away. `tests/unit/test_log_redaction.py` asserts against every
contiguous *fragment* of a fake token, not the whole string, because a truncated token is still a
token.

**The API error shape is `{"error": {"code", "message", …}}`** — flat, un-nested, and the same for
every failure including Starlette's own `404`/`405` and body validation (`app/api/errors.py`).
`error_body` remains the single builder; `detail` is FastAPI's word and does not appear on the wire.

**A note list is scoped in SQL, in one place.** Compose onto `app.auth.notes_owned_by`, which
carries `WHERE owner_id = :caller`; `backend/tests/unit/test_no_unscoped_note_query.py` fails if
`Note` reaches a `select()` anywhere else under `app/`. A *single* note is fetched unscoped on
purpose — `authorize_note` cannot answer `403` for someone else's note if the fetch never found it —
which is why `note_addressed_as_ref` / `note_addressed_as_id` also live in `app/auth/authorization.py`
rather than beside the resolver that calls them. That guard is not negotiable: put the query in the
sanctioned module, never in the allow-list.

Introspection latency is now **measured** (KAN-539, re-runnable as `make measure-auth`): a cache hit
is **1.6 µs**, a warm miss **387 ms**, and a **cold miss 21.8 s** (measured with the harness's
deadline lifted to 30 s, so a cold start produced a number rather than a timeout). That last figure
is more than twice `KAYA_PANDAN_TIMEOUT_SECONDS`'s 10 s default, so a cold pandan currently answers
a *valid* PAT with a `503`. **Do not fix that by raising the timeout** — it converts the `503` into a 22-second
request holding a Postgres connection, which is worse. PLAN §Open risks carries the escalation and
the argument; read it before touching `app/auth/` or that setting.

CI gates each language job on its **directory existing**, so all five now run on every PR. A
package that can't be made green does not belong in the tree.

**Trust the code over the docs.** When this file and the repository disagree, the repository is right
and this file is stale — fix it in the same PR. That rule applies with extra force right now, because
every command in §Commands is a *plan* rather than an observation.

## What this project is

A cloud-hosted markdown notes app, API-first and agent-drivable, and the docs half of the `kayatoast`
suite. Its sibling is [pandan](https://github.com/leejianrong/pandan), the kanban board. Read
[`docs/PLAN.md`](docs/PLAN.md) before doing anything substantial; it is the live spec.

Work is tracked on **pandan board 18** ("kaya — Notes (MVP)"), 7 epics matching the 7 slices in
[`docs/SLICES.md`](docs/SLICES.md). Use the `pandan` CLI to read and move cards.

## How the docs relate

A deliberate chain, not scratch notes. Treat it as the spec for intended behaviour:

[`docs/kaya-vision.md`](docs/kaya-vision.md) (settled intent) → [`docs/PLAN.md`](docs/PLAN.md) +
[`docs/adr/`](docs/adr/) → [`docs/SLICES.md`](docs/SLICES.md), with
[`docs/QUESTIONS.md`](docs/QUESTIONS.md) as the decision register.

- **`PLAN.md`** absorbs what pandan splits across FRAME / PRD / CONTEXT / SHAPING / BREADBOARD, so
  nothing can drift between them. One narrative document with sections.
- **`QUESTIONS.md`** tells a **decision** from a **default**. A row marked `ASSUMED` is a default
  taken on the maintainer's behalf — correct it if it's wrong rather than treating it as settled.
- **`docs/adr/`** (0001–0010) is the *why*. Do not re-litigate an accepted ADR; amend it.
- **"pandan ADR NNNN"** always means an ADR in the pandan repo. Bare "ADR NNNN" means this repo's.

## The five decisions you will trip over if you don't know them

Read these before writing code. Each one is a place where the obvious implementation is wrong.

1. **Payload shaping lives in `kaya-client`, never in an adapter** ([ADR 0004](docs/adr/0004-shaping-lives-in-the-shared-client.md)).
   Projection, truncation, aggregates and serialization go through one `render()` seam in the shared
   client. The CLI and the MCP server both call it. A projection or truncation rule appearing in
   `kaya-cli/` or `mcp/` is a bug, not a local optimisation. This exists because pandan put shaping in
   its CLI, so its MCP adapter inherited none of it and one `list_cards` call costs 44,902 tokens
   against 2,689 for the equivalent CLI read.
2. **Kaya has no token format and no prefix logic** ([ADR 0002](docs/adr/0002-identity-pandan-as-provider.md)).
   Authentication forwards the bearer to pandan's `GET /api/v1/me` and caches the answer keyed on
   `sha256(token)`. Do not add a `startswith` guard: pandan still accepts pre-rebrand `kanban_pat_…`
   tokens, and that exact guard is the bug pandan ADR 0018 had to correct. Never log or cache a raw
   token.
3. **The output layer's signature lands before behaviour goes inside it** ([ADR 0005](docs/adr/0005-born-agent-conformant.md)).
   V2a builds the seam; V2b fills it. If a V2b-or-later change needs to alter `render()`'s signature,
   stop — that's the signal the sequencing was violated, not a reason to push through.
4. **Nothing in kaya may block on pandan** ([ADR 0003](docs/adr/0003-cross-linking-one-way-soft.md)).
   A note must save, render and appear in search with pandan completely down. Wikilink resolution is a
   cached read that degrades to an unresolved link. Adding a feature that makes a save depend on
   pandan being reachable breaks the design, however reasonable it looks in isolation.
5. **A note's identity is its `NOTE-n` ref, never its path or title** ([ADR 0008](docs/adr/0008-note-identity.md)).
   `path` is mutable metadata; moving a note is a `PATCH` to one column with no link rewriting.
   Resolve refs centrally, not per call site.

## Commands

`make help` is the source of truth. Python packages use **`uv`** (3.12), the SPA uses **`npm`**
(Node 20.19+). Every target runs from the repo root.

```bash
make hooks             # install the pre-push gate — run this once after cloning
make install           # uv sync every Python package + npm ci
make db                # Postgres 17 via docker compose, waits for healthy
make dev               # db, then backend :8000 and SPA :5173 together
make up                # db + migrate + the app image, one origin on :8000
make down              # stop the stack (keeps the volume)
make image             # build the image with TRUE provenance labels
make k3d               # deploy/k8s to a local cluster, then prove the pod serves
make k3d-down          # delete the cluster (it costs ~575 MiB while it runs)
make test              # the fast, no-infra layer (what pre-push runs)
make test-integration  # real Postgres via testcontainers (needs Docker)
make lint              # ruff × 4 packages + eslint + svelte-check
make check             # docs-links + secret-scan + image-pins + lint + test
make build             # SPA into frontend/dist
make audit             # npm audit + pip-audit over every lockfile (network; NOT in `check`)
make measure-auth      # re-measure introspection latency (Docker + a real PAT; KAN-539)
```

`make measure-auth` is the odd one out: it is a measurement, not a gate, and it is the only target
that reads a credential. It takes the PAT from `KAYA_MEASURE_PAT` or `~/.config/pandan/config.toml`,
never prints it, and **exits 0 having done nothing when there is no PAT** — so it can be run
anywhere, and CI never needs a secret to keep it green.

Still a stub, and it says which card unblocks it: `make test-e2e` (KAN-552).

Per-package, if you want the loop tighter:

```bash
cd backend && uv run pytest tests/unit -q       # also: tests/integration, needs Docker
cd backend && uv run uvicorn app.main:app --reload
cd frontend && npm run dev                      # /api proxies to :8000

# The single-origin layout from a checkout, without building the image. Nothing is guessed at:
# unset KAYA_SPA_DIST means the API serves alone, which is what `make dev` wants.
cd frontend && npm run build
cd backend && KAYA_SPA_DIST=../frontend/dist uv run uvicorn app.main:app --port 8000
```

**`make k3d` names its kubectl context explicitly** (`kubectl --context k3d-kaya …`) and so should
anything else that touches the cluster. The `k3d-<name>` context exists only while the cluster does,
so a target relying on "whatever is current" depends on state it did not establish — and the
manifests have to be appliable on the homelab by someone who does not have this laptop's kubeconfig.

**Adding a package directory turns on its CI jobs**, gated on the directory existing rather than on
a changed-paths filter. So a new package needs, from its first commit: a committed `uv.lock`
(CI runs `uv sync --frozen`), ruff passing, and at least one real test — `pytest` exits non-zero on
"no tests collected". The frontend equivalent is a committed `package-lock.json` and a working
`npm run build`.

## Two inherited traps, written down so they aren't rediscovered

Both cost the sibling project real time. They are not hypothetical.

- **Keep every `import app.*` inside a test or fixture body in the integration layer, never at module
  top.** A top-level app import runs at pytest collection, before the database fixture sets
  `DATABASE_URL`, so the engines bind to the wrong database. It passes locally against a dev Postgres
  and fails in CI. This is pandan's "PR #17 trap".
- **Alembic autogenerate needs models imported in `env.py`**, or it will cheerfully generate a
  migration that drops your tables.

## Conventions

**Branching.** One branch per slice off fresh `main`. PR-only; `main` is protected. Use worktrees for
parallel work, and **give each worktree its own database** — worktrees share a filesystem, so one
branch's migration stamps a revision the others don't have and their apps then fail to boot. The
compose file takes `COMPOSE_PROJECT_NAME` and `KAYA_DB_PORT` for exactly this:
`COMPOSE_PROJECT_NAME=kaya-myfeature KAYA_DB_PORT=5433 make db`, then point that tree's
`DATABASE_URL` at 5433.

**Tests.** Layered by cost ([`docs/PLAN.md`](docs/PLAN.md) §Testing approach). A fast layer with no
infrastructure, a heavier layer that needs real Postgres, and e2e that boots the stack. A slow check
never gates a local push.

**Every bug and flake becomes a test**, written failing first. A fixed bug without a test is a bug
waiting to come back.

**Prove a guard by watching it fail.** For anything marked `[mutate]` in `SLICES.md`: break the
protected thing, confirm the failure names the right thing, then restore. Restore with
`git apply -R` or `git stash`, **never `git checkout -- <file>` or `git restore <file>`** — those
overwrite from the index and silently destroy uncommitted work that no reflog can recover.

**Versioning.** A behavioural change to a shipped package bumps its version in the same PR
([ADR 0007](docs/adr/0007-release-provenance-from-the-first-release.md)). The guard diffs against the
**merge-base with `main`**, not the remote tip. When that guard is built (KAN-544) it must classify
by **which table in `pyproject.toml` changed, not by filename**, or every Dependabot PR into
`kaya-client` / `kaya-cli` / `mcp` becomes a red check someone hand-fixes: a `uv.lock`-only change is
the dev environment and is **not** behavioural, a `[project.dependencies]` change becomes
`Requires-Dist` in the wheel and **is**, and a `dev` extra is the test toolchain and is not.
`.github/dependabot.yml` carries the same note.

**Dependencies.** Lockfiles committed, installs frozen, updates by **Dependabot** (not renovate —
`.github/dependabot.yml` says why), vulnerabilities by `make audit`. **Do not move the audit into
the pre-push hook or into `make check`.** `npm audit` exits non-zero on transitive dev advisories
nobody can fix, so gating on it teaches `--no-verify`; it runs weekly instead and reports into one
issue that never blocks a merge. Do not add a `docker` ecosystem to the bot either — base images are
digest-pinned and `scripts/check-image-pins.sh` would reject the tag a bot PR writes.

**Measurements go in the PR body.** Several slices require a number rather than an assertion:
introspection latency (V1), the `toon` delta (V2a), the CodeMirror bundle size (V3), and the MCP
per-read payload cost (V6). "It's fast" is not an acceptance criterion; a number is.

**Docs.** Ban the phrase **"full parity"** from this repo. State the direction (`MCP ⊆ CLI`) and cite
the test that proves it. Pandan's skill asserted full parity in bold while contradicting itself forty
lines below, and the false claim reached a roadmap card where it nearly justified deleting a working
surface.

## Board access

The `pandan` CLI drives board 18. **Never print or paste the PAT** — it lives in
`~/.config/pandan/config.toml` and `pandan` finds it on its own. `pandan config show` redacts it and
is safe to run.

```bash
pandan warmup                        # the API scales to zero; wake it first
pandan list --board 18 --column todo
pandan next --board 18               # highest-priority unblocked card
pandan get KAN-530
```
