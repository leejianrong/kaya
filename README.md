# kaya

A cloud-hosted, Obsidian-like **markdown notes** app — API-first and agent-drivable. It is the docs
half of the `kayatoast` suite, sibling to [pandan](https://github.com/leejianrong/pandan), the kanban
board. Where pandan tracks *work*, kaya holds the *knowledge*: specs, notes, runbooks, meeting notes,
cross-linked to the board.

> **Status: skeleton, not a product.** All five packages exist and boot — a FastAPI backend with a
> health endpoint, the shared client, the `kaya` CLI, the MCP package and a Svelte 5 SPA shell —
> and none of them can store a note yet. See [`docs/PLAN.md`](docs/PLAN.md) for what is being built,
> [`docs/SLICES.md`](docs/SLICES.md) for the order, and [`CLAUDE.md`](CLAUDE.md) for what is
> genuinely in each package today. Work is tracked on pandan board 18.

## What it will do

Write markdown in a real editor, organise notes in folders, search the full text, and link notes to
each other with `[[wikilinks]]`. A wikilink can also point at board work: `[[KAN-12]]` renders the
card's title and column inline, and a backlinks panel answers "which notes mention this card".

The same PAT that drives the board drives the notes, from the same config, with no second login and
no second token. An agent working `KAN-12` reads its spec note, edits it, and moves the card, using
one credential throughout.

## The plan

| Document | What it holds |
|---|---|
| [`docs/PLAN.md`](docs/PLAN.md) | Problem, solution, scope, requirements, the shape, affordances, testing approach, open risks |
| [`docs/SLICES.md`](docs/SLICES.md) | Seven vertical slices, each with a build plan and acceptance criteria |
| [`docs/QUESTIONS.md`](docs/QUESTIONS.md) | The decision register — what was decided, what is a default, what is deferred |
| [`docs/adr/`](docs/adr/) | Ten architectural decisions, with what was rejected and why |
| [`docs/kaya-vision.md`](docs/kaya-vision.md) | The founding statement of intent, kept verbatim |

Start with `PLAN.md`. The ADRs worth reading first are
[0002 (identity)](docs/adr/0002-identity-pandan-as-provider.md) and
[0004 (why payload shaping lives in the shared client)](docs/adr/0004-shaping-lives-in-the-shared-client.md) —
between them they carry most of what makes this project different from a generic notes app.

## Development

Needs `uv` (Python 3.12), Node 20.19+ and Docker.

```bash
make hooks         # install the pre-push gate (do this once)
make install       # uv sync every Python package, npm ci the SPA
make dev           # Postgres, backend on :8000, SPA on :5173
make test          # the fast, no-infra layer
make check         # everything pre-push runs
make help          # every target, including the ones still stubbed
```

Five packages in one repo — `backend/`, `frontend/`, `kaya-client/`, `kaya-cli/`, `mcp/` — with the
dependency arrow pointing one way: adapters depend on the client, and nothing depends on an adapter
([ADR 0001](docs/adr/0001-stack-inherited-from-pandan.md)).

Conventions, commands and the traps worth knowing live in [`CLAUDE.md`](CLAUDE.md), which is written
for coding agents and is equally the fastest orientation for a person.

## Licence

Apache License 2.0. The full text is in [`LICENSE`](LICENSE).
