# CLAUDE.md — agent brief for `kaya`

## Build status, stated honestly

**The skeleton is up; there is no product yet.** All five packages exist and all five are green in
CI, but they hold almost nothing (KAN-531):

| Package | What's actually in it |
|---|---|
| `backend/` | FastAPI app that boots, `GET /health`, one sync engine, migration `0001` (the `user` mirror, `note`, the `NOTE-` sequence), and `app/auth/`: the principal resolver and its `get_principal` dependency. No routes under `/api/v1` yet, so nothing depends on `get_principal` in the app itself |
| `kaya-client/` | An importable package and a version. No `KayaClient`, no `render()` — those are V2a |
| `kaya-cli/` | The `kaya` console script, one entry point, **no verbs** |
| `mcp/` | A package and ADR 0006's frozen tool-name tuple. No server, no tools |
| `frontend/` | Svelte 5 + Vite + TS toolchain, a shell page, and the dev proxy for `/api` |

Not built yet: `authorize_note` and owner-scoped lists (KAN-535), anything under `/api/v1`
(KAN-536), the container image and manifests (KAN-538).

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
make test              # the fast, no-infra layer (what pre-push runs)
make test-integration  # real Postgres via testcontainers (needs Docker)
make lint              # ruff × 4 packages + eslint + svelte-check
make check             # docs-links + secret-scan + lint + test
make build             # SPA into frontend/dist
make measure-auth      # re-measure introspection latency (Docker + a real PAT; KAN-539)
```

`make measure-auth` is the odd one out: it is a measurement, not a gate, and it is the only target
that reads a credential. It takes the PAT from `KAYA_MEASURE_PAT` or `~/.config/pandan/config.toml`,
never prints it, and **exits 0 having done nothing when there is no PAT** — so it can be run
anywhere, and CI never needs a secret to keep it green.

Still stubs, and they say which card unblocks them: `make up` (KAN-538), `make k3d` (KAN-538),
`make test-e2e` (KAN-552).

Per-package, if you want the loop tighter:

```bash
cd backend && uv run pytest tests/unit -q       # also: tests/integration, needs Docker
cd backend && uv run uvicorn app.main:app --reload
cd frontend && npm run dev                      # /api proxies to :8000
```

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
**merge-base with `main`**, not the remote tip.

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
