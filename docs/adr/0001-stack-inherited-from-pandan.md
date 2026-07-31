# ADR 0001 — Reuse pandan's stack verbatim, with three named deviations

- **Status:** Accepted
- **Date:** 2026-08-01
- **Deciders:** Jian (fork F4)
- **Context source:** [`kaya-vision.md`](../kaya-vision.md) §Ethos; pandan ADRs 0001, 0003, 0008, 0011.

## Context

Kaya is a sibling, not a fork, so a shared stack is part of the point: one set of build commands, one
CI shape, one set of idioms, and a maintainer who doesn't context-switch between two dialects of the
same architecture. Defaulting to "same stack" is defensible here in a way it usually isn't.

It was still worth stating rather than assuming, because two of pandan's stack choices exist for
reasons **kaya does not share**. Pandan carries `fastapi-users` and a second async engine because it
does its own GitHub OAuth; under ADR 0002 kaya does no OAuth at all. Inheriting by inertia would have
imported a dependency, an engine, a connection pool and a per-environment OAuth App that kaya has no
use for.

## Decision

**Same stack, verbatim:** FastAPI, **sync** SQLAlchemy over psycopg v3, Postgres, Alembic from day
one, Svelte 5 with runes, `uv` for Python and `npm` for the frontend, a single deployable artifact
serving the built SPA from one origin (pandan ADR 0003), and the same CI shape (lint + unit +
integration + build + e2e as parallel jobs).

**One repo, five packages:** `backend/`, `frontend/`, `kaya-client/`, `kaya-cli/`, `mcp/`. The client
is consumed by two in-tree adapters, which is the case a monorepo is actually for.

Three deviations, each deliberate:

### 1. No `fastapi-users`, no OAuth client, no second engine

Pandan's ADR 0011 added an async engine against the same database because `fastapi-users` has an
async-only user store while ADR 0008 had already committed the board code to sync. It works, and the
standing cost is two session factories, two pools against one database, and a rule every contributor
has to remember about which engine a route may touch.

Kaya delegates identity to pandan (ADR 0002), so it needs none of it: no user store, no session
table, no OAuth client, no `--proxy-headers` redirect_uri handling, and no second GitHub OAuth App per
environment. **Kaya is 100% synchronous — one engine, one pool.**

This holds even if browser SSO is added later. Kaya would forward the cookie to the same upstream
endpoint and let pandan read its own session table; kaya never touches `access_token`, so it never
needs the async store. The async engine is foreclosed on purpose, and reintroducing one should be
read as a signal that something has drifted.

### 2. CodeMirror 6 for the editor

**MIT licensed**, ES modules imported individually (`@codemirror/state`, `view`, `language`,
`lang-markdown`, `autocomplete`, `commands`), and what Obsidian itself uses. Do not hand-roll an
editor. A `<textarea>` cannot do syntax highlighting, wikilink decorations, or a popup positioned at
the caret; a hand-rolled `contenteditable` means owning selection, IME, undo history and mobile
keyboards indefinitely, most of it on devices we don't have.

Two build-time obligations come with it. **Measure the bundle in V3 and record the number** in the
slice, the way pandan V47 measured TOON before shipping it, rather than asserting it's small. And
respect the integration constraint: CodeMirror owns its DOM subtree, so it is mounted once in an
`$effect` against an element ref, changes go in as transactions and come out through an update
listener, and Svelte never renders inside that subtree. A rune bound naively to the document and
written back creates an update loop, so the write-back needs a guard comparing against the editor's
current document.

### 3. Payload shaping lives in `kaya-client`, not in the CLI

See ADR 0004. Listed here because it is a **structural** difference from pandan's package layout, not
merely a coding preference.

## Alternatives considered

| Option | Why not |
|--------|---------|
| A different stack (Node/Next, Go, async Python) | Buys nothing kaya needs and costs the shared idiom that makes a sibling cheaper than a second product. |
| Inherit `fastapi-users` "for consistency" | Consistency with a dependency pandan only has because of a constraint kaya doesn't have. Two engines for zero benefit. |
| Async SQLAlchemy throughout, since kaya is greenfield | Diverges from pandan's ADR 0008 for a workload that is text CRUD plus one upstream HTTP call. The one plausible async win (concurrent wikilink resolution) is a batched call, not a concurrency model. |
| Hand-roll a markdown editor | Open-ended input-handling work masquerading as a small job. |
| Split repos per package | The client has exactly two consumers, both in-tree. Splitting adds release coordination for no isolation benefit. |

## Consequences

- **Positive:** the commands, CI shape, test layering and idioms transfer directly, so a contributor or
  agent fluent in pandan is fluent here. Kaya is *simpler* than pandan in the one place that matters
  most for correctness: a single engine and no async boundary to reason about.
- **Neutral:** CodeMirror 6 is a real new dependency with a real bundle cost. MIT, actively maintained,
  and the alternative is worse.
- **Negative / deferred:** kaya inherits pandan's known stack traps and must respect them without
  having earned them — keep integration-test `import app.*` inside fixture bodies (the PR #17 trap),
  and remember that Alembic autogenerate needs models imported in `env.py`. These are written into
  `CLAUDE.md` rather than left to be rediscovered.
- **Foreclosed:** an async engine. Adding one means either kaya took on its own login (contradicting
  ADR 0002) or something needs re-examining.
